# Việc cần làm / Tiến độ dự án — AIAgent_w_FB

> File này tách ra từ `README.md` (2026-09-09) để `README.md` tập trung vào
> kiến trúc/hướng dẫn cài đặt, còn file này dùng để **theo dõi sát tiến độ
> công việc theo ngày** và làm báo cáo. Xem `README.md` để hiểu
> tổng quan hệ thống, kiến trúc, và bản đồ file `.py`.

- [x] Cài Playwright, xác nhận mở được trình duyệt thật vào facebook.com.
- [x] Tạo `docs/brand-voice.md` — **còn cần bạn tự điền nội dung thật**.
- [x] Bootstrap đăng nhập, lưu phiên cho tài khoản `troy`.
- [x] Ghi Codegen và hoàn thiện `post_to_own_profile` — **đã hoạt động**,
      đang chờ bạn chạy thử lại sau khi chuyển sang Playwright thuần
      (không cần API key AI nào nữa cho bước này).
- [x] Chạy thử lại: `python3 -m human_bot.test_run_task post_to_own_profile troy "<nội dung test>"`
      và xác nhận bài đăng thật xuất hiện trên Facebook (đã sửa xong lỗi selector trùng
      lặp `strict mode violation` gặp phải khi test — xem `docs/architecture.md` /
      lịch sử sửa lỗi trong hội thoại).
- [x] Nghiên cứu hành vi gõ sai tiếng Việt, di chuyển chuột, và khoảng chờ theo ngữ cảnh
      — xem `docs/research/human-behavior-simulation.md`.
- [x] Xây giao diện quản trị nội bộ `/admin` (`human_bot/admin.py`) — chỉnh thông số
      gõ phím không cần sửa `.env`/khởi động lại, và đăng bài không cần gõ trong
      terminal (form trực tiếp + hàng đợi file `.txt` trong `content_queue/`). Cần chạy
      `pip3 install -r requirements.txt` lại để có `python-multipart` trước khi dùng.
- [x] Viết `human_click()`/`human_mouse_move()` (di chuyển chuột kiểu Bézier trước khi
      click) và mô hình gõ sai theo từ cho tiếng Việt (backspace-retype cả từ) trong
      `human_bot/humanize.py`; thêm các khoảng chờ theo ngữ cảnh
      (`pause_after_page_load`, `pause_after_composer_open`, `pause_between_ui_steps`,
      `reading_pause`) và nối tất cả vào `post_to_own_profile` trong `actions.py`. Cả 3
      nhóm cấu hình (gõ phím / khoảng chờ / chuột) đều chỉnh được qua `/admin/config`.
      **Đã test lại bằng bài đăng thật (2026-09-03), thành công.**
- [x] Chuyển toàn bộ tài khoản bot sang giao diện Facebook **tiếng Anh** (English) —
      selector tiếng Việt ghi lúc đầu (tài khoản `troy`) không đáng tin cậy khi có
      tài khoản mới hiển thị tiếng Anh mặc định. `browser_pool.py` ép
      `locale="en-US"`, và mỗi tài khoản Facebook cũng cần tự đặt ngôn ngữ English
      trong Cài đặt — xem `docs/skills/facebook-custom-actions.md`, mục "Facebook
      UI language". `post_to_own_profile` đã được ghi lại Codegen lần 2 bằng tiếng
      Anh (tài khoản `tu_iizuki`) và xác nhận chạy thật thành công qua `/admin`.
- [x] Làm lại giao diện `/admin` (`human_bot/admin.py`) — layout dạng card, màu sắc
      nhất quán, và dropdown chọn tài khoản/hành động tự thiết kế (mở panel bên dưới
      thay vì `<select>` mặc định của trình duyệt), vẫn giữ nguyên `<select>` thật ẩn
      phía sau để form submit không đổi gì.
- [x] Test `human_bot/service.py` qua HTTP thật (`human_bot/test_service_api.py`)
      — xác nhận `GET /health`, `POST /tasks` (đường lỗi và đường thật) đều hoạt
      động; phát hiện và sửa timeout phía client quá ngắn so với thời gian đăng bài
      thật (pacing giống người cố tình chậm, có thể hơn 60s tuỳ độ dài nội dung).

## Đang tập trung tiếp theo (theo thứ tự)

- [x] **`post_to_group` — lớp 4 (`goto()` thẳng URL) đã ghi Codegen và xác nhận
      chạy thật thành công (2026-09-04)**, tài khoản `tu_iizuki`. Không có bước
      chọn audience/quyền riêng tư như `post_to_own_profile` — hiển thị theo đúng
      cài đặt của nhóm. Phát hiện "chờ duyệt" (`_PENDING_APPROVAL_TEXT_SIGNALS`
      trong `actions.py`) **vẫn chưa xác minh thật** vì nhóm dùng để ghi không bật
      duyệt bài — cần test lại với một nhóm có bật duyệt khi thuận tiện.
- [x] **`post_to_group` — 3 lớp điều hướng còn lại đã ghi Codegen và merge xong
      (2026-09-04)**, tài khoản `tu_iizuki`: lớp 1 (lối tắt đã ghim), lớp 2
      ("Your groups" — nhãn thật của UI, không phải "Groups you've joined" như
      đoán ban đầu), lớp 3 (search, cần `group_name` để tìm — lấy từ
      `/admin/groups` qua `_resolve_group_name` trong `agent.py`). Cả 3 lớp
      chỉ ghi tới bước mở khung đăng bài + gõ text mẫu rồi dừng (không đăng
      thật) vì bước đăng bài giống hệt nhau ở mọi lớp, đã xác nhận 1 lần qua
      lớp 4. Thay vì khớp theo tên nhóm hiển thị (dễ bị cắt ngắn/trùng tên),
      `post_to_group` khớp theo id/slug nhóm lấy từ href của link
      (`_click_group_by_id`) — kiểm tra trước khi bấm, rồi xác nhận lại URL
      trang đích sau khi điều hướng (`_confirms_group`) — theo đúng yêu cầu
      của owner. Cũng đã thêm bước click icon Facebook/home (ghi nhận từ cả 3
      lần ghi) làm bước chuẩn trước khi điều hướng, áp dụng luôn cho cả
      `post_to_own_profile`. Xem chi tiết trong `docs/skills/
      group-targeting.md` và docstring của `post_to_group`.
- [x] **Content Strategist Agent — bản đầu tiên đã chạy thật (2026-09-05),
      nhưng phạm vi hẹp hơn nhiều so với kế hoạch gốc ở
      `docs/agents/content-strategist.md`.** Theo yêu cầu của owner: chỉ
      cần AI viết khác nhau khi **một tin tuyển dụng đăng vào nhiều nhóm**
      (`human_bot/content_strategist.py`'s `draft_group_post_variants()`,
      gọi thẳng Anthropic Messages API qua `httpx`, không qua `human_bot/
      llm.py`) — không làm cho tường cá nhân (gõ tay, đăng 1 lần, không
      cần biến tấu) và chưa làm cho tin nhắn ứng viên (`_draft_candidate_
      reply_placeholder` trong `data_sync.py` vẫn là template). Không có
      `ANTHROPIC_API_KEY` trong `.env`, hoặc gọi API lỗi, thì tự rơi về
      đúng template cũ — không văng lỗi, không chặn lịch đăng. **Vẫn
      thiếu so với kế hoạch gốc:** chưa có `normalize_signal()` (input
      adapter), chưa có guardrail chống trùng lặp/từ cấm bằng CODE (mới
      chỉ có trong system prompt — xem Guardrail 1/2/3 trong file spec),
      và chưa mở rộng sang comment/reply ứng viên.
- [ ] Chạy lại `pip3 install -r requirements.txt` trước khi khởi động lại
      `service.py` — vừa thêm `httpx` (dùng để gọi API bên B trong
      `human_bot/data_sync.py`).
- [x] **Nâng cấp giao diện `/admin` (2026-09-04)** — vẫn Python/FastAPI
      render HTML sẵn (không tách React), thêm Tailwind Play CDN
      (`https://cdn.tailwindcss.com`, không cần build step/Node) cho toàn
      bộ phần nhìn, và htmx (`https://unpkg.com/htmx.org`) cho các trang
      có bảng/CRUD (`/admin/groups`, `/admin/schedule`, `/admin/reports`):
      lọc theo tài khoản, thêm/sửa/xoá nhóm, cập nhật/huỷ/đăng-ngay một
      bài trong lịch — tất cả chỉ thay phần nội dung liên quan, không tải
      lại cả trang. Mọi form vẫn giữ `method="post" action="..."` bình
      thường song song với `hx-post`, nên nếu htmx không tải được (JS lỗi,
      mạng chặn CDN) thì form vẫn hoạt động theo kiểu tải lại trang như
      trước — không có gì bị hỏng hoàn toàn. Tên class CSS cũ (`card`,
      `field-row`, `data-table`...) được giữ nguyên và định nghĩa lại bằng
      Tailwind `@apply`, nên hầu hết HTML sinh ra không đổi cấu trúc.
      `/admin/config` và `/admin/post` dùng chung bộ CSS mới nhưng chưa
      chuyển sang htmx (chưa cần thiết, vẫn tải lại trang khi submit).
- [x] **Xác thực (auth) cho `POST /tasks` — xong (2026-09-04).** Header
      `X-API-Key` bắt buộc khi đặt `TASKS_API_KEY` trong `.env`, so sánh bằng
      `secrets.compare_digest` (`_require_tasks_auth` trong `human_bot/
      service.py`) — cùng kiểu "không đặt thì không bắt buộc" như
      `ADMIN_USERNAME`/`ADMIN_PASSWORD` của `/admin`. Chưa đặt `TASKS_API_KEY`
      thật trong `.env` — cần làm trước khi cổng này lộ ra ngoài máy/mạng nội bộ
      (n8n, bên B, ... đều phải gửi lại đúng key này trong header).

## Đợt làm việc 2026-09-05 → 2026-09-07 — quản lý tài khoản + viết lại `/admin/post`

- [x] **Nới rộng layout `/admin` + sửa lỗi hiển thị timestamp thô (2026-09-06
      09:24).** Nới chiều rộng tối đa của khung admin thêm 1 bậc Tailwind
      (`max-w-5xl` → `max-w-6xl`, 1024px → 1152px) theo yêu cầu owner; sửa
      `_fmt_dt` — bảng "Hoạt động gần đây" ở `/admin/reports` từng in thẳng
      timestamp ISO 8601 thô (VD: `2026-09-04T08:37:54.787563+00:00`) ra màn
      hình thay vì định dạng lại, giờ hiển thị `HH:MM:SS DD-MM-YYYY`.
- [x] **Quản lý tài khoản qua `/admin/accounts`** — đăng ký tài khoản mới
      qua modal (bấm nút mới mở form, không còn nằm sẵn to đùng trên
      trang), **Tạm dừng/Kích hoạt lại** thủ công, và **Xoá** — áp dụng
      được cho MỌI tài khoản kể cả loại khai báo sẵn trong `ACCOUNTS` dict
      ở `config.py` (trước đó các tài khoản này không có nút Xoá nào cả).
      Xoá một tài khoản khai báo trong code không thể gỡ hằng số Python
      lúc đang chạy — thực chất là "ẩn" nó khỏi `get_all_accounts()` qua
      một override trong `runtime_config.json`
      (`set_account_removed`/`get_removed_account_ids`); muốn dùng lại chỉ
      cần đăng ký lại đúng `account_id` đó. Xoá cũng tự huỷ mọi bài đang
      chờ lịch của tài khoản và xoá danh sách nhóm đã lưu, không để sót
      dữ liệu tham chiếu tới tài khoản không còn tồn tại — nhưng **không**
      đụng tới `storage_state.json` (phiên đăng nhập thật).
- [x] **Viết lại hoàn toàn `/admin/post`** — trước đây là "Đăng trực
      tiếp" (gõ nội dung, bấm Đăng, chạy ngay lập tức) không khác gì tự
      vào Facebook đăng tay. Giờ là luồng "soạn & lên lịch": chia 3 tab
      (Tường cá nhân / Đăng vào nhóm / Hàng đợi nội dung); đăng nhóm hỗ
      trợ nhiều khối nội dung khác nhau, mỗi khối gán cho một tập nhóm
      riêng (kèm nút "Chọn tất cả"); giờ đăng dùng `<input
      type="datetime-local">` thật (có nút "Ngay bây giờ"/"+1 giờ"/"Ngày
      mai") thay vì gõ tay chuỗi ISO 8601. **Mọi bài đều tạo ra một
      `ScheduledTask`, không có đường nào bỏ qua `/admin/schedule`** — kể
      cả "đăng ngay" cũng chỉ là để trống giờ rồi bấm nút ở trang lịch.
      Một giờ đã chọn nhưng bị "để quên" (submit trễ, có thể rơi vào quá
      khứ) được tự kẹp về "giờ thật lúc bấm Đăng" để giữ đúng khoảng giãn
      cách giữa các bài trong cùng một lượt đăng nhiều nhóm — không đăng
      dồn cục dù người dùng chần chừ trước khi bấm.
- [x] **`/admin/schedule`** — thêm bộ lọc theo tài khoản + phân trang (20
      bài/trang) để danh sách không bị quá dài; giờ đăng hiển thị theo
      **giờ Nhật Bản** (đối tượng chính của các nhóm Facebook dự án này
      nhắm tới), tách dòng riêng, bỏ hẳn UTC khỏi màn hình. File
      `posted/failed/cancelled` cũ hơn 30 ngày (`SCHEDULE_RETENTION_DAYS`
      trong `.env`) tự động bị xoá bởi một vòng lặp nền mới trong
      `service.py`, chạy 1 lần/ngày — `pending` không bao giờ bị đụng dù
      cũ tới đâu.
- [x] **`/admin/reports`** — thêm khối tổng quan nhanh (tổng số hành
      động/thành công/thất bại/tỉ lệ %/số tài khoản có hoạt động) và bộ
      lọc theo khoảng thời gian (7/30/90 ngày/tất cả) áp dụng cho mọi
      bảng; "Hoạt động gần đây" đổi từ cắt cứng 50 dòng sang phân trang
      thật, giới hạn chiều cao khung (cuộn dọc bên trong) để không kéo
      dài cả trang; cột "Ghi chú" (thông điệp lỗi) giờ có thể bấm mở rộng
      xem toàn bộ thay vì cắt cụt 80 ký tự không cách nào xem lại.
- [x] **Toàn bộ `/admin`**: key nội bộ (tên hành động, account_id, nguồn)
      hiển thị ra màn hình giờ đổi thành nhãn tiếng Việt (`_ACTION_LABELS`,
      `_account_label()`...) thay vì in thẳng `post_to_group`/`tu_iizuki`.
- [x] **2 lỗi tìm thấy trong lúc rà soát `/admin` và đã sửa:** (1) sửa nội
      dung bài ở `/admin/schedule` từng bị cắt cụt ở 400 ký tự khi bấm
      "Lưu" — vì ô xem trước (đã cắt để hiển thị gọn) bị dùng lại làm giá
      trị ban đầu của ô sửa; (2) route đăng từ hàng đợi/tải file lên vẫn
      redirect kèm thông báo thành công nhưng trang đã ngừng đọc tham số
      đó từ lần viết lại trước — thông báo bị mất mà không ai để ý.
- [x] **Cảnh báo tài khoản đang Tạm dừng ngay trên dashboard và `/admin/post`
      (2026-09-07 11:26).** Thêm banner trên dashboard (`/admin`) liệt kê mọi
      tài khoản đang Tạm dừng, và cảnh báo riêng ở `/admin/post` khi tài
      khoản đang chọn để soạn bài là tài khoản đã Tạm dừng — không chặn việc
      lên lịch (bài vẫn xếp hàng an toàn ở `/admin/schedule`), chỉ tránh bất
      ngờ khi bài đó không tự đăng được về sau. Đồng thời làm mới lại mô tả ở
      2 thẻ link trang chủ cho `/admin/post`/`/admin/schedule` (vẫn còn mô tả
      luồng "đăng ngay lập tức" cũ trước khi viết lại).
- [x] **3 việc từng ghi "chưa làm" ở đây — xong (2026-09-07).** UI chỉnh
      giới hạn đăng bài/tốc độ mỗi tài khoản (`RateLimits`) ở
      `/admin/accounts` (modal "⏱️ Giới hạn", có khôi phục mặc định); xoá/sửa
      nhóm ở `/admin/groups` đổi sang tham chiếu theo `GroupRef.id` cố định
      thay vì vị trí (`new_group_id()` kiểm tra trùng thật, không chỉ dựa
      xác suất); nút Tạm dừng/Kích hoạt/Xoá ở `/admin/accounts` chuyển sang
      htmx, cập nhật tại chỗ như `/admin/groups`.
- [x] **Chụp screenshot bằng chứng + xác minh đăng thành công thật —
      xong (2026-09-07), NHƯNG cần bạn tự chạy thử thật để xác nhận
      selector đúng (xem ghi chú "CẦN XÁC NHẬN SỐNG" bên dưới).**
      - `TaskResult.screenshot_path` (trước đây luôn `None`) giờ chụp
        thật — **cả lúc thành công lẫn thất bại** — qua
        `human_bot/screenshots.py`'s `capture()`, gọi tập trung 1 chỗ
        duy nhất trong `run_task()` (`agent.py`), không phải sửa từng
        hàm action riêng lẻ. Lưu vào `screenshots/<account_id>/`, tự
        dọn sau 30 ngày (`SCREENSHOT_RETENTION_DAYS`) giống hệt cách
        `scheduled/` đang được dọn. `human_bot.db`'s `action_log` có
        thêm cột `screenshot_path` (tự động thêm vào DB cũ có sẵn, không
        mất dữ liệu), `/admin/reports` → "Hoạt động gần đây" có cột
        "Ảnh" bấm xem trực tiếp (`/admin/screenshot`, có chặn dò file
        ngoài phạm vi).
      - **Đồng thời sửa đúng gốc rễ của mục "Không xác minh bài đăng
        thật sự thành công" bên dưới**: `post_to_own_profile` và
        `post_to_group` (`actions.py`) trước đây chờ cứng 2 giây rồi
        luôn báo `success=True`, không kiểm tra gì — giờ **chủ động chờ
        nút "Post" biến mất khỏi màn hình** (dấu hiệu Facebook đã nhận
        submit) trong tối đa 15 giây, hết giờ mà nút vẫn còn thì báo
        thất bại thật (`post_button_still_visible_after_click`) thay vì
        đoán mò. `_attach_media` (đính kèm ảnh) cũng thêm bước chờ
        thumbnail ảnh thật sự hiện ra trong khung soạn trước khi tiếp
        tục — đúng chỗ đã từng gây sự cố thật (ảnh gắn nhầm input, báo
        thành công nhưng ảnh không lên bài).
      - **⚠️ CẦN XÁC NHẬN SỐNG:** cả 2 selector xác minh trên (nút
        "Post" biến mất, ảnh thumbnail xuất hiện) đều **chưa được ghi
        Codegen/kiểm chứng thật trên Facebook** — viết theo suy luận hợp
        lý từ cấu trúc DOM đã biết, có ghi rõ trong code
        (`# NEEDS LIVE CONFIRMATION`). Hãy `test_run_task` thử đăng 1
        bài thật (có và không có ảnh) để xác nhận không báo `False` sai
        cho một bài thật ra đã đăng thành công, trước khi tin tưởng
        hoàn toàn vào báo cáo.

## Đợt làm việc 2026-09-08 → 2026-09-09 — rate-limit theo loại hành động, đồng bộ bên B nhiều tài khoản, bỏ hàng đợi `.txt`

- [x] **Rate-gap thật sự có hiệu lực + tier theo tuổi tài khoản + cooldown sau khi
      kích hoạt lại (2026-09-08 11:27, gộp cùng commit với `comment_on_group_post`
      ở mục "Còn lại" bên dưới — trước đây tasks.md chỉ ghi phần
      `comment_on_group_post`, bỏ sót 4 phần còn lại của cùng đợt này).**
      1. `RateLimiter` giờ **thật sự** ép buộc `min_delay_seconds/max_delay_seconds`
         thành khoảng nghỉ tối thiểu giữa 2 hành động liên tiếp, từ chối thẳng task
         nếu chưa đủ giờ — trước đó 2 field này chỉ được khai báo trong code,
         **chưa từng được gọi tới ở đâu** (dead code). Đồng thời nâng mặc định lên
         1-2 giờ sau khi tham khảo thêm tài liệu bên ngoài về phát hiện bot Facebook.
      2. **`ACCOUNT_AGE_TIERS`** (`human_bot/config.py`) — 5 bộ giới hạn tốc độ dựng
         sẵn theo "tuổi" tài khoản Facebook, chọn được lúc đăng ký hoặc bằng nút
         quick-apply trong modal "⏱️ Giới hạn" ở `/admin/accounts`.
      3. **Cooldown sau khi kích hoạt lại** (`human_bot/safety_cooldown_config.py`,
         mới) — một tài khoản vừa được Kích hoạt lại sau Tạm dừng sẽ chạy ở giới
         hạn tốc độ thấp hơn trong một số ngày cấu hình được, thay vì quay lại tốc
         độ đầy đủ ngay lập tức.
      4. Ghi lại lý do + thời điểm tạm dừng, hiển thị cả 2 cùng cooldown đang hoạt
         động (nếu có) ở `/admin/accounts`; xoá tài khoản giờ cũng dọn luôn override
         rate-limit và trạng thái cooldown, không để "sống lại" khi đăng ký lại
         cùng `account_id`.
      5. Sửa nút quick-apply tier trong modal "⏱️ Giới hạn" bị render lại toàn bộ
         modal mỗi lần bấm.
- [x] **Hardening đồng bộ dữ liệu bên B (2026-09-08 18:56).**
      1. **Bật/tắt đồng bộ riêng từng tài khoản** — độc lập với Tạm
         dừng/Kích hoạt (một tài khoản ACTIVE bị tắt đồng bộ ở đây vẫn
         đăng/comment bình thường qua `/admin/post`, chỉ riêng việc tự lấy
         job/candidate mới từ bên B bị bỏ qua), kèm theo dõi trạng thái
         lần sync gần nhất theo từng tài khoản.
      2. **Ghi log ra file** — `human_bot/logging_setup.py` (mới), ghi
         `logs/human_bot.log`, thay vì chỉ có `print()`/SQLite.
      3. Sắp xếp lại `/admin` thành tab Tài khoản/Đồng bộ và tab Cấu hình
         hành vi/Đồng bộ dữ liệu cho khớp với (1).
      4. **Fix bug thật:** `apply_quiet_hours()` dồn cục nhiều bài lịch
         lại chỉ cách nhau vài phút thay vì giữ đúng khoảng giãn cách đã
         cấu hình — nguyên nhân gốc của hiện tượng bài dồn đống ngay lúc
         hết khung giờ yên tĩnh (quiet hours).
      5. Phát hiện trang "nội dung này không khả dụng" (link chết) của
         Facebook **trước khi** hành động comment timeout vì tìm mãi
         không thấy phần tử sẽ không bao giờ xuất hiện.
      6. Fix bug hiển thị: thuộc tính candidate (list, không phải string)
         bị in ra dạng Python repr thẳng vào nội dung comment; thêm field
         reply gợi ý sẵn từ bên B làm nguồn nội dung ưu tiên hàng đầu (tên
         field tạm, chờ xác nhận).
      7. Thực thi đúng giới hạn `posts_per_day` theo từng tài khoản cho
         bài tự động đăng nhóm, tràn dồn qua ngày kế tiếp nếu vượt quá,
         cộng thêm khoảng cách tối thiểu giữa 2 bài đăng cùng 1 nhóm.
      8. Vòng lặp nền poll/fire phản ứng với thay đổi cấu hình trong vài
         giây qua `asyncio.Event`, thay vì chỉ đọc lại cấu hình sau khi
         `sleep` xong (dựa trên cấu hình cũ đã lỗi thời).
- [x] **Rate-limit tách riêng theo TỪNG LOẠI hành động, không còn dùng
      chung 1 đồng hồ cho cả tài khoản (2026-09-08 20:35).** Trước đây
      `RateLimits.min_delay_seconds/max_delay_seconds` là khoảng nghỉ tối
      thiểu giữa **BẤT KỲ 2 hành động liên tiếp nào** trên 1 tài khoản —
      nghĩa là 1 comment vừa chạy xong sẽ chặn cả 1 bài đăng ngay sau đó,
      dù chúng thuộc 2 "hạn mức" khác nhau (`posts_per_day` và
      `comments_per_day` vốn đã tách riêng sẵn). Giờ khoảng nghỉ này tính
      riêng theo từng bucket `post`/`comment`/`like` (`human_bot/safety.py`
      — `RateLimiter.next_allowed_at(action_type)`), giống cách
      `posts_per_day`/`comments_per_hour` vốn đã đếm riêng theo loại. Đi
      kèm:
      1. `rate_limit_wait_message()` (mới, `safety.py`) — thông báo tiếng
         Việt kèm giờ gợi ý dời lịch (giờ Nhật Bản), dùng chung bởi
         `data_sync.py`/`admin.py`.
      2. `fire_due_tasks()` kiểm tra trước (không tốn 1 lần gọi
         Playwright/DB) nếu tài khoản còn đang bị chặn rate-limit —
         trước đây một bài kẹt rate-limit nhiều giờ sẽ bị thử lại (và ghi
         log) mỗi phút suốt thời gian chờ, giờ chỉ cập nhật banner cảnh
         báo, không thử thật cho tới khi hết hạn chặn.
      3. Bài bị chặn rate-limit (tự động lẫn bấm tay "🚀 Đăng ngay") giờ ở
         lại `pending/` kèm banner cảnh báo thay vì rơi thẳng vào
         `failed/` — lẫn với lỗi thật.
      4. `/admin/schedule`: mỗi loại hành động có icon + màu badge riêng
         (dễ phân biệt "Đăng vào nhóm" và "Comment bài trong nhóm" hơn),
         nút "📋 Copy" cho URL đích, banner cảnh báo rate-limit ngay trong
         từng dòng lịch (`ScheduledTask.last_warning`, tự xoá khi admin
         sửa lại giờ).
      5. Khoảng giãn cách ngẫu nhiên của bộ tự lên lịch
         (`comment_gap_min/max_minutes`...) giờ tự nới rộng nếu cấu hình
         hẹp hơn `RateLimits.min_delay_seconds` thật của tài khoản — trước
         đây thường hẹp hơn (10-45 phút so với 1-2h+), khiến hầu hết bài
         tự động đăng đều dính rate-limit-wait một cách vô ích.
      6. Selector khung nhập comment (`comment_on_group_post`) mở rộng
         khớp cả "comment" lẫn "answer" — xác nhận sống 2026-09-08: bài
         nhóm dạng Hỏi-Đáp (Q&A) hiển thị "Write an answer…" thay vì
         "Write a comment…", trước đó gây timeout 30s. Nút gửi vẫn CHƯA
         hỗ trợ đầy đủ dạng Q&A (composer thu gọn, không có nút text
         "Post comment" như bài thường).
- [x] **Sửa bug "đói job" nhiều tài khoản + bug quiet-hours lệch múi giờ
      (2026-09-09 17:12).**
      1. Thay `sync_once()` (chạy riêng từng tài khoản) bằng `sync_all()`
         — lấy job/candidate từ bên B **đúng 1 lần** mỗi vòng poll, chia
         công bằng (water-filling) cho mọi tài khoản active, giới hạn
         theo hạn mức riêng từng tài khoản. Bug cũ: mỗi vòng chỉ tài
         khoản **đầu tiên** xử lý mới thực sự nhận job mới — mọi tài
         khoản còn lại thấy các id đó đã bị đánh dấu "seen" nên bị đói im
         lặng.
      2. `apply_quiet_hours()` trước đó so `quiet_hour_start/end_local`
         (giờ JST) trực tiếp với giờ UTC — người dùng chọn 10:00 giờ Nhật
         có thể bị dời muộn hơn dự kiến vì 01:00 UTC rơi vào khung "yên
         tĩnh" mặc định 1-6h. Đã sửa: đổi sang giờ JST trước khi so
         sánh/kẹp giờ.
      3. Tích hợp `GET /api/candidates/{id}/reply` thật từ bên B — gọi
         ngay trước khi comment thật sự đăng (trong `fire_due_tasks()`,
         không phải lúc đồng bộ), vì bên B chỉ chạy AI soạn reply (Claude)
         đúng lúc gọi endpoint này và mỗi task chỉ chạy đúng 1 lần. Rơi về
         mẫu (template) nội bộ nếu gọi lỗi/rỗng — mẫu giờ có **10 biến thể
         ngẫu nhiên** thay vì 1 câu cố định, để candidate lặp lại không bị
         đăng đúng y hệt chữ. **Chưa có lần chạy thử/test nào cho riêng
         phần gọi `/reply` này** — không có script test, không thấy ghi
         chú xác nhận nào trong code/docs liên quan.
- [x] **Xoá hẳn tab "Hàng đợi nội dung" và `human_bot/content_queue.py`
      (2026-09-09 17:24).** Luồng thả/tải file `.txt` rồi đăng tay đã bị
      luồng lên lịch (`schedule_store.py`) thay thế hoàn toàn — mọi bài
      giờ đều qua lịch để review trước khi chạy, nên bước xếp hàng file
      riêng là dư thừa. Xoá route `/post/queue`, `/post/upload`, và xoá
      hẳn file `content_queue.py` — không còn chỗ nào phụ thuộc vào nó.

## Đợt làm việc 2026-09-09 — chọn audience khi đăng tường cá nhân, đăng nhập qua web, fingerprint, fix crash khởi động

> ⚠️ **Chưa commit (kiểm tra lại 2026-09-09).** Code của cả 4 mục dưới đây đã
> có thật trong working tree (`actions.py`, `admin.py`, `agent.py`,
> `browser_pool.py`, `data_sync.py`, `schedule_store.py`, `service.py` đang
> modified; `bootstrap_login_sessions.py`, `fingerprint.py` là file mới chưa
> add) nhưng **chưa có commit nào** cho đợt này — `git status` vẫn thấy
> "Changes not staged for commit". Đánh dấu `[x]` bên dưới nghĩa là "code đã
> viết xong", không phải "đã an toàn trong git". Nhớ commit sớm để có lưới an
> toàn, tránh mất việc nếu máy gặp sự cố.

- [x] **`post_to_own_profile` không còn ép cứng "Only me" — chọn được
      audience mỗi lần đăng.** Trước đây hàm này luôn set "Only me" cho
      MỌI bài, không có cách nào đổi. Giờ nhận tham số `audience`
      (`"public"` mặc định | `"friends"` | `"only_me"`), đi xuyên suốt
      pipeline: `TaskRequest`/`ScheduledTask`/`TaskIn` (API `/tasks`) đều
      có field `audience`; `/admin/post` có dropdown "Đối tượng xem" khi
      soạn bài tường cá nhân. Khi `audience="public"`, bước mở dropdown
      "Edit privacy" bị **bỏ qua hẳn** (không bấm chọn "Public" tường
      minh) — do đó bài sẽ đăng theo đúng audience Facebook **đang nhớ
      sẵn** cho tài khoản đó (Facebook lưu lựa chọn audience lần gần nhất
      theo từng tài khoản), không chắc chắn là Public thật. **Với tài
      khoản đã từng chạy qua bot này trước 2026-09-09** (khi mọi bài đều
      bị ép "Only me"), lần đăng "public" **đầu tiên** sau bản cập nhật
      này nhiều khả năng vẫn ra "Only me" cho tới khi đổi tay 1 lần trên
      Facebook (hoặc chạy 1 lần với `audience` khác rồi mới quay lại
      `public`). Selector cho "Friends" **chưa được xác nhận sống** —
      chỉ "Only me" từng chạy thật, xem `actions.py`.
- [x] **Đăng nhập & lưu phiên qua web `/admin/accounts`** — module mới
      `human_bot/bootstrap_login_sessions.py`, thay thế (không bắt buộc,
      `bootstrap_login.py` vẫn dùng được) cho việc tự chạy
      `python3 human_bot/bootstrap_login.py <account_id>` trong terminal.
      Tài khoản nào có badge đỏ "chưa có storage_state.json" ở
      `/admin/accounts` giờ có thêm nút "🌐 Đăng nhập & lưu phiên" → mở
      trình duyệt Chrome thật → đăng nhập thủ công (kể cả 2FA) → bấm "Đã
      đăng nhập xong, lưu phiên" → badge tự chuyển "phiên OK" ngay, không
      cần tải lại trang. **Giới hạn quan trọng: chỉ dùng được khi service
      chạy trên máy có màn hình** — cửa sổ Chrome mở ra nằm trên MÁY ĐANG
      CHẠY human_bot, không phải máy đang xem `/admin`; không dùng được
      nếu service chạy trên server từ xa/không màn hình (lúc đó vẫn phải
      dùng `bootstrap_login.py` qua SSH có forward màn hình, hoặc chạy nó
      ngay trên máy đó).
- [x] **Fix sự cố thật: service crash toàn bộ lúc khởi động nếu một tài
      khoản ACTIVE chưa có `storage_state.json`.** Phát hiện khi đăng ký
      tài khoản `tu_test2` ở `/admin/accounts` rồi khởi động
      `uvicorn human_bot.service:app` mà chưa đăng nhập —
      `warm_up()` gọi `ensure_started()` cho MỌI tài khoản active,
      Playwright's `new_context(storage_state=<path không tồn tại>)` ném
      `FileNotFoundError`, kéo sập cả tiến trình (không chỉ tài khoản đó).
      Đã sửa `human_bot/browser_pool.py`: (1) chỉ truyền `storage_state`
      khi file thật sự tồn tại, không thì context khởi động ở trạng thái
      chưa đăng nhập (giống hồ sơ Chrome mới toanh) thay vì crash; (2)
      `warm_up()` bọc `try/except` quanh từng tài khoản — một tài khoản
      lỗi không còn kéo sập các tài khoản khác hay cả service.
- [x] **Đa dạng hoá fingerprint theo từng tài khoản** — xem mục "Điểm yếu
      đã ghi nhận" bên dưới, mục chống fingerprint.

## Còn lại (chưa tới lượt ngay, nhưng đã ghi nhận — xem đánh giá 2026-09-03)

- [x] **`comment_on_group_post` — đã ghi Codegen và xác nhận sống
      (2026-09-08).** Ghi lại đúng nhóm tài khoản đã tham gia thật
      ("Việc làm Kỹ Sư Nhật Bản"), comment xác nhận hiện lên sau khi F5.
      Có thêm bước re-check anomaly khi verify submit timeout (cùng
      pattern `post_to_own_profile`/`post_to_group`).
- [~] **Ngưng làm — chưa cần thiết (quyết định 2026-09-08).** 3 hành động
      còn lại (`comment_on_friend_post`, `like_post`, `read_recent_comments`)
      không cần cho nhu cầu hiện tại — chủ dự án chủ động yêu cầu dừng,
      không phải vì vướng lỗi hay bị chặn kỹ thuật. Xem lại nếu sau này
      thật sự cần.
- [x] **Safety Monitor — hành vi #1 (tự pause khi phát hiện bất thường)
      đã làm thật (2026-09-06/07), khớp `docs/agents/safety-monitor.md`.**
      `human_bot/safety.py`'s `AnomalyDetected` (trước đây chỉ raise
      `RuntimeError` chung, dừng đúng 1 lần rồi tài khoản vẫn bị thử lại
      bình thường ở lượt sau) giờ được `agent.py`'s `run_task()` bắt riêng
      và gọi `runtime_config.py`'s `set_account_paused()` — tài khoản
      chuyển hẳn sang trạng thái Tạm dừng, **bền vững qua cả restart
      service**, chặn mọi task tiếp theo ngay từ đầu (`account_paused`),
      cho tới khi người vận hành tự tay kích hoạt lại ở `/admin/accounts`
      (trang này cũng cho tạm dừng thủ công bất cứ lúc nào, không cần chờ
      phát hiện tự động). **Vẫn thiếu so với spec:** hành vi #2 (throttle
      sớm khi gần chạm giới hạn, không chờ tới khi fail hẳn) và hành vi #3
      (báo động qua Slack/email/Telegram) — xem `docs/agents/
      safety-monitor.md` mục "Status".
- [x] **Đăng kèm ảnh/video (`media_path`) — xong (2026-09-04).**
      - Kho ảnh `media/memes/` + `human_bot/media.py` (`pick_random_meme()` chọn
        ngẫu nhiên), công tắc bật/tắt "Tự động đính kèm ảnh" ở `/admin/config`
        (mặc định BẬT). Nối vào `run_task()` trong `agent.py`: nếu
        `TaskRequest.media_path` đã có sẵn (VD: bên B tự gửi ảnh riêng cho bài đó
        — chỗ nối cụ thể còn để TODO trong `data_sync.py` vì chưa rõ tên field ảnh
        bên phía bên B) thì luôn ưu tiên dùng ảnh đó, chỉ random khi chưa có.
      - Bước Playwright thật sự đính kèm file đã ghi Codegen và merge xong
        (`_attach_media` trong `actions.py`, dùng chung cho cả `post_to_own_profile`
        và `post_to_group`): bấm "Photo/video" rồi `set_input_files` thẳng vào
        `<input type="file">` ẩn — Playwright không thao tác hộp thoại chọn file
        của hệ điều hành, mà chặn ngay cú click và set file trực tiếp. Xác nhận
        thật (live) qua composer đăng tường cá nhân; với `post_to_group` thì
        selector giống hệt nhưng **CHƯA xác nhận thật riêng** (ghi chú UNVERIFIED
        trong code) — nếu lần đăng nhóm kèm ảnh đầu tiên báo lỗi strict-mode,
        cần thu hẹp phạm vi selector giống cách các chỗ khác trong `actions.py`
        đã từng sửa.
- [~] Cân nhắc audience thật (không chỉ luôn "Only me") — **phần cốt lõi đã
      xong ở đợt 2026-09-09 phía trên** (tham số `audience`, dropdown "Đối
      tượng xem" ở `/admin/post`, xem lưu ý ⚠️ chưa commit ở đầu đợt đó); phần
      còn thiếu là **bước xác nhận an toàn trước khi mở rộng phạm vi hiển thị
      bài đăng** (VD: cảnh báo/double-check khi đổi từ Only me sang Public),
      xem docstring `post_to_own_profile` trong `actions.py`.
- [x] **Xây bộ "kéo dữ liệu từ bên B" (2026-09-04)** — `human_bot/data_sync.py`
      gọi `GET /api/jobs` (→ bài đăng nhóm) và `GET /api/candidates` (→ reply
      ứng viên); `GET /api/content` **không dùng** (dành cho fanpage, ngoài
      phạm vi hệ thống này — xem `docs/architecture.md` mục 3c). Chống trùng
      bằng cache theo ngày (`data_sync_cache/`, dựa trên `id`) + một chỉ mục
      riêng cho `attributes.contact` (tránh nhắn trùng người dù họ đăng ở
      nhiều nhóm). Lên lịch bằng `human_bot/schedule_store.py`
      (`scheduled/pending|posted|failed|cancelled/`), khoảng cách ngẫu nhiên
      nối tiếp nhau (`post_gap_*`/`comment_gap_*` trong
      `human_bot/data_sync_config.py`, chỉnh được qua `/admin/config`). Chạy
      nền bên trong `human_bot/service.py` (2 vòng lặp: lấy dữ liệu theo
      `poll_interval_minutes`, và kiểm tra bài đến giờ theo
      `due_check_interval_seconds`). **Cổng an toàn `auto_fire_enabled` mặc
      định `false`** — bộ đồng bộ vẫn lấy/chống trùng/lên lịch bình thường,
      nhưng sẽ không tự đăng lên Facebook cho tới khi bật cổng này; trong lúc
      đó, đăng thủ công từng bài qua nút "🚀 Đăng ngay" ở `/admin/schedule`.
      **(2026-09-07: cổng này đã chuyển từ `DataSyncConfig` sang
      `human_bot/scheduling_config.py` riêng — xem đánh giá bên dưới, mục
      "Điểm yếu đã ghi nhận".)**
      Nội dung bài đăng nhóm/reply hiện dùng **template placeholder** (nối
      chuỗi đơn giản, có đánh dấu rõ trong code) — **chưa phải** Content
      Strategist Agent thật, xem mục tiếp theo.
      **Cần làm trước khi dùng thật:** vào `/admin/groups` để nhập danh sách
      URL nhóm cho từng tài khoản (không cần sửa code — xem mục tiếp theo), và
      đặt `DATA_INGESTION_BASE_URL`/`DATA_INGESTION_API_TOKEN` (của **bên B**,
      dịch vụ `data-ingestion`) trong `.env`.
- [x] **Quản lý nhóm đã tham gia qua `/admin/groups`** thay vì sửa
      `human_bot/config.py` — mỗi nhóm lưu **cả tên lẫn URL**
      (`human_bot/config.py`'s `GroupRef`), không lưu URL trơ để còn biết đó
      là nhóm nào. Giao diện dạng bảng, có bộ lọc chọn tài khoản (mỗi lần chỉ
      xem/sửa nhóm của đúng tài khoản đó), cột Tên nhóm / URL nhóm, nút Sửa
      (form riêng, không sửa trực tiếp trong bảng) và Xoá (có xác nhận) cho
      từng dòng, cộng form "Thêm nhóm mới" ở cuối trang. Toàn bộ vẫn là
      Python/FastAPI thuần (HTML render sẵn từ server) — không cần React.
      Lưu vào `runtime_config.json` (đè lên danh sách mặc định trong code),
      có hiệu lực ngay. `human_bot/data_sync.py` đọc qua
      `get_joined_groups(account_id)` (`runtime_config.py`) chứ không đọc
      thẳng `account.joined_groups` nữa.
- [x] **Thêm mục quản lý lịch đăng vào `/admin`** — `/admin/schedule`: xem
      danh sách bài đang chờ (nội dung, nhóm, giờ đăng, nguồn dữ liệu), sửa
      nội dung/giờ đăng, huỷ, hoặc đăng ngay thủ công (bỏ qua
      `auto_fire_enabled`).
- [x] **Lịch sử hành động + báo cáo (2026-09-04)** — `human_bot/db.py`
      (SQLite, `human_bot.db`, dùng thẳng `sqlite3` có sẵn trong Python,
      **không cần cài thêm package nào**). Mọi lần `run_task()` chạy (đăng
      thủ công, từ hàng đợi, "Đăng ngay", tự động từ bộ đồng bộ bên B, hay
      gọi thẳng `POST /tasks`) đều được ghi lại — kể cả khi thất bại (tài
      khoản tạm dừng, action không hỗ trợ, bị rate limit) — vì tất cả đều đi
      qua đúng một hàm `run_task()` nên chỉ cần ghi log ở một chỗ.
      `/admin/reports`: bài đăng thành công theo tuần theo tài khoản, theo
      nhóm, tỉ lệ thành công/thất bại theo hành động, và nhật ký 50 hoạt
      động gần nhất — lọc được theo tài khoản.
- [ ] Cân nhắc chọn nhóm theo chủ đề (bài IT → nhóm IT, bài Tokutei →
      nhóm Tokutei...) thay vì luôn broadcast vào mọi nhóm đã tham gia —
      đang suy nghĩ thêm, xem `docs/architecture.md` mục 3c.
- [ ] Dựng workflow n8n gọi vào service này (nối toàn bộ các phần lại thành
      một luồng chạy tự động theo lịch hoặc theo trigger từ bên B).
- [ ] Về lâu dài — nếu định chạy nhiều tài khoản song song trên nhiều máy,
      `human_bot/browser_pool.py` hiện tự ghi rõ trong docstring là chỉ an
      toàn với đúng 1 process; cần tính lại kiến trúc (pool theo process
      riêng cho mỗi account, hoặc hàng đợi công việc) nếu muốn scale.

## Điểm yếu đã ghi nhận (2026-09-07) — cần cân nhắc, chưa xếp lịch làm

- [x] **3 lỗi thật đã sửa cùng đợt (2026-09-07 14:32) — trước đây tasks.md chỉ
      ghi lỗi (1), bỏ sót lỗi (2) và (3) dù cùng 1 commit.**
      1. **`auto_fire_enabled` bị "giấu" trong cấu hình sai chỗ.**
      Phát hiện qua đúng sự cố thật: một bài lên lịch thủ công ở `/admin/post`
      lúc 12:40 không tự đăng, vì cổng an toàn `auto_fire_enabled` nằm trong
      `DataSyncConfig` ("Đồng bộ dữ liệu bên B") dù nó áp dụng cho **mọi** bài
      trong lịch, kể cả bài soạn tay — người dùng tìm cấu hình "lịch đăng" sẽ
      không nghĩ tới việc lục trong mục đồng bộ bên B. Đã xử lý: tách cờ
      này ra `human_bot/scheduling_config.py` riêng (`SchedulingConfig`), có
      mục `/admin/config` riêng "Lên lịch & tự động đăng"; `runtime_config.py`
      tự đọc lại giá trị cũ đã lưu dưới key `data_sync` (nếu có) làm fallback
      một lần, để không vô tình reset về tắt cho ai đã từng bật; `.env` đổi
      tên biến thành `SCHEDULING_AUTO_FIRE_ENABLED` (vẫn đọc được
      `DATA_SYNC_AUTO_FIRE_ENABLED` cũ nếu chưa đặt biến mới); sửa luôn một
      lỗi liên quan: vòng lặp "no lịch" (`_data_sync_fire_loop` trong
      `service.py`) trước đây chỉ chạy khi `DataSyncConfig.enabled=true` — tức
      tắt hẳn "bộ đồng bộ bên B" cũng vô tình chặn luôn việc tự đăng bài lên
      lịch thủ công; giờ vòng lặp này chạy độc lập, chỉ còn phụ thuộc đúng
      `auto_fire_enabled`; thêm banner **trạng thái BẬT/TẮT hiện tại** trực
      tiếp trên `/admin/post` và `/admin/schedule` (không cần vào `/admin/config`
      mới biết), qua `_auto_fire_status_html()` trong `admin.py`.
      2. **`/admin/config` ép mọi field số về `float` khi lưu**, kể cả field
      vốn khai báo là `int` (VD: `HumanMouseConfig.min_steps/max_steps`) —
      sau đó `human_mouse_move()` crash với lỗi `'float' object cannot be
      interpreted as an integer` khi gọi `range()` ở một số khoảng cách click
      cụ thể. Sửa: cast theo đúng kiểu khai báo thật của từng field, không ép
      cứng về `float` nữa.
      3. **`browser_pool.py`'s `AccountSession` có thể kẹt vĩnh viễn ở trạng
      thái trỏ tới page/browser đã chết** (phổ biến nhất: người dùng tự đóng
      cửa sổ Chrome hiển thị khi chạy `HEADLESS=false`) — `ensure_started()`
      trước đây chỉ kiểm tra "có phải `None` không", không kiểm tra "còn sống
      thật không", nên mọi task sau đó cứ fail liên tục cho tới khi restart cả
      service. Đã thêm kiểm tra "còn sống" thật (liveness check) kèm tự đóng
      và mở lại (teardown-and-relaunch) khi phát hiện session đã chết.
      (Việc chuyển nút Tạm dừng/Kích hoạt/Xoá ở `/admin/accounts` sang htmx —
      cùng đợt commit này — đã ghi ở mục "3 việc từng ghi 'chưa làm'" phía trên.)
- [x] **Không xác minh bài đăng thật sự thành công — đã sửa (2026-09-07,
      cần xác nhận sống).** Xem chi tiết ở mục "Chụp screenshot bằng
      chứng + xác minh đăng thành công thật" phía trên (đợt
      2026-09-05 → 2026-09-07) — cùng 1 đợt sửa với việc thêm screenshot.
- [ ] **Không có cơ chế fallback khi 1 selector gãy trong lúc đăng bài.** Mỗi
      bước (mở composer, gõ nội dung, bấm Post, đính kèm ảnh) chỉ dùng đúng 1
      selector; Facebook đổi giao diện là cả hành động fail luôn. Chỉ riêng
      bước điều hướng vào group (`post_to_group`) là có chuỗi fallback 4 tầng.
- [ ] **Fallback bằng LLM đã thiết kế nhưng chưa nối vào luồng chạy thật.**
      `human_bot/llm.py` và docstring đầu `actions.py` mô tả ý định: khi
      selector ghi sẵn (Codegen) bị gãy vì Facebook đổi UI, để một AI/LLM tự
      "nhìn" trang (qua `browser-use`) và tự tìm nút bấm thay vì dựa vào
      selector cứng. Hiện **chưa có chỗ nào trong `actions.py`/`agent.py` thật
      sự gọi tới fallback này** — cần quyết định có nối vào hay không, và nếu
      có thì áp dụng cho hành động nào trước.
- [~] `comment_on_friend_post`, `like_post`, `read_recent_comments` vẫn là
      hàm rỗng (`# TODO`, chỉ `goto()` rồi báo thành công giả) — **ngưng
      làm, chưa cần thiết** (quyết định 2026-09-08, xem mục ngay phía
      trên). `comment_on_group_post` đã xong và xác nhận sống (2026-09-08).
- [x] **Sự cố thật: tài khoản `tu_iizuki` bị Facebook checkpoint
      "confirm your identity" (2026-09-07)** — xảy ra lúc đang ghi
      Codegen thủ công (comment vào 2 bài nhóm liên tiếp trong thời gian
      ngắn, cộng dồn với hoạt động tự động của bot cùng ngày). Mức độ:
      trung bình — chỉ chặn một số hành động (đăng/comment), không khoá
      hẳn tài khoản; xác minh qua app Facebook trên điện thoại là xong,
      không cần giấy tờ tuỳ thân. Đã xử lý: xác minh xong, tạm dừng tài
      khoản qua `/admin/accounts` trong lúc "hạ nhiệt" trước khi dùng lại.
      **2 phát hiện quan trọng từ sự cố này:**
      1. Cả 2 cụm chữ thật trên màn hình checkpoint ("confirm your
         identity", "unusual activity") **đã có sẵn** trong
         `ANOMALY_TEXT_SIGNALS` (`safety.py`) — xác nhận lần đầu bằng
         ảnh chụp màn hình thật, không còn là suy đoán (xem
         `docs/skills/anomaly-detection.md`). Thêm cụm thứ 3 "certain
         actions have been restricted" cho chắc.
      2. **Lỗ hổng thật sự phát hiện được, vẫn còn tồn tại (chủ đích, xem
         ghi chú của owner):** `AnomalyDetected` (auto-pause tài khoản)
         **chỉ hoạt động khi chạy qua pipeline tự động** (`run_task()`)
         — lúc thao tác tay qua Playwright Codegen (như sự cố này), hệ
         thống **không hề biết** tài khoản vừa bị cảnh báo, không tự tạm
         dừng gì cả. Nếu ngay sau đó bot tự động chạy tiếp trên đúng tài
         khoản đang bị để ý, rủi ro cao. Từng cân nhắc thêm cảnh báo vào
         hướng dẫn ghi Codegen (`facebook-custom-actions.md`) nhắc tự tay
         tạm dừng tài khoản trước khi ghi — **owner quyết định không cần
         thiết**, giữ nguyên tài liệu như cũ. Ghi lại đây để nếu sự cố
         tương tự lặp lại thì nhớ đây là rủi ro đã biết, không phải bug
         mới.
- [~] **Chống fingerprint — một phần đã làm (2026-09-09), phần lớn vẫn
      chưa.** Trước đây mọi tài khoản dùng chung y hệt 1 cấu hình
      Chromium (viewport/DPI mặc định), dù mỗi tài khoản đã có process
      Chromium riêng (`browser_pool.py`, không share browser giữa các tài
      khoản). Đã thêm `human_bot/fingerprint.py`: mỗi `account_id` được
      băm (SHA256) ra một viewport + `device_scale_factor` cố định trong
      số 5 cấu hình màn hình phổ biến ngoài đời — **ổn định qua các lần
      restart** (không đổi ngẫu nhiên mỗi lần mở, vì đổi liên tục còn là
      tín hiệu bot rõ hơn cả dùng chung 1 cấu hình), áp dụng ở cả
      `browser_pool.py` (browser chạy task thật) và
      `bootstrap_login_sessions.py` (browser lúc đăng nhập) để không lệch
      nhau. **Cố tình chưa làm, có lý do** (xem docstring đầu
      `fingerprint.py`):
      1. **user-agent**: đổi riêng `navigator.userAgent` mà không đổi
         Client Hints thật (`Sec-CH-UA-*`, `navigator.userAgentData`) của
         Chromium sẽ tạo ra sai lệch giữa 2 nguồn — bản thân đó là tín
         hiệu bot còn rõ hơn dùng UA mặc định giống nhau giữa các tài
         khoản.
      2. **timezone/geolocation**: cần khớp với IP thật (qua proxy) của
         từng tài khoản — nếu chưa có proxy riêng theo tài khoản mà đổi
         timezone thì timezone lệch IP còn tệ hơn dùng chung timezone.
      3. **proxy/IP riêng theo tài khoản** — chưa làm, nhiều tài khoản
         cùng chạy chung 1 IP nhà/VPS vẫn là tín hiệu liên kết mạnh hơn
         nhiều so với fingerprint trình duyệt; đây mới là hướng cải thiện
         có tác động thực tế lớn nhất nếu mở rộng quy mô nhiều tài khoản,
         nhưng tốn phí mua proxy nên chưa triển khai.
      Vẫn chưa dùng `playwright-stealth` hay tương đương.
- [x] **Nâng cấp mô phỏng chuột/cuộn trang (2026-09-08), sau khi nghiên cứu
      thêm bên ngoài (ghost-cursor, các bài viết về mouse-dynamics bot
      detection — xem hội thoại thêm chi tiết/nguồn):**
      1. **Dwell time khi click** — `human_click()` giờ truyền
         `delay=40-120ms` (cấu hình được, `HumanMouseConfig.click_delay_*`)
         vào `page.mouse.click()`, thay vì bấm-nhả gần như 0ms như trước —
         khoảng dừng giữa nhấn/nhả là 1 tín hiệu phân biệt người/bot khá rõ.
      2. **Đường cong tốc độ (velocity profile)** — thêm hàm easing
         `_ease_in_out()` (smoothstep) áp vào từng bước di chuyển, mô phỏng
         đúng dạng "tăng tốc → đỉnh giữa đường → giảm tốc" của chuyển động
         tay thật (định luật Fitts), thay vì tốc độ đều như trước.
      3. **Rung tay (jitter)** — mỗi điểm trung gian trên đường Bézier lệch
         ngẫu nhiên ±`HumanMouseConfig.jitter_px` (mặc định 1.5px, không áp
         dụng cho điểm đích cuối cùng) — đường cong toán học "quá sạch"
         cũng là 1 tín hiệu bị các hệ phân loại mouse-dynamics dùng.
      4. **Cuộn trang có giảm tốc** — hàm mới `human_scroll_to()`
         (`HumanScrollConfig`, mục `/admin/config` → "Cuộn trang") dùng
         `page.mouse.wheel()` nhiều bước co dần theo khoảng cách còn lại,
         thay cho `scroll_into_view_if_needed()` nhảy thẳng tức thời trước
         đây; chốt lại bằng chính hàm đó ở bước cuối để đảm bảo chính xác.
         Đã nối thẳng vào `human_click()` nên toàn bộ ~25 chỗ gọi trong
         `actions.py` tự động dùng, không cần sửa từng chỗ.
      Cả 4 điểm đều dùng API thật của Playwright (`page.mouse.*`,
      `page.keyboard.*` — lệnh CDP cấp thấp, sự kiện có `isTrusted: true`),
      **không phải** tự dựng sự kiện DOM bằng JS injection kiểu
      `dispatchEvent(new PointerEvent(...))` (kỹ thuật đó luôn cho ra
      `isTrusted: false`, không sửa được — xem ghi chú đầu file
      `human_bot/humanize.py`, mục "GIỚI HẠN KHÔNG VÁ ĐƯỢC Ở TẦNG CODE
      NÀY").
- [ ] **Đã cân nhắc và QUYẾT ĐỊNH CHƯA LÀM (2026-09-08): điều khiển chuột
      thật ở tầng hệ điều hành (OS-level, không qua CDP nữa) —** ví dụ
      `pyautogui`/`pynput` điều khiển con trỏ chuột vật lý thật thay vì
      `page.mouse.*` của Playwright. Lý do không làm, dù về lý thuyết loại
      bỏ hẳn được giới hạn "movementX/Y luôn = 0" và "không có mẫu toạ độ
      tần số cao" của CDP (xem ghi chú đầu `human_bot/humanize.py`):
      1. Máy phải luôn có 1 phiên desktop thật, mở khoá, còn màn hình —
         mất khả năng chạy nền 24/7 không người trông (máy ngủ/khoá màn
         hình là dừng hẳn).
      2. Không dùng máy song song được — chuột OS là tài nguyên vật lý
         dùng chung, con trỏ sẽ nhảy lung tung nếu ai đó dùng máy đúng lúc
         bot đang chạy.
      3. Mất khả năng chạy nhiều tài khoản song song — mỗi tài khoản hiện
         có 1 trình duyệt + 1 "chuột ảo" độc lập qua CDP; chuột OS chỉ có
         1 con trỏ vật lý, bắt buộc xếp hàng tuần tự cho mọi tài khoản.
      4. Dễ vỡ vì bất kỳ cửa sổ/thông báo nào che khuất Chrome đúng lúc
         click — trong khi CDP luôn click đúng vào tab Playwright đang
         điều khiển bất kể trên màn hình đang hiện gì.
      5. Khoá cứng vĩnh viễn vào "phải có màn hình thật" — không bao giờ
         chuyển sang chạy server không màn hình (headless) được nữa.
      Theo nghiên cứu thêm, các hệ chống bot tinh vi ngoài đời thực tế vẫn
      dùng chính cách CDP + làm mượt hành vi (đường cong có nhiễu, easing,
      dwell time — đúng 4 điểm vừa làm ở trên) và được xem là đủ tốt cho
      production; lợi ích thêm từ chuột OS thật là biên rất nhỏ so với chi
      phí vận hành ở trên. **Owner đồng ý ghi lại, sẽ tự nghiên cứu thêm,
      chưa triển khai.**
