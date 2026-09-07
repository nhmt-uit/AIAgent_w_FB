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
cd ~/Documents/Company_Project/iizuki/AIAgent_w_FB
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
trên Facebook (mặc định audience "Only me" — chỉ mình bạn thấy), vậy là
mọi thứ đã chạy đúng. Chi tiết kiến trúc/lý do thiết kế nằm ở các mục
bên dưới.

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
  hành động một hàm riêng: `post_to_own_profile` (**đã hoạt động**, ghi từ
  Codegen thật), `post_to_group`, `comment_on_friend_post`,
  `comment_on_group_post`, `like_post`, `read_recent_comments` (còn TODO)
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
   mục 9). Tài khoản cũng **tự động chuyển sang Tạm dừng** nếu hệ thống
   phát hiện dấu hiệu Facebook hạn chế khi đang đăng bài thật (xem mục 9,
   "Safety Monitor").
4. **Cấu hình hành vi** (`/admin/config`): chỉnh tốc độ gõ, xác suất gõ
   sai, các khoảng chờ, cấu hình bộ đồng bộ bên B... ghi vào
   `runtime_config.json` (không đụng `.env`), có hiệu lực ngay.
5. **Đăng bài** (`/admin/post`) — chia 3 tab: "Tường cá nhân" (soạn 1 nội
   dung, chọn giờ đăng bằng lịch chọn ngày giờ thật), "Đăng vào nhóm" (tạo
   nhiều khối nội dung khác nhau, mỗi khối gán cho một tập nhóm riêng, có
   nút "Chọn tất cả"), và "Hàng đợi nội dung" (thả file `.txt` vào
   `content_queue/pending/` hoặc tải lên qua form). **Mọi bài đều đi qua
   lịch đăng** (`/admin/schedule`) trước khi thật sự chạy — không còn nút
   "đăng ngay lập tức" nào bỏ qua bước này, kể cả muốn đăng ngay thì cũng
   để trống giờ rồi bấm "🚀 Đăng ngay" ở `/admin/schedule`.
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
| `human_bot/safety.py` | Bộ đếm giới hạn tốc độ + hàm phát hiện dấu hiệu tài khoản bị hạn chế (`AnomalyDetected`) — khi bắt được, `agent.py` tự chuyển tài khoản sang trạng thái Tạm dừng bền vững (xem mục 9, "Safety Monitor") | Có |
| `human_bot/browser_pool.py` | Giữ trình duyệt Playwright mở 24/24 cho từng tài khoản | Có |
| `human_bot/agent.py` | Nhận Task JSON, tra bảng dispatch, gọi thẳng hàm trong actions.py | Có |
| `human_bot/service.py` | FastAPI service — cửa ngõ HTTP để n8n gọi vào | Có |
| `human_bot/runtime_config.py` | Lưu/đọc các thông số gõ phím do trang `/admin` chỉnh, ghi ra `runtime_config.json` (không phải `.env`), áp dụng ngay không cần khởi động lại | Có |
| `human_bot/content_queue.py` | Hàng đợi nội dung bài đăng dựa trên file `.txt` (`content_queue/pending|posted|failed/`), dùng cho trang `/admin` | Có |
| `human_bot/data_sync_config.py` | Cấu hình bộ đồng bộ dữ liệu bên B — nhịp gọi API, khoảng cách lịch đăng ngẫu nhiên, ngưỡng lọc ứng viên | Có |
| `human_bot/scheduling_config.py` | Cổng an toàn `auto_fire_enabled` — tách riêng khỏi `data_sync_config.py` (2026-09-07) vì áp dụng cho MỌI bài trong lịch, kể cả bài soạn tay ở `/admin/post`, không chỉ bài từ bên B | Có |
| `human_bot/schedule_store.py` | Kho lưu lịch đăng dựa trên file (`scheduled/pending|posted|failed|cancelled/`), tương tự `content_queue.py` | Có |
| `human_bot/data_sync.py` | Poller: gọi `GET /api/jobs` + `GET /api/candidates` bên B, chống trùng theo cache ngày, lên lịch đăng ngẫu nhiên nối tiếp; `fire_due_tasks()` chỉ thực sự đăng lên Facebook khi `SchedulingConfig.auto_fire_enabled=true` | Có |
| `human_bot/db.py` | Lịch sử mọi hành động (SQLite, `human_bot.db`) — ghi lại mỗi lần `run_task()` chạy (thành công lẫn thất bại), dùng cho `/admin/reports` | Có |
| `human_bot/content_strategist.py` | Soạn nội dung khác nhau cho mỗi nhóm khi một tin tuyển dụng được đăng vào nhiều nhóm cùng lúc — gọi thẳng Anthropic API nếu có `ANTHROPIC_API_KEY` trong `.env`, tự rơi về mẫu (template) cũ nếu không có key hoặc gọi lỗi. **Chỉ áp dụng cho bài đăng nhóm** — đăng tường cá nhân và tin nhắn ứng viên không qua đây (xem mục 9) | Có |
| `human_bot/admin.py` | Giao diện web quản trị nội bộ tại `/admin`: quản lý tài khoản (`/admin/accounts` — đăng ký/tạm dừng/kích hoạt/xoá), cấu hình hành vi (`/admin/config`), soạn & lên lịch đăng (`/admin/post`), quản lý nhóm (`/admin/groups`), lịch đăng (`/admin/schedule`), báo cáo (`/admin/reports`) | Có |
| `human_bot/llm.py` | Chọn LLM theo key có trong `.env` | **Dự phòng** — chưa được gọi ở đâu trong luồng chính |
| `human_bot/prompt_loader.py` | Đọc file agent + skill, ghép thành prompt cho AI | **Dự phòng** — để dành cho phương án browser-use sau này |
| `human_bot/bootstrap_login.py` | Đăng nhập **thủ công** một lần để lưu phiên đăng nhập đầu tiên | **Không** — chạy tay khi thiết lập tài khoản mới |
| `human_bot/fallback_auto_login.py` | Phương án dự phòng: tự động điền email/mật khẩu để đăng nhập | **Không** — chỉ chạy tay khi cần |
| `human_bot/test_run_task.py` | Chạy thử một hành động trực tiếp, không cần n8n/FastAPI | **Không** — công cụ test thủ công |
| `human_bot/test_service_api.py` | Gọi thử `GET /health` và `POST /tasks` qua HTTP thật (không đi tắt qua run_task() như file trên) — mô phỏng đúng cách n8n hoặc một service ngoài (VD: bên B) sẽ gọi vào | **Không** — công cụ test thủ công |
| `human_bot/smoke_test/open_facebook.py` | Kiểm tra môi trường: mở trình duyệt vào facebook.com | **Không** — chỉ để kiểm tra ban đầu |

## 9. Việc cần làm tiếp theo

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

### Đang tập trung tiếp theo (theo thứ tự)

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

### Đợt làm việc 2026-09-05 → 2026-09-07 — quản lý tài khoản + viết lại `/admin/post`

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
- [ ] Chưa làm (ghi nhận lại để không quên): cảnh báo/UI cho giới hạn
      đăng bài mỗi tài khoản (`RateLimits` — vẫn chỉ sửa được qua code);
      xoá/sửa nhóm ở `/admin/groups` theo vị trí (index) thay vì theo ID
      cố định (rủi ro thấp ở quy mô hiện tại nhưng dễ nhầm nếu có 2 tab
      cùng sửa); nút Tạm dừng/Kích hoạt/Xoá ở `/admin/accounts` vẫn tải
      lại cả trang thay vì cập nhật tại chỗ như `/admin/groups`.
- [ ] Chụp screenshot khi một hành động thất bại — `TaskResult.
      screenshot_path` trong `human_bot/agent.py` hiện luôn là `None`
      (TODO ngay trong code). Các file spec (`docs/agents/
      human-bot-executor.md`, `docs/agents/safety-monitor.md`) mô tả như
      thể tính năng này đã có — thực tế chưa, cần làm để khớp lại.

### Còn lại (chưa tới lượt ngay, nhưng đã ghi nhận — xem đánh giá 2026-09-03)

- [ ] Ghi Codegen cho 3 hành động còn lại: `comment_on_friend_post`,
      `comment_on_group_post`, `like_post`.
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
- [ ] Cân nhắc audience thật (không chỉ luôn "Only me") — cần thêm tham số
      `audience` và có thể thêm bước xác nhận an toàn trước khi mở rộng phạm vi
      hiển thị bài đăng, xem docstring `post_to_own_profile` trong `actions.py`.
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
- [ ] Cân nhắc chọn nhóm theo chủ đề (bài IT → nhóm IT, bài Tokutei → nhóm
      Tokutei...) thay vì luôn broadcast vào mọi nhóm đã tham gia — đang suy
      nghĩ thêm, xem `docs/architecture.md` mục 3c.
- [ ] Dựng workflow n8n gọi vào service này (nối toàn bộ các phần lại thành một
      luồng chạy tự động theo lịch hoặc theo trigger từ bên B).
- [ ] Về lâu dài — nếu định chạy nhiều tài khoản song song trên nhiều máy,
      `human_bot/browser_pool.py` hiện tự ghi rõ trong docstring là chỉ an toàn
      với đúng 1 process; cần tính lại kiến trúc (pool theo process riêng cho mỗi
      account, hoặc hàng đợi công việc) nếu muốn scale.

### Điểm yếu đã ghi nhận (2026-09-07) — cần cân nhắc, chưa xếp lịch làm

- [x] **`auto_fire_enabled` bị "giấu" trong cấu hình sai chỗ — đã sửa (2026-09-07).**
      Phát hiện qua đúng sự cố thật: một bài lên lịch thủ công ở `/admin/post`
      lúc 12:40 không tự đăng, vì cổng an toàn `auto_fire_enabled` nằm trong
      `DataSyncConfig` ("Đồng bộ dữ liệu bên B") dù nó áp dụng cho **mọi** bài
      trong lịch, kể cả bài soạn tay — người dùng tìm cấu hình "lịch đăng" sẽ
      không nghĩ tới việc lục trong mục đồng bộ bên B. Đã xử lý: (1) tách cờ
      này ra `human_bot/scheduling_config.py` riêng (`SchedulingConfig`), có
      mục `/admin/config` riêng "Lên lịch & tự động đăng"; (2) `runtime_config.py`
      tự đọc lại giá trị cũ đã lưu dưới key `data_sync` (nếu có) làm fallback
      một lần, để không vô tình reset về tắt cho ai đã từng bật; (3) `.env` đổi
      tên biến thành `SCHEDULING_AUTO_FIRE_ENABLED` (vẫn đọc được
      `DATA_SYNC_AUTO_FIRE_ENABLED` cũ nếu chưa đặt biến mới); (4) sửa luôn một
      lỗi liên quan: vòng lặp "no lịch" (`_data_sync_fire_loop` trong
      `service.py`) trước đây chỉ chạy khi `DataSyncConfig.enabled=true` — tức
      tắt hẳn "bộ đồng bộ bên B" cũng vô tình chặn luôn việc tự đăng bài lên
      lịch thủ công; giờ vòng lặp này chạy độc lập, chỉ còn phụ thuộc đúng
      `auto_fire_enabled`; (5) thêm banner **trạng thái BẬT/TẮT hiện tại** trực
      tiếp trên `/admin/post` và `/admin/schedule` (không cần vào `/admin/config`
      mới biết), qua `_auto_fire_status_html()` trong `admin.py`.
- [ ] **Không xác minh bài đăng thật sự thành công.** `post_to_own_profile` và
      `post_to_group` chỉ chờ cứng 2 giây (`page.wait_for_timeout(2000)`) rồi
      luôn trả về `success=True` — không kiểm tra bài có thật sự xuất hiện
      không. Từng có sự cố thật: báo thành công nhưng ảnh không hề được đăng
      (do chọn sai `<input type="file">`).
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
- [ ] `comment_on_friend_post`, `comment_on_group_post`, `like_post`,
      `read_recent_comments` vẫn là hàm rỗng (`# TODO`, chỉ `goto()` rồi báo
      thành công giả) — xem mục "Ghi Codegen cho 3 hành động còn lại" ở trên,
      gộp chung vào đây vì cùng nhóm "chưa làm thật".
- [ ] **Chưa có biện pháp chống fingerprint/chống phát hiện ở tầng mạng.** Mới
      chỉ có giả lập hành vi (di chuột kiểu Bézier, gõ phím có tốc độ/lỗi,
      khoảng chờ ngẫu nhiên, rate limit) trong `humanize.py`/`safety.py` —
      chưa đổi user-agent, chưa proxy rotation, chưa dùng `playwright-stealth`
      hay tương đương. Cân nhắc thêm nếu mở rộng quy mô nhiều tài khoản.

## 10. Cấu trúc thư mục

```
AIAgent_w_FB/
  README.md                    # bạn đang đọc file này
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
    content_queue.py           # hàng đợi nội dung .txt dùng cho /admin
    llm.py                     # dự phòng, chưa dùng
    prompt_loader.py           # dự phòng, chưa dùng
    bootstrap_login.py         # chạy tay: đăng nhập thủ công lần đầu
    fallback_auto_login.py     # chạy tay: đăng nhập tự động, phương án dự phòng
    test_run_task.py           # chạy tay: test một hành động
    smoke_test/open_facebook.py
  accounts/                    # (đã tạo, có troy) phiên đăng nhập — KHÔNG commit
  content_queue/                # (tự tạo khi chạy) hàng đợi nội dung .txt — KHÔNG commit
    pending/ posted/ failed/
  runtime_config.json          # (tự tạo khi lưu ở /admin) — KHÔNG commit
  requirements.txt
  .env.example
  .gitignore
```
