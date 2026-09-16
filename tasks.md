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
      **⚠️ Đã thay đổi kiến trúc ở đợt 2026-09-10 phía trên** —
      `draft_group_post_variants()` (batch, gọi lúc nhận data) không còn
      được gọi ở đâu nữa (giữ lại code, không xoá), thay bằng
      `draft_single_post()` (gọi lúc đến giờ đăng); tin nhắn ứng viên
      cũng đã có nhánh AI riêng (`rewrite_candidate_reply()`) — đoạn mô tả
      trên chỉ còn đúng cho bối cảnh 2026-09-05, không phải trạng thái
      hiện tại.
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

> ✅ **Đã commit (2026-09-10).** Tách thành 4 commit riêng theo tính năng —
> `git add -p` để tách các hunk bị gộp chung file (vài chỗ phải tạm revert
> rồi khôi phục lại bằng tay để mỗi commit đứng độc lập, compile được ngay):
> - `d978a4b` — Add audience control (public/friends/only_me) for post_to_own_profile
> - `271928b` — Add web-based login flow, fix startup crash on missing storage_state.json
> - `86b9afa` — Diversify browser fingerprint (viewport/DPI) per account
> - `5db3649` — Add AI-assisted drafting for job posts and candidate replies, both toggleable (xem đợt 2026-09-10 bên dưới)

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

## Đợt làm việc 2026-09-10 — AI soạn bài job/reply ứng viên chuyển sang lúc đến giờ đăng, có bật/tắt riêng

> ✅ Đã commit — `5db3649` (cùng đợt audience/login/fingerprint ở trên, xem
> ghi chú commit hash phía trên).

- [x] **AI soạn bài tin tuyển dụng đăng nhóm — chuyển từ "lúc nhận data từ
      bên B" sang "lúc đến giờ đăng thật".** Trước đây `sync_all()` gọi
      Anthropic ngay khi vừa nhận job mới, soạn 1 lần cho tất cả nhóm cùng
      lúc (`draft_group_post_variants`, đảm bảo N nhóm chắc chắn khác chữ
      vì AI thấy hết cả N nhóm trong 1 lần gọi). Giờ `sync_all()` chỉ dùng
      template (`content_strategist.template_variants()`, không AI) để lưu
      tạm vào `ScheduledTask.content` + `job_data` (title/attributes của
      job); AI chỉ thật sự chạy trong `fire_due_tasks()`, đúng lúc bài sắp
      đăng, qua hàm mới `draft_single_post()` — 1 lần gọi/1 bài/1 nhóm,
      **không còn đảm bảo N nhóm chắc chắn khác chữ** (đánh đổi chủ dự án
      đã đồng ý — dựa vào AI tự biến tấu độc lập mỗi lần gọi, live-test
      thực tế vẫn đọc khác nhau tự nhiên). `draft_group_post_variants` cũ
      **giữ lại, không xoá**, đánh dấu "NOT CALLED ANYWHERE" — theo yêu cầu
      chủ dự án, để dùng lại nếu sau này cần bật lại kiểu batch.
- [x] **Viết lại template mẫu (nhánh không-AI) theo yêu cầu cụ thể:**
      - Câu mở đầu: bỏ dấu `[]`, đổi sang pool 8 cụm ngẫu nhiên (TÌM ĐỒNG
        ĐỘI/TÌM NHÂN SỰ/TÌM NHÂN TÀI/TÌM ỨNG VIÊN/TUYỂN GẤP/TIN TUYỂN
        DỤNG/CƠ HỘI VIỆC LÀM/CẦN TUYỂN), tự tách 2 dòng nếu ghép với title
        dài hơn 65 ký tự.
      - Địa điểm: bỏ dấu `[]` (fix bug in nguyên Python repr `['Shizuoka']`
        lên bài thật), pool 6 nhãn (Địa điểm/Địa điểm làm việc/Địa chỉ/Vị
        trí/Nơi làm việc/Khu vực làm việc).
      - Visa: mã thô bên B (`gijinkoku`...) map sang tên thông dụng tiếng
        Việt/kanji, random giữa mã gốc/tên Việt/kanji; pool 4 kiểu nhãn
        (`Visa:`/`Loại visa:`/`Hỗ trợ Visa:`/ghi liền không dấu `:`).
      - Lương: đổi qua đơn vị "man" (chia 10.000) cho lương tháng/năm bằng
        JPY, gọi ngẫu nhiên bằng "man"/"m"/"lá"/"tờ" (2 từ lóng cuối theo
        yêu cầu cụ thể); pool nhãn (Lương/Mức lương/Thu nhập/Đãi ngộ/**Về
        tay** — riêng "Về tay" chỉ ghép với cách nói "khoảng"/"~", không
        ghép "từ...đến"/"trên"). Lương giờ/ngày giữ nguyên số yên.
      - Không còn chèn link — bỏ hẳn dòng "Chi tiết: <url>", thay 1 trong
        10 câu mời nhắn tin/inbox, random.
      - Visa/lương thiếu cả 2 → gộp 1 dòng "Thông tin visa/lương — <câu
        ngắn>" (JLPT thiếu thì vẫn bỏ dòng như cũ, không gộp — theo đúng
        yêu cầu chỉ visa/lương).
- [x] **AI reply ứng viên — pipeline 3 tầng, 2 tầng sau LOẠI TRỪ LẪN NHAU
      (không bao giờ chạy cả 2):**
      1. Template có sẵn (`_draft_candidate_reply_placeholder`) — soạn lúc
         lên lịch, baseline/fallback cuối.
      2. Gọi `GET /api/candidates/{id}/reply` của bên B — chỉ gọi khi
         **KHÔNG** dùng AI riêng của mình ở bước 3 (tắt cờ, hoặc thiếu
         `ANTHROPIC_API_KEY`).
      3. AI (Anthropic) viết lại từ template — hàm mới
         `rewrite_candidate_reply()`, tối đa ~200 ký tự (chặn cứng 400),
         không chèn link, giữ đúng ý mời nhắn tin nhưng đổi cách diễn đạt.
         Chỉ chạy khi bật cờ **VÀ** có key — nếu bật cờ nhưng thiếu key,
         tự động rơi về gọi bên B (bước 2) như cũ, tránh tốn cả 2 lượt gọi
         AI cho cùng 1 reply.
- [x] **2 công tắc bật/tắt riêng ở `/admin/config` → "Đồng bộ dữ liệu bên
      B"** (`DataSyncConfig.job_post_ai_enabled` /
      `candidate_reply_ai_enabled`) — độc lập với việc có key hay không,
      đổi được ngay không cần sửa `.env`/restart. **Bug đã fix trong lúc
      làm:** 2 checkbox này lúc đầu hiện ra thành `<input type="number">`
      thay vì checkbox — do thiếu trong allowlist `_BOOL_FIELDS` ở
      `admin.py`, đã bổ sung.
- [x] **Đã test sống với AI thật (Anthropic), sau khi nạp lại credit** —
      owner xác nhận đã đăng 1 tin tuyển dụng (Kỹ sư đóng tàu/Cơ khí,
      Ehime) vào 2 nhóm khác nhau, cả 2 bài đều do AI soạn thật (không
      phải fallback template), đúng luật hệ thống prompt (không trùng
      chữ giữa 2 bài, không chèn link, tên visa/lương đúng định dạng) —
      xem 2 ví dụ nguyên văn ở `FB_Post_Assistant.md` mục 4.10.

## Đợt làm việc 2026-09-10 (tiếp) — Switch thay checkbox, đa nhà cung cấp AI

- [x] **Đổi toàn bộ checkbox bật/tắt ở `/admin/config` (cả 3 tab: Cấu hình
      hành vi / Đồng bộ dữ liệu / AI) thành switch (nút gạt)** — chỉ đổi
      giao diện, input ẩn phía dưới vẫn là `<input type="checkbox"
      name=... value="true">` y hệt cũ nên logic lưu không đổi gì. CSS mới
      `.switch`/`.switch-slider` trong `_PAGE_STYLE`, tham số `render_rows()`
      không đổi (mọi field bool giờ luôn render switch).
- [x] **Hỗ trợ nhiều nhà cung cấp AI, chọn được ngay trên Admin UI** — theo
      yêu cầu owner: trước đây tính năng AI soạn bài/reply chỉ gọi cứng
      Anthropic Messages API, dán key OpenAI/hãng khác vào ô cũ không dùng
      được (vẫn gọi `api.anthropic.com`, key sai định dạng → 401 → rơi về
      template, không báo lỗi rõ). Đã thêm:
      1. `human_bot/ai_client.py` (file mới) — điểm gọi AI duy nhất, nhận
         `(system_prompt, user_prompt, max_tokens)`, tự dispatch theo
         provider đang chọn: Anthropic (giữ nguyên request cũ), OpenAI/
         "custom" (chung 1 hàm — cùng chuẩn Chat Completions, "custom" chỉ
         khác `base_url`), Google Gemini (`generateContent` + `key=` query
         param).
      2. `human_bot/secrets_config.py` — `SecretsConfig` thêm `ai_provider`
         + 1 bộ (key, model, [base_url]) riêng cho từng provider
         (anthropic/openai/gemini/custom) thay vì chỉ 1 field
         `anthropic_api_key` như trước.
      3. `human_bot/runtime_config.py` — `get_active_ai_provider_config()`
         (mới) đọc `SecretsConfig.ai_provider` rồi trả về đúng
         key/model/base_url của provider đang chọn, fallback về
         `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` trong `.env` cho 2 provider
         đó (Gemini/custom không có env fallback — chỉ nhập được trên
         admin). `get_anthropic_api_key()` cũ đã bị xoá (không còn nơi nào
         gọi).
      4. `human_bot/content_strategist.py` — 2 hàm gọi API trùng lặp
         (`_draft_via_anthropic`, `rewrite_candidate_reply`) gộp lại dùng
         chung `ai_client.call_ai_text()`; `anthropic_key_configured()`
         đổi tên thành `ai_provider_configured()` (cập nhật luôn call site
         trong `data_sync.py`).
      5. `human_bot/admin.py` — card "🔑 API Key AI (Anthropic)" cũ đổi
         thành "🔑 Cấu hình AI": dropdown chọn provider + 1 fieldset
         key/model (custom có thêm Base URL) mỗi provider, JS thuần
         ẩn/hiện fieldset theo lựa chọn, 1 form submit lưu hết. Route
         `/admin/config/anthropic-key[/clear]` đổi thành
         `/admin/config/ai-provider` và `/admin/config/ai-provider/clear-key`
         (client gửi kèm `provider` để biết xoá key của ai).
      6. Tên model giờ nhập được trên Admin UI theo từng provider (trước
         chỉ đổi được qua env `CONTENT_STRATEGIST_MODEL`, đã bỏ biến này —
         không còn nơi nào đọc). **Lưu ý quan trọng đã báo owner:** tên
         model là định danh API, phải gõ đúng chính xác từng ký tự kể cả
         hoa/thường (vd `gpt-4o-mini`, `gemini-2.5-flash`) — gõ sai không
         crash app, chỉ rơi về fallback template (log lại lỗi thật).
      **Chưa test sống với OpenAI/Gemini/custom thật** (chỉ test logic lưu/
      đọc override bằng script, chưa có key thật của các provider này để
      gọi thử end-to-end) — cần owner tự thử với key thật trước khi coi là
      xong hẳn.
- [x] **2 điểm chỉnh theo phản hồi owner sau khi xem UI:**
      1. Ô nhập API key không có viền, khó phân biệt với nền — do
         `input[type=password]` bị thiếu trong danh sách selector CSS
         `input[type=text], input[type=number]...` ở `admin.py` (chỉ là bug
         thiếu, không phải cố ý). Đã thêm vào chung selector.
      2. Ô nhập tên model giờ gợi ý 3 model nổi bật của từng nhà cung cấp
         (Anthropic: claude-opus-4-5/claude-sonnet-4-5/claude-haiku-4-5,
         OpenAI: gpt-4o/gpt-4o-mini/gpt-4.1-mini, Gemini:
         gemini-2.5-pro/gemini-2.5-flash/gemini-2.5-flash-lite; "Tuỳ chỉnh"
         không có gợi ý vì không có "top 3" hợp lý cho 1 endpoint bất kỳ).
         **Bản đầu dùng `<select>` riêng đặt cạnh ô nhập — owner phản hồi
         hiện 2 control cùng lúc rối mắt.** Đổi sang `<datalist>` (HTML
         chuẩn): chỉ còn 1 ô input duy nhất, bấm vào hiện gợi ý thả xuống
         để chọn nhanh, nhưng vẫn gõ/sửa tự do bình thường — không khoá
         giá trị, không cần JS riêng để đồng bộ 2 control.
- [x] **Bổ sung ví dụ mẫu thật vào `FB_Post_Assistant.md` mục 4.10** — trước
      đó chỉ mô tả luật/cơ chế của template (pool câu mở đầu, cách đổi
      lương, cách gọi tên visa...), chưa có đoạn text mẫu cụ thể. Đã chạy
      trực tiếp `content_strategist._draft_job_post_placeholder()` (3 ví
      dụ: đủ thông tin, thiếu lương, lương theo giờ) và
      `data_sync._draft_candidate_reply_placeholder()` (3 ví dụ: có/không
      khu vực mong muốn, mẫu câu khác nhau trong pool 10 mẫu) để có ví dụ
      thật (không tự bịa), chèn vào ngay dưới đoạn mô tả tương ứng — mỗi ví
      dụ đều kèm chú thích ngắn giải thích quy tắc nào đang được minh hoạ.

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
- [ ] **Giới hạn số nhóm đăng bài cho mỗi bài đăng, tránh bị đánh dấu
      spam** — hiện tại `data_sync.py`'s `sync_all()` luôn phát 1 tin
      tuyển dụng vào TOÀN BỘ nhóm tài khoản đã tham gia (`get_joined_groups()`),
      không có giới hạn số nhóm/bài. Đăng cùng lúc vào quá nhiều nhóm là
      dấu hiệu spam rõ (đã có nghiên cứu trong mục 4.4-4.6 tài liệu chính
      về tần suất/khoảng cách, nhưng chưa có giới hạn riêng cho SỐ NHÓM
      mỗi lượt broadcast). Cần: (1) thêm cấu hình max số nhóm/bài đăng
      (VD ở `/admin/config`), (2) quyết định cách chọn nhóm nào trong số
      đã tham gia khi có nhiều hơn giới hạn (ngẫu nhiên? xoay vòng để mọi
      nhóm đều được phủ theo thời gian?) — liên quan tới ý "chọn nhóm
      theo chủ đề" ngay trên, có thể làm chung một đợt.
- [ ] **Kiểm tra lại phần viết lại nội dung khi đăng bài vào nhóm** —
      `content_strategist.draft_single_post()` gọi AI redraft đúng lúc
      đến giờ đăng (`fire_due_tasks()`), 2 ví dụ AI thật (Anthropic) đã
      xác nhận đăng thành công và đọc khác nhau ở mục 4.10
      `FB_Post_Assistant.md` — nhưng đó mới chỉ là kiểm tra thủ công 1
      lần. Cần rà soát kỹ hơn: nội dung viết lại có luôn đúng luật đã đặt
      (không trùng chữ giữa nhiều nhóm, không chèn link, đúng định dạng
      lương/visa, không bịa thêm thông tin ngoài dữ liệu job) trên diện
      rộng hơn (nhiều job/nhiều nhóm hơn, không chỉ 1 job mẫu), và xác
      nhận nhánh fallback template hoạt động đúng khi AI lỗi/tắt.
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

## Đợt làm việc 2026-09-10 (tiếp) — Bộ test tự động đầu tiên cho dự án

- [x] **Rà soát toàn dự án + `tasks.md` để tìm việc cần làm tiếp theo** —
      dùng agent audit toàn bộ code (không chỉ đọc tài liệu), đối chiếu
      TODO/FIXME/marker trong code với những gì đã ghi trong tasks.md/
      FB_Post_Assistant.md. Kết quả: tài liệu khớp đúng với code, không
      có gap nào bị giấu — chỉ phát hiện 1 gap MỚI chưa từng ghi ở đâu:
      **dự án hoàn toàn chưa có bộ test tự động** (chỉ có 4 script chạy
      tay cần Facebook thật, không có assertion/CI). Danh sách ưu tiên đưa
      ra: (P0) đặt `TASKS_API_KEY`/`ADMIN_USERNAME`/`ADMIN_PASSWORD` thật
      trước khi expose ra ngoài máy cá nhân; (P1) xác nhận sống các cơ chế
      verify còn "chưa test thật" đã ghi từ trước; (P2) viết test cho phần
      logic thuần — **chọn làm P2 trước**, xem bên dưới.
- [x] **Thêm bộ test tự động đầu tiên cho dự án (`pytest`), cho các phần
      logic THUẦN không cần trình duyệt/Facebook thật:**
      1. `requirements-dev.txt` (mới, tách riêng khỏi `requirements.txt` —
         chỉ cần khi phát triển/test, không cần để chạy service thật):
         `pytest`, `pytest-asyncio`.
      2. `pytest.ini` (mới): `pythonpath = .` để `import human_bot...` chạy
         được dù gọi `pytest` từ đâu, `testpaths = tests`.
      3. `tests/conftest.py` — fixture `isolated_runtime_config` monkeypatch
         `human_bot.runtime_config.RUNTIME_CONFIG_PATH` sang file tạm
         (`tmp_path`) — **quy tắc bắt buộc, không test nào được phép đụng
         vào `runtime_config.json`/`accounts/`/`data_sync_cache/` thật**
         (đã xác nhận lại bằng `md5sum runtime_config.json` trước/sau khi
         chạy toàn bộ suite — giống hệt nhau).
      4. `tests/test_safety.py` (14 test) — `human_bot/safety.py`:
         `detect_anomaly`/`is_content_unavailable` (khớp tín hiệu, không
         khớp, dấu hiệu qua URL checkpoint), và `RateLimiter` đầy đủ (chặn
         theo count cap posts/day, comments/hour+day, likes/hour; chặn/
         không chặn theo khoảng cách min_delay_seconds; `ignore_gap=True`
         chỉ bỏ qua gap chứ không bỏ qua count cap; gap tính riêng theo
         từng loại hành động — post không bị chặn bởi comment vừa chạy;
         `record()` ghi đúng khoảng `next_allowed_at`). Dùng 1 class giả
         (`_FakeAccount`, duck-type đúng interface `AccountConfig` mà
         `RateLimiter` cần) thay vì `AccountConfig` thật — log ghi vào
         `tmp_path`, không đụng thư mục `accounts/` thật.
      5. `tests/test_runtime_config.py` (14 test) — merge/fallback logic:
         không có file → dùng default code; lưu 1 field → chỉ field đó đổi;
         field lạ bị lọc bỏ khi lưu; file JSON hỏng/không phải object →
         fallback `{}` an toàn, không crash; toàn bộ logic
         `get_active_ai_provider_config()` mới thêm (override thắng env,
         Anthropic/OpenAI có env fallback, Gemini/custom không, provider lạ
         rơi về field mapping của anthropic).
      6. `tests/test_content_strategist.py` (30 test) — soạn template job
         post: đổi lương qua man/lá/tờ đúng luật (tháng/năm mới đổi, giờ/
         ngày giữ nguyên, tiền tệ khác giữ nguyên), tên visa map đúng, join
         list không còn lộ `['Shizuoka']` kiểu Python repr (lỗi thật đã sửa
         trước đây), dòng "thiếu visa/lương" gộp đúng, xuống dòng header
         quá dài, opener đúng theo INDEX NHÓM (bug cũ: theo index job) —
         cộng cả nhánh fallback AI (tắt cờ / thiếu key / AI lỗi đều rơi về
         template, không exception nào lọt ra ngoài). Dùng
         `monkeypatch.setattr(random, "choice", lambda seq: seq[0])` để
         khử ngẫu nhiên, assert đúng nội dung thay vì "một trong N khả
         năng".
      7. `tests/test_ai_client.py` (7 test, thêm ngoài kế hoạch ban đầu vì
         rẻ và đúng tinh thần "logic thuần") — dùng `httpx.MockTransport`
         (không gọi mạng thật) để xác nhận đúng URL/header/body cho cả 4
         provider (Anthropic `x-api-key`, OpenAI/custom `Authorization:
         Bearer` + đúng `base_url`, Gemini `?key=` query param), và
         `AIProviderError` khi thiếu key/model.
      **Kết quả: 65 test, chạy trong 0.35s, không có mock/thật nào đụng
      vào Facebook hay file cấu hình thật.** Chạy bằng
      `pip install -r requirements.txt -r requirements-dev.txt && pytest -q`.
- [x] **Cảnh báo lúc khởi động nếu thiếu `ADMIN_USERNAME`/`ADMIN_PASSWORD`/
      `TASKS_API_KEY`, kèm bước xác nhận y/n** — theo P0 đã ghi ở đợt audit
      trên: 3 biến này để trống thì `/admin` và `POST /tasks` chạy KHÔNG
      có xác thực nào cả (code âm thầm bỏ qua kiểm tra, không lỗi). Vì
      `.env` bị gitignore, clone/deploy dự án sang máy khác mà quên đặt
      lại 3 biến này sẽ lặp lại đúng tình trạng đó mà không có gì báo
      hiệu. Chia làm 2 hàm trong `human_bot/service.py`, cả 2 đều gọi ở
      đầu `lifespan()` mỗi lần service khởi động:
      1. `_warn_if_auth_unconfigured()` — vẫn ghi `logger.warning()` vào
         `logs/human_bot.log` như bản đầu, liệt kê đúng biến đang thiếu.
      2. `_confirm_startup_or_abort()` (mới, thêm sau khi owner phản hồi
         cảnh báo chỉ nằm trong file log thì dễ bỏ lỡ lúc đang nhìn
         terminal) — nếu có biến thiếu VÀ `sys.stdin.isatty()` là True
         (đang chạy trên terminal thật, có người ngồi gõ lệnh
         `uvicorn human_bot.service:app` và Enter): in cảnh báo ra
         `stderr` + hỏi `Vẫn tiếp tục khởi động? [y/N]:` — gõ gì khác
         "y" (kể cả Enter trống hoặc Ctrl-D/EOF) thì **dừng hẳn việc khởi
         động** (raise trong `lifespan()` trước `yield` khiến uvicorn báo
         "Application startup failed" và thoát, không phục vụ request
         nào). Nếu `stdin` KHÔNG phải terminal thật (chạy nền qua
         systemd/Docker/`nohup ... &`/CI) thì **bỏ qua hẳn việc hỏi**,
         chỉ giữ lại cảnh báo ghi log — hỏi mà không ai trả lời được sẽ
         treo service vĩnh viễn, tệ hơn cả im lặng bỏ qua như trước.
      Không tự đặt giá trị thật cho 3 biến — đó vẫn là việc chủ dự án cần
      tự làm trong `.env` khi sắp chạy ngoài máy cá nhân; tính năng này
      chỉ đảm bảo không ai vô tình bỏ lỡ việc đó.
      10 test mới trong `tests/test_service_auth_warning.py` (cảnh báo
      log — thiếu cả 3/thiếu 1 phần/đủ cả 3/chuỗi khoảng trắng tính là
      thiếu; xác nhận y/n — không hỏi khi không thiếu gì, không hỏi khi
      không phải tty, tiếp tục khi gõ "y", dừng khi gõ khác "y", dừng khi
      EOF) — tổng bộ test giờ là 75.

## Đợt làm việc 2026-09-10 (tiếp) — Tách riêng giãn cách post/comment, cấu hình lại 5 mức tuổi tài khoản

- [x] **Phát hiện nguyên nhân gốc vì sao backlog job/candidate của
      `tu_iizuki` không bao giờ giảm** (56 job/14 candidate cứ lấy đi lấy
      lại, chỉ ~8 bài/lượt được lên lịch) — soát kỹ số liệu thật
      (`scheduled/pending/`, `data_sync_cache/`) cùng owner qua nhiều bước
      hỏi đáp: `RateLimits.min_delay_seconds/max_delay_seconds` là **1
      cặp số dùng chung cho MỌI loại hành động** (post/comment/like), dù
      `comments_per_day` luôn được đặt CAO HƠN `posts_per_day` ở mọi mức —
      nên giãn cách dùng chung khiến comment về mặt toán học không thể
      nào nhét đủ số lượng vào 1 ngày, kể cả khi post thì vừa.
- [x] **Tách `min_delay_seconds`/`max_delay_seconds` thành 2 cặp riêng —
      `post_min/max_delay_seconds` và `comment_min/max_delay_seconds`**
      (`human_bot/config.py`'s `RateLimits`). `like` dùng chung cặp
      comment (dự án chưa có lịch/số riêng cho like). Cập nhật dây
      chuyền:
      1. `human_bot/safety.py` — thêm `_gap_bounds(limits, action_type)`,
         `RateLimiter.record()` gọi hàm này thay vì đọc thẳng
         `limits.min_delay_seconds`.
      2. `human_bot/data_sync.py` — `_effective_gap_minutes()` nhận thêm
         tham số `kind` ("post"/"comment") để đọc đúng cặp field, 2 nơi
         gọi (post_gap/comment_gap) truyền đúng kind của mình.
      3. `human_bot/runtime_config.py` — `EDITABLE_RATE_LIMITS_FIELDS`
         đổi tên field; `_start_resume_cooldown()` (áp dụng cấu hình hạ
         nhiệt sau khi kích hoạt lại tài khoản) set CẢ 2 cặp mới bằng
         đúng 1 cặp số của `SafetyCooldownConfig` — cooldown giữ nguyên
         không tách riêng vì vốn đã là mức thận trọng nhất.
      4. `human_bot/admin.py` — modal "⏱️ Giới hạn" ở `/admin/accounts`
         đổi 2 ô nhập giãn cách thành 4 ô (2 cho post, 2 cho comment);
         validate riêng từng cặp min ≤ max.
      5. `tests/test_safety.py` — cập nhật toàn bộ field name, thêm 1
         test mới xác nhận post và comment dùng đúng cặp giãn cách độc
         lập (min==max để loại ngẫu nhiên, assert chính xác từng giá trị)
         — tổng bộ test giờ là 76.
- [x] **Cấu hình lại cả 5 mức tuổi tài khoản theo số owner tự tính toán,
      sau khi kiểm tra tính khả thi** (owner đưa số ban đầu, tôi tính
      xem (số lượng - 1) × giãn cách tối đa có nhét vừa 1 ngày hoạt động
      hay không — quiet hours 2h-6h sáng = 20 tiếng hoạt động, trừ thêm
      10% đệm an toàn = ngân sách 18 tiếng — hầu hết các mức đều VƯỢT
      ngân sách này ở phần comment, một số mức còn vượt cả phần post):

      | Mức | Bài/ngày | Comment/ngày | Giãn cách post | Giãn cách comment |
      |---|---|---|---|---|
      | Dưới 1 tháng | 5 | 7 | 2–3.5h | 1.5–3h |
      | Dưới 3 tháng | 8 | 10 | 1.75–2.5h | 1–2h |
      | Dưới 6 tháng | 12 | 15 | 1.25–1.6h | 0.6–1.25h |
      | Dưới 12 tháng | 20 | 25 | 0.75–0.95h | 0.35–0.75h |
      | Trên 12 tháng | 30 | 35 | 0.5–0.62h | 0.25–0.5h |

      Giữ nguyên số bài/comment mỗi ngày và mức min của giãn cách owner
      đưa ra; chỉ hạ trần (max) giãn cách ở 3 mức cao hơn cho vừa ngân
      sách 18h. `comments_per_hour`/`likes_per_hour` (owner không đưa số)
      vẫn suy theo tỉ lệ như cách bảng cũ đã làm — dễ chỉnh lại sau qua
      quick-apply nếu sai. `RateLimits()` mặc định (không tier/override)
      = đúng hàng "Trên 12 tháng".
- [x] **Đổi quiet hours mặc định từ 1h-6h sáng thành 2h-6h sáng**
      (`DataSyncConfig.quiet_hour_start_local`, theo yêu cầu owner) —
      `human_bot/data_sync_config.py`.
- [x] **Migrate dữ liệu thật đang chạy** — `tu_iizuki` đang có override
      rate-limit lưu sẵn theo TÊN FIELD CŨ trong `runtime_config.json`;
      sau khi đổi tên field, override cũ sẽ bị lọc bỏ âm thầm (không
      match `EDITABLE_RATE_LIMITS_FIELDS` mới) → tài khoản sẽ vô tình rơi
      về mức LỎNG NHẤT (Trên 12 tháng) thay vì giữ đúng ý "Dưới 1
      tháng". Đã áp lại tier "Dưới 1 tháng" (số mới) cho `tu_iizuki`
      bằng đúng hàm `save_rate_limits_overrides()` admin UI dùng.
      **Sự cố thật xảy ra trong lúc làm:** khi cập nhật
      `quiet_hour_start_local`, gọi nhầm `save_data_sync_overrides()`
      với chỉ 1 field — hàm này THAY THẾ TOÀN BỘ section thay vì merge,
      xoá mất mọi override `data_sync` khác đã lưu trước đó (poll
      interval, gap minutes, 2 công tắc AI...). Phát hiện ngay lập tức
      (kiểm tra lại sau khi gọi), khôi phục đủ nguyên trạng bằng giá trị
      đã ghi nhớ trong hội thoại trước đó, không có dữ liệu nào mất vĩnh
      viễn — nhưng là lời nhắc: `save_*_overrides()` luôn cần đọc giá trị
      hiện tại trước rồi merge tay, không được gọi với chỉ 1 field.

## Đợt làm việc 2026-09-10 (tiếp) — Thêm nhãn "Nenshuu", giữ nguyên nội dung lịch khi AI đăng bài lỗi

- [x] **Thêm nhãn lương "Nenshuu"/"年収" cho lương THEO NĂM** — owner hỏi
      "Về tay" lấy ở đâu (trả lời: đã có sẵn trong `_SALARY_LABELS`,
      1 trong 5 nhãn được chọn ngẫu nhiên cho dòng lương) và đề nghị thêm
      2 từ mượn tiếng Nhật quen thuộc với cộng đồng đi làm ở Nhật. Thêm
      `_SALARY_LABELS_YEAR_EXTRA = ["Nenshuu", "年収"]`
      (`content_strategist.py`), **chỉ cộng vào pool nhãn khi
      `period == "year"`** — không thêm vào lương tháng/giờ/ngày vì
      "Nenshuu" nghĩa đúng là "thu nhập cả năm", gắn cho lương tháng sẽ
      sai nghĩa chứ không chỉ là khác văn phong. 2 test mới xác nhận: có
      xuất hiện Nenshuu/年収 khi period=year, không bao giờ xuất hiện khi
      period=month (dùng `monkeypatch` ép `random.choice` chọn phần tử
      cuối để chắc chắn test được cả trường hợp hiếm).
- [x] **Sửa lỗi thật: AI đăng bài lỗi/thiếu key thì tạo bản template MỚI
      ngẫu nhiên thay vì giữ nguyên nội dung đã hiển thị ở Lịch đăng —
      mất luôn nội dung admin đã tự tay sửa.** Owner phát hiện qua thực
      tế: sửa nội dung 1 task ở `/admin/schedule`, nhưng lúc đăng nếu bật
      công tắc AI mà AI lỗi/hết key, `draft_single_post()` gọi lại
      `_draft_job_post_placeholder()` với `variant_seed` ngẫu nhiên MỚI —
      ra một bản hoàn toàn khác, đè mất bản admin vừa sửa. Sửa bằng cách
      đổi chữ ký `draft_single_post(job, existing_content, group_name,
      ai_enabled)` — nhận thêm `existing_content` (chính là
      `task.content` hiện tại, có thể đã bị admin sửa tay), và **trả về
      nguyên `existing_content` ở MỌI nhánh không dùng được AI** (tắt
      công tắc / thiếu key / gọi AI lỗi) thay vì tự soạn lại — cùng
      nguyên tắc "không bao giờ mất nội dung đã có" mà
      `rewrite_candidate_reply()` (nhánh reply ứng viên) vốn đã áp dụng
      từ trước, giờ áp dụng nhất quán cho cả nhánh job post.
      `data_sync.py`'s `fire_due_tasks()` cập nhật lời gọi tương ứng.
      4 test cập nhật/thêm mới trong `test_content_strategist.py`
      (tắt AI / thiếu key / AI lỗi đều trả đúng nguyên `existing_content`;
      thêm 1 test xác nhận AI thành công thì vẫn dùng đúng bài AI soạn).
      **Tổng bộ test giờ là 79.**
- [x] **Xác nhận bug thật (chưa xác nhận fix) — dấu hiệu "bài chờ duyệt
      admin nhóm" chưa từng bắt được ca thật nào.** Owner đăng thật vào
      nhóm bật duyệt bài, gửi ảnh chụp toast Facebook thật: "Thanks for
      your post! It's been submitted to group admins for approval."
      Tra lại task tương ứng (`scheduled/posted/20260910T150503Z_80e521d1.result.txt`,
      account `tu_iizuki`, group "Việc làm Kỹ Sư Nhật Bản (Uy tín hàng
      đầu)") xác nhận code lúc đó trả về `posted_to_group` — KHÔNG phải
      `posted_to_group_pending_approval` — chứng minh danh sách
      `_PENDING_APPROVAL_TEXT_SIGNALS` (`actions.py`) cũ (toàn suy đoán,
      không khớp text thật) đã bỏ sót ca chờ duyệt này. `success=True`
      vẫn đúng, chỉ message sai. Đã thêm
      `"submitted to group admins for approval"` làm signal đầu tiên,
      bỏ nhãn UNVERIFIED trong comment.
- [x] **Xác nhận text + timing của fix bằng Codegen thật** — owner chạy
      `python3 -m playwright codegen ... codegen_verify_pending_approval.py`
      trên đúng group đó, đăng 1 bài test. File ghi lại
      `page.get_by_text("Thanks for your post! It's").click()` — chứng
      minh text toast nằm trong DOM dạng text thường, định vị được bằng
      Playwright (không phải canvas/ảnh). Owner quan sát toast tồn tại
      ~3-5 giây trước khi tự ẩn; code đọc `page.inner_text("body")`
      ngay sau khi Post button ẩn (gần tức thời), nên nằm gọn trong
      khung đó. Text + timing của fix hợp lý về nguyên lý.
      **Vẫn thiếu bước cuối:** chưa chạy 1 task `post_to_group` thật
      qua chính bot (end-to-end, không phải Codegen tay) để xác nhận
      `result.txt` ra đúng `posted_to_group_pending_approval`.
- [ ] **(TẠM HOÃN — owner chủ động rewind, chờ xác nhận có phải lỗi code
      thật không)** `comment_on_group_post` timeout 30s khi
      `page.goto(post_url)` vào permalink bài trong nhóm
      (`Page.goto: Timeout 30000ms exceeded... waiting until "load"`,
      task thật gây lỗi: `scheduled/failed/20260910T114429Z_c2545f89`,
      group "vieclamtimnguoi", account đã tham gia nhóm — không phải
      lỗi chưa join). Chẩn đoán ban đầu: Facebook giữ kết nối nền gần
      vô hạn trên trang permalink, nên sự kiện `"load"` mặc định của
      Playwright có thể không bao giờ bắn dù nội dung đã hiển thị
      xong. Từng áp dụng fix (đổi `wait_until="domcontentloaded"` + dời
      `pause_after_page_load()` lên trước 2 bước kiểm tra
      anomaly/unavailable) nhưng **owner chủ động rewind lại
      `actions.py` (2026-09-10)** — chưa chắc chắn đây là lỗi code thật
      hay chỉ mạng/Facebook chậm nhất thời, muốn xem task đó chạy lại
      với code gốc trước khi quyết định vá.

      **Đã thử "Đăng lại" 1 lần (2026-09-10) — KHÔNG phải bằng chứng
      hợp lệ, đã sửa nhầm lẫn của assistant ở đây:** tra
      `human_bot.db`'s `action_log` (đầy đủ hơn
      `scheduled/failed/*.result.txt`, vốn chỉ ghi lại đúng lần fail
      GỐC, không cập nhật khi repost vì "Đăng lại" tạo task mới qua
      `run_task()` chứ không đụng file cũ) cho thấy: lần "Đăng lại" đó
      (`source=manual`, 12:46:20 UTC) bị CHÍNH rate-limiter của hệ
      thống chặn (`rate_limited:min_delay_seconds gap not elapsed yet,
      wait ~5280s`) — chưa hề chạm tới `page.goto()`. Assistant lúc đó
      nhầm mtime của file cũ (chỉ phản ánh lần fail gốc lúc 12:25:04
      UTC) là kết quả của lần repost, kết luận sai "timeout lặp lại".
      **Thực tế mới có đúng 1 lần fail thật chạm goto** (id #62 trong
      `action_log`, 12:25:04 UTC, `schedule_auto`) — cần thử "Đăng lại"
      thêm 1 lần nữa SAU khi qua mốc rate-limit (~14:14 UTC hôm đó) để
      mới thật sự có dữ liệu thứ 2 kiểm chứng có lặp lại hay không.
- [x] **Sửa lỗi thật: comment lên lịch quá gần nhau giữa các lần poll
      `sync_all()` khác nhau — thêm "kẹp sàn" cho comment scheduling.**
      Owner phát hiện 3 comment cùng tài khoản chỉ cách nhau 5-20 phút
      dù `comment_min/max_delay_seconds` đặt 90-180 phút. Nguyên nhân:
      `next_comment_time` (`data_sync.py`) chỉ cộng dồn ngẫu nhiên
      TRONG PHẠM VI 1 LẦN `sync_all()` — sang lần poll kế (~15 phút
      sau) khởi tạo lại từ `now` mới, không biết gì về comment đã lên
      lịch từ lần poll trước.
      Thêm `_last_scheduled_comment_time(account_id)` (soi comment
      pending/posted từ các lần poll trước, kẹp theo TÀI KHOẢN — khác
      `_last_scheduled_time_per_group()` của bài đăng vốn kẹp theo
      từng NHÓM, vì rate-limit comment enforce theo tài khoản) và kẹp
      thêm `RateLimiter(account).next_allowed_at("comment")` — sàn
      enforcement thật từ lần comment gần nhất đã THỰC SỰ đăng xong.
      Cả 2 sàn áp dụng ngay sau khi tính `next_comment_time` ban đầu
      trong `sync_all()`, trước vòng lặp gán cho từng candidate.
      79 test hiện có vẫn pass (chưa có test riêng cho `data_sync.py`).
      **Vẫn CHƯA xử lý** (theo yêu cầu owner, chỉ ghi nhận lại): va chạm
      giữa gap lên lịch (x₁, biết trước) và gap enforcement thật
      (x_safety, chỉ random SAU KHI comment trước đăng xong, không thể
      biết trước ở thời điểm lên lịch) — xem chi tiết + các hướng đã
      bàn (A: chấp nhận tự dò lại / B: gộp 2 lớp random / cố định
      x_safety = min) ở FB_Post_Assistant.md mục 4.13.

## Đợt làm việc 2026-09-11 — Phân trang Lịch đăng

- [x] **Thêm nút "Trang đầu"/"Trang cuối" + ô nhảy tới trang bất kỳ ở
      `/admin/schedule`** — owner phản ánh chỉ có 2 nút Trang trước/Trang
      sau, bất tiện khi muốn từ trang 1 nhảy thẳng tới trang 10 hoặc
      trang cuối. Thêm `«« Đầu`/`Cuối »»` (tái dùng `_schedule_page_link()`
      có sẵn) và 1 form nhỏ (ô số + nút "Đi") gửi GET
      `/admin/schedule?page=N` qua htmx — `_schedule_content_html()` đã
      tự kẹp `page` vào `[1, total_pages]` từ trước (dòng
      `page = min(max(page, 1), total_pages)`) nên nhập số ngoài phạm vi
      tự động về đúng trang gần nhất, không cần validate thêm.
      **Chưa xác nhận sống** — service thật đang chạy (24/7, đã nạp code
      cũ vào bộ nhớ), cần restart mới thấy hiệu lực trên trang thật;
      chưa restart vì đây là service đang có phiên trình duyệt Facebook
      sống, để owner quyết định thời điểm.
- [x] **Làm đẹp ô "đi tới trang" + thêm chọn số item/trang** (owner phản
      hồi: ô nhập số trang lúc mới thêm chưa đẹp, và không biết/chỉnh
      được mỗi trang có bao nhiêu item). Gộp "Trang X/Y" + ô nhập + nút
      "Đi" thành 1 khối duy nhất kiểu pill ("Trang `[_]`/23 `[Đi]`",
      nền xám nhạt bo góc — cùng ngôn ngữ hình ảnh với các khối khác
      trong `admin.py`) thay vì 3 phần tử rời rạc.
      Thêm `_SCHEDULE_PAGE_SIZE_CHOICES = (10, 20, 50, 100)` + dropdown
      "Hiển thị" cạnh bộ lọc tài khoản — chọn thẳng, không cần form
      submit riêng (`hx-trigger=change`). `page_size` xuyên suốt mọi
      nơi `page`/`account_id` đã có: `_schedule_content_html()`,
      `_schedule_page_link()`, `_schedule_form_filter()` (giờ trả
      3-tuple thay vì 2), `_schedule_redirect()` (đã nhận **kwargs sẵn
      nên không cần đổi chữ ký), route `schedule_list`, và 3 handler
      `schedule_update`/`schedule_cancel`/`schedule_fire_now` +
      `_fire_now_confirm_modal_html()` — để đổi trang/thao tác (Lưu,
      Huỷ, Đăng ngay) không âm thầm reset số item/trang về mặc định.
      2 dropdown (tài khoản + số item/trang) dùng `hx-include` trỏ vào
      nhau qua id để đổi cái này không làm mất giá trị đang chọn của
      cái kia. `_clamp_schedule_page_size()` chặn giá trị lạ (VD sửa
      tay URL) rơi về mặc định 20 thay vì render hàng nghìn item.
      Verify bằng cách gọi thẳng `_schedule_content_html()` qua Python
      (không cần trình duyệt) — `page_size=10` → đúng 23 trang cho
      227 task pending thật; `page=999` → tự kẹp về trang 23. 79 test
      vẫn pass. **Chưa xác nhận trên UI thật** — cùng lý do chưa restart
      service ở mục ngay trên.
- [x] **Nới rộng ô nhập số trang** (`/admin/schedule`, owner phản hồi
      ô nhập số quá hẹp) — `width:48px` → `64px`, đủ chỗ nhập 3-4 chữ số.
- [x] **Áp dụng y hệt bộ phân trang (Đầu/Cuối + ô nhảy trang dạng pill +
      chọn số item/trang) sang `/admin/reports`'s bảng "Hoạt động gần
      đây".** Thêm `_REPORTS_PAGE_SIZE_CHOICES = (10, 15, 30, 50, 100)`
      + `_clamp_reports_page_size()` (giữ mặc định 15 như cũ, không đổi
      hành vi khi không truyền `page_size`). Cùng cách xuyên suốt
      `page_size` như `/admin/schedule`: `_reports_content_html()`,
      closure `_recent_page_link()` (thêm Đầu/Cuối), route
      `reports_page`, handler `reports_repost` (parse + truyền qua mọi
      nhánh redirect/re-render), `_repost_button_html()`'s hidden
      field. 3 dropdown lọc (tài khoản/khoảng thời gian/số item) dùng
      `hx-include` trỏ chéo lẫn nhau qua id để đổi 1 cái không làm mất
      2 cái còn lại. Verify qua Python trực tiếp: 42 mục thật,
      `page_size=10` → đúng 5 trang; `page=999` → kẹp về trang 5;
      `page_size=999` (không hợp lệ) → tự về mặc định 15 → 3 trang;
      không truyền `page_size` → vẫn ra 3 trang y hệt hành vi cũ. 79
      test vẫn pass. **Chưa xác nhận trên UI thật** — cùng lý do chưa
      restart service.
- [x] **Owner restart service, xác nhận sống 2 mục trên (đã thấy trên
      UI thật) — sau đó phản hồi 3 điểm tiếp theo về thiết kế
      `/admin/reports`, cả 3 đã sửa:**
      1. Khối KPI (Tổng số/Thành công/Thất bại/Tỉ lệ/Tài khoản hoạt
         động) trước đây `display:flex` nên 5 ô rộng không đều — đổi
         sang `display:grid; grid-template-columns:repeat(auto-fit,
         minmax(150px, 1fr))` để chia đều, vẫn tự co cột trên màn hình
         hẹp thay vì tràn ngang.
      2. Bảng "Tỉ lệ thành công/thất bại theo hành động" trước đây lặp
         2 dòng/hành động (cột "Kết quả" chỉ 1 giá trị) — pivot lại
         trong Python (`db.action_type_counts()`'s SQL giữ nguyên,
         không cần đổi) thành đúng 1 dòng/hành động, 2 cột riêng
         "Thành công"/"Thất bại".
      3. Dropdown "Hiển thị" (số item/trang) của khối "Hoạt động gần
         đây" trước đặt chung hàng với bộ lọc tài khoản/khoảng thời
         gian ở trên cùng — dời xuống footer của chính khối đó, cạnh
         phân trang, vì nó chỉ ảnh hưởng khối này chứ không phải lọc
         toàn trang. Luôn hiển thị kể cả khi chỉ có 1 trang (trước đây
         phân trang ẩn hẳn khi ≤1 trang). `hx-include` giữa 3 dropdown
         vẫn hoạt động bình thường dù đổi vị trí DOM (tham chiếu theo
         id, không phụ thuộc cùng cha).
      Verify qua Python trực tiếp: grid layout đúng, header bảng pivot
      đúng `Hành động|Thành công|Thất bại`, dropdown page_size không
      còn nằm trong khối filter trên cùng mà chỉ còn tham chiếu qua
      `hx-include`. 79 test vẫn pass. **Chưa xác nhận trên UI thật.**
- [x] **Chỉnh tiếp giao diện phân trang Báo cáo theo 2 phản hồi liên
      tiếp của owner (2026-09-11):** (1) label "Hiển thị" bị xuống 2
      dòng, dời "{N} mục" lên cùng hàng — thêm `white-space:nowrap` +
      `flex-shrink:0` cho khối bên phải, dời dropdown `page_size` từ
      footer lên cùng hàng tiêu đề "🕒 Hoạt động gần đây" (owner: footer
      "xấu quá"), bỏ dòng "mục" trùng lặp ở footer (chỉ còn nav khi
      >1 trang, ẩn hẳn nếu chỉ có 1 trang thay vì để trống).
- [x] **"Đăng lại" bị rate-limit không còn tính là lỗi** — owner phản
      hồi: nút "Đăng lại" ở Báo cáo khi dính rate-limit hiển thị y hệt
      lỗi thật ("Đăng lại thất bại: rate_limited:..."), trong khi đây
      chỉ là rate-limiter đang làm đúng việc của nó (giống hệt
      "Đăng ngay" ở Lịch đăng, vốn đã tách riêng từ trước — mục 4.12).
      Thêm tham số `warning` riêng cho `_reports_content_html()` (class
      CSS `.warning` màu hổ phách có sẵn, trước đó chưa dùng ở trang
      Báo cáo — khác `.error` màu đỏ), route `reports_page` nhận thêm
      query `warning`. `reports_repost()` giờ bắt riêng
      `result.message.startswith("rate_limited:")` TRƯỚC khi rơi vào
      nhánh lỗi chung, tra `rate_limit_wait_message(account, bucket)`
      để hiện gợi ý giờ thử lại bằng tiếng Việt (giống hệt cách
      `schedule_fire_now()` đã làm), chỉ fallback về `result.message`
      thô nếu không tra được. Verify qua Python: `warning=` render đúng
      `<p class="warning">`, không lẫn với `.error`. 79 test vẫn pass.
      **Chưa xác nhận trên UI thật.**
- [x] **Đồng bộ dữ liệu thống kê Báo cáo với quyết định "rate-limit
      không phải lỗi" ở trên** — owner hỏi thẳng: sửa UI của nút
      "Đăng lại" rồi, còn phần DỮ LIỆU báo cáo (KPI, bảng theo hành
      động, "Hoạt động gần đây") có sửa theo không, vì trước đó MỌI
      task bị `rate_limited:` (không riêng từ "Đăng lại" — cả
      `schedule_auto`/`schedule_manual` cũng bị) đều ghi `success=0`
      vào `action_log` giống hệt lỗi thật (selector gãy, timeout...),
      làm KPI "Thất bại"/"Tỉ lệ thành công" bị kéo lệch bởi thứ vốn
      chưa từng thực sự thử làm gì (rate-limit chặn TRƯỚC khi
      `run_task()` mở trình duyệt — xem `agent.py`'s `run_task()`,
      `can_proceed()` chạy trước `get_session()`).
      Sửa `human_bot/db.py`: `summary_stats()` và `action_type_counts()`
      giờ loại trừ dòng `message LIKE 'rate_limited:%'` khỏi
      total/succeeded/failed (SQL, không phải lọc tay ở Python) —
      `active_accounts` CỐ Ý giữ nguyên tính trên mọi dòng kể cả
      rate-limited (tài khoản bị rate-limit vẫn tính là "có hoạt
      động"). Bảng "Hoạt động gần đây" (`admin.py`) KHÔNG bị lọc bỏ
      dòng nào (vẫn cần thấy để biết mà "Đăng lại") nhưng đổi icon cột
      KQ: rate_limited giờ hiện ⏳ riêng biệt, không còn dùng chung ⚠️
      với lỗi thật.
      Verify bằng dữ liệu THẬT trong `human_bot.db` (không phải mock,
      theo đúng nguyên tắc không ghi đè config thật nhưng ĐỌC thì được):
      42 dòng thật, 10 dòng `rate_limited:` — `summary_stats()` mới ra
      `total=32, succeeded=18, failed=14, success_rate=56.2%` (khớp
      42-10=32); `action_type_counts()` cộng lại đúng 32; bảng "Hoạt
      động gần đây" hiện đúng 10 dòng icon ⏳. 79 test vẫn pass.
- [x] **Điều tra sâu 2 câu hỏi thật của owner về `comments_per_day` —
      cả 2 đều tìm ra nguyên nhân thật + sửa, không phải bug ở chỗ owner
      nghĩ ban đầu:**

      **(1) "Lúc lên lịch đã kiểm tra còn slot hay không, sao vẫn dư?"**
      — Xác nhận lớp LÊN LỊCH (`_count_scheduled_actions_by_day()`,
      `data_sync.py`) hoạt động ĐÚNG: đếm theo NGÀY DƯƠNG LỊCH (UTC),
      chưa bao giờ xếp quá 7 comment/ngày cho `tu_iizuki` (kiểm tra
      thật: 2026-09-09=1, 09-10=6, 09-11=4, đúng cả). Vấn đề thật nằm ở
      lớp ENFORCEMENT (`safety.py`'s `RateLimiter.can_proceed()`) — đếm
      theo CỬA SỔ TRƯỢT 24 GIỜ tính từ lúc kiểm tra, KHÔNG phải theo
      ngày dương lịch. Vì `auto_fire_enabled` tắt phần lớn thời gian
      (task dồn lại thành pending qua nhiều ngày), khi cuối cùng bắn ra
      (bật auto-fire tạm/bấm tay), các comment lên lịch cho 2 NGÀY
      DƯƠNG LỊCH khác nhau (09-10 và 09-11) lại rơi vào CÙNG một cửa sổ
      24h thực tế lúc đăng — xác nhận bằng log thật: 7 comment tính vào
      cửa sổ trượt trải từ `2026-09-10T08:12` đến `2026-09-11T00:18`
      (~16 tiếng thực), đủ 7 nên chặn. Đây là 2 định nghĩa "1 ngày"
      không khớp nhau giữa 2 lớp — cùng bản chất với vụ x₁/x_safety đã
      bàn trước đó cho gap, nhưng lần này là cho GIỚI HẠN SỐ LƯỢNG.
      **Chưa sửa lớp này** (đúng tinh thần "ghi nhận, có thể chưa cần
      vá ngay" như x_safety) — chỉ ghi nhận nguyên nhân thật ở đây và
      FB_Post_Assistant.md.

      **(2) "Sao dính limit rồi vẫn cứ đăng lại?"** — Bug thật, ĐÃ SỬA.
      Thêm `safety.py`'s `rate_limit_hard_cap_message()` (song song
      `rate_limit_wait_message()` sẵn có nhưng chỉ biết về soft gap) —
      phát hiện đang bị chặn bởi hard cap (posts_per_day/
      comments_per_hour/comments_per_day/likes_per_hour), trả về câu
      gợi ý dời lịch tiếng Việt (không tính giờ chính xác được vì cửa
      sổ trượt, chỉ nói chung "dời sang thời điểm khác"). Wire vào pre-
      check của `fire_due_tasks()` (`data_sync.py`) — giờ SKIP hẳn
      `run_task()` (và cả bước AI rewrite tốn tiền thật trước đó) khi
      dính hard cap, y hệt cách đã làm cho soft gap từ trước, thay vì
      lặp lại mỗi phút vô nghĩa (xác nhận thật: 44 dòng
      `rate_limited:comments_per_day` + tốn 44 lần gọi AI thật trong 24
      phút, do pre-check cũ chỉ biết `rate_limit_wait_message()` — hàm
      đó CHỈ xử lý soft gap, không hề biết gì về hard cap). Cùng sửa
      `schedule_fire_now()` ("Đăng ngay") và `reports_repost()` ("Đăng
      lại") ở `admin.py` để dùng chung `rate_limit_hard_cap_message()`
      thay vì rơi vào lỗi chung/thô. Đã kiểm tra `posts_per_day` — cùng
      lỗi y hệt (2 dòng `rate_limited:posts_per_day limit reached`
      thật trong DB), cùng 1 pre-check sửa chung cho mọi loại action
      (post/comment/like), không cần sửa riêng.
      Verify bằng dữ liệu thật: `rate_limit_hard_cap_message(tu_iizuki,
      "comment")` trả đúng câu gợi ý; mô phỏng lại đúng pre-check mới
      cho 2 task comment đang due xác nhận sẽ SKIP `run_task()`. 79
      test vẫn pass.

## Đợt làm việc 2026-09-11 (tiếp) — Chặn spam nhiều nhóm: bỏ tài khoản 0 nhóm, giới hạn 3 nhóm/job

- [x] **2 lỗi thật + 1 điểm xác nhận đã đúng, phát hiện qua trao đổi sâu
      với owner về việc "1 job phát vào TẤT CẢ nhóm đã tham gia" bị coi
      là dấu hiệu spam rõ (10 nhóm = 10 bài, dù đã viết lại nội dung
      vẫn là cross-posting pattern dễ nhận ra):**

      **(a) Bug thật — tài khoản 0 nhóm vẫn được chia job, job đó mất
      vĩnh viễn.** `job_capacities` (`data_sync.py`) chỉ tính theo
      `posts_per_day`, không kiểm tra `get_joined_groups(aid)`. Xác
      nhận bằng test thật:
      `_water_fill_distribute(['job1','job2'], {'acc_no_group':5,
      'acc_has_group':5})` → `job1` rơi vào `acc_no_group` → vòng lặp
      `for group in groups` chạy 0 lần (groups=[]) → không tạo task
      nào → nhưng `_mark_seen(jid,"job")` vẫn chạy (nằm ngoài vòng lặp
      nhóm) → **job1 mất vĩnh viễn, không ai đăng, không quay lại lần
      sau** — đồng thời "cướp" mất phần chia đều lẽ ra dành cho
      `acc_has_group`. Sửa: loại tài khoản 0 nhóm khỏi `job_capacities`
      ngay từ đầu (`if get_joined_groups(aid)`).

      **(b) Gap thật — chưa có giới hạn số nhóm/job.**
      `content_strategist.template_variants()` trả đúng `len(groups)`
      biến thể — không cap. Thêm `DataSyncConfig.max_groups_per_post`
      (mặc định 3, sửa được qua `/admin/config` tab Đồng bộ, dùng
      chung cơ chế cast kiểu tự động theo dataclass field đã có sẵn ở
      `config_save()` — không cần code riêng). Chọn nhóm theo
      **round-robin dựa trên `last_group_post_at`** (đã có sẵn, tính từ
      `_last_scheduled_time_per_group()`) — ưu tiên nhóm **lâu chưa
      đăng nhất** (nhóm chưa từng đăng = ưu tiên cao nhất,
      `datetime.min`), không phải random (có thể bỏ quên nhóm dài hạn
      hoặc trúng lặp) hay cố định N nhóm đầu (không bao giờ xoay
      vòng). `last_group_post_at` được cập nhật ngay trong vòng lặp
      nên tự xoay vòng đúng cả khi nhiều job xử lý trong CÙNG 1 lần
      poll. Verify bằng dữ liệu thật `tu_iizuki` (4 nhóm): chọn đúng 3
      nhóm lâu chưa đăng nhất, loại đúng 1 nhóm vừa đăng gần nhất.

      **(c) Đã kiểm tra, KHÔNG phải bug — 1 job có bao giờ bị phân phối
      cho >1 tài khoản không?** Test thật xác nhận KHÔNG:
      `_water_fill_distribute()` chia theo **list item**, mỗi job chỉ
      rơi vào đúng 1 tài khoản (không nhân bản); `_mark_seen()` dùng
      cache toàn cục theo id nên 1 khi đã gán cho 1 tài khoản, không
      bao giờ được xét lại cho tài khoản khác ở poll sau. Giữ nguyên,
      không sửa.

      Test suite (79) vẫn pass sau (a)+(b).
- [x] **Chuyển `max_groups_per_post` từ cấu hình TOÀN CỤC sang RIÊNG TỪNG
      TÀI KHOẢN** — owner phản hồi ngay sau khi (b) xong: muốn tài khoản
      A giới hạn 3 nhóm/job, tài khoản B giới hạn 5 nhóm/job, không thể
      làm được nếu để chung 1 giá trị toàn hệ thống ở `DataSyncConfig`.
      Bỏ hẳn field vừa thêm ở `DataSyncConfig`/tab "Đồng bộ", chuyển
      sang `RateLimits` (`config.py`) — cùng nhóm với `posts_per_day`/
      `comments_per_day` đã có sẵn cơ chế override riêng từng tài khoản
      (`EDITABLE_RATE_LIMITS_FIELDS`, modal "⏱️ Giới hạn" ở
      `/admin/accounts`) — tận dụng nguyên cơ chế generic có sẵn
      (form render qua `_RATE_LIMITS_LABELS`, parse/validate qua vòng
      lặp `EDITABLE_RATE_LIMITS_FIELDS` trong `accounts_rate_limits_save()`),
      không cần code riêng cho field mới. `data_sync.py` đổi
      `cfg.max_groups_per_post` → `account.rate_limits.max_groups_per_post`.

      **Phát hiện + sửa thêm 1 gotcha trong lúc làm (chưa ai hỏi,
      tự phát hiện khi cài đặt đúng):** nút "Áp nhanh theo tuổi tài
      khoản" (quick-apply `ACCOUNT_AGE_TIERS`) dùng
      `dataclasses.asdict(preset)` để lưu — nhưng các preset tuổi tài
      khoản KHÔNG hề khai báo `max_groups_per_post` (đây là trục kiểm
      soát spam, khác hẳn trục tốc độ/số lượng theo tuổi), nên bấm nút
      này sẽ ÂM THẦM RESET `max_groups_per_post` về mặc định cứng (3)
      dù admin vừa chỉnh riêng thành 5 — đúng kiểu mất dữ liệu ngầm dự
      án này luôn tránh. Sửa: giữ nguyên giá trị `max_groups_per_post`
      hiện tại của tài khoản khi áp tier, không lấy từ preset.

      Verify: đọc/ghi override qua **file cấu hình cách ly hoàn toàn**
      (không đụng `runtime_config.json` thật — sửa lỗi nhỏ tự mắc phải
      lúc đầu test bằng account id không tồn tại `tu_test2`, khôi phục
      lại file thật từ backup ngay khi phát hiện), xác nhận
      `tu_iizuki` giữ mặc định 3, override thử nghiệm lên 5 hoạt động
      đúng và không ảnh hưởng tài khoản khác. Render modal thật xác
      nhận field hiện đúng. 79 test vẫn pass.
- [x] **x_safety (enforcement) đổi từ random sang cố định = gap_min —
      loại bỏ hoàn toàn va chạm x1/x_safety đã ghi nhận từ trước
      (2026-09-10, mục "kẹp sàn" comment scheduling), theo quyết định
      chủ dự án (đánh dấu TẠM THỜI).** `safety.py`'s `RateLimiter.record()`
      trước đây `random.uniform(gap_min, gap_max)` mỗi lần 1 hành động
      chạy xong — độc lập hoàn toàn với x₁ (số đã random khi lên lịch
      hành động kế tiếp, `data_sync.py`). Lý do đổi: x₁ luôn nằm trong
      `[gap_min, gap_max]` theo đúng định nghĩa, nên nếu x_safety cố
      định = gap_min thì `x₁ ≥ x_safety` là CHẮC CHẮN TOÁN HỌC (không
      phải xác suất ~50% như trước) — không cần random thêm 1 lần nữa
      ở lớp enforcement, vì độ ngẫu nhiên thật của giờ đăng đã có đủ ở
      lớp lên lịch rồi. `next_allowed_at` giờ chỉ còn ý nghĩa "mốc nghỉ
      tối thiểu tuyệt đối" để các đường KHÔNG qua lịch (đặt tay, "Đăng
      ngay"/"Đăng lại") biết mà né, không phải nguồn ngẫu nhiên chính.
      **Đánh đổi ghi nhận rõ trong code (chưa giải quyết):** mọi đường
      không qua lịch giờ có khoảng cách enforcement CỐ ĐỊNH mỗi lần
      (đúng kiểu lặp lại từng bị nhận diện là dấu hiệu bất thường ở
      nơi khác trong dự án) — chấp nhận vì các đường đó do người thật
      bấm tay, không phải vòng lặp tự động lặp lại; cần xem lại nếu
      sau này có thêm đường gọi tự động không qua lịch.
      Xoá import `random` không còn dùng trong `safety.py`.
      Verify: mô phỏng 100,000 lần `x1 = random.uniform(gap_min,
      gap_max)` so với `x_safety = gap_min` (số thật của `tu_iizuki`,
      5400-10800s) → **0 va chạm**. 79 test vẫn pass (test
      `test_record_writes_next_allowed_at_within_configured_range` vẫn
      đúng vì kiểm tra dạng khoảng `[95,205]`, không phụ thuộc có
      random hay không).

## Đợt làm việc 2026-09-11 (tiếp) — Kẹp sàn số lượng theo cửa sổ trượt 24h thật, bỏ tràn-ngày

- [x] **Triển khai đúng thiết kế đã thống nhất qua nhiều lượt trao đổi:
      lên lịch kiểm tra capacity theo cửa sổ trượt 24h THẬT (không chỉ
      theo ngày dương lịch), bỏ hẳn cơ chế "tràn sang ngày mai" cho bài
      đăng, đăng vừa đủ số nhóm còn slot thay vì hoãn cả job.**

      1. **`safety.py`:** thêm `RateLimiter.recent_count(action_type,
         window) -> int` (đọc log thật, không ghi gì) — tách ra từ logic
         đếm sẵn có trong `can_proceed()`, giờ `can_proceed()` gọi lại
         chính hàm này (DRY, không có 2 chỗ đếm khác nhau).
      2. **`data_sync.py`'s `_next_available_post_slot()`:** bỏ hẳn
         tham số `daily_limit`/`day_counts` và nhánh "tràn sang ngày
         mai" — giờ chỉ còn xử lý giờ yên tĩnh + khoảng cách tối thiểu
         giữa 2 bài cùng 1 nhóm. Lý do bắt buộc phải bỏ CÙNG LÚC với
         việc kẹp sàn (không thể tách riêng — đã phân tích kỹ trong
         nhiều lượt trao đổi trước): cách đếm theo ngày dương lịch cũ
         CHỈ TĂNG (giữ đúng thứ tự công bằng vì "đầy" là đầy vĩnh viễn
         cho ngày đó); cách đếm theo cửa sổ trượt thật CÓ THỂ GIẢM (khi
         hoạt động cũ trôi khỏi 24h) — nếu vẫn giữ tràn-ngày, job cũ bị
         đẩy sang mai sẽ kẹt vĩnh viễn trong khi job mới hơn có thể
         "nẫng" slot vừa mở ra giữa ngày, gây đảo thứ tự.
      3. **`job_capacities`/`comment_capacities`:** đổi từ chỉ đếm theo
         `_count_scheduled_actions_by_day()` (ngày dương lịch) sang
         `max(theo ngày dương lịch, RateLimiter.recent_count() thật
         trong 24h)` — "kẹp sàn". Áp dụng cho CẢ post lẫn comment (owner
         xác nhận cùng 1 vấn đề gốc cho cả 2 loại).
      4. **Vòng lặp job trong `sync_all()`:** thêm biến `available`
         (kẹp sàn, tính LẠI mỗi job vì `day_post_counts` tăng dần trong
         cùng 1 lần poll, còn `real_recent_posts` đóng băng cho cả lần
         poll vì việc lên lịch không tự tạo hoạt động thật). Logic theo
         đúng ví dụ owner đưa ra (còn 2 slot, cap 3 → đăng 2, không
         phải 0 hay 3):
         - `available <= 0` → **hoãn cả job** (không tạo task, không
           `_mark_seen()`, lấy lại nguyên vẹn ở poll sau).
         - `available > 0` → chọn `min(max_groups_per_post, available)`
           nhóm theo round-robin, đăng, **coi job đã xử lý xong**
           (mark_seen) dù có thể chưa phủ đủ số nhóm dự kiến — KHÔNG
           cố đăng nốt phần thiếu ở poll sau.
      5. **Comment không cần logic "đăng vừa đủ"** — 1 candidate luôn
         tạo đúng 1 task (không "nở" ra nhiều nhóm như job), nên chỉ
         cần sửa đúng con số `comment_capacities` là
         `_water_fill_distribute()` đã tự defer đúng phần vượt quá vào
         `deferred_candidates` (cơ chế có sẵn, không cần sửa gì thêm).
      6. **Bug tự phát hiện khi cài đặt (chưa ai hỏi):** job bị hoãn
         BÊN TRONG vòng lặp (do `available<=0` giữa chừng, không phải
         bị water-fill loại từ đầu) không nằm trong `deferred_jobs`
         (list ngoài) — nếu không merge vào, cursor lấy dữ liệu từ bên
         B sẽ không được giữ lại đúng mốc, job có thể KHÔNG BAO GIỜ
         được lấy lại (khác với việc chỉ "chưa mark_seen" — nếu cursor
         trôi qua mốc thời gian của nó, bên B sẽ không trả về nó nữa ở
         lần gọi API sau). Thêm `deferred_jobs_inner` theo từng tài
         khoản, `.extend()` vào `deferred_jobs` (list ngoài, cùng
         reference) trước khi tính cursor.

      Verify: gọi `_next_available_post_slot()` với chữ ký mới (4 tham
      số, không còn `daily_limit`/`day_counts`) chạy đúng; mô phỏng lại
      chính xác công thức `available`/`groups_to_post` đã cài vào code
      khớp đúng ví dụ owner đưa ra (2 slot, cap 3 → đăng 2; đầy hẳn →
      hoãn). 79 test vẫn pass. **Chưa có test tự động riêng cho
      `data_sync.py`** (gap đã ghi nhận từ trước, không phải mới) và
      **chưa chạy `sync_all()` thật qua service** (cần restart + có dữ
      liệu mới từ bên B mới quan sát được).
- [x] **Thay hẳn cơ chế enforcement SỐ LƯỢNG (posts_per_day/comments_per_day)
      từ cửa sổ trượt 24h sang "ngày nghiệp vụ" 2h sáng JST → 2h sáng JST
      hôm sau — sau khi phát hiện qua trao đổi: đặt cứng job vào đúng 1
      giờ tính được (VD 19h) sẽ tạo khuôn mẫu lặp lại mỗi ngày (19h hôm
      qua, 19h hôm nay) — mất hẳn tính ngẫu nhiên, một dấu hiệu bất
      thường rõ hơn cả việc thiếu slot.**

      **Vì sao chọn mốc 2h sáng, không phải nửa đêm:** 2h-6h sáng JST là
      khung giờ yên tĩnh có sẵn (`DataSyncConfig.quiet_hour_start_local`),
      không bao giờ có hoạt động nào diễn ra — reset đúng lúc đó nằm gọn
      trong "vùng chết", loại bỏ hẳn nguy cơ dồn cục 2 phía mốc reset
      (VD 7 bài trước 2h + 7 bài ngay sau 6h) mà nửa đêm (giữa giờ hoạt
      động) sẽ không tránh được. Cộng thêm khoảng nghỉ tối thiểu nhiều
      giờ giữa 2 hành động cùng loại đã có sẵn khiến việc dồn cục kiểu
      đó càng bất khả thi về mặt toán học.

      **Quyết định kiến trúc quan trọng của owner: `safety.py` GIỮ
      NGUYÊN, KHÔNG XOÁ, chỉ không còn được gọi cho phần đếm SỐ LƯỢNG
      nữa** — để đọc lại/quay về sau nếu cần. Triển khai:
      1. File mới `human_bot/daily_limits.py` — `_business_day_start()`
         (tìm mốc 2h sáng JST gần nhất, verify bằng 3 mốc giờ thật:
         đúng ranh giới, ngay trước ranh giới, giữa ngày — cả 3 đúng),
         `count_since_business_day_start()` (đọc THẲNG cùng file log
         JSONL mà `safety.py` đang dùng, không tạo nguồn dữ liệu mới),
         `can_proceed()` (thay thế 1-1 cho `RateLimiter.can_proceed()`
         — chỉ đổi phần `posts_per_day`/`comments_per_day`, phần gap và
         `comments_per_hour`/`likes_per_hour` TÁI DÙNG NGUYÊN
         `RateLimiter`, không đổi), `hard_cap_message()` (thay
         `safety.py`'s `rate_limit_hard_cap_message()`).
      2. `safety.py`: thêm `RateLimiter.gap_ok()` — wrapper public nhỏ
         lộ ra `_last_action_gap_ok()` để `daily_limits.py` tái dùng
         được phần gap mà không cần đi qua `can_proceed()`.
         `can_proceed()` và `rate_limit_hard_cap_message()` giữ nguyên
         y hệt logic cũ, chỉ thêm docstring "NOT CALLED ANYWHERE as of
         2026-09-11" + trỏ sang `daily_limits.py` — đúng yêu cầu
         "trích dẫn tới file safety.py để sau này cần thì đọc lại".
      3. Đổi đúng 3 nơi thật sự gọi `RateLimiter.can_proceed()`/
         `rate_limit_hard_cap_message()` (rà bằng `grep`, xác nhận
         không phải 5 như ước lượng ban đầu): `agent.py`'s `run_task()`
         (điểm chốt duy nhất mọi hành động thật đều đi qua),
         `admin.py`'s `schedule_fire_now()` (2 lượt gọi trong cùng hàm
         — pre-check trước và fallback sau khi `run_task()` chạy),
         `admin.py`'s `reports_repost()`, `data_sync.py`'s
         `fire_due_tasks()` pre-check.
      Verify bằng dữ liệu THẬT `tu_iizuki`: đếm kiểu cũ (cửa sổ trượt)
      ra 7, đếm kiểu mới (ngày nghiệp vụ) ra 4 — khác nhau đúng như dự
      kiến vì phạm vi thời gian khác nhau; `can_proceed()`/
      `hard_cap_message()` mới chạy đúng cho cả 3 loại action (post
      đang bị chặn bởi gap mềm — `hard_cap_message=None` đúng, không
      lẫn với hard cap; comment/like đang được phép). `grep` xác nhận
      sạch — không còn nơi nào gọi thẳng `RateLimiter.can_proceed()`
      hay `safety.rate_limit_hard_cap_message()` ngoài định nghĩa gốc
      và bên trong `daily_limits.py`. 79 test vẫn pass.
- [x] **Đồng bộ lớp LÊN LỊCH sang cùng "ngày nghiệp vụ" (2h sáng JST)
      với lớp enforcement vừa đổi, rồi mang lại cơ chế tràn-ngày cho
      bài đăng — owner tự nhận ra: khi 2 lớp đã thống nhất 1 định
      nghĩa "ngày" duy nhất (không còn cửa sổ trượt tự trôi), việc
      khoá 1 job vào ngày mai không còn rủi ro đảo thứ tự đã phân tích
      kỹ trước đó — có thể bỏ hẳn cách "hoãn cả job, chờ poll sau",
      biết chắc chắn và set lịch thẳng luôn.**

      1. `daily_limits.py`: thêm 2 hàm public — `business_day_start()`
         (wrapper public của `_business_day_start()` nội bộ) và
         `business_day_key(dt) -> date` (ngày dương lịch JST của mốc
         bắt đầu ngày nghiệp vụ chứa `dt` — dùng làm key nhóm theo
         đúng "ngày nghiệp vụ", không phải ngày dương lịch UTC thô).
      2. `data_sync.py`'s `_count_scheduled_actions_by_day()`: đổi key
         từ `scheduled.date()` (ngày dương lịch UTC) sang
         `daily_limits.business_day_key(scheduled)`. `today` (biến
         dùng khắp `sync_all()`) đổi từ `_utc_today()` sang
         `daily_limits.business_day_key(now)`.
      3. `job_capacities`/`comment_capacities`'s "kẹp sàn": phần "thật"
         đổi từ `RateLimiter.recent_count(action, 24h)` (cửa sổ trượt)
         sang `daily_limits.count_since_business_day_start()` (cùng
         định nghĩa "ngày" với lớp enforcement) — khớp đúng ý nghĩa so
         sánh, không còn so 2 khái niệm khác nhau như trước.
      4. **Mang lại tràn-ngày:** hàm mới
         `_next_available_business_day(dt, daily_limit, day_counts,
         today_key, real_used_today)` — đẩy `dt` sang ĐẦU ngày nghiệp
         vụ kế tiếp (`daily_limits.business_day_start() + 1 ngày`, mốc
         2h sáng JST — KHÔNG phải nửa đêm UTC như bản gốc trước đây),
         lặp tối đa 60 ngày tìm ngày còn slot. `_next_available_post_slot()`
         giữ nguyên KHÔNG có logic capacity (chỉ giờ yên tĩnh + gap
         cùng nhóm) — capacity giờ tách hẳn ra hàm riêng, gọi 1 lần
         cho mỗi job TRƯỚC khi chọn nhóm, không còn logic "hoãn cả
         job" nữa (trừ trường hợp bệnh lý vượt 60 ngày tìm kiếm).
      5. **Logic "đăng vừa đủ" (còn 2 slot, cap 3 → đăng 2) GIỮ NGUYÊN
         không đổi** — chỉ áp dụng cho NGÀY được `_next_available_business_day()`
         tìm ra (có thể là hôm nay hoặc ngày mai), không đổi công thức
         `min(max_groups_per_post, available)`.
      Verify bằng test thật (gọi trực tiếp hàm mới, không mock): kịch
      bản "hôm nay đầy 3/3" → nhảy đúng sang ngày nghiệp vụ kế tiếp,
      full lại 3 slot (chưa có gì xảy ra ở đó); qua tiếp
      `_next_available_post_slot()` (giờ yên tĩnh) → đúng ~6h24 sáng
      JST (không phải giờ cố định tuyệt đối, có biến thiên tự nhiên
      nhờ phần random sẵn có trong `apply_quiet_hours()`); kịch bản
      "còn 2 slot, cap 3" → vẫn đúng `available=2`, không tràn ngày vì
      còn slot — công thức "đăng vừa đủ" không bị ảnh hưởng. 79 test
      vẫn pass.
- [x] **Rà soát kỹ toàn bộ đợt thay đổi "ngày nghiệp vụ" + tràn-ngày ở
      trên, theo yêu cầu owner — cộng thêm bộ test tự động đầu tiên cho
      `daily_limits.py` và `data_sync.py` (2 module trước đây CHƯA từng
      có test riêng, gap đã ghi nhận nhiều lần).**

      Rà bằng `grep` từng điểm nối dây: `_next_available_post_slot()`
      chỉ còn đúng 1 nơi gọi (chữ ký mới, 4 tham số); 4 lượt gọi thật
      của `daily_limits.can_proceed()`/`hard_cap_message()` (agent.py,
      admin.py x2, data_sync.py) đều đã đổi, không sót `RateLimiter(...).can_proceed()`
      hay `safety.rate_limit_hard_cap_message()` cũ nào ngoài định
      nghĩa gốc; `deferred_jobs_inner` → merge vào `deferred_jobs` →
      vào cursor bên B: còn nguyên, đúng thứ tự; không import thừa.

      **Test mới:**
      - `tests/test_daily_limits.py` (17 test) — `business_day_start()`/
        `business_day_key()` (3 mốc giờ biên đúng/sai), `can_proceed()`
        (daily cap theo ngày nghiệp vụ KHÁC rolling window — verify
        đúng cả 2 chiều: dòng SAU mốc 2h sáng có tính, dòng TRƯỚC mốc
        không tính; `comments_per_hour` vẫn dùng rolling window như cũ,
        không đổi; gap check vẫn hoạt động; `ignore_gap` chỉ bỏ qua gap
        chứ không bỏ qua daily cap), `hard_cap_message()`.
      - `tests/test_data_sync.py` (12 test) — `_next_available_post_slot()`
        (giờ yên tĩnh, gap cùng nhóm/khác nhóm), `_next_available_business_day()`
        (không tràn khi còn slot — **đúng khớp ví dụ owner đưa ra: 5
        slot, dùng 3, còn 2, cap 3 → đăng 2**; tràn đúng ngày nghiệp vụ
        kế tiếp khi đầy; ngày tương lai bỏ qua `real_used_today` của
        hôm nay đúng như thiết kế; dừng đúng sau 60 ngày tìm kiếm nếu
        cấu hình bệnh lý; điểm rơi sau tràn đúng 2h sáng JST — không
        phải nửa đêm UTC), `_count_scheduled_actions_by_day()` (dùng
        `monkeypatch` trên `schedule_store`, không đụng file thật) —
        **test quan trọng nhất:** 1 task lúc `16:30 UTC` (=01:30 JST
        ngày hôm sau, TRƯỚC mốc 2h sáng) phải tính đúng vào ngày
        nghiệp vụ HÔM TRƯỚC chứ không phải ngày UTC thô — đúng ca mà
        cách tính cũ (`_utc_today()`) sẽ đếm sai, xác nhận PASS.

      **Phát hiện 1 lỗi khi viết test — lỗi TRONG TEST, không phải
      trong code thật:** ban đầu giả lập dòng log bằng
      `datetime.now(timezone.utc)` (có timezone), nhưng `safety.py`
      thật luôn ghi `datetime.utcnow()` (KHÔNG timezone) — test fail
      ngay vì so sánh naive/aware datetime. Xác nhận bằng `grep` toàn
      bộ `safety.py`: nhất quán dùng naive khắp nơi, không phải bug
      production — sửa lại test cho khớp đúng định dạng log thật.

      **Kết quả cuối: 108/108 test pass (79 cũ + 29 mới), không file
      cấu hình/dữ liệu thật nào bị đụng trong lúc test** (dùng
      `tmp_path`/`monkeypatch` cách ly hoàn toàn).

## Đợt làm việc 2026-09-11 (tiếp) — Reset dữ liệu test: xoá lịch đang chờ + cache đồng bộ bên B

- [x] **Thao tác vận hành theo yêu cầu trực tiếp — không phải thay đổi code.**
      Xoá sạch `scheduled/pending/` (220 file bài đang chờ đăng tại thời
      điểm xoá) và cache đồng bộ dữ liệu bên B trong `data_sync_cache/`
      (`2026-09-10.json` — file id đã-thấy theo ngày dùng để chống trùng;
      `_state.json` — con trỏ `jobs_since`/`candidates_since` dùng để chỉ
      hỏi bên B những gì mới kể từ lần trước) để lần đồng bộ tiếp theo
      chạy như một lần lấy dữ liệu đầu tiên (không có `since`, không có id
      nào bị coi là "đã thấy"). **Không đụng** `scheduled/posted/`,
      `scheduled/failed/`, `scheduled/cancelled/` (lịch sử) theo đúng yêu
      cầu, và **không xoá** `data_sync_cache/_sync_status.json` (chỉ là
      thông tin hiển thị lần đồng bộ gần nhất ở `/admin`, không ảnh hưởng
      hành vi lấy dữ liệu) — giữ lại để không mất thông tin không cần
      thiết.
      **Chưa đụng tới `_contacted_contacts.json`** (chưa tồn tại tại thời
      điểm reset) — đây là danh sách chống nhắn trùng người (theo
      `attributes.contact`, khác mục đích với cache chống trùng theo
      `id`); nếu về sau cần "quên" luôn việc đã liên hệ ai đó, đây là file
      riêng cần xoá thêm, không tự động bị xoá theo thao tác này.
- [x] **Lặp lại thao tác reset (2026-09-11 18:33) — dữ liệu mới tích luỹ
      trở lại sau lần reset đầu (37 file `pending/` mới, cache ngày
      `2026-09-11.json` mới, `_state.json` mới do bộ đồng bộ nền vẫn chạy
      liên tục).** Xoá lại đúng `scheduled/pending/*` và toàn bộ
      `data_sync_cache/*.json` — lần này gộp luôn `_sync_status.json` vào
      lệnh xoá (khác lần trước là cố tình giữ lại) vì dùng `rm -f
      data_sync_cache/*.json` chung một lệnh; không ảnh hưởng gì về mặt
      chức năng (file này chỉ hiển thị "lần đồng bộ gần nhất", tự ghi lại
      ở lần sync kế tiếp), chỉ nêu ra để khớp đúng những gì đã thực sự xảy
      ra. `scheduled/posted|failed|cancelled/` vẫn giữ nguyên, không đụng.

## Đợt làm việc 2026-09-11 (tiếp) — Sửa bug thật: `sync_all()` crash mỗi lần poll

- [x] **Bug thật, ảnh hưởng service đang chạy sống — owner báo "restart +
      đặt 5 phút chạy sync mà không thấy gì".** Tra `logs/human_bot.log`
      thấy `sync_all()` crash NGAY LẬP TỨC mỗi chu kỳ poll kể từ lúc
      restart, kể cả sau khi reset dữ liệu test ở mục ngay trên:
      ```
      TypeError: can't compare offset-naive and offset-aware datetimes
        File "human_bot/data_sync.py", line 876, in sync_all
          next_comment_time = max(next_comment_time, enforced_comment_floor)
      ```
      **Không liên quan gì tới đợt "ngày nghiệp vụ" vừa làm hôm nay** —
      lỗi nằm ở đoạn "kẹp sàn" cho comment gap đã thêm SỚM HƠN trong buổi
      (commit "Prevent comment scheduling collisions across sync_all()
      polls"). `RateLimiter.next_allowed_at()` (`safety.py`) luôn trả về
      datetime NAIVE (mọi timestamp trong log của `record()` đều ghi bằng
      `datetime.utcnow()`, không bao giờ có timezone — xác nhận bằng
      `grep` toàn file, nhất quán khắp nơi), trong khi `next_comment_time`
      ở `data_sync.py` lại là AWARE (`datetime.now(timezone.utc)`). So
      sánh 2 loại khác nhau bằng `max()` ném `TypeError` ngay lập tức.
      **Lỗi này đã "ngủ yên" từ lúc thêm (chưa từng lộ ra) vì chỉ kích
      hoạt khi tài khoản đã có ít nhất 1 comment từng đăng thật** (để
      `next_allowed_at()` trả về giá trị khác `None`) — `tu_iizuki` hội
      đủ điều kiện đó từ lâu trong buổi làm việc này, nên crash ngay khi
      restart.
      **Vì sao "im lặng" với người vận hành:** `service.py`'s vòng lặp
      poll chỉ `logger.exception("data_sync.sync_all failed")` rồi tiếp
      tục vòng lặp — không có gì hiển thị trên `/admin`, trông y hệt như
      "chạy nhưng không tìm thấy dữ liệu mới" thay vì "đang crash".
      Sửa: chuẩn hoá `enforced_comment_floor` sang aware UTC trước khi
      so sánh (`if enforced_comment_floor.tzinfo is None:
      enforced_comment_floor = enforced_comment_floor.replace(tzinfo=timezone.utc)`)
      — cùng cách chuẩn hoá đã dùng ở `daily_limits.py`'s
      `count_since_business_day_start()` cho đúng lý do tương tự.
      Verify bằng dữ liệu thật `tu_iizuki`: `next_allowed_at()` xác nhận
      trả về naive (`tzinfo=None`); sau khi chuẩn hoá, `max()` chạy đúng
      không còn lỗi. Thêm 2 test hồi quy khoá chặt đúng hợp đồng này
      (`next_allowed_at()` luôn naive; so sánh trực tiếp phải raise,
      sau chuẩn hoá thì không) — **110 test, tất cả pass.**
      **Chưa xác nhận trên service thật sau fix** — cần restart để nạp
      code mới, quan sát `sync_all()` không còn crash trong log.

## Đợt làm việc 2026-09-11 (tiếp) — 3 cải thiện Admin UI theo phản hồi trực tiếp

- [x] **Nút "Áp nhanh theo tuổi tài khoản" (modal "⏱️ Giới hạn") không
      còn tự lưu ngay khi bấm — owner phát hiện qua chính buổi làm việc
      này** (hạn mức tu_iizuki đổi từ 12/15 xuống 5/7 giữa 2 lần tôi
      kiểm tra, hoá ra do bấm thử nút tier mà không biết nó lưu ngay).
      Chuyển hẳn sang client-side: nút giờ chỉ điền số vào các ô nhập
      của form chính, phải bấm "Lưu" mới thật sự ghi vào
      `runtime_config.json`. Giá trị vẫn lấy đúng từ `ACCOUNT_AGE_TIERS`
      thật (render sẵn ra `data-*` attribute trên nút, JS chỉ đọc lại —
      không hardcode số ở JS, không thể lệch với server). Riêng
      `max_groups_per_post` (không thuộc tier preset) cố tình KHÔNG có
      trong `data-*` — bấm tier không đụng gì tới ô đó, giữ nguyên giá
      trị hiện tại của tài khoản. Xoá hẳn route
      `/admin/accounts/rate-limits/apply-tier` (không còn ai gọi).
- [x] **Cột "Tuổi tài khoản" mới trong `/admin/accounts`** — hàm
      `_account_age_tier_label()` so khớp `posts_per_day`/
      `comments_per_day` hiện tại với 5 tier trong `ACCOUNT_AGE_TIERS`,
      hiện đúng nhãn (VD "Dưới 1 tháng") hoặc "Tuỳ chỉnh" nếu không
      khớp — không cần mở modal mới biết tài khoản đang ở mức nào.
- [x] **Đồng bộ toàn bộ chỗ hiển thị giờ trong Admin UI theo giờ trình
      duyệt đang mở** — rà bằng `grep` mọi nơi gọi `_fmt_jst()`/`_fmt_dt()`
      (hàm hiển thị giờ CỐ ĐỊNH — JST hoặc UTC, không theo người xem),
      đổi cả 5 chỗ còn sót sang `_local_dt_html()` (cơ chế đã có sẵn
      cho Lịch đăng — server render JST làm fallback, JS ghi đè bằng
      giờ trình duyệt thật qua `Date` — không cần thư viện): trạng thái
      đồng bộ + tạm dừng + hạ nhiệt ở `/admin/accounts`, và quan trọng
      nhất — cột "Thời gian (UTC)" ở bảng "Hoạt động gần đây"
      (`/admin/reports`), đúng chỗ vừa gây nhầm lẫn "2 nhóm/2 comment"
      thay vì 3/4 thật do đọc ngày UTC thay vì ngày nghiệp vụ. Đổi tên
      cột thành "Thời gian" (không còn gắn cứng UTC). Xoá hẳn `_fmt_dt()`
      — không còn nơi nào gọi sau khi đổi.
      Verify: render trực tiếp qua Python xác nhận cả 3 điểm đúng
      (nút tier ra `<button type="button">` thuần không còn `<form>`
      POST; cột "Tuổi tài khoản" so khớp đúng tier thật của `tu_iizuki`
      lẫn trường hợp tuỳ chỉnh; bảng Hoạt động gần đây không còn nhãn
      "(UTC)", có `data-local-dt`). 110 test vẫn pass. **Chưa xác nhận
      trên UI thật** — cần restart service.

## Báo cáo "Theo từng lần đăng" (2026-09-12) — hoàn thành

- [x] Thêm dạng báo cáo mới xem theo TỪNG LẦN ĐĂNG (theo job), gom theo
      `(source_kind='job', source_id, account_id)` thay vì từng dòng
      hành động rời rạc như "Hoạt động gần đây". Chọn hướng (a) đã ghi
      chú trước đó: thêm cột `job_data TEXT` vào `action_log` (migrate
      qua `ALTER TABLE`, cùng mẫu với `screenshot_path`) để lưu title +
      attributes thô từ bên B — trước đó chỉ nằm trong file JSON của
      `schedule_store`, không nối ngược lại được từ `action_log`.
      - `human_bot/db.py`: cột `job_data`, index mới
        `idx_action_log_source(source_kind, source_id, account_id)`,
        `log_action(job_data=...)`, 3 hàm truy vấn mới
        `job_post_groups()` / `job_post_groups_count()` /
        `job_post_group_detail()`.
      - `human_bot/agent.py`'s `TaskRequest` + `_log_result()`: thêm
        field `job_data`, truyền xuống `db.log_action()`.
      - `human_bot/data_sync.py`'s `fire_due_tasks()` và
        `human_bot/admin.py`'s `schedule_fire_now()` (2 nơi bắn job
        post thật — tự động + thủ công "Đăng ngay"): truyền
        `job_data=task.job_data` vào `TaskRequest`. `reports_repost()`
        (chức năng "Đăng lại") CHỦ Ý không truyền — repost vốn đã bỏ
        toàn bộ nguồn gốc job theo thiết kế cũ, không đổi mà không được
        hỏi trước.
      - `human_bot/admin.py`'s `/admin/reports`: thêm card mới
        "📮 Theo từng lần đăng" giữa 2 card "Tỉ lệ thành công/thất bại"
        và "Hoạt động gần đây" — mỗi job 1 khối `<details>` gập lại
        được, mở ra thấy dữ liệu gốc (tiêu đề/công ty/địa điểm/visa/
        JLPT/lương) + bảng con từng nhóm (giờ đăng riêng, nội dung ĐÃ
        đăng riêng, KQ, ghi chú). Có phân trang riêng
        (`job_page`, cố định 10 job/trang) — luôn kèm theo
        `page`/`page_size` của "Hoạt động gần đây" trên mọi link để 2
        khối phân trang không tự reset lẫn nhau khi swap chung 1 khối
        `#reports-content` qua htmx.
      - Migration đã chạy thật trên `human_bot.db` đang dùng (xác nhận
        96 dòng cũ còn nguyên, cột + index mới đã có).
      - Test mới: `tests/test_db.py` (8 test, cô lập bằng
        `monkeypatch.setattr(db, "DB_PATH", tmp_path/...)`, không đụng
        DB thật). Toàn bộ suite: 118 passed.

## /admin/reports — chỉnh nhỏ + chia tab (2026-09-12)

- [x] Cột "Nhóm" trong bảng chi tiết "Theo từng lần đăng" hiện là link
      (`<a href target="_blank">`) bấm mở thẳng nhóm Facebook, thay vì
      chỉ hiện tên chữ thường.
- [x] Sửa `_expandable_text()` (dùng chung cho cột "Nội dung đã đăng"
      và "Ghi chú" ở mọi bảng báo cáo) — bug owner phát hiện: bấm mở
      rộng bị lặp lại đoạn text đã hiện rút gọn phía trên. Nguyên nhân:
      code cũ tách riêng `<summary>` (bản rút gọn) và `<div>` (bản đầy
      đủ) — `<summary>` vẫn hiển thị khi `<details>` mở, nên 2 bản
      chồng lên nhau. Sửa bằng CSS-only: `<summary>` giờ chứa NGUYÊN
      VĂN BẢN ĐẦY ĐỦ, class `.expandable-text` tự cắt 1 dòng + dấu "…"
      khi đóng (`white-space:nowrap; overflow:hidden; text-overflow:
      ellipsis`) và bỏ cắt khi mở (`details[open] summary`) — không còn
      2 bản riêng biệt để bị lặp.
- [x] Cố định độ rộng cột cho 2 bảng "Theo từng lần đăng" (chi tiết
      từng nhóm) và "Hoạt động gần đây" — chuyển sang
      `table-layout:fixed; width:100%` + chia % cho từng `<th>` (không
      dùng px cố định — lần đầu tính nhầm bằng px tuyệt đối khiến tổng
      cột vượt quá khung màn hình thật của owner, đã sửa lại theo %,
      luôn khớp đúng bất kể màn hình rộng bao nhiêu). Cột "Nội dung đã
      đăng" chỉnh về 32% (không cần rộng — owner: mỗi dòng chỉ hiện
      ~65-70 ký tự do đã bị cắt 1 dòng).
- [x] **Chia tab cho `/admin/reports`** (owner nhận thấy trang quá
      nhiều nội dung — 6 card xếp chồng, 2 card có phân trang riêng
      phải luôn mang theo state của nhau qua mọi link). 3 tab:
      "📊 Thống kê chi tiết" (KPI + theo tuần/nhóm/hành động, tab mặc
      định — giữ hành vi cũ cho link/bookmark cũ không có `tab` trong
      URL), "📮 Theo từng lần đăng", "🕒 Hoạt động gần đây". Bộ lọc
      tài khoản/khoảng thời gian dùng CHUNG cho mọi tab (nằm ngoài,
      phía trên tab-nav). Chuyển tab qua htmx (`hx-get`, không JS),
      chỉ tab đang active mới thực sự chạy query + render — 2 tab kia
      không tốn query DB. Mỗi tab giờ độc lập hoàn toàn về phân trang
      (không cần mang `job_page` theo link "Hoạt động gần đây" hay
      ngược lại nữa). Tham số mới `tab` thêm vào
      `_reports_content_html()`, `reports_page()`, `reports_repost()`
      (mặc định `"recent"` cho repost vì nút "Đăng lại" chỉ có ở tab
      đó). Verify: render riêng từng tab qua Python xác nhận đúng nội
      dung xuất hiện/không xuất hiện đúng tab, `tab` lạ/thiếu rơi về
      "tables" mặc định. Toàn bộ suite vẫn 118 passed.

## Báo cáo "Theo từng lần bình luận" (2026-09-12) — hoàn thành

- [x] Owner hỏi báo cáo "Theo từng lần đăng" có gồm comment không —
      kiểm tra code xác nhận KHÔNG: mỗi job chỉ tạo task
      `action="post_to_group", source_kind="job"`; comment
      (`comment_on_group_post`/`comment_on_friend_post`) chỉ gắn với
      `source_kind="candidate"` (trả lời ứng viên bên B, hoàn toàn
      tách biệt luồng job đăng nhóm) — xem `data_sync.py`'s `sync_all()`
      dòng ~1022-1027. Owner sau đó yêu cầu thêm báo cáo tương tự cho
      comment: comment nào đăng vào bài nào, nội dung gốc, nội dung
      đã đăng.
- [x] Phát hiện thêm 1 lỗ hổng khi tra: `ScheduledTask.candidate_data`
      (thuộc tính gốc của ứng viên — `desiredJobField`/
      `preferredRegion`, dùng để AI viết lại reply — xem
      `content_strategist.rewrite_candidate_reply()`) **chưa từng được
      truyền xuống `action_log`** — giống hệt tình trạng `job_data`
      TRƯỚC lần sửa 2026-09-12 ở trên. `data_sync.py`'s
      `fire_due_tasks()` và `admin.py`'s `schedule_fire_now()` đều chỉ
      truyền `job_data=task.job_data` khi tạo `TaskRequest` — với task
      loại candidate thì `task.job_data` luôn `None` (chỉ job mới có),
      nên dữ liệu gốc ứng viên trước giờ bị mất khi ghi log. Sửa bằng
      cách đổi thành `job_data=task.job_data or task.candidate_data`
      (đúng 1 trong 2 luôn có giá trị tuỳ `source_kind`) ở CẢ 2 nơi —
      **không cần thêm cột DB mới**, tái dùng đúng cột `job_data` sẵn
      có (đổi ý nghĩa thành "dữ liệu gốc chung cho job HOẶC candidate",
      đã cập nhật docstring `db.log_action()`).
      - `human_bot/db.py`: 3 hàm mới `candidate_comments()` /
        `candidate_comments_count()` / `candidate_comment_detail()` —
        y hệt cấu trúc `job_post_groups()` nhưng lọc
        `source_kind='candidate'` (khác biệt: 1 ứng viên bình thường
        chỉ có ĐÚNG 1 lượt bình luận, không fan-out nhiều nhóm như
        job — GROUP BY vẫn cần để gộp đúng trường hợp hiếm bị retry
        qua "Đăng lại" tạo 2 dòng cho cùng 1 ứng viên).
      - `human_bot/admin.py`'s `/admin/reports`: thêm tab thứ 4
        "💬 Theo từng lần bình luận" (giữa "Theo từng lần đăng" và
        "Hoạt động gần đây") — cùng cấu trúc card `<details>` gập lại
        được như tab job, dữ liệu gốc hiện "Muốn làm"/"Khu vực mong
        muốn", bảng con "Bài/Nhóm" (link bấm mở thẳng)/"Nội dung đã
        đăng"/KQ/Ghi chú. Phân trang riêng (`candidate_page`, cố định
        10 ứng viên/trang, cùng mẫu `job_page`). Tách 2 hàm dùng
        chung (`_recent_result_icon`, `_group_link_html`) ra khỏi
        block `if tab == "jobs":` lên phạm vi chung của hàm — trước đó
        nằm lồng trong nhánh job nên tab candidate gọi vào sẽ
        `NameError`, phát hiện và sửa ngay khi viết.
      - **Dữ liệu gốc cho các dòng comment CŨ (trước lần sửa này) sẽ
        hiện "(không có dữ liệu gốc)"** — xác nhận thật trên
        `human_bot.db`: các dòng `source_kind='candidate'` có sẵn đều
        có `job_data = None`. Chỉ ứng viên được xử lý SAU khi service
        chạy code mới mới có đủ dữ liệu gốc.
      - Test mới: 8 test thêm vào `tests/test_db.py` (nay 16 test
        tổng cho file này) — bao gồm test riêng cho trường hợp retry
        tạo 2 dòng cùng 1 ứng viên. Toàn bộ suite: 126 passed.

## Chỉnh tiếp báo cáo job/comment (2026-09-12)

- [x] Thêm cột **"Ảnh"** vào cả 2 bảng chi tiết "Theo từng lần đăng" và
      "Theo từng lần bình luận" — tái dùng `_screenshot_link_html()` +
      cột `screenshot_path` sẵn có trong `action_log` (giống hệt "Hoạt
      động gần đây"), không cần đổi schema DB.
- [x] **Bỏ gom nhóm cho "Theo từng lần bình luận"** — owner: "chỉ có 1
      bình luận cho từng bài viết nên không cần gom nhóm lại đâu, thể
      hiện rõ ra luôn cũng được". Đổi từ cấu trúc card `<details>` gập
      lại (kiểu job, vốn cần gom vì 1 job → nhiều nhóm) sang **bảng
      phẳng 1 dòng/1 lượt bình luận**, cột đúng theo yêu cầu: Thời
      gian | Bài/Nhóm | Dữ liệu gốc | Nội dung đã đăng | KQ | Ảnh |
      Ghi chú.
      - `human_bot/db.py`: bỏ hẳn `candidate_comments()` bản GROUP BY
        + hàm `candidate_comment_detail()` (không cần nữa) — viết lại
        `candidate_comments()` thành query phẳng `SELECT * ... ORDER
        BY created_at DESC LIMIT/OFFSET` trực tiếp trên `action_log`,
        `candidate_comments_count()` cũng bỏ GROUP BY tương ứng.
      - `human_bot/admin.py`: xoá vòng lặp card/detail lồng nhau, thay
        bằng 1 bảng `<table>` duy nhất y hệt cấu trúc "Hoạt động gần
        đây" nhưng thêm cột "Dữ liệu gốc" (Muốn làm/Khu vực mong
        muốn, rút gọn từ `_candidate_data_summary_html()`).
      - Cập nhật lại `tests/test_db.py` theo API phẳng mới — xoá 2
        test cho `candidate_comment_detail()` (hàm không còn tồn
        tại), sửa 2 test group-by thành test cho hành vi phẳng (mỗi
        dòng action_log hiện riêng, kể cả dòng do retry tạo ra không
        còn bị gộp). Toàn bộ suite: 124 passed (giảm 2 so với trước
        do bớt 2 hàm/test không còn cần).

## Đổi tên tab + 3 lựa chọn "Đăng lại" (2026-09-12)

- [x] Đổi tên tab: "Theo từng lần đăng" → **"Bài đăng"**, "Theo từng
      lần bình luận" → **"Bình luận"** (giữ nguyên emoji 📮/💬).
- [x] **Thêm 3 lựa chọn khi bấm "↻ Đăng lại"** ở CẢ 3 nơi (Hoạt động
      gần đây, Bài đăng, Bình luận — owner: khi bấm Đăng lại, hiện
      modal giải thích ngắn gọn 3 nút cho ADMIN chọn, thay vì đăng lại
      ngay lập tức như trước) — chỉ áp dụng cho dòng THẤT BẠI (giữ
      nguyên phạm vi cũ của nút Đăng lại):
      - **🚀 Đăng ngay** — y hệt hành vi cũ, không đổi (`run_task()`
        ngay lập tức qua `/admin/reports/repost`, vẫn kiểm tra đủ
        giới hạn số lượng/ngày, /giờ).
      - **📅 Đặt lịch** — mở `/admin/post`, điền sẵn nội dung + URL
        đích qua query param (`prefill_content`/`prefill_target_url`),
        admin tự chọn ngày giờ. Với bài đăng nhóm: tick sẵn đúng
        checkbox nhóm trên tab "Đăng vào nhóm". Với bình luận: **thêm
        hẳn 1 tab mới "💬 Bình luận" vào /admin/post** (chưa từng có
        form soạn comment nào ở đó trước đây) — URL bài/hồ sơ cần
        bình luận nhập tay (không có danh sách nhóm để chọn như bài
        đăng, vì bình luận nhắm vào 1 bài CÓ SẴN cụ thể), submit qua
        route mới `/admin/post/schedule-comment`, tự suy ra
        `comment_on_group_post` hay `comment_on_friend_post` từ URL
        (dùng đúng quy tắc `"/groups/" in url` như `data_sync.py`'s
        `sync_all()` đang dùng cho candidate thật).
      - **🔄 Lên lịch lại** — tự tính giờ trống gần nhất KHÔNG vi phạm
        posts_per_day/comments_per_day, TÁI DÙNG nguyên các hàm đã có
        sẵn thay vì viết luật riêng: `daily_limits.hard_cap_message()`
        (còn hạn mức hôm nay không), `daily_limits.business_day_start()`
        (nếu hết hạn mức thì nhảy sang đúng mốc 2h sáng ngày nghiệp vụ
        kế tiếp), `apply_quiet_hours()` (không rơi vào giờ yên tĩnh),
        `RateLimiter.next_allowed_at()` (không sớm hơn khoảng cách tối
        thiểu với lần đăng gần nhất) — gói lại trong hàm mới
        `_suggest_reschedule_at()`. Hiện giờ gợi ý, ADMIN bấm "Xác
        nhận" mới thật sự thêm vào lịch (`schedule_store.add()`) —
        route mới `/admin/reports/reschedule-confirm`. **Khác với
        "Đăng ngay" (cố tình bỏ nguồn gốc job/candidate theo thiết kế
        cũ), "Đặt lịch"/"Lên lịch lại" giữ lại đúng `source_kind`/
        `source_id`/`job_data` hoặc `candidate_data`** — task mới tạo
        ra sẽ hiện đúng vị trí (gom đúng job/candidate) trong báo cáo
        "Bài đăng"/"Bình luận" một khi nó thật sự chạy.
      - `human_bot/admin.py`: hàm mới `_repost_choice_button_html()`
        (nút "↻" giờ mở modal thay vì submit thẳng),
        `_repost_choice_modal_html()` (modal 3 lựa chọn),
        `_suggest_reschedule_at()`. Route mới: `GET
        /reports/repost-choice` (mở modal), `GET
        /reports/reschedule-suggest` (bước 1 "Lên lịch lại" — tính +
        hiện giờ gợi ý), `POST /reports/reschedule-confirm` (bước 2 —
        thật sự thêm vào lịch), `POST /post/schedule-comment` (tạo
        task comment mới từ tab "💬 Bình luận"). `reports_repost()`
        (route cũ, không đổi logic) giờ trả thêm `_MODAL_CLOSE_OOB` để
        modal tự đóng sau khi "Đăng ngay" xong.
      - Verify: gọi trực tiếp từng hàm/route qua Python xác nhận đúng
        HTML (modal có đủ 3 nút, gợi ý giờ đúng dạng aware datetime),
        và test tay 2 route có ghi dữ liệu
        (`post_schedule_comment`/`reports_reschedule_confirm`) bằng
        cách `mock.patch` 4 hằng số thư mục của `schedule_store`
        (`PENDING_DIR`/...) sang thư mục tạm — xác nhận task mới tạo
        ra đúng field (`action`/`content`/`scheduled_at`/
        `source_kind`/`job_data`), **không đụng thư mục `scheduled/`
        thật**. Không thêm test cố định vào `tests/` cho các route
        admin.py này — theo đúng phạm vi test hiện có của dự án (chỉ
        cover logic thuần, chưa từng unit-test route admin.py nào).
        Toàn bộ suite pytest hiện có: 124 passed (không đổi).

## 3 sửa nhỏ + 1 bug thật ở "Đăng lại" (2026-09-12)

- [x] Ô input "URL bài đăng/hồ sơ cần bình luận" ở tab "💬 Bình luận"
      (`/admin/post`) rộng ra hết khung — trước đó dùng độ rộng mặc
      định của trình duyệt (rất hẹp), giờ `width:100%;
      box-sizing:border-box;`.
- [x] **Thay nút "↻ Đăng lại" bằng text trạng thái khi đã xử lý rồi**
      (owner: "Bài Đăng/Bình luận nào đã được lên lịch lại (tự động
      hay ADMIN thêm lại, hoặc đã ĐĂNG NGAY)" thì đổi nút thành text
      "Đã đăng lại"/"Đã lên lịch lại"). Trước đây KHÔNG có cách nào
      biết 1 dòng thất bại đã được xử lý chưa — mỗi lần vào báo cáo
      lại thấy y hệt nút "↻" dù đã bấm "Đăng ngay"/"Đặt lịch"/"Lên
      lịch lại" trước đó rồi.
      - Thêm cột mới `retry_of_log_id INTEGER` vào `action_log`
        (migrate `ALTER TABLE`, **lưu ý migration order**: phải chạy
        `ALTER TABLE` xong rồi mới `CREATE INDEX` trên cột mới — lúc
        đầu để chung trong `_SCHEMA`'s `executescript()`, `CREATE
        INDEX` chạy TRƯỚC `ALTER TABLE` nên báo lỗi "no such column"
        ngay khi import `human_bot.db` — phát hiện ngay lập tức vì
        đây là module chạy `ensure_schema()` lúc import, sửa xong xác
        nhận lại 100 dòng cũ + cột/index mới đều còn nguyên trên
        `human_bot.db` thật).
      - `schedule_store.ScheduledTask` + `agent.py`'s `TaskRequest`:
        thêm field `retry_of_log_id`, truyền xuyên suốt tới
        `db.log_action()` — set ở CẢ 3 nhánh: `reports_repost()`
        ("Đăng ngay", set thẳng), `reports_reschedule_confirm()` ("Lên
        lịch lại", set thẳng), và `post_schedule_profile()`/
        `post_schedule_groups()`/`post_schedule_comment()` (mới, "Đặt
        lịch" — đọc từ hidden field `retry_of_log_id` do
        `_repost_choice_modal_html()`'s link "Đặt lịch" truyền qua
        query param). `data_sync.py`'s `fire_due_tasks()` và
        `admin.py`'s `schedule_fire_now()` đều truyền tiếp
        `task.retry_of_log_id` khi task đó thật sự chạy.
      - `db.py`: hàm mới `successful_retry_log_ids(log_ids)` — 1 query
        gộp cho CẢ TRANG thay vì 1 query/dòng.
      - `admin.py`: hàm mới `_repost_action_cell_html()` — kiểm tra
        `pending_retry_ids` (quét `schedule_store.list_pending()` 1
        lần/trang, dùng chung cho cả 3 tab) trước, rồi mới tới
        `done_retry_ids` (theo từng tab, chỉ query trên đúng tập dòng
        đang hiển thị) — pending thắng vì đó là trạng thái mới hơn.
        3 nơi hiển thị (Bài đăng/Bình luận/Hoạt động gần đây) đều đổi
        sang dùng hàm này thay vì gọi thẳng nút.
      - Verify: giả lập cả 3 trạng thái (chưa xử lý → nút hiện; vừa
        "Lên lịch lại" nhưng chưa chạy → "⏳ Đã lên lịch lại"; đã chạy
        thành công → "✅ Đã đăng lại") bằng cách `mock.patch` cả
        `schedule_store` LẪN `db.DB_PATH` sang thư mục/file tạm, xác
        nhận đúng text hiện đúng lúc. Không đụng dữ liệu thật.
- [x] **Bug thật: "🔄 Lên lịch lại" gợi ý ĐÚNG 1 giờ y hệt cho nhiều
      dòng khác nhau trong cùng 1 lần làm việc** (owner tự tay phát
      hiện: bấm Lên lịch lại dòng A → 12/9 15:04, xác nhận, bấm Lên
      lịch lại dòng B → VẪN 12/9 15:04). Nguyên nhân: `_suggest_
      reschedule_at()` chỉ đọc dữ liệu THẬT ĐÃ XẢY RA (`daily_limits`/
      `RateLimiter` đều chỉ đọc `action_log`/log file) — 1 task vừa
      được "Lên lịch lại" thành công chỉ nằm trong `schedule_store`'s
      `pending/`, CHƯA hề chạy, nên hạn mức/khoảng cách tính ra y hệt
      lần trước, không "thấy" gợi ý cũ vừa được chấp nhận. Sửa bằng
      cách gộp thêm task PENDING (cùng tài khoản + cùng bucket
      post/comment) vào cả 2 phép kiểm: (1) đếm hạn mức ngày nghiệp vụ
      — nếu hôm nay đã đủ (tính real + pending) thì nhảy sang ngày kế
      tiếp, lặp có giới hạn 60 lần giống `data_sync.py`'s
      `_next_available_business_day()`; (2) khoảng cách tối thiểu —
      lấy thêm mốc "task pending trễ nhất + min_delay_seconds" làm
      sàn, cùng với sàn cũ từ `RateLimiter.next_allowed_at()`. Verify:
      viết lại kịch bản y hệt owner mô tả (mock `schedule_store` sang
      thư mục tạm, gọi gợi ý 2 lần liên tiếp có tạo pending task ở
      giữa) — xác nhận lần 2 KHÁC lần 1 và tôn trọng đúng khoảng cách
      tối thiểu.
      - Toàn bộ suite pytest: 124 passed (không đổi — vẫn chưa thêm
        test cố định cho route admin.py theo đúng quy ước cũ, chỉ
        verify bằng script tạm không commit).

## "Dữ liệu gốc" đầy đủ hơn (2026-09-12)

- [x] Owner hỏi tab "Bài đăng"/"Bình luận" giờ đầy đủ hơn "Hoạt động
      gần đây" — xác nhận KHÔNG dư: "Hoạt động gần đây" vẫn là nơi
      DUY NHẤT hiện `post_to_own_profile`, `like_post`, và bài/comment
      soạn tay không qua job/candidate (không có `source_kind`) — 2
      tab mới chỉ phủ đúng phần có nguồn job/candidate.
      Owner tiếp: **"Phần nội dung gốc nên đầy đủ hơn"** — `_job_data_
      summary_html()`/`_candidate_data_summary_html()` trước đó chỉ
      hiện đúng 1 danh sách field cố định (job: Công ty/Địa điểm/Loại
      visa/JLPT/Lương; candidate: Muốn làm/Khu vực mong muốn) — dù
      `job_data`/`candidate_data` lưu trong DB đã là NGUYÊN VẸN dict
      thô từ bên B (không lọc bớt gì lúc ghi), field nào không nằm
      trong danh sách cứng đó (VD `confidence`, `contact`) bị ẩn
      hoàn toàn dù dữ liệu vẫn có sẵn.
      - `human_bot/admin.py`: thêm `_ATTR_LABELS` (map tên field thô
        → nhãn tiếng Việt cho các field đã biết) + hàm dùng chung
        `_attrs_summary_html(title, attrs)` — hiện ĐỘNG mọi field
        không rỗng trong `attrs`, field lạ không có trong
        `_ATTR_LABELS` vẫn hiện (dùng luôn tên field thô làm nhãn)
        thay vì biến mất — tự động phủ được field bên B thêm sau này
        mà không cần sửa code. `confidence` (số thập phân 0-1) format
        lại thành phần trăm cho dễ đọc (`0.99` → `99%`).
      - `_job_data_summary_html()`/`_candidate_data_summary_html()`
        giờ chỉ còn việc parse JSON rồi gọi `_attrs_summary_html()` —
        không tự liệt kê field nữa. Tránh trùng lặp: `title` không
        còn fallback về `jobField` (vì `jobField` đã tự hiện qua vòng
        lặp field dưới "Ngành nghề" rồi, fallback sẽ hiện 2 lần).
      - Verify: dữ liệu thật trong `human_bot.db` xác nhận field
        `confidence` (trước đây bị ẩn) giờ hiện đúng dạng "99%"; test
        tay field lạ (`unknownField`) vẫn hiện bằng tên thô; dữ liệu
        rỗng vẫn rơi về "—" đúng như cũ. Toàn bộ suite: 124 passed.

## Sửa GẤP: không tự đăng bài quá hạn sau khi server tắt/mở lại (2026-09-14)

- [x] Owner hỏi: server tắt lâu rồi mở lại thì bài lỡ giờ đăng có bị
      "dồn chạy 1 lần" không? Tra code xác nhận: KHÔNG dồn trên CÙNG 1
      tài khoản + cùng loại hành động (rate-limiter tự chặn), nhưng
      GIỮA nhiều tài khoản khác nhau (hoặc post/comment cùng 1 tài
      khoản, 2 loại không chia sẻ gap) thì CÓ THỂ đăng gần như liên
      tiếp ngay khi service vừa dậy — `fire_due_tasks()`'s vòng lặp
      `for task in due:` không có khoảng nghỉ nhân tạo nào giữa các
      task. Owner yêu cầu sửa gấp: task đã quá giờ đăng khi server tắt
      thì KHÔNG được tự đăng nữa — phải đưa ra chỗ khác cho ADMIN duyệt
      lại (đăng lại — tự chọn giờ hoặc để hệ thống tính giờ trống, hay
      xoá/huỷ, hỗ trợ chọn nhiều/chọn tất cả rồi xoá 1 lúc).
      **Owner làm rõ thêm khi được hỏi về ngưỡng**: KHÔNG dùng ngưỡng
      thời gian trễ bao lâu — chỉ so sánh 1 LẦN DUY NHẤT ngay lúc
      service KHỞI ĐỘNG LẠI (so với mốc giờ start), task nào lúc đó đã
      quá giờ mới bị coi là "quá hạn"; trong lúc server đang chạy bình
      thường mà bị trễ/dồn việc (rate-limit, backlog...) thì KHÔNG coi
      là quá hạn — đây là hành vi bình thường của hệ thống, không đụng
      tới.
      - `human_bot/schedule_store.py`: thêm trạng thái thứ 5
        `MISSED_DIR` (cùng kiểu "thư mục là trạng thái" với
        pending/posted/failed/cancelled sẵn có — không xoá gì, chỉ
        chuyển thư mục). Hàm mới: `list_missed()`, `get_missed()`,
        `get_missed_reason()`, `mark_missed()` (pending → missed, kèm
        `.result.txt` giải thích lý do), `restore_to_pending()` (missed
        → pending, đồng thời cho sửa `content`/`scheduled_at` — dùng
        chung cho cả "Đặt lịch" và "Lên lịch lại"), `cancel_missed()`
        (missed → cancelled, cùng đích với "Huỷ" bình thường).
        **Phát hiện + sửa 1 bug thật lúc viết test**: `_move_to()` cũ
        có `source_dir: Path = PENDING_DIR` làm giá trị mặc định cho
        tham số — giá trị mặc định này gán CỐ ĐỊNH lúc Python LOAD
        module (import time), không phải lúc gọi hàm, nên
        `monkeypatch`/`mock.patch` đổi `schedule_store.PENDING_DIR`
        sang thư mục tạm để test KHÔNG có tác dụng gì với default đó —
        hàm vẫn âm thầm ghi vào đúng thư mục THẬT. Sửa bằng cách đổi
        default thành `None`, resolve về `PENDING_DIR` THẬT SỰ bên
        trong thân hàm (đọc biến module lúc gọi, không phải lúc định
        nghĩa) — đúng nguyên tắc Python "mutable/global default argument
        bị đóng băng lúc def". Phát hiện ngay lập tức vì viết test cô
        lập trước khi tin là đúng, không phải chạy thật rồi mới biết.
      - `human_bot/data_sync.py`: hàm mới
        `sweep_overdue_on_startup()` — chỉ gọi ĐÚNG 1 LẦN, so sánh với
        1 mốc `datetime.now(timezone.utc)` chụp ngay lúc gọi, quét
        `schedule_store.list_pending()`, task nào `scheduled_at` đã
        qua mốc đó thì `mark_missed()`. KHÔNG phải một vòng lặp định
        kỳ, KHÔNG có ngưỡng phút/giờ nào — đúng yêu cầu owner.
      - `human_bot/service.py`: gọi `sweep_overdue_on_startup()` đúng
        1 lần trong `lifespan()`, TRƯỚC KHI tạo `fire_task` (vòng lặp
        `fire_due_tasks()` định kỳ) — đảm bảo không có task quá hạn
        nào lọt qua được due-check đầu tiên. Log cảnh báo nếu có task
        bị quét.
      - `human_bot/admin.py`: thêm mục **"⚠️ Task quá hạn cần duyệt"**
        vào đầu `/admin/schedule` (chỉ hiện khi có task quá hạn, không
        chiếm chỗ lúc bình thường) — mỗi dòng có nội dung/giờ dự kiến
        ban đầu/lý do quá hạn, checkbox chọn từng dòng (dùng thuộc
        tính HTML `form="missed-bulk-form"` để checkbox nằm ngoài
        `<form>` bulk vẫn tham gia submit được, tránh lồng `<form>`
        trong `<form>` không hợp lệ), "Chọn tất cả", nút "🗑️ Xoá đã
        chọn" (bulk), và mỗi dòng có 2 lựa chọn xử lý riêng: "📅 Đặt
        lịch" (form sửa nội dung + chọn giờ tay, submit thẳng) và
        "🔄 Lên lịch lại" (mở modal — TÁI DÙNG nguyên
        `_suggest_reschedule_at()` đã viết cho `/admin/reports`, chỉ
        đổi input từ 1 dòng action_log sang 1 `ScheduledTask` — cùng
        logic gợi ý giờ trống, admin xác nhận mới thật sự lên lịch).
        5 route mới: `POST /schedule/missed/reschedule`,
        `GET /schedule/missed/suggest`,
        `POST /schedule/missed/reschedule-confirm`,
        `POST /schedule/missed/cancel`,
        `POST /schedule/missed/bulk-cancel`.
      - Verify: viết kịch bản đầy đủ bằng `mock.patch`/`monkeypatch` 5
        hằng số thư mục của `schedule_store` sang thư mục tạm — tạo 3
        task "quá hạn" (giả lập server tắt), chạy
        `sweep_overdue_on_startup()` xác nhận cả 3 bị chuyển sang
        `missed/` và KHÔNG đăng gì cả; test riêng 1 task tương lai xác
        nhận KHÔNG bị quét; gọi sweep lần 2 (giả lập không có downtime)
        xác nhận `swept=0`; test cả 3 đường xử lý (Đặt lịch tay, Lên
        lịch lại tự động + xác nhận, Xoá theo lô) đều đưa đúng task ra
        khỏi `missed/`. Không đụng `scheduled/` thật. Sau khi verify
        bằng script tạm, viết lại thành test cố định: **12 test mới**
        — `tests/test_schedule_store.py` (9 test, file mới — trước đó
        `schedule_store.py` chưa có test riêng, chỉ được đụng gián
        tiếp qua stub trong `test_data_sync.py`; có 1 test hồi quy
        riêng khoá chặt đúng bug `_move_to()` vừa sửa) + 3 test
        `sweep_overdue_on_startup()` thêm vào `test_data_sync.py`.
        Toàn bộ suite pytest: **136 passed** (124 cũ + 12 mới).

## Chia LỊCH ĐĂNG thành 2 tab (2026-09-14)

- [x] Owner yêu cầu tách `/admin/schedule` thành 2 tab: **"📋 Task đã
      lên lịch"** (danh sách pending sẵn có) và **"⚠️ Task quá hạn"**
      (mục vừa thêm ở trên, trước đó chỉ là 1 card cảnh báo hiện phía
      trên danh sách pending). Cùng kiểu tab (`hx-get` đổi tab, không
      JS riêng) đã dùng cho `/admin/reports`.
      - `human_bot/admin.py`: `_schedule_content_html()` thêm tham số
        `tab`, hằng số `_SCHEDULE_TABS`/`_clamp_schedule_tab()`. Tiêu
        đề tab hiện luôn kèm số lượng — "Task đã lên lịch (N)"/"Task
        quá hạn (M)" — nên không cần đếm lặp lại trong nội dung tab
        nữa (bỏ số đếm khỏi tiêu đề card cũ của mục quá hạn).
      - `_missed_tasks_section_html()`: bỏ `if not missed: return ""`
        (trước đây conditionally ẩn cả card) — giờ là nội dung CHÍNH
        của 1 tab, tab vẫn hiện được kể cả rỗng (hiện
        "Không có task nào quá hạn — mọi thứ đúng lịch." thay vì biến
        mất hẳn), đúng cách "Task đã lên lịch" tab cũng hiện
        empty-state khi rỗng.
      - 5 route `/schedule/missed/*` (reschedule/suggest/
        reschedule-confirm/cancel/bulk-cancel) đều hardcode
        `tab="missed"` khi gọi lại `_schedule_content_html()`/
        `_schedule_redirect()` — đảm bảo sau khi xử lý xong 1 task quá
        hạn, trang render lại đúng Ở NGUYÊN tab "Task quá hạn" thay vì
        nhảy về mặc định "Task đã lên lịch". 4 route pending cũ
        (`update`/`cancel`/`fire-now`) không cần sửa gì — mặc định
        `tab=None` đã tự rơi về "pending" sẵn, đúng hành vi cũ.
      - Verify: render qua Python xác nhận tab mặc định chỉ hiện nội
        dung "Task đã lên lịch", `tab=missed` chỉ hiện nội dung quá
        hạn (không lẫn nội dung 2 tab), `tab` lạ/rỗng rơi về "pending"
        an toàn; trang đầy đủ (không qua htmx) vẫn render đúng cả 2
        tab. Toàn bộ suite: 136 passed (không đổi — chỉ tổ chức lại
        UI, không đổi logic đã có test).

## 2 sửa nhỏ cho tab "Task quá hạn" (2026-09-14)

- [x] **Giờ trong lý do quá hạn hiển thị dạng ISO thô** (VD "Đã quá giờ
      đăng dự kiến (2026-09-13T07:58:00+00:00) lúc service khởi động
      lại (2026-09-14T04:14:27.174285+00:00)...") — owner yêu cầu hiện
      giờ đồng bộ theo giờ trình duyệt như mọi nơi khác trong Admin UI.
      Chuỗi lý do này do `data_sync.sweep_overdue_on_startup()` build
      sẵn dạng text thuần (ghi vào `.result.txt`, file audit — vẫn giữ
      nguyên ISO thô ở ĐÓ, không đổi, vì là file text thô không phải
      HTML). Chỗ CẦN đổi là lúc ADMIN.PY RENDER chuỗi đó ra HTML — thêm
      hàm mới `_localize_iso_timestamps_html(text)`: dò bằng regex mọi
      chuỗi giống ISO 8601 trong `text`, thay từng chuỗi khớp bằng
      `_local_dt_html()` (span JS tự đổi theo giờ trình duyệt), phần
      còn lại của `text` vẫn `html.escape()` bình thường (không hở lỗ
      hổng chèn HTML qua phần chữ xung quanh). Verify: chạy thử đúng
      câu lý do owner dán vào, xác nhận cả 2 mốc giờ đều được bọc
      `data-local-dt` đúng.
- [x] **Thêm phân trang cho tab "Task quá hạn"** — trước đó hiện hết
      toàn bộ danh sách 1 lần, không giới hạn. Thêm `missed_page`
      **TÁCH RIÊNG** khỏi `page` của tab "Task đã lên lịch" (2 tab có
      số lượng không liên quan gì nhau, dùng chung 1 biến "page" sẽ
      lệch trạng thái y hệt lỗi `job_page`/`candidate_page` đã gặp ở
      `/admin/reports`) — dùng chung `page_size`/`_SCHEDULE_PAGE_SIZE_CHOICES`
      sẵn có. Hàm mới `_missed_page_link()`/`_missed_pagination_html()`
      (Đầu/Trước/nhảy trang/Sau/Cuối, y hệt kiểu đã dùng cho tab
      pending). `missed_page` xuyên suốt qua cả 5 route
      `/schedule/missed/*` (hidden field trong mỗi form + query param
      của route GET suggest) để mọi hành động (đặt lịch/lên lịch
      lại/xoá/xoá theo lô) render lại đúng TRANG đang xem, không nhảy
      về trang 1. `_schedule_form_filter()` đổi từ trả về 3 giá trị
      thành 4 (`account_id, page, page_size, missed_page`) — cập nhật
      cả 7 nơi đang unpack tuple này (3 route pending + 4 route
      missed).
      - Verify: tạo 25 task quá hạn (vượt page_size mặc định 20) bằng
        thư mục tạm — xác nhận trang 1 hiện đúng 20, trang 2 hiện đúng
        5 còn lại, khối phân trang hiện "/ 2"; tab "Task đã lên lịch"
        không bị ảnh hưởng. Toàn bộ suite: 136 passed (không đổi).

## Bug thật: vượt `posts_per_day` do nhóm bị "trôi" sang ngày khác giữa job (2026-09-14)

- [x] Owner hỏi vì sao 1 lần sync lấy 132 job nhưng chỉ lên lịch được 1
      bài — tra `_sync_status.json` xác nhận đúng (132 fetched, 1
      scheduled). Nguyên nhân lần đó: capacity ngày hôm đó gần hết (đã
      có 4/5 slot dùng từ các job trước), `job_capacities` chỉ còn 1 →
      water-fill chỉ chia đúng 1 job, 131 job còn lại KHÔNG mất — quay
      lại `deferred_jobs`, giữ cursor bên B để lần sync sau lấy lại.
      Đây là hành vi ĐÚNG, không phải bug.
      **Nhưng khi tra sâu hơn để xác nhận cơ chế tràn-ngày còn hoạt
      động, phát hiện 1 bug thật riêng biệt**: ngày nghiệp vụ 15/9 có
      tới **9 bài đã lên lịch** dù `posts_per_day = 5` — vượt hạn mức
      thật sự (xác nhận bằng dữ liệu thật trong `schedule_store`, toàn
      bộ 9 dòng đều `reasoning: "auto: ..."` — KHÔNG liên quan gì tới
      tính năng "Đăng lại"/"Lên lịch lại" của admin vừa làm, loại trừ
      hẳn nghi ngờ ban đầu của owner).
      **Nguyên nhân gốc**: `_next_available_business_day()` chỉ kiểm
      tra "còn chỗ không" **ĐÚNG 1 LẦN cho cả job** (tính ra
      `post_day_key` + `available`, dùng để giới hạn CHỌN bao nhiêu
      nhóm cho job đó) — nhưng giờ đăng THẬT của từng nhóm lại tính
      SAU đó, riêng lẻ, qua `_next_available_post_slot()`. Hàm này áp
      thêm khoảng cách tối thiểu RIÊNG cho từng nhóm (VD 120 phút nếu
      nhóm đó vừa đăng gần đây) — có thể đẩy nhóm cuối của job **qua
      khỏi mốc 2h sáng JST**, tức sang MỘT NGÀY NGHIỆP VỤ KHÁC với
      `post_day_key` đã chốt — mà không ai kiểm tra lại ngày đó còn
      chỗ hay không, cứ thế cộng dồn `day_post_counts` bất kể ngày đó
      đã đầy chưa. Tích luỹ qua nhiều lần sync (mỗi ~15-20 phút) →
      vượt hạn mức ngày đó.
      **Hướng sửa (thảo luận kỹ với owner trước khi làm, xác nhận
      từng bước qua ví dụ số cụ thể)**: kiểm tra lại hạn mức ngay khi
      phát hiện 1 nhóm bị "trôi" sang ngày khác — nếu ngày đó cũng hết
      chỗ, DỪNG job tại đó (không đăng nhóm này và các nhóm còn lại),
      coi job đã xử lý xong VỚI SỐ NHÓM ĐÃ ĐĂNG ĐƯỢC (tái dùng đúng
      nguyên tắc "đăng vừa đủ" đã có). **Owner tự phát hiện thêm 1 lỗ
      hổng trong hướng sửa ban đầu**: nếu NHÓM ĐẦU TIÊN của job đã
      dính (0 nhóm nào đăng được), code cũ vẫn gọi `_mark_seen()` vô
      điều kiện sau vòng lặp → job bị đánh dấu "đã xong" dù chưa đăng
      gì cả, mất vĩnh viễn — đúng loại lỗi đã từng sửa cho tài khoản 0
      nhóm. Sửa lại: đếm số nhóm THẬT SỰ đăng được trong job
      (`groups_posted_this_job`) — ≥1 nhóm mới `_mark_seen()`, 0 nhóm
      thì đưa vào `deferred_jobs_inner` để thử lại lần sync sau.
      - `human_bot/data_sync.py`: hàm mới `_has_room_for_drifted_group()`
        (tách riêng, theo đúng kiểu các hàm logic thuần đã tách sẵn
        như `_next_available_business_day()` — để viết test cô lập
        được) — kiểm tra 1 ngày nghiệp vụ còn chỗ hay không, dùng
        trong vòng lặp đăng từng nhóm của `sync_all()`: nhóm nào
        `scheduled_day_key != post_day_key` (đã trôi ngày) mới cần
        gọi hàm này; nếu hết chỗ thì `break` khỏi vòng lặp nhóm.
      - Verify: 4 test mới cho `_has_room_for_drifted_group()` — đúng
        kịch bản owner quan sát được (ngày đã đầy 5/5, nhóm trôi tới
        → từ chối), ngày còn chỗ → chấp nhận, `real_used_today` chỉ
        áp dụng đúng `today_key` không áp nhầm sang ngày tương lai
        khác. `sync_all()` bản thân chưa unit-test được (cần gọi HTTP
        thật tới bên B, đúng giới hạn test đã ghi nhận từ trước) —
        verify bằng cách đọc lại đúng luồng code + logic đã tách hàm
        con để test riêng. Toàn bộ suite: 140 passed (136 cũ + 4
        mới).

## Bug thật: `_suggest_reschedule_at()` áp giờ yên tĩnh trước, không tái kiểm tra sau (2026-09-14)

- [x] Owner hỏi vì sao ngày nghiệp vụ 15/9 đang bị xếp nhiều hơn 5
      comment và 5 post (câu hỏi này khác câu hỏi "132 job chỉ lên
      lịch 1 bài" ở mục trên — dẫn tới 1 bug khác). Tra dữ liệu thật:
      số lượng comment thực tế vẫn đúng (4 < cap 7), nhưng phát hiện
      `_suggest_reschedule_at()` (hàm gợi ý giờ cho "🔄 Lên lịch lại")
      áp giờ yên tĩnh **TRƯỚC** khi cộng "sàn" khoảng cách tối thiểu
      (gap floor) — nếu sàn đẩy giờ gợi ý lùi lại rơi ĐÚNG vào khung
      giờ yên tĩnh, không có bước nào tái kiểm tra lại; tương tự,
      phép kiểm tra "ngày có đầy không" chỉ chạy ĐÚNG 1 LẦN trước khi
      áp sàn, nên sàn có thể đẩy gợi ý sang đúng 1 ngày đã đầy sẵn mà
      không ai biết.
- [x] Sửa bằng cách viết lại thành **vòng lặp hội tụ**: áp sàn → áp
      giờ yên tĩnh → kiểm tra lại hạn mức ngày, lặp lại tới khi không
      còn gì thay đổi (giới hạn 60 lần lặp). Thêm file test mới
      `tests/test_admin.py` (test đầu tiên cho `admin.py`) — 4 test:
      tái hiện đúng cả 2 kịch bản bug (sàn đẩy vào giờ yên tĩnh, sàn
      đẩy sang ngày đã đầy), hồi quy cho bug gợi ý trùng giờ gốc
      (2026-09-12), và 1 test sanity không có lịch sử.

## Owner làm rõ luật đăng vào nhóm bằng văn bản + rà soát code khớp/lệch (2026-09-15)

- [x] Owner phát biểu rõ ràng bằng văn bản toàn bộ ràng buộc mong
      muốn cho việc đăng bài vào nhóm: (1) tổng số bài đăng vào n
      nhóm ≤ `posts_per_day`; (2) khoảng cách giữa 2 lần đăng vào BẤT
      KỲ nhóm nào chỉ cần tuân `post_min/max_delay_seconds` (không có
      luật riêng cho từng nhóm); (3) cần cơ chế chia đều nhóm được
      chọn cho 1 tài khoản qua nhiều bài (không cố định cụm 1,2,3 rồi
      4,5,6..., nhưng cũng không cần random thật sự — chỉ cần tránh
      nhóm được đăng quá nhiều trong khi nhóm khác không được đăng
      lần nào).
- [x] Đối chiếu với code thật, báo lại owner: **THIẾU** — chưa có
      chút ngẫu nhiên nào trong việc chọn nhóm (thuần sắp xếp
      cũ-nhất-trước, luôn ra đúng 1 tổ hợp cố định); **KHÁC** — code
      đang có thêm 1 luật riêng cho từng nhóm
      (`_next_available_post_slot()`) mà owner chưa từng yêu cầu, và
      luật đó còn đang dùng NHẦM giá trị cấu hình
      (`cfg.post_gap_min_minutes` — khoảng cách chung 20 phút mặc
      định — thay vì `post_min_delay_seconds` thật của tài khoản).
      Owner xác nhận: bỏ hẳn luật riêng từng nhóm, và làm cơ chế chọn
      nhóm "không cố định cụm nhưng không cần random thật sự".
- [x] **Xoá hẳn `_next_available_post_slot()`** (`human_bot/
      data_sync.py`) — chỗ gọi duy nhất đổi thành gọi thẳng
      `apply_quiet_hours()`. **Thêm `_pick_groups_for_job()`** — sắp
      xếp nhóm theo cũ-nhất-trước (đảm bảo không nhóm nào bị bỏ đói),
      lấy 1 pool rộng hơn số cần chọn (`_GROUP_SELECTION_POOL_SLACK =
      2`), rồi `random.sample()` trong pool đó — vừa đảm bảo công
      bằng (nhóm lâu nhất chưa đăng luôn nằm trong pool) vừa tránh
      lặp lại đúng y hệt tổ hợp mỗi lần. 5 test mới: không bao giờ bỏ
      đói nhóm lâu nhất (50 lần thử), trả về ít hơn khi không đủ
      nhóm, không trùng lặp, không bao giờ chọn ra ngoài pool, kết
      quả thay đổi qua nhiều lần gọi (30 lần thử) — không cố định.

## Bug thật: thiếu "sàn" cho `next_post_time` giữa các lần sync (2026-09-15)

- [x] Trong lúc dọn dữ liệu thật bị xếp lịch sai (do 2 bug ở trên),
      phát hiện nguyên nhân RIÊNG khiến bài đăng thật vẫn dồn cục dù
      2 bug trên đã sửa: `next_comment_time` đã có "sàn" chống 2 lần
      sync độc lập xếp giờ quá gần nhau
      (`_last_scheduled_comment_time()`, thêm 2026-09-10 cho đúng sự
      cố tương tự bên comment) — nhưng `next_post_time` **chưa từng
      có sàn tương đương**. Mỗi lần `sync_all()` chạy đều tính
      `next_post_time` mới hoàn toàn từ `now`, không biết lần sync
      TRƯỚC đã xếp gì — 2 lần sync độc lập có thể ra giờ gần nhau
      thuần do trùng hợp ngẫu nhiên (đúng hiện tượng owner quan sát:
      các bài chỉ cách nhau ~30 phút dù cấu hình 120-210 phút).
- [x] Sửa bằng hàm mới `_last_scheduled_post_time()` (rập khuôn y hệt
      `_last_scheduled_comment_time()`) + `_POST_ACTIONS =
      {post_to_group, post_to_own_profile}`, nối vào `sync_all()`
      làm sàn cho `next_post_time` (cùng cách `next_comment_time`
      đang làm) — cả sàn "lần sync trước đã xếp gì" lẫn sàn
      `RateLimiter.next_allowed_at("post")` (chặn thật từ lần đăng
      gần nhất). 5 test mới xác nhận đúng hành vi.

## Dọn dữ liệu thật bị xếp sai do 3 bug trên (2026-09-15)

- [x] Sau khi sửa xong cả 3 bug (trôi ngày, thiếu random chọn nhóm +
      luật thừa, thiếu sàn `next_post_time`), 13 task `post_to_group`
      đang `pending` của tài khoản `tu_iizuki` vẫn còn mang dấu vết
      xếp lịch SAI từ trước khi sửa (ngày 15/9 có 9 bài dù cap 5,
      giãn cách nhiều chỗ chỉ ~30 phút). Tính lại kế hoạch xếp lịch
      cho đúng 13 task này theo luật đã sửa (cap 5/ngày, giãn cách
      120-210 phút, né giờ yên tĩnh), dùng `random.seed(20260915)` cố
      định để có thể trình bày trước cho owner xem đúng y hệt kết quả
      sẽ áp dụng — owner duyệt ("Áp dụng"), chạy
      `schedule_store.update()` cho từng task (chỉ đổi `scheduled_at`,
      không đụng nội dung/URL/tài khoản). Xác nhận lại trạng thái
      cuối: 14/9 = 4 (giữ nguyên, đã đúng từ trước), 15/9 = 5 (đủ
      cap), 16/9 = 5 (đủ cap), 17/9 = 3 (tràn), mọi khoảng cách liên
      tiếp ≥ 120 phút.

## Rà soát lần 2 (yêu cầu owner "kiểm tra kĩ lưỡng") + sửa 3 lỗi phát hiện được (2026-09-15)

- [x] Owner yêu cầu rà soát kỹ lại toàn bộ việc sửa trong ngày (dùng
      1 agent review độc lập, tự tay verify lại từng phát hiện trước
      khi báo owner — không tin thẳng kết quả agent). Phát hiện 5 vấn
      đề, xếp theo mức nghiêm trọng, đã tự tay verify từng cái bằng
      script/đọc code trực tiếp trước khi báo:
      1. **[Đã sửa]** `max_groups_per_post = 0` (giá trị hợp lệ lưu
         được qua `/admin/accounts` — form chỉ chặn số âm) khiến
         `_pick_groups_for_job(..., needed=0)` trả về `[]`,
         `groups_posted_this_job` không bao giờ > 0 → job bị hoãn
         (defer) mãi mãi thay vì đánh dấu xong — hệ quả trực tiếp của
         chính bản sửa "chỉ mark_seen khi ≥1 nhóm đăng được" ở trên.
         Kiểm chứng bằng cách gọi thẳng hàm với `needed=0`, xác nhận
         trả `[]`. Sửa: thêm chốt kiểm tra `max_groups_per_post <= 0`
         y hệt cách xử lý `available <= 0` đã có sẵn, hoãn job ngay
         từ đầu thay vì đi tiếp vào bước chọn nhóm vô ích. **Lưu ý
         trung thực**: hành vi CUỐI CÙNG không đổi so với code cũ
         (nhánh else có sẵn đã tự hoãn đúng job) — bản sửa chủ yếu
         tránh lãng phí tính toán + làm rõ ý định bằng comment.
      2. **[Chưa sửa, đã giải thích cho owner]** Vòng lặp comment
         (candidate) chỉ mới có bước "phát hiện ngày đầy → hoãn",
         CHƯA có bước "tràn sang ngày kế tiếp" như vòng lặp job đã
         có (`_next_available_business_day()`) — 1 candidate rơi vào
         ngày đầy sẽ khiến MỌI candidate còn lại trong cùng lượt sync
         cũng bị hoãn theo (vì `next_comment_time` không được đẩy
         sang ngày khác), dù ngày sau vẫn còn chỗ. Không mất dữ liệu
         (đều vào hàng đợi hoãn để thử lại), chỉ bị chậm không cần
         thiết. Owner xác nhận chưa cần làm ngay.
      3. **[Đã sửa]** `_last_scheduled_post_time()`/
         `_last_scheduled_comment_time()`/
         `_last_scheduled_time_per_group()` không tự chuẩn hoá
         naive/aware datetime (khác `RateLimiter` floor cạnh đó có
         làm) — nếu 1 task có `scheduled_at` thiếu múi giờ (lý
         thuyết: qua `/admin/schedule/update` hoặc `.../missed/
         reschedule`, 2 route duy nhất đưa thẳng chuỗi form vào
         `schedule_store` không qua parse) sẽ crash `TypeError` khi
         so sánh. Tự kiểm chứng: ô nhập giờ trên UI thực chất luôn
         convert sang ISO có "Z" qua JS (`toISOString()`) trước khi
         submit, nên đường UI bình thường KHÔNG gặp — chỉ rủi ro nếu
         JS lỗi/tắt hoặc gọi thẳng API. Sửa: hàm dùng chung
         `_parse_scheduled_at()`, luôn trả về aware (tự gán UTC nếu
         thiếu offset), thay cho `datetime.fromisoformat()` trần ở 4
         chỗ. Thêm 3 test (chuẩn hoá đúng, chuỗi rác trả `None`,
         không crash khi trộn naive/aware).
      4. **[Đã sửa]** Sót 2 dòng comment/docstring trong `admin.py`
         (~dòng 3715, 3776) vẫn nhắc tên hàm
         `_next_available_post_slot()` đã bị xoá hẳn ở mục trên — chỉ
         là dọn tài liệu, không ảnh hưởng chức năng.
      5. **[Đã sửa theo yêu cầu owner]** Vòng lặp hội tụ mới của
         `_suggest_reschedule_at()` (viết lại 2026-09-14, mục trên)
         vô tình co hẹp phạm vi tìm ngày trống từ 60 ngày (code cũ)
         xuống còn ~30 ngày thực — vì mỗi lần "nhảy" sang 1 ngày đã
         đầy giờ tốn ~2 lần lặp thay vì 1: ngày nghiệp vụ luôn bắt
         đầu đúng 2h sáng JST, mà giờ yên tĩnh mặc định cũng bắt đầu
         đúng 2h sáng — nên mỗi lần đẩy sang ngày mới đều cần thêm 1
         lần lặp riêng chỉ để né giờ yên tĩnh của ngày đó. Owner xác
         nhận 30 ngày là đủ, không cần tận 60 — đặt tường minh bằng
         hằng số `_RESCHEDULE_SEARCH_DAYS = 30` (ngân sách lặp `30 ×
         3`) thay vì để co hẹp ngoài ý muốn.
      - Toàn bộ suite sau khi sửa cả #1/#3/#4/#5: **155 passed**
        (152 cũ + 3 mới cho `_parse_scheduled_at()`/naive-aware).

## Thêm filter "Hành động" + "Ngày đăng" cho /admin/schedule (2026-09-15)

Owner yêu cầu: tab "📋 Task đã lên lịch" ở LỊCH ĐĂNG chỉ lọc được theo
tài khoản — thêm lọc theo **Hành động** (Đăng vào nhóm | Comment bài
trong nhóm) và **Ngày đăng**, yêu cầu rõ ngày phải khớp ĐÚNG giờ đang
hiển thị trên web (không phải giờ server).

- `_schedule_content_html()` (`admin.py`) nhận thêm `action_filter`/
  `date_filter`/`tz_offset`, lọc `tasks` trước khi phân trang — 2 lựa
  chọn hành động cố định qua `_SCHEDULE_FILTERABLE_ACTIONS =
  ("post_to_group", "comment_on_group_post")` (không đưa cả 6 giá trị
  `_ACTION_LABELS` vào — 4 còn lại là hành động tạm dừng/chỉ đăng thủ
  công, xem `project_deprioritized_fb_actions`).
- **Đúng giờ hiển thị trên web**: `/admin/schedule` vốn đã hiển thị
  giờ theo browser của người xem (`_local_dt_html()`, JS
  `initLocalDateTime()`), không cố định JST — nên filter ngày PHẢI
  dùng đúng múi giờ đó, không phải giờ server. Thêm field ẩn
  `tz_offset` (id `schedule-tz-offset`), JS mới `initTzOffsetField()`
  tự điền `-Date().getTimezoneOffset()` (phút cần CỘNG vào UTC để ra
  giờ local) mỗi lần trang tải/htmx swap — cùng cơ chế
  `initLocalDateTime()` đang dùng. Server so khớp bằng
  `_task_local_date()`: `utc_datetime + timedelta(minutes=tz_offset)`
  rồi lấy `%Y-%m-%d`.
- 5 ô filter (tài khoản/số dòng mỗi trang/hành động/ngày/tz_offset ẩn)
  include chéo nhau qua `hx-include`, giống pattern 2 ô filter cũ —
  đổi 1 ô không làm mất giá trị 4 ô còn lại.
- Thread `action`/`date`/`tz_offset` xuyên suốt: link phân trang
  (`_schedule_page_link()`), field ẩn trong mỗi form
  sửa/đăng-ngay/huỷ theo dòng (`filter_fields`), modal xác nhận
  "Vẫn đăng ngay" khi bị rate-limit (`_fire_now_confirm_modal_html()`),
  route GET `/schedule`, và `_schedule_form_filter()` dùng chung bởi
  cả 7 route POST (đổi tuple trả về từ 4 sang 7 phần tử — 2 route
  pending (`schedule_update`, `schedule_cancel`, `schedule_fire_now`)
  dùng thật, 4 route thuộc tab "Task quá hạn" chỉ giải nén rồi bỏ qua
  vì filter mới không áp dụng ở tab đó).
- Test thật bằng service chạy port riêng (8123, không đụng port 8000
  đang chạy thật): xác nhận tổng 2 hành động cộng lại = tổng không
  lọc (21+4=25), tổng theo ngày cộng lại = tổng không lọc
  (6+6+5+5+3=25), và **tz_offset thật sự đổi kết quả** — cùng ngày
  15/09 nhưng `tz_offset=0` (UTC) ra 9 dòng còn `tz_offset=540` (JST)
  ra 6 dòng, đúng vì biên ngày dịch theo múi giờ khác nhau.
- Chưa viết unit test riêng cho `_task_local_date()`/lọc mới (chỉ xác
  nhận bằng chạy thật ở trên) — `admin.py` vẫn chưa có test suite nào
  (xem mục 4.15's "Vẫn còn thiếu"), cùng tình trạng với phần còn lại
  của file này.
- Toàn bộ 155 test cũ vẫn pass (không đụng logic `data_sync.py`/
  `schedule_store.py`, chỉ thêm lọc ở lớp hiển thị `admin.py`).

**Chỉnh tiếp theo owner phản hồi (cùng ngày):** tách "Hành động"/"Ngày
đăng" xuống hàng riêng dưới "Tài khoản"/"Hiển thị" (2 `<div
class="account-filter">` xếp chồng thay vì 1 hàng dài `flex-wrap` co
giãn theo độ rộng màn hình), và thêm nút "✕ Xoá bộ lọc" — chỉ hiện khi
`action_filter`/`date_filter` đang có giá trị, chỉ xoá 2 ô đó (giữ
nguyên tài khoản/số-dòng-mỗi-trang đang chọn, không reset toàn bộ).
Xác nhận lại bằng service thật (port 8123): nút không hiện khi chưa
lọc gì, hiện khi có lọc, và link của nó giữ đúng `account_id` trong
khi bỏ hẳn `action`/`date`/`tz_offset` khỏi query string.

## Bug thật: datetime picker hiện trống sau khi chuyển tab trình duyệt (2026-09-15)

Owner báo: ô chọn giờ (`_datetime_picker_html()`, dùng ở cả
"Sửa"/"📅 Đặt lịch" trên /admin/schedule và "Đăng lên tường cá nhân"
trên /admin/post) đang có giá trị, chuyển sang tab trình duyệt khác rồi
quay lại thì ô hiện TRỐNG — bấm F5 mới thấy lại giá trị đúng.

- Không phải mất dữ liệu: field ẩn `data-schedule-utc` (field thật được
  submit) vẫn giữ đúng giá trị suốt — chỉ có ô hiển thị
  `<input type="datetime-local">` (`data-schedule-local`) bị trống về
  mặt hiển thị. Đây là quirk đã biết của Chromium: giá trị field
  datetime-local được SET BẰNG JS (không phải người dùng tự gõ, ở đây
  là `initScheduleField()`'s bước tự điền ban đầu, hoặc nút chọn nhanh
  "+1h"/"+1d") không luôn giữ nguyên hiển thị sau khi tab mất/lấy lại
  focus — F5 "sửa" được chỉ vì nó chạy lại đúng bước tự điền đó từ đầu
  trên trang parse mới.
- Không liên quan tới 2 tab của CHÍNH /admin/schedule ("Task đã lên
  lịch"/"Task quá hạn") — 2 tab đó đã tự re-sync đúng qua
  `initDynamicScope()` chạy lại trên mọi `htmx:afterSwap` (comment sẵn
  có, mục 4.12, giải quyết đúng loại bug này cho trường hợp htmx swap
  toàn bộ nội dung). Đây là tab của TRÌNH DUYỆT (alt-tab/chuyển qua
  tab khác rồi quay lại) — không có htmx swap nào chạy, nên không tự
  sửa được.
- Sửa: hoist `pad`/`toLocalInputValue` ra khỏi `initScheduleField()`
  lên scope ngoài (dùng chung), thêm `refreshScheduleFieldDisplays()`
  quét mọi `[data-schedule-field]` đã init, ĐỌC LẠI hiển thị từ chính
  `data-schedule-utc` (không phải set giá trị mới) — không thể ghi đè
  mất 1 chỉnh sửa đang gõ vì mỗi lần gõ vào ô hiển thị đã tự đồng bộ
  ngược lại field ẩn ngay qua listener `input` sẵn có. Gọi hàm này ở
  cả `visibilitychange` (tab trình duyệt lấy lại focus) và `pageshow`
  (một số trình duyệt không bắn `visibilitychange` khi phục hồi từ
  bfcache, ví dụ bấm Back).
- Xác nhận: service thật (port 8124) trả về JS hợp lệ
  (`node --check`), markup `data-schedule-field`/`data-schedule-local`/
  `data-schedule-utc` không đổi ở cả 20 dòng render thật. Chưa test
  được hành vi tab-switch thật (cần browser thật, không unit-test
  được) — cùng tình trạng "Vẫn còn thiếu" đã ghi ở mục 4.16 cho phần
  JS/browser của Admin UI. 155 test cũ vẫn pass (thay đổi chỉ ở JS
  nhúng trong `admin.py`, không đụng route/logic Python nào).

## Sửa lại đúng bug datetime picker (owner báo "vẫn chưa ổn") (2026-09-15)

Owner phản hồi: bug KHÔNG chỉ ở chuyển tab TRÌNH DUYỆT — ngay cả
chuyển qua lại giữa 2 tab "Task đã lên lịch"/"Task quá hạn" (2 tab
NGAY TRONG trang Lịch đăng) đã đủ làm mất giá trị datetime picker.
Đợt sửa trước (`visibilitychange`/`pageshow`) không giải quyết case
này — vì đó không phải nguyên nhân thật.

**Tìm nguyên nhân thật bằng Playwright (Chromium thật, không đoán mò
nữa sau khi đợt trước đoán sai):**
- Viết script tự động: mở `/admin/schedule`, đọc giá trị datetime
  picker đầu tiên, bấm tab "Task quá hạn" → bấm lại "Task đã lên
  lịch" → đọc lại giá trị. Tái hiện ĐÚNG bug: `'2026-09-15T19:24'` →
  `''`.
- Bắt `pageerror` trên trang: có lỗi JS thật `TypeError: Cannot read
  properties of null (reading 'addEventListener')`, xảy ra ngay lúc
  TẢI TRANG LẦN ĐẦU (trước khi bấm tab nào), tại đúng dòng
  `document.body.addEventListener("htmx:afterSwap", ...)`.
- **Nguyên nhân gốc**: toàn bộ `<script>` của trang (`_PAGE_STYLE`,
  nhúng vào `<head>` qua `_layout()`) chạy NGAY TRONG `<head>` —
  lúc đó `document.body` CHƯA TỒN TẠI (`<body>` chưa được parse).
  `document.body.addEventListener(...)` vì vậy NÉM LỖI ngay từ lúc
  parse, nghĩa là listener `htmx:afterSwap` **CHƯA TỪNG được đăng ký
  thành công, ở BẤT KỲ trang admin nào, từ lúc dòng này được viết**
  — không phải bug mới, không phải do đợt sửa filter/picker gần đây.
  Hệ quả: mọi lần htmx swap nội dung (chuyển tab, đổi filter, sửa/
  đăng-ngay/huỷ...) ĐỀU không chạy lại `initDynamicScope()` — chỉ
  được che giấu vì `DOMContentLoaded`'s init chạy đúng 1 lần lúc tải
  trang lần đầu, làm tưởng "picker vẫn hoạt động, chỉ lỗi lúc chuyển
  tab" trong khi thật ra CƠ CHẾ RE-INIT SAU SWAP LÚC NÀO CŨNG KHÔNG
  CHẠY.
- Xác nhận bằng cách đọc `dataset` của phần tử ngay sau khi swap:
  `{"scheduleField":""}` — thiếu hẳn key `scheduleInit`, chứng minh
  `initScheduleField()` chưa từng chạy cho phần tử vừa được htmx
  chèn vào.

**Sửa đúng chỗ**: đổi `document.body.addEventListener(...)` thành
`document.addEventListener(...)` — event tuỳ biến do htmx bắn ra vẫn
nổi bọt (bubble) lên tới `document` như thường, mà `document` thì
LUÔN tồn tại kể cả khi đang parse giữa `<head>`, khác với
`document.body`. Đây là sửa TRIỆT ĐỂ (không phải giải pháp tạm), áp
dụng chung cho MỌI trang admin dùng htmx swap, không riêng
/admin/schedule.

**Xác nhận lại bằng Playwright sau khi sửa:**
- Không còn `pageerror` nào.
- `dataset` sau swap có đủ `scheduleInit:"1"`.
- Giá trị datetime picker giữ đúng sau khi chuyển tab 1 lần, và sau
  3 lần chuyển tới-lui liên tiếp.
- Đổi bộ lọc "Hành động" (cũng là 1 htmx swap khác) — giá trị picker
  vẫn giữ đúng.

Đợt sửa `visibilitychange`/`pageshow` ở mục trên (dành cho case
chuyển tab TRÌNH DUYỆT, alt-tab) vẫn giữ nguyên — vô hại, và có thể
vẫn cần cho đúng trường hợp đó (Chromium's quirk là thật, độc lập với
bug `document.body` này), chỉ là nó không phải nguyên nhân của báo
cáo lần này. 155 test cũ vẫn pass.

## Viết lại toàn bộ cơ chế "hạ nhiệt" sau khi Kích hoạt lại — 2 tuần có nấc, sửa tận gốc bug mất rate-limit gốc (2026-09-15)

Owner yêu cầu (sau khi tôi báo bug `prior_overrides` bị ghi đè khi
pause/resume chồng lấn, mục trên): thiết kế lại hẳn cooldown thành 14
ngày (2 tuần), có nấc tăng dần theo tuổi tài khoản, và khi hết hạn
phải ưu tiên khôi phục đúng số ADMIN đã tự cài trước đó (nếu có),
không phải lúc nào cũng ép về đúng tier.

**Thiết kế cuối (đã thống nhất qua nhiều vòng hỏi-đáp với owner):**
- Tuần 1 (ngày 0–7): mọi tier đều về mức sàn cố định (1/1/2/2,
  `SafetyCooldownConfig`).
- Tuần 2 (ngày 7–14): nhích lên 1 nấc theo bảng
  `COOLDOWN_WEEK2_STEP_UP_TIER` (mới, `human_bot/config.py`):
  Dưới 3 tháng/Dưới 6 tháng → mức Dưới 1 tháng; Dưới 12 tháng/Trên 12
  tháng → mức Dưới 3 tháng; ri.eng Dưới 1 tháng không có tier thấp
  hơn nên giữ nguyên mức sàn cả 2 tuần (owner chọn).
- Sau 14 ngày: **không ghi gì cả** — chỉ xoá record cooldown. Vì suốt
  cả quá trình hạ nhiệt KHÔNG BAO GIỜ đụng tới `rate_limits` override
  thật của tài khoản (đây là điểm mấu chốt), số admin tự cài trước đó
  tự động "hiện lại" ngay khi cooldown không còn được áp — đúng ý
  "ưu tiên khôi phục số admin cài, nếu không có thì theo tier" (không
  có gì để khôi phục ngoài tier thì mặc nhiên nó vẫn đang ở đó rồi).

**Nguồn "tier gốc" ổn định — field mới `account_age_tier`:**
lấy từ dropdown lúc đăng ký tài khoản (mặc định "Dưới 1 tháng" nếu
không chọn — owner yêu cầu rõ, sửa cả nhánh cũ lỡ fallback về 30
bài/ngày nếu form thiếu field) hoặc nút "Áp nhanh theo tuổi" ở modal
Giới hạn tốc độ sau này. **Cố tình KHÔNG suy ngược từ rate_limits** —
đây chính là nguyên nhân gốc của bug cũ (đọc số hiện tại lúc đang hạ
nhiệt sẽ chỉ thấy số đã giảm). Gõ tay số tuỳ ý (không qua nút tier)
giữ nguyên `account_age_tier` cũ, không xoá.

**Vòng lặp nền mới** (`service.py`'s `_resume_cooldown_maintenance_loop`,
owner đặc tả chính xác): kiểm tra 1h/lần khi KHÔNG có tài khoản nào
đang hạ nhiệt (rẻ, chỉ đọc danh sách key), chuyển sang 1 ngày/lần một
khi có ít nhất 1 tài khoản — chạy `get_active_cooldown_rate_limits()`
cho từng tài khoản (tự hết hạn nếu đã đủ 14 ngày). Khởi động lại
service cũng tự vào đúng vòng này ngay từ đầu — trạng thái cooldown
là JSON trên đĩa (`started_at`+`base_tier`), không mất gì qua restart.
**Lưu ý quan trọng**: vòng lặp này chỉ để CẬP NHẬT KỊP THỜI cho người
xem `/admin/accounts` — tính đúng/sai của rate-limit thật không phụ
thuộc vòng lặp này chạy hay không, vì `get_all_accounts()` luôn tính
lại tươi mỗi lần gọi.

**Test viết mới** — trước đây khu vực cooldown này CHƯA từng có test
nào (một phần lý do bug âm thầm tồn tại lâu):
- `tests/test_runtime_config.py`: 16 test mới (age tier get/set/clear,
  tuần 1 sàn, tuần 2 nhích đúng theo bảng, tuần 2 giữ sàn cho Dưới 1
  tháng, hết hạn không đụng override thật, **test hồi quy trực tiếp
  tái hiện đúng bug cũ** — pause/resume chồng lấn giữa lúc cooldown
  #1 chưa hết hạn, xác nhận `base_tier` VÀ override thật không bị
  hỏng — và `get_rate_limits_overrides()` không còn side-effect hết
  hạn cooldown nữa).
- `tests/test_config.py` (file test ĐẦU TIÊN cho `config.py`): 3 test
  xác nhận `get_all_accounts()` lồng đúng số cooldown lên trên số
  thật (không ghi đè), số thật hiện lại đúng sau khi hết hạn, và
  `max_groups_per_post` (field cooldown không định nghĩa) giữ nguyên.
- Toàn bộ suite: **170 passed** (155 cũ + 12 mới trong
  `test_runtime_config.py` + 3 mới trong `test_config.py`).

**Xác nhận sống qua route thật** (service chạy port riêng 8126, dùng
`tu_iizuki` thật rồi dọn sạch lại sau):
- Modal Giới hạn tốc độ render đúng `data-tier_key` trên cả 5 nút +
  field ẩn `tier_key` rỗng.
- Bấm 1 nút tier (giả lập qua POST thật `/admin/accounts/rate-limits`
  kèm `tier_key`) → `account_age_tier` được lưu đúng, số cũng lưu
  đúng.
- Tạm dừng + Kích hoạt lại thật qua `/admin/accounts/pause`+`/resume`
  → cooldown tuần 1 áp đúng (1/1/2/2), `get_all_accounts()` trả đúng
  số đã giảm, còn `get_rate_limits_overrides()` (số thật bên dưới)
  **không hề đổi** — đúng thiết kế.
- Phát hiện thêm: `runtime_config.json` thật vẫn còn override
  `safety_cooldown.cooldown_days=7` từ trước (đè lên class default
  code mới đổi 14) — cập nhật lại bằng read-merge-write
  (`save_safety_cooldown_overrides`, giữ nguyên các field khác, đúng
  quy tắc "replace cả section, không merge" của hàm này) để khớp
  thiết kế 14 ngày mới.

**Sửa dữ liệu thật cho `tu_iizuki`** (owner đồng ý để mặc định "Dưới
1 tháng" — không nhớ tuổi thật, giá trị gốc đã mất vĩnh viễn do bug
cũ không thể tự khôi phục): đặt `account_age_tier="under_1_month"`,
khôi phục `rate_limits` về đúng preset "Dưới 1 tháng" (5 bài/ngày,
2h-3.5h giữa 2 bài, 7 comment/ngày), xoá `resume_cooldown` (đang rỗng
sẵn, không có gì để xoá thật).

## Rà soát lại toàn bộ đợt viết lại "hạ nhiệt" — phát hiện 3 sai sót nhỏ (2026-09-15)

Owner yêu cầu dò lại lần nữa cho chắc. Đọc lại từng file đã sửa,
kiểm tra logic biên (elapsed_days, ngưỡng tuần 1/2, enabled flag),
grep toàn bộ codebase tìm tham chiếu còn sót tới hàm/field đã xoá.

Phát hiện 3 vấn đề, cả 3 đã sửa và có test:

1. **Bug thật (mới do chính đợt viết lại này gây ra):**
   `get_active_cooldown_rate_limits()` có kiểm tra
   `SafetyCooldownConfig.enabled` nhưng `get_resume_cooldown_info()`
   (hàm build banner "🧊 Đang hạ nhiệt" ở `/admin/accounts`) thì
   KHÔNG — nếu owner tắt công tắc "Bật hạ nhiệt" giữa lúc 1 tài
   khoản đang hạ nhiệt dở dang, tài khoản đó lập tức chạy full tốc
   độ thật (đúng), nhưng UI vẫn hiện "Đang hạ nhiệt tới ngày X",
   sai lệch hoàn toàn với thực tế. Sửa bằng cách gộp điều kiện
   `enabled` vào đúng 1 chỗ dùng chung (`_live_cooldown_entry()`) —
   cả 2 hàm giờ luôn đồng bộ. Quyết định thêm: tắt công tắc KHÔNG
   xoá record đang có (để giữ nguyên tiến độ, bật lại là tiếp tục
   đúng chỗ cũ, không mất `started_at`). Thêm test hồi quy
   `test_disabling_safety_cooldown_hides_the_info_banner_too`.
2. **Nhãn hiển thị ở `/admin/config`'s "Hạ nhiệt sau khi kích hoạt
   lại" chưa cập nhật theo thiết kế 2 tuần mới** — các field
   `posts_per_day`/`comments_per_hour`/... trong `SafetyCooldownConfig`
   ghi "trong lúc hạ nhiệt" (nghe như áp dụng suốt cả cooldown), thật
   ra chỉ là mức TUẦN 1 (tuần 2 của tier đã "trưởng thành" đọc từ
   preset tier khác hẳn, không hề đọc các field này) — dễ khiến
   owner chỉnh số ở đây tưởng ảnh hưởng cả 2 tuần. Sửa nhãn ghi rõ
   "Ở TUẦN 1 hạ nhiệt (mọi tier)", và bổ sung giải thích ngắn cho
   `cooldown_days`.
3. **`docs/skills/anomaly-detection.md` còn trỏ tới hàm đã xoá hẳn**
   (`_expire_resume_cooldown_if_due()`) và mô tả cooldown theo bản
   cũ (1 mức, restore-from-snapshot) — cập nhật lại đúng cơ chế 2
   tuần có nấc + `account_age_tier` mới.

Nhân tiện dọn 1 chỗ nhỏ không phải bug: hardcode chuỗi `"under_1_month"`
ở nhánh fallback của `get_active_cooldown_rate_limits()` đổi sang dùng
hằng số `DEFAULT_ACCOUNT_AGE_TIER` cho nhất quán.

Grep toàn bộ code + docs xác nhận không còn chỗ nào gọi tới
`_expire_resume_cooldown_if_due`/đọc `prior_overrides` (2 chỗ còn lại
là comment giải thích lịch sử bug, không phải code thật).

**171 test passed** (170 trước đó + 1 test hồi quy mới cho vụ
`enabled`).

- [x] **2026-09-15 — Sửa `post_to_group` crash "strict mode violation"
      trên `get_by_role("paragraph")`** (action_log id 146, task thật
      lúc 08:41:44 UTC, nhóm "Việc làm Kỹ Sư Nhật Bản (Uy tín hàng
      đầu)"). Nguyên nhân: locator mở ô soạn bài ở `actions.py` không
      giới hạn phạm vi trong hộp thoại "Create post" — đúng lúc đó có
      cửa sổ chat Messenger ("Write to Thanh Loan") đang mở ở góc màn
      hình, bong bóng tin nhắn trong đó cũng có role "paragraph", nên
      locator khớp 2 phần tử và Playwright ném lỗi thay vì click liều.
      Ảnh chụp lỗi (`screenshots/tu_iizuki/20260915T084144039Z_post_to_group_fail.png`)
      xác nhận nhóm cũng dùng modal "Create post" giống hệt
      `post_to_own_profile`, chứ không phải composer mở "inline" như
      comment cũ trong code từng giả định. Sửa: bó toàn bộ các bước của
      `post_to_group` (paragraph click, textbox, `_attach_media`, nút
      Post) vào `composer_dialog = page.get_by_role("dialog")`, cùng
      cách `post_to_own_profile` đã dùng; đồng thời bó luôn bước
      paragraph-click trong nhánh audience khác "public" của
      `post_to_own_profile` (chưa từng lỗi thật nhưng cùng dạng locator
      không giới hạn phạm vi). Chưa có test tự động (các hàm trong
      `actions.py` cần trình duyệt thật, không unit-test được) — cần
      xác nhận lại khi `post_to_group` chạy thật lần tới.

- [x] **2026-09-16 — Phát hiện & sửa lỗi thứ 2 cùng nguyên nhân gốc: cửa
      sổ chat Messenger còn mở đè lên nút "Post comment"** (action_log id
      151, task thật lúc 10:59 JST / 01:59:12 UTC, comment nhóm
      "vieclamtimnguoi"). Lỗi trả về `comment_box_still_has_content_after_click`
      — đúng như owner quan sát: focus/nhập text vào đúng ô, nhưng bấm nút
      đăng không có tác dụng. Khác với lỗi hôm qua (id 146, trùng role
      selector gây crash strict-mode), lần này không có exception nào cả:
      `human_click()` (`humanize.py`) tự tính toạ độ tâm nút "Post
      comment" rồi bấm chuột thật vào đúng toạ độ đó, KHÔNG kiểm tra phần
      tử tại toạ độ đó có đang bị thứ khác che hay không (bỏ qua hẳn bước
      "actionability check" mà `Locator.click()` chuẩn của Playwright vẫn
      làm). Cửa sổ chat Messenger đang nổi đúng ngay vị trí nút "Post
      comment" thật, nên click chuột thật rơi trúng cửa sổ chat thay vì
      nút Facebook — không báo lỗi ngay, chỉ lộ ra 15 giây sau khi bước
      xác minh "ô comment có rỗng lại không" phát hiện nội dung vẫn còn.
      Đã hỏi owner chọn hướng sửa: **chủ động đóng mọi cửa sổ chat
      Messenger đang mở trước khi thao tác** (thay vì sửa `human_click()`
      để tự kiểm tra che khuất — hướng đó có thể làm sau nếu cần, áp dụng
      chung cho mọi hành động). Thêm hàm `_close_chat_popups()` trong
      `actions.py`, gọi ở đầu `post_to_own_profile`, `post_to_group`, và
      `comment_on_group_post` (trước bước tương tác composer/comment
      box).

      **Cập nhật cùng ngày — đã xác nhận sống bằng Codegen**: owner tự
      ghi lại (`codegen_close_chat_popup.py`, tài khoản `tu_iizuki`) cả 2
      thao tác thu nhỏ và đóng chat thật, xác nhận tên accessible chính
      xác là **"Minimize chat"** và **"Close chat"** (không cần regex,
      match `exact=True`; cả 2 đều generic, không kèm tên người — chỉ nút
      mở lại "Open chat with <tên>" mới cá nhân hoá). Theo yêu cầu owner
      ("ưu tiên minimize, không được thì close"), sửa `_close_chat_popups()`
      thử "Minimize chat" trước, phần chat nào không có nút đó (nếu có)
      mới rơi xuống thử "Close chat". Vẫn best-effort/bọc try-except —
      chỉ còn CHƯA XÁC NHẬN nhánh fallback "Close chat" có thật sự bao giờ
      cần dùng tới không (Codegen ghi lại luôn thấy có nút minimize).

      **Cập nhật cùng ngày — owner tự quan sát và chỉ ra 1 điểm quan
      trọng:** 2 lỗi trên thực chất KHÁC cơ chế, dù cùng một thủ phạm là
      khung chat. Modal "Create post" (đăng nhóm/cá nhân) luôn nổi ĐÈ LÊN
      TRÊN khung chat — nên task 146 không phải do che khuất pixel, mà do
      `get_by_role("paragraph")` quét toàn bộ accessibility tree, không
      quan tâm thứ gì đang nổi trên/dưới về mặt hình ảnh. Ô comment (bài
      viết trong nhóm) thì ngược lại — nằm inline trong luồng trang, KHÔNG
      có z-index riêng để nổi lên, nên thực sự bị khung chat che đè lên
      trên về mặt hiển thị, dẫn tới task 151 (click rơi trúng khung chat).
      Kết luận: gọi `_close_chat_popups()` trước đăng bài vẫn cần thiết
      (phòng lỗi kiểu 146), trước khi comment thì càng quan trọng hơn
      (phòng cả 2 kiểu lỗi). Đã ghi lại phân biệt này vào docstring
      `_close_chat_popups()` trong `actions.py` để tránh nhầm lẫn 2 lỗi
      là một khi debug sau này.

- [x] **2026-09-16 — Sửa bug thứ tự hiển thị `/admin/schedule`: bài quá
      hạn dời lịch sang ngày sau lại hiện lên ĐẦU danh sách** (owner báo
      trực tiếp: dời 1 bài quá hạn sang 17/9, nó hiện trước cả bài 16/9).
      Nguyên nhân: `task_id` (cũng là tên file) được sinh 1 LẦN DUY NHẤT
      lúc tạo task, với tiền tố là `scheduled_at` LÚC ĐÓ
      (`new_task_id()`); `list_pending()`/`list_missed()` sort theo TÊN
      FILE (giả định filename luôn khớp nội dung). Khi "Đặt lịch"/"Lên
      lịch lại" (`restore_to_pending()`) hoặc sửa giờ 1 task đang chờ
      (`update()`) đổi `scheduled_at`, cả 2 hàm chỉ ghi đè field bên
      trong JSON, KHÔNG đổi tên file/sinh `task_id` mới — filename vẫn
      mang mốc giờ CŨ (đã quá hạn), nên vẫn thắng khi sort theo tên file,
      dù nội dung thật đã dời sang tận 17/9. Sửa tận gốc: thêm
      `_scheduled_at_sort_key()` trong `schedule_store.py`, sort
      `list_pending()`/`list_missed()` theo `scheduled_at` ĐỌC LẠI TỪ NỘI
      DUNG file, không dựa vào tên file/task_id nữa — đúng luôn cho mọi
      trường hợp sau này kể cả nếu filename lệch nội dung vì lý do khác.
      Xử lý thêm ca `scheduled_at` bị ghi dạng "naive" (không timezone) —
      vốn là tình trạng thật đã biết (form `/admin/schedule/update` và
      reschedule bài quá hạn ghi thẳng giá trị form, không chuẩn hoá) —
      coi là UTC, cùng quy ước `data_sync.py`'s `_last_scheduled_post_time()`
      đã dùng, để tránh crash khi so sánh naive với aware. Thêm 4 test hồi
      quy trong `test_schedule_store.py`: dời bài quá hạn sang sau vẫn
      xếp đúng vị trí, sửa giờ 1 bài pending vẫn xếp lại đúng, `list_missed()`
      cũng sort đúng, và ca `scheduled_at` naive không bị crash.
      **175 test passed** (171 trước đó + 4 mới), không đụng
      `runtime_config.json`/DB thật (đã xác nhận bằng `md5sum` không đổi
      và `git status` sạch ngoài các file code/test/docs vừa sửa).
