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

**Bước 4 — Đăng ký tài khoản Facebook trong `human_bot/config.py`:**
Mở file, thêm một dòng vào dict `ACCOUNTS`, ví dụ:
```python
ACCOUNTS: dict[str, AccountConfig] = {
    "troy": AccountConfig(account_id="troy", display_name="Troy"),
    "my_page": AccountConfig(account_id="my_page", display_name="Trang của tôi"),  # dòng mới
}
```
`account_id` là tên bạn tự đặt (chữ thường, không dấu cách) — dùng lại
đúng tên này ở bước 5 và mọi lệnh sau này.

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

**Bước 6 — Chạy thử một hành động thật:** chọn một trong hai cách:

- Qua giao diện web `/admin` (khuyên dùng, đỡ lỗi gõ dấu ngoặc trong
  terminal):
  ```
  uvicorn human_bot.service:app --host 0.0.0.0 --port 8000
  ```
  rồi mở `http://localhost:8000/admin` trên trình duyệt, vào mục "Đăng
  bài", chọn tài khoản `my_page`, gõ nội dung, bấm Đăng.

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

**Giao diện quản trị `/admin` (mới):** thay vì sửa `.env` + khởi động lại
service để đổi thông số gõ phím, hoặc gõ nội dung bài đăng trực tiếp trong
lệnh terminal (dễ lỗi dấu ngoặc kép như từng gặp), giờ có thể:

1. Chạy service: `uvicorn human_bot.service:app --host 0.0.0.0 --port 8000`
2. Mở `http://<host>:8000/admin` trên trình duyệt.
3. **Cấu hình gõ phím** (`/admin/config`): chỉnh tốc độ gõ, xác suất gõ
   sai, các khoảng chờ... form này ghi vào `runtime_config.json` (không
   đụng `.env`), có hiệu lực ngay từ bài đăng tiếp theo.
4. **Đăng bài** (`/admin/post`): dán nội dung vào ô textarea rồi bấm Đăng,
   hoặc thả file `.txt` vào `content_queue/pending/` (hoặc tải lên qua
   form) rồi bấm "Đăng mục này" trong danh sách hàng đợi.
5. Trang này có quyền đăng bài thật — nếu chạy ở đâu ngoài máy cá nhân,
   đặt `ADMIN_USERNAME`/`ADMIN_PASSWORD` trong `.env` (xem `.env.example`)
   để có xác thực HTTP Basic Auth.

Nhớ chạy lại `pip3 install -r requirements.txt` một lần (có thêm
`python-multipart` cho form tải file lên).

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
| `human_bot/safety.py` | Bộ đếm giới hạn tốc độ + hàm phát hiện dấu hiệu tài khoản bị hạn chế | Có |
| `human_bot/browser_pool.py` | Giữ trình duyệt Playwright mở 24/24 cho từng tài khoản | Có |
| `human_bot/agent.py` | Nhận Task JSON, tra bảng dispatch, gọi thẳng hàm trong actions.py | Có |
| `human_bot/service.py` | FastAPI service — cửa ngõ HTTP để n8n gọi vào | Có |
| `human_bot/runtime_config.py` | Lưu/đọc các thông số gõ phím do trang `/admin` chỉnh, ghi ra `runtime_config.json` (không phải `.env`), áp dụng ngay không cần khởi động lại | Có |
| `human_bot/content_queue.py` | Hàng đợi nội dung bài đăng dựa trên file `.txt` (`content_queue/pending|posted|failed/`), dùng cho trang `/admin` | Có |
| `human_bot/admin.py` | Giao diện web quản trị nội bộ tại `/admin`: chỉnh cấu hình gõ phím, đăng bài trực tiếp hoặc từ hàng đợi — thay cho việc gõ nội dung trong lệnh terminal | Có |
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
- [ ] `post_to_group` — ghi tiếp 3 lớp điều hướng còn lại (lối tắt đã ghim → danh
      sách "Groups you've joined" → search), theo đúng thứ tự ưu tiên trong
      `docs/skills/group-targeting.md`.
- [ ] Viết Content Strategist Agent — bản tối thiểu trước, không chờ bên B chốt
      xong định dạng dữ liệu. Xem kế hoạch chi tiết trong
      `docs/agents/content-strategist.md`, mục "Implementation plan (đợt 1)".
- [ ] Thêm xác thực (auth) cho endpoint `POST /tasks` trong `human_bot/service.py`
      — hiện đang mở, ai gọi tới cổng cũng đăng bài thật được, không cần token/API
      key gì cả. Cần làm trước khi một hệ thống khác (VD: bên B lấy dữ liệu, gửi
      JSON content sang để đăng) gọi vào từ ngoài máy/mạng nội bộ. `/admin` đã có
      Basic Auth tùy chọn (`ADMIN_USERNAME`/`ADMIN_PASSWORD`) — `/tasks` thì chưa,
      nên làm tương tự (API key header là đủ, không cần phức tạp).

### Còn lại (chưa tới lượt ngay, nhưng đã ghi nhận — xem đánh giá 2026-09-03)

- [ ] Ghi Codegen cho 3 hành động còn lại: `comment_on_friend_post`,
      `comment_on_group_post`, `like_post`.
- [ ] Làm Safety Monitor thật (hiện mới có spec trong
      `docs/agents/safety-monitor.md`) — đếm số lần `detect_anomaly()` bắt được
      trong một khoảng thời gian cho từng tài khoản, tự động chuyển
      `account.status` sang tạm dừng (không chỉ raise lỗi tại chỗ như hiện tại),
      và báo cho người vận hành (email/Telegram/Slack, tuỳ chọn sau) khi có dấu
      hiệu bất thường — quan trọng vì đây là lớp bảo vệ tài khoản duy nhất khi hệ
      thống chạy không có người theo dõi sát.
- [ ] Thêm hỗ trợ đăng kèm ảnh/video (`media_path`) — hiện `post_to_own_profile`
      (và các hành động post khác khi ghi Codegen) mới đăng được text thuần.
- [ ] Cân nhắc audience thật (không chỉ luôn "Only me") — cần thêm tham số
      `audience` và có thể thêm bước xác nhận an toàn trước khi mở rộng phạm vi
      hiển thị bài đăng, xem docstring `post_to_own_profile` trong `actions.py`.
- [ ] Dựng workflow n8n gọi vào service này (nối toàn bộ các phần lại thành một
      luồng chạy tự động theo lịch hoặc theo trigger từ bên B).
- [ ] Về lâu dài — nếu định chạy nhiều tài khoản song song trên nhiều máy,
      `human_bot/browser_pool.py` hiện tự ghi rõ trong docstring là chỉ an toàn
      với đúng 1 process; cần tính lại kiến trúc (pool theo process riêng cho mỗi
      account, hoặc hàng đợi công việc) nếu muốn scale.

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
