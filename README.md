# AIAgent_w_FB — Tự động hoá Facebook bằng AI Agent (human_bot)

> File này viết bằng tiếng Việt để bạn đọc và theo dõi dự án. Các file kỹ
> thuật (trong `docs/agents/`, `docs/skills/`, `docs/architecture.md`, và
> toàn bộ code) được viết bằng tiếng Anh có chủ đích. Xem mục 7 bên dưới.

## 1. Dự án này là gì

Hệ thống tự động hoá Facebook (đăng bài, comment, tương tác) phối hợp giữa
n8n (điều phối) và `human_bot` (thực thi thao tác thật trên trình duyệt).

**Quyết định kiến trúc quan trọng nhất (đã thay đổi so với bản đầu):**
`human_bot` **không dùng AI để quyết định thao tác trên trình duyệt** —
mỗi hành động (đăng bài, comment...) được ghi lại một lần bằng Playwright
Codegen (bạn tự tay làm thao tác đó, công cụ tự ghi lại thành code), sau
đó chạy lại y hệt bằng Playwright thuần mỗi lần cần. Không cần LLM, không
tốn phí AI, không cần API key nào cho việc đăng bài/comment thật.

Lý do: khi đã biết chính xác từng bước phải làm, để một AI "suy nghĩ lại"
mỗi lần chỉ tốn thêm tiền, chậm hơn, và có rủi ro AI hiểu nhầm rồi bấm
sai. AI chỉ hữu ích khi *không biết trước* phải làm gì — không phải
trường hợp của các thao tác Facebook cố định này.

`browser-use` (thư viện điều khiển trình duyệt bằng AI, dùng ở bản thiết
kế đầu tiên) hiện được **giữ lại làm phương án dự phòng cho tương lai**
(`human_bot/llm.py`) — dùng khi một selector đã ghi bị lỗi do Facebook đổi
giao diện và chưa kịp ghi lại — chứ không còn nằm trong luồng chạy chính.

## 2. Bắt đầu nhanh — chạy lần đầu

Làm đúng thứ tự 6 bước dưới đây, trên máy thật của bạn (không phải qua
sandbox/bridge nào) — mỗi bước có lệnh cụ thể để copy-paste.

**Bước 1 — Cài dependencies Python:**
```
cd AIAgent_w_FB
pip3 install -r requirements.txt
```

**Bước 2 — Cài trình duyệt Chromium cho Playwright** (bắt buộc, dependencies
ở bước 1 không tự tải sẵn):
```
python3 -m playwright install chromium
```

**Bước 3 — Tạo file `.env`:**
```
cp .env.example .env
```
Với luồng chính (đăng bài/comment bằng Playwright thuần), bạn **không cần
điền API key AI nào** — cứ để `.env` gần như trống cũng chạy được. Chỉ cần
điền khi bạn dùng tới `/admin` ở nơi không phải máy cá nhân (`ADMIN_USERNAME`/
`ADMIN_PASSWORD`) hoặc dùng `fallback_auto_login.py` (xem mục 8, bảng file map).

**Bước 4 — Đặt tên `account_id` cho tài khoản Facebook sắp thêm:**
Chỉ cần tự chọn một cái tên (chữ thường, số, dấu gạch dưới — không dấu
cách, không hoa), ví dụ `my_page`. Dùng đúng tên này ở bước 5 và mọi lệnh
sau này — **không cần sửa code ở bước này nữa**, việc đăng ký tài khoản đã
chuyển sang giao diện web `/admin/accounts` (xem cuối bước 5). Vẫn có thể
thêm thẳng vào dict `ACCOUNTS` trong `human_bot/config.py` nếu muốn tài
khoản đó là mặc định cố định, commit vào repo — nhưng không bắt buộc.

> **Lưu ý quan trọng trước khi đăng nhập:** vào tài khoản Facebook bạn sắp
> dùng cho bot → **Cài đặt → Ngôn ngữ (Language)** → đặt thành **English
> (US)**, trước khi chạy bước 5. Toàn bộ selector trong
> `human_bot/actions.py` được ghi lại theo giao diện tiếng Anh — nếu tài
> khoản hiển thị tiếng Việt (hoặc ngôn ngữ khác), hành động đăng bài sẽ
> timeout ngay ở bước đầu tiên (nút mở khung soạn bài không tìm thấy). Xem
> chi tiết lý do ở `docs/skills/facebook-custom-actions.md`, mục "Facebook
> UI language". Nội dung bài đăng vẫn viết tiếng Việt bình thường — chỉ
> giao diện Facebook cần là tiếng Anh.

**Bước 5 — Đăng nhập thủ công một lần, lưu phiên đăng nhập:**
```
python3 human_bot/bootstrap_login.py my_page
```
(`my_page` ở đây chính là `account_id` bạn tự đặt ở Bước 4 — không phải
tên cố định, hãy thay bằng tên bạn đã chọn.)
Một cửa sổ trình duyệt thật sẽ mở ra trang đăng nhập Facebook — bạn tự tay
đăng nhập (kể cả 2FA nếu có), đợi vào được trang chủ Facebook bình thường,
rồi quay lại Terminal nhấn Enter. Lệnh này tạo ra
`accounts/my_page/storage_state.json` — phiên đăng nhập được lưu lại, các
bước sau sẽ dùng lại, không cần đăng nhập lại nữa.

Sau đó, đăng ký tài khoản này để hệ thống nhận ra: khởi động service
(lệnh ở Bước 6 bên dưới), mở `http://localhost:8000/admin/accounts`,
điền `account_id` **khớp đúng tên vừa dùng ở lệnh trên** (`my_page`) và
tên hiển thị, bấm "Đăng ký" — không cần sửa file code, có hiệu lực ngay,
không cần khởi động lại service.

**Thay thế:** nếu chạy service trước rồi mới nhớ ra chưa đăng nhập, không
cần quay lại terminal — đăng ký tài khoản trước (kể cả khi chưa có
`storage_state.json`), vào `/admin/accounts`, bấm nút "🌐 Đăng nhập & lưu
phiên" ngay trên badge đỏ "chưa có storage_state.json" của tài khoản đó,
làm y hệt bước 5 nhưng qua giao diện web. Chỉ dùng được nếu service đang
chạy trên chính máy bạn (có màn hình) — xem tasks.md, đợt 2026-09-09.

**Bước 6 — Chạy thử một hành động thật:** chọn một trong hai cách:

- Qua giao diện web `/admin` (khuyên dùng, đỡ lỗi gõ dấu ngoặc trong
  terminal):
  ```
  uvicorn human_bot.service:app --host 0.0.0.0 --port 8000
  ```
  rồi mở `http://localhost:8000/admin` trên trình duyệt — nếu chưa đăng ký
  tài khoản ở bước 5, vào `/admin/accounts` đăng ký trước — sau đó vào mục
  "Đăng bài", chọn tài khoản `my_page`, gõ nội dung, bấm Đăng.

- Qua dòng lệnh (test nhanh, không cần chạy service):
  ```
  python3 -m human_bot.test_run_task post_to_own_profile my_page "Nội dung test"
  ```

Nếu bước 6 báo `TaskResult(success=True, ...)` và bạn thấy bài đăng thật
trên Facebook, vậy là mọi thứ đã chạy đúng. Mặc định audience là
**"Public"** (chọn được "Friends"/"Only me" qua tham số `audience` hoặc
dropdown "Đối tượng xem" ở `/admin/post` — xem tasks.md, đợt 2026-09-09);
lưu ý nếu tài khoản đã từng chạy bot này trước 2026-09-09, Facebook có
thể vẫn nhớ audience "Only me" cũ cho tới khi bạn đổi tay 1 lần.

**Bước 7 — Nhập danh sách nhóm đã tham gia** (bắt buộc nếu dùng
`post_to_group`/`comment_on_group_post`, hoặc bộ đồng bộ bên B): mở
`http://localhost:8000/admin/groups`, chọn tài khoản, thêm từng nhóm
(tên + URL). Bỏ qua bước này nếu chỉ đăng lên tường cá nhân
(`post_to_own_profile`). Chi tiết: tasks.md, "Quản lý nhóm đã tham gia qua
`/admin/groups`".

**Bước 8 — Bật tự động đăng theo lịch (nếu cần):** mặc định cổng
`auto_fire_enabled` ở `/admin/config` mục "Lên lịch & tự động đăng" đang
**tắt** — mọi bài lên lịch (kể cả soạn tay ở `/admin/post`) sẽ nằm chờ ở
`/admin/schedule`, không tự đăng, phải tự bấm "🚀 Đăng ngay" từng bài. Bật
cổng này lên nếu muốn bài tự động đăng đúng giờ đã hẹn không cần bấm tay.
Chi tiết: tasks.md, "Điểm yếu đã ghi nhận" → `auto_fire_enabled`.

**Bước 9 — Đặt `TASKS_API_KEY` trước khi mở ra ngoài máy cá nhân:** nếu
n8n hoặc một service khác sẽ gọi `POST /tasks` từ máy/mạng khác (không
chỉ chạy trên localhost để test tay), đặt `TASKS_API_KEY` trong `.env` —
nếu không đặt, endpoint này không yêu cầu xác thực. Chi tiết: tasks.md,
"Xác thực (auth) cho `POST /tasks`".

Chi tiết kiến trúc/lý do thiết kế nằm ở các mục bên dưới.

## 3. Đã nghiên cứu gì

- Đánh giá công nghệ browser-use (bản thiết kế đầu tiên): xem
  `docs/research/browser-use.md` (tiếng Việt — ghi chú nghiên cứu).
- Đã thử nghiệm thực tế và phát hiện: browser-use dùng API nội bộ riêng
  (không phải Playwright chuẩn), free-tier LLM Gateway của họ không dùng
  được — hai lý do trực tiếp dẫn tới quyết định chuyển sang Playwright
  thuần ở mục 1.
- Cú pháp Playwright (Codegen, storage_state, Page/Locator API) đã được
  đưa vào các file kỹ thuật trong `docs/skills/`.

## 4. Kiến trúc: 3 agent, không hơn

1. **Content Strategist Agent** — chỉ "nghĩ": quyết định nên đăng gì, comment
   gì, khi nào, dựa trên ngữ cảnh bài viết thật. Không chạm trình duyệt.
   (Đây là nơi AI thực sự cần thiết — quyết định nội dung, không phải
   thao tác click.)
2. **human_bot Executor Agent** — chỉ "làm": nhận lệnh cụ thể đã quyết định
   sẵn, thực thi bằng Playwright thuần, không có AI ở bước này (xem mục 1).
3. **Safety Monitor** — theo dõi kết quả/log, tự động tạm dừng một tài khoản
   nếu phát hiện dấu hiệu bị Facebook hạn chế (checkpoint, captcha...).

Chi tiết đầy đủ, sơ đồ luồng dữ liệu: `docs/architecture.md`.
Vai trò từng agent: `docs/agents/`.

## 5. Các "kỹ năng" (skills) — tài liệu tham chiếu cho từng phần

Nằm trong `docs/skills/` — bảng dưới đây cũng khớp với đoạn giới thiệu
song ngữ ở đầu mỗi file:

| File | Dùng cho | Nội dung |
|---|---|---|
| `facebook-custom-actions.md` | human_bot Executor | Hợp đồng của từng hành động Playwright — đọc khi thêm hành động mới hoặc khi Facebook đổi giao diện |
| `session-persistence.md` | human_bot Executor | Cách lưu/tái dùng phiên đăng nhập Facebook bằng Playwright storage_state |
| `rate-limiting-pacing.md` | human_bot Executor, Safety Monitor | Giới hạn tốc độ hành động, giãn cách giống người thật |
| `anomaly-detection.md` | human_bot Executor, Safety Monitor | Dấu hiệu tài khoản bị hạn chế, và việc phải dừng ngay, không thử lại |
| `content-context-awareness.md` | Content Strategist | Bắt buộc đọc ngữ cảnh bài viết thật trước khi soạn nội dung |
| `vision-fallback.md` | human_bot Executor | **Dự phòng, chưa nối vào luồng chính** — kế hoạch dùng AI khi selector lỗi |
| `human-like-interaction.md` | human_bot Executor | Mô phỏng tốc độ gõ phím, độ trễ ngẫu nhiên từng ký tự, gõ sai rồi sửa — **đã hoạt động**, dùng trong `post_to_own_profile` |

**Lưu ý quan trọng đã thay đổi:** ở bản thiết kế đầu (dùng browser-use),
sửa file skill sẽ tự động "dạy lại" agent ở lần chạy sau. Với Playwright
thuần, hành vi nằm trong **code** (`human_bot/actions.py`), không phải
trong prompt AI — nên "sửa" nghĩa là sửa trực tiếp hàm Python tương ứng,
rồi restart service. Các file skill giờ đóng vai trò tài liệu tham chiếu/
quy tắc thiết kế cho người phát triển (và cho AI hỗ trợ code sau này),
không phải "bộ nhớ" agent tự đọc lại nữa.

## 6. Khung code đã dựng (`human_bot/`) — trình duyệt chạy 24/24, không cần AI

`human_bot/service.py` là một **tiến trình chạy liên tục** — khi khởi
động, tự mở sẵn một trình duyệt Playwright đã đăng nhập cho mỗi tài khoản
đang active, **giữ nguyên không đóng** trong suốt vòng đời service
(`human_bot/browser_pool.py`). Mỗi khi n8n gọi `POST /tasks`, hệ thống
dùng lại đúng trình duyệt đang mở đó.

**n8n gọi vào hệ thống như thế nào:** n8n chỉ gọi HTTP vào **một endpoint
duy nhất** (`POST /tasks`). `human_bot/agent.py` nhận Task JSON, tra bảng
để biết `action` nào ứng với hàm Python nào trong `actions.py`, rồi gọi
thẳng hàm đó — không có bước "AI chọn công cụ" ở giữa.

- `human_bot/config.py` — cấu hình tài khoản, giới hạn tốc độ
- `human_bot/actions.py` — các hành động cụ thể bằng Playwright thuần, mỗi
  hành động một hàm riêng: `post_to_own_profile`, `post_to_group`,
  `comment_on_group_post` (**đã hoạt động**, ghi từ Codegen thật và xác
  nhận sống); `comment_on_friend_post`, `like_post`, `read_recent_comments`
  còn TODO
- `human_bot/safety.py` — rate limiter + phát hiện dấu hiệu bị hạn chế
- `human_bot/browser_pool.py` — quản lý trình duyệt Playwright sống 24/24
  cho từng tài khoản
- `human_bot/agent.py` — nhận Task JSON, tra bảng dispatch, gọi thẳng hàm
  trong `actions.py`
- `human_bot/service.py` — FastAPI service, tự mở trình duyệt khi khởi
  động, expose `POST /tasks`
- `human_bot/llm.py` — **dự phòng, chưa dùng trong luồng chính** — chọn
  LLM (Anthropic/OpenAI/browser-use) nếu sau này cần cho vision-fallback
- `human_bot/prompt_loader.py` — **dự phòng**, giữ lại cho phương án
  browser-use trong tương lai, không được gọi ở luồng chính hiện tại
- `human_bot/bootstrap_login.py` — đăng nhập thủ công một lần, lưu phiên
  đăng nhập (Playwright thuần)
- `human_bot/fallback_auto_login.py` — phương án dự phòng, tự động điền
  email/mật khẩu, chỉ chạy tay khi cần
- `human_bot/test_run_task.py` — chạy thử một hành động trực tiếp, không
  cần n8n/FastAPI
- `human_bot/smoke_test/open_facebook.py` — script kiểm tra môi trường ban
  đầu, đã xác nhận chạy được trên máy bạn

Xem mục 8 bên dưới để biết đầy đủ từng file `.py` dùng để làm gì.

**Giao diện quản trị `/admin` (đã viết lại 2026-09-05 → 2026-09-07):** thay
vì sửa `.env`/code + khởi động lại service, hoặc gõ nội dung bài đăng trực
tiếp trong lệnh terminal, giờ quản lý toàn bộ qua web:

1. Chạy service: `uvicorn human_bot.service:app --host 0.0.0.0 --port 8000`
2. Mở `http://<host>:8000/admin` trên trình duyệt.
3. **Tài khoản** (`/admin/accounts`): đăng ký tài khoản mới (sau khi chạy
   `bootstrap_login.py`) qua modal — không cần sửa `human_bot/config.py`.
   Mỗi tài khoản có thể **Tạm dừng/Kích hoạt lại** thủ công bất cứ lúc nào,
   hoặc **Xoá** (áp dụng cả với tài khoản khai báo sẵn trong code — xem
   tasks.md). Tài khoản cũng **tự động chuyển sang Tạm dừng** nếu hệ thống
   phát hiện dấu hiệu Facebook hạn chế khi đang đăng bài thật (xem tasks.md,
   "Safety Monitor").
4. **Cấu hình hành vi** (`/admin/config`): chỉnh tốc độ gõ, xác suất gõ
   sai, các khoảng chờ, cấu hình bộ đồng bộ bên B... ghi vào
   `runtime_config.json` (không đụng `.env`), có hiệu lực ngay.
5. **Đăng bài** (`/admin/post`) — chia 2 tab: "Tường cá nhân" (soạn 1 nội
   dung, chọn đối tượng xem — Public/Friends/Only me, xem tasks.md, đợt
   2026-09-09 — và giờ đăng bằng lịch chọn ngày giờ thật) và "Đăng vào
   nhóm" (tạo nhiều khối nội dung khác nhau, mỗi khối gán cho một tập
   nhóm riêng, có nút "Chọn tất cả"). Tab "Hàng đợi nội dung" (thả file
   `.txt`) đã **bị xoá hẳn** (2026-09-09) — xem tasks.md. **Mọi bài đều đi
   qua lịch đăng** (`/admin/schedule`) trước khi thật sự chạy — không còn
   nút "đăng ngay lập tức" nào bỏ qua bước này, kể cả muốn đăng ngay thì
   cũng để trống giờ rồi bấm "🚀 Đăng ngay" ở `/admin/schedule`.
6. **Lịch đăng** (`/admin/schedule`): lọc theo tài khoản, phân trang (20
   bài/trang), sửa nội dung/giờ, huỷ, hoặc đăng ngay — có cả bài lên lịch
   thủ công lẫn tự động từ bộ đồng bộ bên B. Giờ đăng hiển thị theo giờ
   Nhật Bản. Các bài đã đăng/thất bại/huỷ tự động dọn sau 30 ngày
   (`SCHEDULE_RETENTION_DAYS`), bài đang chờ thì không bao giờ bị đụng.
7. **Báo cáo** (`/admin/reports`): thêm khối tổng quan nhanh (tổng số/
   thành công/thất bại/tỉ lệ/số tài khoản hoạt động) và bộ lọc theo
   khoảng thời gian (7/30/90 ngày/tất cả), áp dụng cho mọi bảng.
8. Trang này có quyền đăng bài thật — nếu chạy ở đâu ngoài máy cá nhân,
   đặt `ADMIN_USERNAME`/`ADMIN_PASSWORD` trong `.env` (xem `.env.example`)
   để có xác thực HTTP Basic Auth.

Nhớ chạy lại `pip3 install -r requirements.txt` một lần (có thêm
`python-multipart` cho form tải file lên, `httpx` cho bộ đồng bộ bên B).

## 7. Quy ước ngôn ngữ trong dự án (quan trọng)

- **Tiếng Việt**: `README.md` (file này), và các file mô tả/nghiên cứu dưới
  `docs/research/`, `docs/brand-voice.md` — dành cho người đọc.
- **Tiếng Anh**: mọi file dưới `docs/agents/`, `docs/skills/`,
  `docs/architecture.md`, và toàn bộ code (kể cả comment trong code).
- Từ chuyên ngành tiếng Anh vẫn dùng bình thường trong file tiếng Việt khi
  không có từ tương đương tự nhiên.

## 8. Bản đồ file — mỗi file .py dùng để làm gì

| File | Dùng để làm gì | Nằm trong pipeline chính? |
|---|---|---|
| `human_bot/config.py` | Cấu hình tài khoản Facebook, giới hạn tốc độ hành động | Có |
| `human_bot/humanize.py` | Mô phỏng gõ phím giống người (tốc độ, độ trễ ngẫu nhiên từng ký tự, gõ sai/sửa) và khoảng nghỉ giữa các bước UI, cấu hình qua `.env` | Có |
| `human_bot/actions.py` | Hành động Playwright thuần trên Facebook, mỗi hành động một hàm riêng | Có |
| `human_bot/safety.py` | Bộ đếm giới hạn tốc độ + hàm phát hiện dấu hiệu tài khoản bị hạn chế (`AnomalyDetected`) — khi bắt được, `agent.py` tự chuyển tài khoản sang trạng thái Tạm dừng bền vững (xem tasks.md, "Safety Monitor") | Có |
| `human_bot/browser_pool.py` | Giữ trình duyệt Playwright mở 24/24 cho từng tài khoản | Có |
| `human_bot/agent.py` | Nhận Task JSON, tra bảng dispatch, gọi thẳng hàm trong actions.py | Có |
| `human_bot/service.py` | FastAPI service — cửa ngõ HTTP để n8n gọi vào | Có |
| `human_bot/runtime_config.py` | Lưu/đọc các thông số gõ phím do trang `/admin` chỉnh, ghi ra `runtime_config.json` (không phải `.env`), áp dụng ngay không cần khởi động lại | Có |
| `human_bot/data_sync_config.py` | Cấu hình bộ đồng bộ dữ liệu bên B — nhịp gọi API, khoảng cách lịch đăng ngẫu nhiên, ngưỡng lọc ứng viên | Có |
| `human_bot/logging_setup.py` | Ghi log ra file (`logs/human_bot.log`), thêm 2026-09-08 — trước đó chỉ có `print()`/log SQLite (`db.py`), không có file log riêng để tra khi cần | Có |
| `human_bot/scheduling_config.py` | Cổng an toàn `auto_fire_enabled` — tách riêng khỏi `data_sync_config.py` (2026-09-07) vì áp dụng cho MỌI bài trong lịch, kể cả bài soạn tay ở `/admin/post`, không chỉ bài từ bên B | Có |
| `human_bot/schedule_store.py` | Kho lưu lịch đăng dựa trên file (`scheduled/pending|posted|failed|cancelled/`), cùng kiểu "thư mục là trạng thái" mà `content_queue.py` từng dùng trước khi bị xoá (2026-09-09, xem tasks.md) | Có |
| `human_bot/data_sync.py` | Poller: gọi `GET /api/jobs` + `GET /api/candidates` bên B, chống trùng theo cache ngày, lên lịch đăng ngẫu nhiên nối tiếp; `fire_due_tasks()` chỉ thực sự đăng lên Facebook khi `SchedulingConfig.auto_fire_enabled=true` | Có |
| `human_bot/db.py` | Lịch sử mọi hành động (SQLite, `human_bot.db`) — ghi lại mỗi lần `run_task()` chạy (thành công lẫn thất bại), dùng cho `/admin/reports` | Có |
| `human_bot/content_strategist.py` | Soạn nội dung khác nhau cho mỗi nhóm khi một tin tuyển dụng được đăng vào nhiều nhóm cùng lúc — gọi thẳng Anthropic API nếu có `ANTHROPIC_API_KEY` trong `.env`, tự rơi về mẫu (template) cũ nếu không có key hoặc gọi lỗi. **Chỉ áp dụng cho bài đăng nhóm** — đăng tường cá nhân và tin nhắn ứng viên không qua đây (xem tasks.md) | Có |
| `human_bot/admin.py` | Giao diện web quản trị nội bộ tại `/admin`: quản lý tài khoản (`/admin/accounts` — đăng ký/tạm dừng/kích hoạt/xoá), cấu hình hành vi (`/admin/config`), soạn & lên lịch đăng (`/admin/post`), quản lý nhóm (`/admin/groups`), lịch đăng (`/admin/schedule`), báo cáo (`/admin/reports`) | Có |
| `human_bot/llm.py` | Chọn LLM theo key có trong `.env` | **Dự phòng** — chưa được gọi ở đâu trong luồng chính |
| `human_bot/prompt_loader.py` | Đọc file agent + skill, ghép thành prompt cho AI | **Dự phòng** — để dành cho phương án browser-use sau này |
| `human_bot/bootstrap_login.py` | Đăng nhập **thủ công** một lần để lưu phiên đăng nhập đầu tiên (chạy trong terminal) | **Không** — chạy tay khi thiết lập tài khoản mới |
| `human_bot/bootstrap_login_sessions.py` | Bản tương đương `bootstrap_login.py` nhưng điều khiển được qua web `/admin/accounts` (nút "🌐 Đăng nhập & lưu phiên") thay vì terminal — quản lý browser Playwright đang chờ xác nhận trong bộ nhớ tiến trình | Có (chỉ nhánh đăng ký tài khoản) |
| `human_bot/fingerprint.py` | Đa dạng hoá viewport/DPI theo từng tài khoản (băm `account_id`, ổn định qua các lần restart) — xem tasks.md, đợt 2026-09-09 | Có |
| `human_bot/fallback_auto_login.py` | Phương án dự phòng: tự động điền email/mật khẩu để đăng nhập | **Không** — chỉ chạy tay khi cần |
| `human_bot/test_run_task.py` | Chạy thử một hành động trực tiếp, không cần n8n/FastAPI | **Không** — công cụ test thủ công |
| `human_bot/test_service_api.py` | Gọi thử `GET /health` và `POST /tasks` qua HTTP thật (không đi tắt qua run_task() như file trên) — mô phỏng đúng cách n8n hoặc một service ngoài (VD: bên B) sẽ gọi vào | **Không** — công cụ test thủ công |
| `human_bot/smoke_test/open_facebook.py` | Kiểm tra môi trường: mở trình duyệt vào facebook.com | **Không** — chỉ để kiểm tra ban đầu |

## 9. Việc cần làm tiếp theo

> Toàn bộ checklist chi tiết, tiến độ theo ngày, các đợt làm việc, và danh
> sách "điểm yếu đã ghi nhận" đã chuyển sang **[`tasks.md`](tasks.md)**
> (2026-09-09) để file này gọn lại, chỉ còn kiến trúc/hướng dẫn cài đặt.
> Mở `tasks.md` để xem/điền tiến độ — đó là file dùng để theo dõi công việc
> và báo cáo, không phải file này.

## 10. Cấu trúc thư mục

```
AIAgent_w_FB/
  README.md                    # bạn đang đọc file này
  tasks.md                     # tiến độ công việc theo ngày, checklist, báo cáo
  docs/
    research/browser-use.md    # ghi chú nghiên cứu (VN)
    architecture.md            # kiến trúc hệ thống (EN)
    brand-voice.md             # giọng văn / nội dung — bạn cần điền (VN)
    agents/                    # spec từng agent (EN)
    skills/                    # tài liệu tham chiếu/quy tắc thiết kế (EN)
  human_bot/                   # code Executor Agent (EN, xem mục 8)
    config.py
    actions.py                 # Playwright thuần — luồng chính
    browser_pool.py
    agent.py
    safety.py
    service.py
    admin.py                   # giao diện web /admin (chỉnh cấu hình + đăng bài)
    runtime_config.py          # lưu/đọc cấu hình do /admin chỉnh (runtime_config.json)
    schedule_store.py           # kho lưu lịch đăng dựa trên file (scheduled/pending|posted|failed|cancelled/)
    data_sync.py                # poller đồng bộ dữ liệu bên B + fire_due_tasks()
    db.py                       # lịch sử hành động (SQLite, human_bot.db) — dùng cho /admin/reports
    logging_setup.py            # ghi log ra file logs/human_bot.log (thêm 2026-09-08)
    bootstrap_login_sessions.py # đăng nhập & lưu phiên qua web /admin/accounts (thêm 2026-09-09)
    fingerprint.py               # viewport/DPI riêng theo tài khoản (thêm 2026-09-09)
    llm.py                     # dự phòng, chưa dùng
    prompt_loader.py           # dự phòng, chưa dùng
    bootstrap_login.py         # chạy tay: đăng nhập thủ công lần đầu (trong terminal)
    fallback_auto_login.py     # chạy tay: đăng nhập tự động, phương án dự phòng
    test_run_task.py           # chạy tay: test một hành động
    smoke_test/open_facebook.py
  accounts/                    # (đã tạo, có troy) phiên đăng nhập — KHÔNG commit
  logs/human_bot.log           # (tự tạo khi chạy) — KHÔNG commit
  runtime_config.json          # (tự tạo khi lưu ở /admin) — KHÔNG commit
  requirements.txt
  .env.example
  .gitignore
```

**Lưu ý (2026-09-09):** `human_bot/content_queue.py` và thư mục
`content_queue/` từng có ở đây (hàng đợi nội dung `.txt` cho `/admin/post`)
đã **bị xoá hoàn toàn** — xem tasks.md, đợt 2026-09-09. Cây thư mục trên chỉ
liệt kê các file chính, không đầy đủ 100% — xem bảng đầy đủ ở mục 8.
