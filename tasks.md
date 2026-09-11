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
