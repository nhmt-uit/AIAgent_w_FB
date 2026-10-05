"""
Unit tests for admin.py's _account_health_signals() and its 2 renderers
(_account_health_card_html() for /admin's home page,
_account_health_telegram_text() for the Telegram 2-way health query,
2026-10-05) — confirm both renderers stay in sync with the single shared
signal computation, since the whole point of the 2026-10-05 refactor
(see tasks.md) was "the 5-signal logic itself must only ever live in ONE
place". HTTP-level behavior of the signals themselves is already covered
by tests/test_admin_home.py; these tests go one level down, calling the
3 functions directly with a real AccountConfig instance.
"""
from __future__ import annotations

import re

from datetime import datetime, timedelta, timezone

from human_bot import admin
from human_bot.config import AccountConfig, get_all_accounts


def _account(aid="acc-a", name="Account A") -> AccountConfig:
    return AccountConfig(account_id=aid, display_name=name)


def _assert_row_rendered_in_both(icon: str, row_text: str, card_html: str, telegram_text: str) -> None:
    """A row's FIXED (non-date) text must appear verbatim in both
    renderers — but a row containing a raw ISO timestamp (see
    _account_health_signals()'s docstring, 2026-10-05) legitimately
    renders that ONE part differently per renderer: the HTML card shows
    a live viewer-local-time span (_localize_iso_timestamps_html()), the
    Telegram text shows fixed-JST text (_fmt_jst()) — so this only
    checks the prefix before the timestamp verbatim, plus that each
    renderer's own timestamp conversion is present."""
    match = admin._ISO_DT_RE.search(row_text)
    if match is None:
        assert f"{icon} {row_text}" in telegram_text
        assert row_text in card_html
        return
    prefix = row_text[: match.start()]
    assert f"{icon} {prefix}" in telegram_text
    assert admin._fmt_jst(match.group(0)) in telegram_text
    assert prefix in card_html
    assert f'data-utc="{match.group(0)}"' in card_html


def test_card_html_and_telegram_text_agree_on_neutral_account(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    account = _account()
    severity_html, card_html = admin._account_health_card_html(account.account_id, account, {}, {})
    text = admin._account_health_telegram_text(account.account_id, account, {}, {})
    severity_signals, rows = admin._account_health_signals(account.account_id, account, {}, {})

    assert severity_html == severity_signals
    for icon, row_text in rows:
        _assert_row_rendered_in_both(icon, row_text, card_html, text)


def test_card_html_and_telegram_text_agree_on_paused_account(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    from human_bot.runtime_config import set_account_paused, save_registered_account

    save_registered_account("acc-a", "Account A")
    set_account_paused("acc-a", True, reason="checkpoint thật")
    account = get_all_accounts()["acc-a"]

    _severity, rows = admin._account_health_signals(account.account_id, account, {}, {})
    _severity_html, card_html = admin._account_health_card_html(account.account_id, account, {}, {})
    text = admin._account_health_telegram_text(account.account_id, account, {}, {})

    assert any("Tạm dừng" in t for _icon, t in rows)
    for icon, row_text in rows:
        _assert_row_rendered_in_both(icon, row_text, card_html, text)


def test_card_html_and_telegram_text_agree_on_silent_and_sync_error(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    account = _account()
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    last_success_map = {"acc-a": old}
    sync_statuses = {"acc-a": {"status": "error", "last_run_at": old, "error": "boom"}}

    _severity, rows = admin._account_health_signals(account.account_id, account, sync_statuses, last_success_map)
    _severity_html, card_html = admin._account_health_card_html(
        account.account_id, account, sync_statuses, last_success_map,
    )
    text = admin._account_health_telegram_text(account.account_id, account, sync_statuses, last_success_map)

    assert any("Im lặng" in t for _icon, t in rows)
    assert any("Đồng bộ lỗi" in t for _icon, t in rows)
    for icon, row_text in rows:
        _assert_row_rendered_in_both(icon, row_text, card_html, text)


def test_account_health_card_html_dims_the_no_data_yet_rows(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    """Regression test (2026-10-05 self-review, round 2): the refactor
    that split rendering out of _account_health_card_html() dropped the
    `class="muted"` styling the pre-refactor version applied to the 3
    ⚪ "chưa có dữ liệu" rows (no browser session/sync/success yet) —
    restored by deriving it from icon == "⚪" (the icon this card only
    ever uses for that exact case)."""
    account = _account()
    _severity, card_html = admin._account_health_card_html(account.account_id, account, {}, {})
    assert card_html.count('class="muted"') == 3
    assert '<div class="muted">⚪ Chưa mở phiên trình duyệt nào</div>' in card_html


def test_account_health_card_html_shows_live_browser_local_time_span(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    """Regression test for the 2026-10-05 refactor briefly hard-coding
    fixed-JST text into this card and silently dropping the live
    viewer-local-time conversion every other date on /admin already
    gets (see _account_health_signals()'s docstring) — the HTML card
    must render a `data-local-dt` span (initLocalDateTime() in this
    module's page script swaps it to the viewer's own browser time),
    not a plain fixed-JST string."""
    account = _account()
    recent = datetime.now(timezone.utc).isoformat()
    _severity, card_html = admin._account_health_card_html(
        account.account_id, account, {}, {"acc-a": recent},
    )
    assert re.search(r'<span data-local-dt data-utc="[^"]+">', card_html)


def test_telegram_text_includes_display_name_and_account_id(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status,
):
    account = _account(aid="acc-x", name="Tài khoản X")
    text = admin._account_health_telegram_text("acc-x", account, {}, {})
    assert text.startswith("Tài khoản X (acc-x)")
