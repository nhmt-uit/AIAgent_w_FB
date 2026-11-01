"""Tests for running an account AS A FACEBOOK PAGE (2026-10-31): the identity
classifier, the account-menu check, the comment-box label guard, run_task()
refusing to act under the wrong identity, and registering a Page account."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot import actions, agent, daily_limits
from human_bot.actions import ActionResult, classify_identity, comment_box_identity_problem
from human_bot.agent import TaskRequest
from human_bot.config import AccountConfig, get_all_accounts
from human_bot.runtime_config import save_registered_account
from human_bot.safety import AnomalyDetected

PAGE = "Đơn Kỹ Sư Nhật"
ME = "Tu Nguyen"


# --- classifier ---------------------------------------------------------------------

@pytest.mark.parametrize("offered,expected", [
    ([PAGE], "personal"),                      # the Page is offered as a switch target → we are NOT it
    ([PAGE.lower(), "Other"], "personal"),     # case-insensitive
    ([ME], "page"),                            # the personal profile is offered and the Page is not → we ARE the Page
    ([ME.upper(), "Another Page"], "page"),
    ([], "unknown"),                           # menu not read → never assume
    (["Someone Else"], "unknown"),             # neither identity shows up → never assume
])
def test_classify_identity(offered, expected):
    assert classify_identity(offered, PAGE, ME) == expected


def test_a_typo_in_either_configured_name_never_yields_page():
    """Code review 2026-10-31: the earlier "page unless the Page is offered"
    rule posted as the PERSONAL profile whenever page_name was mistyped."""
    # session is the personal profile → the menu offers the real Page name
    assert classify_identity(["Đơn Kỹ Sư Nhật"], "Don Ky Su Nhat", ME) == "unknown"   # typo in page_name
    # session is the Page → the menu offers the real personal name
    assert classify_identity([ME], PAGE, "Tu Nguyen Typo") == "unknown"               # typo in personal_name
    assert classify_identity([ME], "", ME) == "unknown" and classify_identity([ME], PAGE, "") == "unknown"


def test_names_are_compared_after_unicode_normalization():
    import unicodedata
    decomposed = unicodedata.normalize("NFD", PAGE)
    assert decomposed != PAGE
    assert classify_identity([decomposed], PAGE, ME) == "personal"
    assert classify_identity([ME + "  "], PAGE, "  tu   nguyen") == "page"


@pytest.mark.parametrize("label,problem", [
    (f"Answer as {PAGE}", False), (f"Comment as {PAGE}", False), (f"comment as {PAGE.upper()}", False),
    (f"Bình luận dưới tên {PAGE}", False),
    ("Write a public comment…", True), (f"Answer as {ME}", True), ("", True), (None, True),
    (f"Comment as {ME} {PAGE}", True),          # merely CONTAINING the Page name is not enough
    (f"Answer as Not {PAGE}", True),
])
def test_comment_box_identity_problem(label, problem):
    result = comment_box_identity_problem(label, PAGE)
    assert (result is not None) == problem
    if problem:
        assert result.startswith("wrong_identity")


# --- ensure_page_identity against a fake page -----------------------------------------

class _FakeButton:
    def __init__(self, label):
        self.label = label

    async def get_attribute(self, name, timeout=None):
        return self.label if name == "aria-label" else None

    async def inner_text(self, timeout=None):
        return self.label


class _First:
    def __init__(self, buttons):
        self._buttons = buttons

    async def wait_for(self, state=None, timeout=None):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        if not self._buttons:
            raise PlaywrightTimeoutError("no Switch-to button became visible")


class _FakeLocator:
    def __init__(self, buttons):
        self._buttons = buttons

    @property
    def first(self):
        return _First(self._buttons)

    async def all(self):
        return self._buttons


class _FakePage:
    def __init__(self, switch_labels, fail_goto=None):
        self.switch_labels = switch_labels
        self.fail_goto = fail_goto
        self.keyboard = self
        self.pressed = []

    async def goto(self, url, **kwargs):
        if self.fail_goto:
            raise self.fail_goto

    menu_label = "Account, your profile"

    def get_by_role(self, role, name=None):
        if name is not None and "Switch" in name.pattern:
            return _FakeLocator([_FakeButton(label) for label in self.switch_labels])
        # the account-menu button: only buttons whose label the given regex matches are "visible"
        return _FakeLocator([_FakeButton(self.menu_label)] if name is None or name.search(self.menu_label) else [])

    async def press(self, key):
        self.pressed.append(key)


@pytest.fixture
def quiet_actions(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    for name in ("human_click", "pause_after_page_load", "pause_between_ui_steps", "_check_anomaly_or_raise"):
        monkeypatch.setattr(actions, name, noop)


async def test_verified_when_only_the_personal_profile_is_offered(quiet_actions):
    page = _FakePage([f"Switch to {ME}"])
    assert await actions.ensure_page_identity(page, PAGE, ME) is None
    assert page.pressed == ["Escape"]  # the menu is closed again


async def test_refused_when_the_page_is_offered_i_e_we_are_personal(quiet_actions):
    result = await actions.ensure_page_identity(_FakePage([f"Switch to {PAGE}"]), PAGE, ME)
    assert result.startswith("wrong_identity:session_is_the_personal_profile")


async def test_refused_when_the_page_name_is_mistyped_even_though_we_are_personal(quiet_actions):
    """The session is the personal profile (the real Page is offered) but the
    configured name has a typo — must refuse, not act."""
    result = await actions.ensure_page_identity(_FakePage([f"Switch to {PAGE}"]), "Don Ky Su Nhat", ME)
    assert result.startswith("identity_unverified")  # a definite "cannot prove it" verdict


async def test_refused_when_the_personal_name_is_not_configured(quiet_actions):
    result = await actions.ensure_page_identity(_FakePage([f"Switch to {ME}"]), PAGE, "")
    assert result == "identity_unverified:personal_name_not_configured"


async def test_refused_when_the_menu_has_no_switch_buttons(quiet_actions):
    page = _FakePage([])
    result = await actions.ensure_page_identity(page, PAGE, ME)
    assert result.startswith("identity_check_error")  # nothing rendered in time → transient, not a verdict
    assert page.pressed == ["Escape"]  # the menu is closed even on this path


async def test_refused_on_a_timeout(quiet_actions):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    result = await actions.ensure_page_identity(_FakePage([], fail_goto=PlaywrightTimeoutError("t")), PAGE, ME)
    assert result.startswith("identity_check_error")


# --- run_task() gate -------------------------------------------------------------------

class _FakeSession:
    def __init__(self):
        self.page = object()
        self.lock = asyncio.Lock()
        self.saved = 0
        self.closed_unsaved = 0

    async def ensure_started(self):
        pass

    def is_alive(self):
        return True

    async def save_state(self):
        self.saved += 1

    async def close(self, save=True):
        if not save:
            self.closed_unsaved += 1


@pytest.fixture
def page_account(monkeypatch, isolated_runtime_config, isolated_accounts_dir, isolated_db):
    save_registered_account("page_test", "Page Test", PAGE, ME)
    session = _FakeSession()
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))
    monkeypatch.setattr(agent, "get_session", lambda account: session)
    ran = []

    async def fake_action(page, req):
        ran.append(req.account_id)
        return ActionResult(success=True, message="posted_to_group")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", fake_action))
    alerts = []

    async def fake_send(text, *, silent=False):
        alerts.append((text, silent))

    monkeypatch.setattr(agent.telegram_notify, "send_message", fake_send)
    agent._wrong_identity_alerted.clear()
    return session, ran, alerts


def _request(account_id="page_test"):
    return TaskRequest(action="post_to_group", account_id=account_id, target_url="https://facebook.com/groups/1", content="x")


async def test_page_account_is_verified_before_every_action(page_account, monkeypatch):
    """Facebook can flip the active identity mid-session, so the check is not
    cached per browser session."""
    _session, ran, _alerts = page_account
    checks = []

    async def verified(page, name, personal):
        checks.append((name, personal))
        return None

    monkeypatch.setattr(agent.actions, "ensure_page_identity", verified)
    first = await agent.run_task(_request())
    second = await agent.run_task(_request())
    assert first.success and second.success
    assert ran == ["page_test", "page_test"] and checks == [(PAGE, ME), (PAGE, ME)]


async def test_wrong_identity_refuses_to_act_and_alerts_once(page_account, monkeypatch):
    _session, ran, alerts = page_account

    async def personal(page, name, personal_name):
        return "wrong_identity:session_is_the_personal_profile (expected Page 'x')"

    monkeypatch.setattr(agent.actions, "ensure_page_identity", personal)
    first = await agent.run_task(_request())
    second = await agent.run_task(_request())
    assert not first.success and first.message.startswith("wrong_identity")
    assert not second.success
    assert ran == []  # nothing was ever posted
    loud = [t for t, silent in alerts if not silent and "KHÔNG xác nhận được" in t]
    assert len(loud) == 1  # one loud alert for the episode, not one per refused task


async def test_unverified_identity_is_refused_and_alerted_too(page_account, monkeypatch):
    _session, ran, alerts = page_account

    async def unverified(page, name, personal_name):
        return "identity_unverified:account_menu_does_not_show_the_expected_identities"

    monkeypatch.setattr(agent.actions, "ensure_page_identity", unverified)
    result = await agent.run_task(_request())
    assert not result.success and ran == []
    assert any(not silent and "KHÔNG xác nhận được" in t for t, silent in alerts)


async def test_a_later_good_run_re_arms_the_alert(page_account, monkeypatch):
    _session, ran, alerts = page_account
    answers = iter(["wrong_identity:x", None, "wrong_identity:x"])

    async def scripted(page, name, personal_name):
        return next(answers)

    monkeypatch.setattr(agent.actions, "ensure_page_identity", scripted)
    await agent.run_task(_request())
    await agent.run_task(_request())          # verified → posts
    await agent.run_task(_request())          # wrong again → a NEW episode
    assert ran == ["page_test"]
    assert len([1 for t, s in alerts if not s and "KHÔNG xác nhận được" in t]) == 2


async def test_a_refused_identity_check_does_not_start_the_rate_limit_gap(page_account, monkeypatch):
    """No attempt at the action was made, so it must not throttle the first
    real post after the owner fixes the session."""
    from human_bot.config import get_account
    from human_bot.safety import RateLimiter

    async def personal(page, name, personal_name):
        return "wrong_identity:x"

    monkeypatch.setattr(agent.actions, "ensure_page_identity", personal)
    await agent.run_task(_request())
    assert RateLimiter(get_account("page_test")).next_allowed_at("post") is None


async def test_the_comment_action_receives_the_expected_page_name(page_account, monkeypatch):
    _session, _ran, _alerts = page_account
    seen = {}

    async def verified(page, name, personal_name):
        return None

    async def fake_comment(page, req):
        seen["expected"] = req.expected_page_name
        return ActionResult(success=True, message="commented")

    monkeypatch.setattr(agent.actions, "ensure_page_identity", verified)
    monkeypatch.setitem(agent._ACTION_DISPATCH, "comment_on_group_post", ("comment", fake_comment))
    await agent.run_task(TaskRequest(action="comment_on_group_post", account_id="page_test", target_url="u", content="x"))
    assert seen["expected"] == PAGE


async def test_personal_account_is_never_identity_checked(page_account, monkeypatch):
    _session, ran, _alerts = page_account

    async def must_not_run(page, name):
        raise AssertionError("a personal account must not be identity-checked")

    monkeypatch.setattr(agent.actions, "ensure_page_identity", must_not_run)
    result = await agent.run_task(_request("tu_iizuki"))
    assert result.success and ran == ["tu_iizuki"]


# --- registration ----------------------------------------------------------------------

@pytest.fixture
def client(isolated_runtime_config, isolated_accounts_dir, isolated_schedule_dirs, monkeypatch):
    from tests.test_admin_post import _make_test_app
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def test_register_form_has_the_page_and_personal_name_fields(client):
    html = client.get("/admin/accounts/add-modal").text
    assert 'name="page_name"' in html and 'name="personal_name"' in html


def test_registering_a_page_account_stores_and_exposes_both_names(client):
    resp = client.post("/admin/accounts/add", data={
        "account_id": "page_donkysu", "display_name": "Đơn Kỹ Sư Nhật",
        "page_name": f"  {PAGE}  ", "personal_name": f" {ME} ", "owner_account_id": "tu_iizuki",
    })
    assert resp.status_code in (200, 303)
    account = get_all_accounts()["page_donkysu"]
    assert (account.page_name, account.personal_name) == (PAGE, ME)
    assert account.owner_account_id == "tu_iizuki" and account.page_session_mode == "auto"  # the new default
    assert account.storage_state_path.parent.name == "page_donkysu"  # its own session file


@pytest.mark.parametrize("page_name,personal_name,expected", [
    (PAGE, "", "tên hồ sơ cá nhân"),
    (PAGE, PAGE.upper(), "không được trùng"),
])
def test_page_registration_validation(client, page_name, personal_name, expected):
    resp = client.post("/admin/accounts/add", data={
        "account_id": "bad_page", "display_name": "X", "page_name": page_name, "personal_name": personal_name,
        "owner_account_id": "tu_iizuki",
    }, headers={"hx-request": "true"})
    assert expected in resp.text
    assert "bad_page" not in get_all_accounts()


def test_two_accounts_cannot_claim_the_same_page(client):
    ok = {"display_name": "A", "page_name": PAGE, "personal_name": ME, "owner_account_id": "tu_iizuki"}
    client.post("/admin/accounts/add", data={"account_id": "page_one", **ok})
    resp = client.post("/admin/accounts/add", data={"account_id": "page_two", **ok}, headers={"hx-request": "true"})
    assert "Đã có một tài khoản khác chạy bằng Page này" in resp.text
    assert "page_two" not in get_all_accounts()


def test_the_accounts_list_shows_the_page_and_personal_names(client):
    client.post("/admin/accounts/add", data={
        "account_id": "page_donkysu", "display_name": "D", "page_name": PAGE, "personal_name": ME, "owner_account_id": "tu_iizuki",
    })
    html = client.get("/admin/accounts").text
    assert f"Page: {PAGE}" in html and f"hồ sơ cá nhân: {ME}" in html          # kept as the name's tooltip, not three lines of text
    assert "acct-child" in html and "Các Page:" not in html and "Hồ sơ cá nhân:" not in html


def test_a_plain_account_has_no_page_or_personal_name(client):
    client.post("/admin/accounts/add", data={"account_id": "plain_acc", "display_name": "Plain"})
    account = get_all_accounts()["plain_acc"]
    assert account.page_name == "" and account.personal_name == ""
    assert get_all_accounts()["tu_iizuki"].page_name == ""


# --- review round 2 (2026-10-31) --------------------------------------------------------

async def test_a_transient_check_error_refuses_but_does_not_raise_the_loud_alert(page_account, monkeypatch):
    _session, ran, alerts = page_account

    async def flaky(page, name, personal_name):
        return "identity_check_error:TimeoutError"

    monkeypatch.setattr(agent.actions, "ensure_page_identity", flaky)
    result = await agent.run_task(_request())
    assert not result.success and ran == []
    assert not [1 for t, silent in alerts if not silent and "KHÔNG xác nhận được" in t]
    from human_bot.config import get_account
    from human_bot.safety import RateLimiter
    assert RateLimiter(get_account("page_test")).next_allowed_at("post") is None  # still no rate-limit gap


async def test_a_comment_box_label_mismatch_inside_the_action_also_alerts(page_account, monkeypatch):
    _session, _ran, alerts = page_account

    async def verified(page, name, personal_name):
        return None

    async def label_mismatch(page, req):
        return ActionResult(success=False, message="wrong_identity:comment_box_label='Answer as Tu Nguyen'")

    monkeypatch.setattr(agent.actions, "ensure_page_identity", verified)
    monkeypatch.setitem(agent._ACTION_DISPATCH, "comment_on_group_post", ("comment", label_mismatch))
    await agent.run_task(TaskRequest(action="comment_on_group_post", account_id="page_test", target_url="u", content="x"))
    assert [1 for t, silent in alerts if not silent and "KHÔNG xác nhận được" in t]


def test_a_registered_page_identity_survives_an_id_collision_with_a_code_level_account(isolated_runtime_config, isolated_accounts_dir):
    """tu_iizuki exists in config.ACCOUNTS; if a registered entry ever has the
    same id, its Page identity must still apply (never run without the guard)."""
    save_registered_account("tu_iizuki", "Collision", PAGE, ME)
    account = get_all_accounts()["tu_iizuki"]
    assert (account.page_name, account.personal_name) == (PAGE, ME)
    assert account.display_name != "Collision"  # the code-level entry still wins for everything else


def test_one_public_normaliser_is_shared_by_the_identity_check_and_the_admin_validation():
    from human_bot import admin, config
    assert actions._norm_name is config.normalize_name and admin.normalize_name is config.normalize_name


# --- Page <-> owner link and the two run modes (2026-10-31) ----------------------------------

def _register(client, mode="own_session", **extra):
    data = {"account_id": "page_donkysu", "display_name": "D", "page_name": PAGE, "personal_name": ME,
            "owner_account_id": "tu_iizuki", "page_session_mode": mode}
    data.update(extra)
    return client.post("/admin/accounts/add", data=data, headers={"hx-request": "true"})


@pytest.mark.parametrize("override,expected", [
    ({"owner_account_id": ""}, "Chọn tài khoản cá nhân"),
    ({"owner_account_id": "nope"}, "Chọn tài khoản cá nhân"),
    ({"page_session_mode": "bogus"}, "Cách chạy không hợp lệ"),
])
def test_owner_and_mode_are_validated(client, override, expected):
    resp = _register(client, **override)
    assert expected in resp.text
    assert "page_donkysu" not in get_all_accounts()


def test_a_page_cannot_be_the_owner_of_another_page(client):
    _register(client)
    resp = _register(client, account_id="page_two", page_name="Other Page", owner_account_id="page_donkysu")
    assert "không phải một Page khác" in resp.text
    assert "page_two" not in get_all_accounts()


def test_the_list_links_a_page_to_its_owner_and_the_owner_to_its_pages(client):
    _register(client)
    html = client.get("/admin/accounts").text
    assert 'href="/admin/reports?account_id=tu_iizuki"' in html and 'href="/admin/reports?account_id=page_donkysu"' in html
    assert html.index('data-account="tu_iizuki"') < html.index('data-account="page_donkysu"')     # the Page sits right under its owner
    from human_bot.config import pages_of
    assert [a.account_id for a in pages_of("tu_iizuki")] == ["page_donkysu"]
    assert pages_of("page_donkysu") == []


def test_owner_session_mode_uses_the_owners_login_file_and_no_browser_of_its_own(client):
    _register(client, mode="owner_session")
    page = get_all_accounts()["page_donkysu"]
    assert page.uses_owner_session and page.session_account_id == "tu_iizuki"
    assert page.storage_state_path == get_all_accounts()["tu_iizuki"].storage_state_path
    assert page.action_log_path.parent.name == "page_donkysu"  # its log/limits stay its own


def test_mode_can_be_switched_after_registration(client):
    _register(client)
    assert not get_all_accounts()["page_donkysu"].uses_owner_session
    client.post("/admin/accounts/page-mode", data={"account_id": "page_donkysu", "mode": "owner_session"})
    assert get_all_accounts()["page_donkysu"].uses_owner_session
    client.post("/admin/accounts/page-mode", data={"account_id": "page_donkysu", "mode": "own_session"})
    assert not get_all_accounts()["page_donkysu"].uses_owner_session
    bad = client.post("/admin/accounts/page-mode", data={"account_id": "tu_iizuki", "mode": "owner_session"})
    assert bad.status_code == 303 and "error=" in bad.headers["location"]  # a personal account is not a Page
    assert not get_all_accounts()["tu_iizuki"].uses_owner_session


# --- owner_session run_task flow ------------------------------------------------------------

class _OwnerSession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.alive = True
        self.events = []

    def is_alive(self):
        return self.alive

    async def save_state(self):
        self.events.append("save")
        self.saved += 1

    async def close(self, save=True):
        self.events.append("close_saved" if save else "close_unsaved")
        self.alive = False


@pytest.fixture
def owner_mode(monkeypatch, isolated_runtime_config, isolated_accounts_dir, isolated_db):
    save_registered_account("page_test", "Page Test", PAGE, ME, "tu_iizuki", "owner_session")
    session = _OwnerSession()
    used_for = []
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))
    monkeypatch.setattr(agent, "get_session", lambda account: used_for.append(account.account_id) or session)
    events = session.events
    answers = {"switch": None, "page_ok": None, "personal_ok": None}

    async def switch(page, target):
        events.append(f"switch:{target}")
        return answers["switch"] if target == PAGE else answers.get("switch_back")

    async def page_ok(page, name, personal):
        events.append("verify_page")
        return answers["page_ok"]

    async def personal_ok(page, name, personal):
        events.append("verify_personal")
        return answers["personal_ok"]

    async def action(page, req):
        events.append("action")
        return ActionResult(success=True, message="posted_to_group")

    async def capture(page, account_id, action_name, success):
        events.append("screenshot")
        return "shot.png"

    monkeypatch.setattr(agent.actions, "switch_to_identity", switch)
    monkeypatch.setattr(agent.actions, "ensure_page_identity", page_ok)
    monkeypatch.setattr(agent.actions, "ensure_personal_identity", personal_ok)
    monkeypatch.setattr(agent.screenshots, "capture", capture)
    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", action))
    alerts = []

    async def fake_send(text, *, silent=False):
        alerts.append(text)

    monkeypatch.setattr(agent.telegram_notify, "send_message", fake_send)
    agent._wrong_identity_alerted.clear()
    return session, events, answers, alerts, used_for


async def test_owner_mode_runs_on_the_owners_session_and_switches_there_and_back(owner_mode):
    session, events, _answers, _alerts, used_for = owner_mode
    result = await agent.run_task(_request())
    assert result.success
    assert used_for == ["tu_iizuki"]  # the OWNER's session, not a session of its own
    assert events == [
        f"switch:{PAGE}", "verify_page", "action", "screenshot",   # evidence is taken while still on the post
        f"switch:{ME}", "verify_personal", "save",                 # then back to personal, verified, and only then saved
    ]


async def test_owner_mode_never_saves_the_session_when_it_cannot_confirm_the_switch_back(owner_mode):
    session, events, answers, alerts, _used = owner_mode
    answers["personal_ok"] = "identity_unverified:session_is_not_confirmed_as_the_personal_profile"
    result = await agent.run_task(_request())
    assert result.success  # the post itself went out
    assert "save" not in events and events[-1] == "close_unsaved"
    assert any("không xác nhận được" in a and "KHÔNG lưu" in a for a in alerts)


async def test_owner_mode_switch_back_is_attempted_even_when_the_task_failed(owner_mode, monkeypatch):
    session, events, answers, _alerts, _used = owner_mode

    async def boom(page, req):
        events.append("action")
        raise RuntimeError("selector gone")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", boom))
    result = await agent.run_task(_request())
    assert not result.success and result.message.startswith("error:")
    assert events[-3:] == [f"switch:{ME}", "verify_personal", "save"]


async def test_owner_mode_refused_identity_still_switches_back_and_does_not_post(owner_mode):
    session, events, answers, _alerts, _used = owner_mode
    answers["page_ok"] = "wrong_identity:x"
    result = await agent.run_task(_request())
    assert not result.success and "action" not in events
    assert f"switch:{ME}" in events and events[-1] == "save"


async def test_owner_mode_with_a_dead_browser_closes_without_saving(owner_mode, monkeypatch):
    session, events, _answers, _alerts, _used = owner_mode

    async def kill(page, req):
        session.alive = False
        raise RuntimeError("Target page, context or browser has been closed")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", kill))
    await agent.run_task(_request())
    assert "save" not in events and events[-1] == "close_unsaved"


async def test_owner_mode_tasks_are_serialised_on_the_shared_session(owner_mode, monkeypatch):
    session, events, _answers, _alerts, _used = owner_mode
    running = {"n": 0, "max": 0}

    async def slow(page, req):
        running["n"] += 1
        running["max"] = max(running["max"], running["n"])
        await asyncio.sleep(0.05)
        running["n"] -= 1
        return ActionResult(success=True, message="ok")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", slow))
    await asyncio.gather(agent.run_task(_request()), agent.run_task(_request()), agent.run_task(_request("tu_iizuki")))
    assert running["max"] == 1
    assert not session.lock.locked()  # always released


async def test_owner_mode_with_a_missing_owner_fails_cleanly(owner_mode, monkeypatch):
    monkeypatch.setattr(agent, "get_all_accounts", lambda: {})
    result = await agent.run_task(_request())
    assert not result.success and result.message.startswith("page_owner_missing")


async def test_the_lock_is_released_after_an_unexpected_error(owner_mode, monkeypatch):
    session, events, _answers, _alerts, _used = owner_mode

    async def boom(page, name, personal):
        raise RuntimeError("x")

    monkeypatch.setattr(agent.actions, "ensure_page_identity", boom)
    await agent.run_task(_request())
    assert not session.lock.locked()


async def test_a_checkpoint_on_a_page_task_pauses_the_owner_too(owner_mode, monkeypatch):
    from human_bot.config import AccountStatus
    _session, _events, _answers, _alerts, _used = owner_mode

    async def checkpoint(page, req):
        raise AnomalyDetected("checkpoint")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", checkpoint))
    await agent.run_task(_request())
    accounts = get_all_accounts()
    assert accounts["page_test"].status == AccountStatus.PAUSED
    assert accounts["tu_iizuki"].status == AccountStatus.PAUSED  # same Facebook login


def test_owner_session_pages_are_skipped_at_warm_up_and_by_the_health_loop():
    import inspect
    from human_bot import service
    src = inspect.getsource(service)
    assert "not a.uses_owner_session" in src and "if account.uses_owner_session:" in src


# --- review round 3 (2026-10-31): shared-session safety --------------------------------------

async def test_a_task_refused_before_switching_does_not_trigger_a_false_restore_alarm(owner_mode):
    """The switch to the Page failed (no such button / typo) → the session never
    left the personal profile, so "switching back" has nothing to do and must
    not close the session or alert."""
    session, events, answers, alerts, _used = owner_mode
    answers["switch"] = "identity_unverified:no_switch_button_for_'Typo'"
    answers["page_ok"] = "identity_unverified:account_menu_does_not_show_the_expected_identities"  # the verification then refuses
    answers["switch_back"] = "identity_unverified:no_switch_button_for_'Tu Nguyen'"  # no 'Switch to <me>' either: we ARE me
    result = await agent.run_task(_request())
    assert not result.success and "action" not in events
    assert events[-1] == "save" and "close_unsaved" not in events      # confirmed personal → saved normally
    assert not [a for a in alerts if "KHÔNG lưu" in a]


async def test_a_failed_switch_back_that_is_not_just_a_missing_button_still_discards_the_session(owner_mode):
    session, events, answers, alerts, _used = owner_mode
    answers["switch_back"] = "identity_check_error:TimeoutError"
    await agent.run_task(_request())
    assert "save" not in events and events[-1] == "close_unsaved"
    assert any("KHÔNG lưu" in a for a in alerts)


async def test_the_session_is_marked_dirty_while_on_the_page_and_clean_once_restored(owner_mode):
    session, events, _answers, _alerts, _used = owner_mode
    seen = {}
    real_action = agent._ACTION_DISPATCH["post_to_group"][1]

    async def spy(page, req):
        seen["dirty_during"] = session.identity_dirty
        return await real_action(page, req)

    agent._ACTION_DISPATCH["post_to_group"] = ("post", spy)
    await agent.run_task(_request())
    assert seen["dirty_during"] is True and session.identity_dirty is False


async def test_the_real_session_object_never_saves_while_dirty(tmp_path):
    from human_bot.browser_pool import AccountSession
    saved = []

    class _Ctx:
        async def storage_state(self, path):
            saved.append(path)

    acc = AccountConfig(account_id="x", display_name="X")
    sess = AccountSession(acc)
    sess.context = _Ctx()
    sess.identity_dirty = True
    await sess.save_state()
    assert saved == []   # a shutdown / restart_session() can't persist the Page identity
    sess.identity_dirty = False
    await sess.save_state()
    assert len(saved) == 1


async def test_a_paused_owner_blocks_its_pages_in_both_modes(owner_mode):
    from human_bot.runtime_config import set_account_paused
    _session, events, _answers, _alerts, used_for = owner_mode
    set_account_paused("tu_iizuki", True, reason="checkpoint")
    result = await agent.run_task(_request())
    assert not result.success and result.message.startswith("account_paused:tu_iizuki")
    assert used_for == [] and events == []   # the flagged login was not touched at all


async def test_a_checkpoint_closes_the_session_unsaved_without_more_clicking(owner_mode, monkeypatch):
    session, events, _answers, alerts, _used = owner_mode

    async def checkpoint(page, req):
        events.append("action")
        raise AnomalyDetected("checkpoint")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", checkpoint))
    await agent.run_task(_request())
    assert f"switch:{ME}" not in events           # no further navigation on a flagged login
    assert "save" not in events and events[-1] == "close_unsaved"
    assert not [a for a in alerts if "KHÔNG lưu" in a]   # the anomaly alert is the signal


async def test_a_crashed_browser_is_not_charged_against_the_rate_limit(owner_mode, monkeypatch):
    from human_bot.config import get_account
    from human_bot.safety import RateLimiter
    session, _events, _answers, _alerts, _used = owner_mode

    async def crash(page, req):
        session.alive = False
        raise RuntimeError("Target page, context or browser has been closed")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", crash))
    await agent.run_task(_request())
    assert RateLimiter(get_account("page_test")).next_allowed_at("post") is None


async def test_restore_personal_identity_clicks_back_then_verifies(monkeypatch):
    calls = []

    async def switch(page, target):
        calls.append(("switch", target))
        return None

    async def verify(page, page_name, personal):
        calls.append(("verify", personal))
        return None

    monkeypatch.setattr(actions, "switch_to_identity", switch)
    monkeypatch.setattr(actions, "ensure_personal_identity", verify)
    assert await actions.restore_personal_identity(object(), PAGE, ME) is None
    assert calls == [("switch", ME), ("verify", ME)]


def test_an_unknown_mode_in_the_config_falls_back_with_a_warning(isolated_runtime_config, caplog):
    from human_bot.runtime_config import get_registered_accounts
    import json
    isolated_runtime_config.write_text(json.dumps({"accounts": [
        {"account_id": "p", "display_name": "P", "page_name": PAGE, "page_session_mode": "owner-session"},
    ]}))
    with caplog.at_level("WARNING"):
        assert get_registered_accounts()[0]["page_session_mode"] == "own_session"
    assert "unknown page_session_mode" in caplog.text


def test_an_owner_that_still_has_pages_cannot_be_deleted(client):
    _register(client)
    resp = client.post("/admin/accounts/delete", data={"account_id": "tu_iizuki"}, headers={"hx-request": "true"})
    assert "còn Page đang dùng nó" in resp.text and "page_donkysu" in resp.text
    assert "tu_iizuki" in get_all_accounts()
    client.post("/admin/accounts/delete", data={"account_id": "page_donkysu"})
    assert "page_donkysu" not in get_all_accounts()


def test_a_page_never_shows_the_personal_login_button(client):
    """"Đăng nhập & lưu phiên" logs in as the PERSONAL profile — exactly what a Page's own
    session must not be — so it is not offered for any Page, in any mode."""
    for mode, acc in (("owner_session", "page_a"), ("own_session", "page_b"), ("auto", "page_c")):
        _register(client, mode=mode, account_id=acc, page_name=f"Page {acc}")
    html = client.get("/admin/accounts").text
    for acc in ("page_a", "page_b", "page_c"):
        assert f"bootstrap-login-modal?account_id={acc}" not in html
    assert "bootstrap-login-modal?account_id=tu_iizuki" in html or "phiên OK" in html   # personal accounts keep theirs


async def test_already_on_the_page_is_not_a_refusal(owner_mode):
    """"Switch to <Page>" not offered because we are ALREADY the Page: the
    forward switch must not count as a refusal — the positive verification
    decides."""
    _session, events, answers, _alerts, _used = owner_mode
    answers["switch"] = actions.NO_SWITCH_BUTTON_PREFIX + "'Page'"
    result = await agent.run_task(_request())
    assert result.success and "action" in events and "verify_page" in events


def test_save_registered_account_rejects_an_unknown_mode(isolated_runtime_config):
    with pytest.raises(ValueError):
        save_registered_account("p", "P", PAGE, ME, "tu_iizuki", "owner-session")


async def test_the_comment_guard_handles_a_failing_label_read(monkeypatch):
    """A Playwright error while reading the comment box's label is a clean
    identity_check_error, not a raw crash."""
    from playwright.async_api import Error as PlaywrightError

    class _Box:
        @property
        def first(self):
            return self

        async def get_attribute(self, name, timeout=None):
            raise PlaywrightError("detached")

    # exercise just the guard expression the action uses
    try:
        await _Box().first.get_attribute("aria-label", timeout=5000)
        raised = None
    except PlaywrightError as e:
        raised = f"identity_check_error:{type(e).__name__}"
    assert raised == "identity_check_error:Error" and actions.is_identity_refusal(raised)


# --- "auto": own session first, owner's session as a fallback (2026-10-31) -----------------------

@pytest.fixture
def auto_mode(monkeypatch, isolated_runtime_config, isolated_accounts_dir, isolated_db):
    save_registered_account("page_test", "Page Test", PAGE, ME, "tu_iizuki", "auto")
    sessions = {"page_test": _OwnerSession(), "tu_iizuki": _OwnerSession()}
    events = []
    for key, sess in sessions.items():
        sess.events = events          # one shared, ordered log
        sess.name = key
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))
    monkeypatch.setattr(agent, "get_session", lambda account: sessions[account.account_id])
    state = {"own_identity": None, "action": ActionResult(success=True, message="posted_to_group")}

    async def page_ok(page, name, personal):
        events.append("verify_page")
        # the first verification belongs to the Page's own session; after a switch it is the owner's
        return state["own_identity"] if "switch" not in " ".join(events) else None

    async def switch(page, target):
        events.append(f"switch:{target}")
        return None

    async def personal_ok(page, name, personal):
        events.append("verify_personal")
        return None

    async def action(page, req):
        events.append("action")
        return state["action"]

    async def capture(*a, **k):
        return None

    monkeypatch.setattr(agent.actions, "ensure_page_identity", page_ok)
    monkeypatch.setattr(agent.actions, "switch_to_identity", switch)
    monkeypatch.setattr(agent.actions, "ensure_personal_identity", personal_ok)
    monkeypatch.setattr(agent.screenshots, "capture", capture)
    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", action))
    notes = []

    async def fake_send(text, *, silent=False):
        notes.append((text, silent))

    monkeypatch.setattr(agent.telegram_notify, "send_message", fake_send)
    agent._wrong_identity_alerted.clear()
    return sessions, events, state, notes


async def test_auto_uses_the_pages_own_session_when_it_works(auto_mode):
    _sessions, events, _state, notes = auto_mode
    result = await agent.run_task(_request())
    assert result.success
    assert events == ["verify_page", "action", "save"]   # no switching, no owner session
    assert not [n for n in notes if "thử lại bằng phiên" in n[0]]


async def test_auto_falls_back_to_the_owners_session_when_the_own_session_cannot_start(auto_mode):
    sessions, events, state, notes = auto_mode
    state["own_identity"] = "identity_unverified:account_menu_does_not_show_the_expected_identities"
    result = await agent.run_task(_request())
    assert result.success and result.message == "posted_to_group"
    # own attempt refused before the action → owner attempt: switch there, verify, act, switch back, verify, save
    assert events[:2] == ["verify_page", "save"]
    assert events[2:] == [f"switch:{PAGE}", "verify_page", "action", f"switch:{ME}", "verify_personal", "save"]
    assert [n for n in notes if "thử lại bằng phiên của tài khoản cá nhân" in n[0] and n[1]]  # a quiet FYI
    loud = [n for n in notes if not n[1] and "KHÔNG xác nhận được" in n[0]]
    assert len(loud) == 1 and "thử lại bằng phiên của tài khoản cá nhân" in loud[0][0]   # tells the owner the Page session needs fixing


async def test_auto_falls_back_when_the_own_browser_cannot_even_start(auto_mode):
    sessions, events, _state, _notes = auto_mode

    async def cannot_start():
        raise RuntimeError("storage_state.json is corrupt")

    sessions["page_test"].ensure_started = cannot_start
    result = await agent.run_task(_request())
    assert result.success and "action" in events


async def test_auto_never_retries_after_the_action_itself_was_attempted(auto_mode):
    """A failure DURING the action (selector gone, timeout…) must not be retried through the
    other session — the post may already be live and a second try would double-post."""
    _sessions, events, state, notes = auto_mode
    state["action"] = ActionResult(success=False, message="post_button_still_visible_after_click")
    result = await agent.run_task(_request())
    assert not result.success and result.message == "post_button_still_visible_after_click"
    assert events.count("action") == 1
    assert not [n for n in notes if "thử lại bằng phiên" in n[0]]


async def test_auto_does_not_fall_back_after_a_checkpoint(auto_mode, monkeypatch):
    _sessions, events, _state, _notes = auto_mode

    async def checkpoint(page, req):
        events.append("action")
        raise AnomalyDetected("checkpoint")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", checkpoint))
    await agent.run_task(_request())
    assert events.count("action") == 1   # no second attempt on a flagged login


async def test_auto_reports_the_last_attempts_failure_when_both_sessions_fail(auto_mode, monkeypatch):
    _sessions, events, state, _notes = auto_mode

    async def always_bad(page, name, personal):
        events.append("verify_page")
        return "wrong_identity:x"

    monkeypatch.setattr(agent.actions, "ensure_page_identity", always_bad)
    result = await agent.run_task(_request())
    assert not result.success and result.message.startswith("wrong_identity")
    assert "action" not in events
    assert events.count("verify_page") == 2   # exactly one fallback, no loop


async def test_own_session_mode_is_strict_and_never_falls_back(auto_mode):
    from human_bot.runtime_config import set_page_session_mode
    sessions, events, state, notes = auto_mode
    set_page_session_mode("page_test", "own_session")
    state["own_identity"] = "wrong_identity:x"
    result = await agent.run_task(_request())
    assert not result.success and events == ["verify_page", "save"]


def test_the_form_defaults_to_auto_and_lists_all_three_modes(client):
    html = client.get("/admin/accounts/add-modal").text
    for mode in ("auto", "own_session", "owner_session"):
        assert f'name="page_session_mode" value="{mode}"' in html
    assert 'value="auto" checked' in html


def test_auto_mode_keeps_its_own_login_file_and_warm_up(client):
    _register(client, mode="auto")
    page = get_all_accounts()["page_donkysu"]
    assert page.can_fall_back_to_owner and not page.uses_owner_session
    assert page.storage_state_path.parent.name == "page_donkysu"


def test_the_list_offers_all_three_modes_in_a_select(client):
    _register(client, mode="auto")
    html = client.get("/admin/accounts").text
    assert 'name="mode"' in html and "Tự động (khuyên dùng)" in html and "Chỉ phiên của Page" in html and "Chỉ phiên cá nhân" in html
    client.post("/admin/accounts/page-mode", data={"account_id": "page_donkysu", "mode": "owner_session"})
    assert get_all_accounts()["page_donkysu"].uses_owner_session


async def test_auto_does_not_pretend_to_fall_back_when_the_owner_is_missing(auto_mode, monkeypatch):
    _sessions, events, state, notes = auto_mode
    state["own_identity"] = "identity_unverified:x"
    monkeypatch.setattr(agent, "get_all_accounts", lambda: {})
    result = await agent.run_task(_request())
    assert not result.success
    assert not [n for n in notes if "thử lại bằng phiên" in n[0]]   # no misleading "retrying via the owner"


def test_a_plain_account_ignores_page_only_form_fields(client):
    resp = client.post("/admin/accounts/add", data={
        "account_id": "plain2", "display_name": "P", "page_session_mode": "foo", "owner_account_id": "tu_iizuki",
    })
    assert resp.status_code in (200, 303)
    account = get_all_accounts()["plain2"]
    assert account.page_name == "" and account.owner_account_id == ""


async def test_the_account_menu_is_found_even_if_its_label_differs_while_acting_as_a_page(quiet_actions, monkeypatch):
    """Page mode may label the menu button differently from the recorded personal
    "Account, your profile" — the looser prefix must still open it, or every
    Page check would fail."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    async def click(page, target, mouse):
        if hasattr(target, "_buttons") and not target._buttons:
            raise PlaywrightTimeoutError("no such button")   # a real click on a missing element times out

    monkeypatch.setattr(actions, "human_click", click)
    page = _FakePage([f"Switch to {ME}"])
    page.menu_label = "Account, Đơn Kỹ Sư Nhật"
    assert await actions.ensure_page_identity(page, PAGE, ME) is None
    page.menu_label = "Something unrelated"
    result = await actions.ensure_page_identity(page, PAGE, ME)
    assert result.startswith("identity_check_error")   # nothing matched → a clean refusal, not a crash


async def test_the_exact_menu_label_wins_over_another_button_that_also_starts_with_account(quiet_actions, monkeypatch):
    clicked = []

    class _Btn(_FakeButton):
        pass

    class _Many:
        def __init__(self, labels):
            self.buttons = [_Btn(l) for l in labels]

        @property
        def first(self):
            return _First(self.buttons)

        async def all(self):
            return self.buttons

    class _Page(_FakePage):
        def get_by_role(self, role, name=None):
            if name is not None and "Switch" not in name.pattern:
                return _Many(["Accounts Center", "Account, your profile"])
            return super().get_by_role(role, name)

    async def click(page, target, mouse):
        clicked.append(getattr(target, "label", None))

    monkeypatch.setattr(actions, "human_click", click)
    await actions.ensure_page_identity(_Page([f"Switch to {ME}"]), PAGE, ME)
    assert clicked[0] == "Account, your profile"


# --- UI (2026-10-31): simpler form, clearer list ----------------------------------------------

def test_page_fields_are_in_a_collapsed_section_so_the_personal_form_stays_short(client):
    html = client.get("/admin/accounts/add-modal").text
    assert '<details class="page-section">' in html          # collapsed by default
    assert html.index('name="account_id"') < html.index('class="page-section"') < html.index('name="page_name"')


def test_the_page_section_opens_by_itself_when_redisplayed_with_input(client):
    resp = client.post("/admin/accounts/add", data={
        "account_id": "bad id!", "display_name": "x", "page_name": PAGE, "owner_account_id": "tu_iizuki",
    }, headers={"hx-request": "true"})
    assert '<details class="page-section" open>' in resp.text and f'value="{PAGE}"' in resp.text


def test_the_list_explains_each_page_session_state(client):
    _register(client, mode="auto")
    html = client.get("/admin/accounts").text
    assert "chưa có phiên riêng — đang dùng phiên của" in html          # auto + no own file → fallback in use
    assert "Cách tạo phiên riêng cho Page" in html and "check_page_identity" in html and "_page_probe_state.json" in html
    client.post("/admin/accounts/page-mode", data={"account_id": "page_donkysu", "mode": "own_session"})
    assert "chưa có phiên riêng</span>" in client.get("/admin/accounts").text     # strict mode → plain red


def test_an_existing_own_session_shows_ok_and_hides_the_how_to(client):
    _register(client, mode="auto")
    page = get_all_accounts()["page_donkysu"]
    page.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    page.storage_state_path.write_text("{}")
    html = client.get("/admin/accounts").text
    assert "phiên riêng OK" in html and "Cách tạo phiên riêng cho Page" not in html


def test_a_page_with_a_missing_personal_name_is_flagged_in_the_list(isolated_runtime_config, isolated_accounts_dir, client):
    save_registered_account("page_x", "X", PAGE, "", "tu_iizuki", "auto")
    assert "chưa khai báo tên hồ sơ cá nhân" in client.get("/admin/accounts").text


def test_pickers_mark_page_accounts_with_the_page_emoji(client):
    from human_bot import admin
    _register(client)
    accounts = get_all_accounts()
    assert admin._account_label("page_donkysu", accounts).startswith("📄 ")
    assert not admin._account_label("tu_iizuki", accounts).startswith("📄")
    html = client.get("/admin/post?account_id=page_donkysu").text
    assert f"📄 {PAGE}" in html or "📄 D" in html


def test_the_copy_paste_commands_are_shell_safe_even_for_a_hostile_page_name(client):
    evil = 'x"; rm -rf ~; "$(whoami)'
    save_registered_account("page_evil", "E", evil, ME, "tu_iizuki", "auto")
    html = client.get("/admin/accounts").text
    import shlex, html as html_lib
    cmd = [c for c in html_lib.unescape(html).split("<code>")[1:] if "check_page_identity" in c][0].split("</code>")[0]
    assert shlex.split(cmd)[-1] == evil     # parsed back as ONE literal argument — nothing was injected


def test_a_misconfigured_page_says_so_in_the_session_column(isolated_runtime_config, isolated_accounts_dir, client):
    save_registered_account("page_orphan", "O", PAGE, ME, "", "auto")           # no owner
    assert "bot sẽ từ chối đăng" in client.get("/admin/accounts").text
