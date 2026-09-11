**BÁO CÁO TIẾN ĐỘ DỰ ÁN**

Hệ thống tự động hoá Facebook cho tuyển dụng lao động Việt Nam tại Nhật Bản (AIAgent\_w\_FB)

*(Cập nhật lần này: 2026-09-10. Bản trước mô tả trạng thái ngày 2026-09-04 —
từ đó tới nay dự án đã đi thêm một quãng đáng kể: đăng nhóm, comment nhóm,
quản lý tài khoản/nhóm/lịch đăng qua web, đồng bộ dữ liệu tự động từ hệ
thống tuyển dụng, một tầng "phòng vệ" nhiều lớp chống bị Facebook phát
hiện là bot, và — mới nhất, 2026-09-10 — AI viết/viết lại nội dung được
dời sang đúng lúc bài sắp đăng thật (thay vì lúc vừa nhận dữ liệu), áp
dụng thêm cho cả tin nhắn ứng viên, có công tắc bật/tắt riêng, cùng một
cách đăng nhập tài khoản mới qua web thay cho chạy lệnh tay trong
terminal.)*

# 1\. Tổng quan

Dự án xây dựng một hệ thống tự động thực hiện các hành động trên Facebook (đăng bài lên tường cá nhân, đăng bài vào nhóm, bình luận vào bài nhóm) nhằm phục vụ mục tiêu tuyển dụng lao động Việt Nam tại Nhật Bản, đồng thời tự lấy dữ liệu tin tuyển dụng/ứng viên từ một hệ thống tuyển dụng khác (gọi tắt "bên B") để tự lên lịch đăng/trả lời mà không cần nhập tay từng bài. Hệ thống gồm bốn phần:

* **human\_bot** — bộ thực thi dựa trên Playwright, mô phỏng hành vi người dùng thật (di chuột theo đường cong, gõ chữ có tốc độ và lỗi gõ tự nhiên, dừng đọc lại, cuộn trang, mỗi tài khoản một "dấu vân tay" trình duyệt hơi khác nhau...) để thao tác trên Facebook một cách an toàn nhất có thể trong phạm vi công cụ đang có, hạn chế bị hệ thống chống spam của Facebook phát hiện và hạn chế tài khoản.

* **Bộ tự bảo vệ tài khoản** — tách riêng khỏi phần "thao tác": tự phát hiện khi Facebook cảnh báo/hạn chế một tài khoản và tự tạm dừng tài khoản đó ngay lập tức (không đợi con người nhận ra), cộng với giới hạn tốc độ hành động được phân theo "độ tuổi" tài khoản và một giai đoạn "hạ nhiệt" tự động mỗi khi một tài khoản vừa được kích hoạt lại.

* **Cơ sở dữ liệu SQLite \+ hệ thống lịch đăng dựa trên file** — lưu lịch sử mọi hành động (kể cả thất bại), ảnh chụp màn hình bằng chứng, và toàn bộ bài đang chờ/đã đăng/thất bại/đã huỷ để phục vụ báo cáo, giám sát, và cho phép con người xem lại/sửa/huỷ trước khi bài thật sự lên Facebook.

* **Trang quản trị (Admin UI) & API** — giao diện web đầy đủ để đăng ký/quản lý tài khoản, quản lý danh sách nhóm đã tham gia, soạn và lên lịch bài đăng, xem báo cáo; cùng REST API (`POST /tasks`, có xác thực bằng API key) để n8n hoặc hệ thống bên ngoài gửi yêu cầu, và một bộ đồng bộ nền tự động lấy tin tuyển dụng/ứng viên mới từ bên B để lên lịch đăng mà không cần thao tác tay.

**Quyết định kiến trúc quan trọng nhất — không dùng AI để "lái" trình duyệt.** Ban đầu dự án cân nhắc dùng một AI agent kiểu "browser-use" (agent tự nhìn màn hình, tự suy luận, tự quyết định bước bấm tiếp theo mỗi lần chạy). Sau khi thử nghiệm thực tế, phát hiện `browser-use` dùng API nội bộ riêng (không phải Playwright chuẩn) và gói LLM Gateway miễn phí của họ không dùng được — hai lý do trực tiếp dẫn tới quyết định chuyển hẳn sang Playwright thuần: mỗi hành động (đăng bài, comment...) được ghi lại một lần bằng Playwright Codegen (tự tay làm thao tác thật, công cụ tự ghi lại thành code), sau đó chạy lại y hệt mỗi lần cần, không cần LLM và không tốn phí AI cho việc đăng bài/comment thật. Lý do sâu hơn: khi đã biết chính xác từng bước phải làm, để một AI "suy nghĩ lại" mỗi lần chỉ tốn thêm tiền, chậm hơn, và có rủi ro AI hiểu nhầm rồi bấm sai — AI chỉ thật sự cần thiết ở chỗ *không biết trước* phải làm gì (ví dụ: viết nội dung bài đăng), không phải ở việc bấm nút. `browser-use` được giữ lại làm phương án dự phòng cho tương lai (đã thiết kế, **chưa nối vào luồng chạy**) cho đúng một tình huống: khi Facebook đổi giao diện làm một selector đã ghi bị gãy và chưa kịp ghi lại — xem mục 6.

# 2\. Bảng tổng hợp trạng thái

| Hạng mục | Trạng thái |
| :---- | :---- |
| Điều hướng Facebook chuẩn (goto → click icon Home → từng bước, có lý do kỹ thuật cụ thể — mục 4.1) | Hoàn thành |
| Đăng bài lên tường cá nhân (`post_to_own_profile`), chọn được đối tượng xem (Public/Friends/Only me) | Hoàn thành |
| Đăng bài vào nhóm — đủ 4 lớp dự phòng, khớp theo ID/slug (`post_to_group`) | Hoàn thành |
| Bình luận vào bài trong nhóm (`comment_on_group_post`) | Hoàn thành, xác nhận sống |
| Bình luận bài bạn bè / thả cảm xúc / đọc comment gần đây | **Tạm ngưng theo quyết định chủ dự án** — không cần cho nhu cầu hiện tại |
| Đính kèm ảnh/video khi đăng (ảnh riêng ưu tiên, ngẫu nhiên nếu không có) | Hoàn thành |
| Mô phỏng hành vi người dùng (gõ phím, di chuột, cuộn trang, khoảng nghỉ theo ngữ cảnh) | Hoàn thành, có nghiên cứu nguồn ngoài — mục 4.4 |
| Đa dạng hoá "dấu vân tay" trình duyệt theo từng tài khoản | Một phần đã làm, phần lớn cố tình chưa làm (có lý do kỹ thuật) — mục 4.5 |
| Giới hạn tần suất hành động (rate limiting) — thật sự có hiệu lực, chia theo loại hành động, theo "tuổi" tài khoản | Hoàn thành |
| "Hạ nhiệt" tự động sau khi kích hoạt lại một tài khoản bị tạm dừng | Hoàn thành |
| Tự phát hiện tài khoản bị Facebook hạn chế và tự tạm dừng (persist qua cả restart) | Hoàn thành (hành vi #1); throttle sớm + báo động qua Slack/email — **chưa làm** |
| Xác minh bài đăng thật sự thành công (không chỉ đoán) \+ chụp ảnh bằng chứng mọi lần chạy | Hoàn thành, đang chờ xác nhận sống thêm 1 lần |
| Trang quản trị (Admin UI) — tài khoản, nhóm, cấu hình, đăng bài, lịch đăng, báo cáo | Hoàn thành |
| Lên lịch đăng bài (không đăng "ngay lập tức" nữa, mọi bài đều qua bước duyệt lịch) | Hoàn thành |
| Đồng bộ dữ liệu tự động từ bên B (tin tuyển dụng → đăng nhóm, ứng viên → comment) | Hoàn thành, cổng an toàn tắt mặc định |
| Xác thực API cho `POST /tasks` (X-API-Key) và Admin UI (HTTP Basic Auth) | Hoàn thành |
| Ghi log & báo cáo lịch sử hành động (SQLite) | Hoàn thành |
| Content Strategist Agent (AI soạn/viết lại nội dung job đăng nhóm + reply ứng viên, gọi đúng lúc đến giờ đăng, có bật/tắt riêng, đa nhà cung cấp) | Hoàn thành, **đã xác nhận sống với Anthropic**; OpenAI/Gemini/custom chưa test end-to-end — xem mục 4.10 |
| Đăng nhập tài khoản mới qua web `/admin/accounts` (thay cho chạy lệnh tay) | Hoàn thành — xem mục 4.11 |
| Cơ chế dự phòng khi 1 selector bị Facebook đổi giao diện làm gãy | Đã thiết kế (dùng AI/LLM "nhìn" trang), **chưa nối vào luồng chạy thật** |
| Thiết lập môi trường vận hành thật (proxy/IP riêng theo tài khoản, khoá API bên B thật) | Chưa làm — cần trước khi chạy ngoài phạm vi máy cá nhân |
| Bộ test tự động (`pytest`) cho phần logic thuần (rate-limit, template AI, cấu hình admin, đa nhà cung cấp AI, cảnh báo thiếu xác thực) | Hoàn thành, 79 test — xem mục 4.16. Phần đụng Playwright/trình duyệt thật vẫn chưa có test tự động |

# 3\. Nguyên tắc thiết kế cốt lõi — vì sao mọi hành động đều đi theo cùng một "kịch bản điều hướng"

Đây là quy tắc nền cho toàn bộ hệ thống, áp dụng cho *mọi* hành động, không riêng gì đăng nhóm — nên tách thành mục riêng trước khi đi vào chi tiết từng hành động.

Mọi tác vụ (trừ 2 ngoại lệ nêu dưới) đều bắt đầu đúng theo trình tự:

1. `page.goto("https://www.facebook.com/")` — vào thẳng trang chủ Facebook. Đây là hành vi hoàn toàn bình thường của người dùng thật (gõ địa chỉ, mở bookmark), **không phải** điểm khiến hệ thống chống bot nghi ngờ.
2. Ngay sau đó, dù trình duyệt trước đó đang đứng ở trang nào, hệ thống **luôn bấm vào icon Facebook (logo)** để quay về đúng home feed bằng một cú click UI thật — bước này mới là bước thật sự quan trọng về mặt kỹ thuật.
3. Từ home feed, mới lần lượt bấm từng bước thật để đến đích (vào nhóm, mở khung đăng bài...).

**Vì sao bước 2 (click icon Home) lại quan trọng, không chỉ là hình thức:** `page.goto(url)` gửi request **không kèm header `Referer`** — giống hệt việc gõ địa chỉ hoặc mở bookmark. Một người dùng thật bấm xuyên suốt giao diện Facebook thì mọi request đều mang `Referer` trỏ về trang trước đó. Nếu hệ thống *luôn luôn* đi thẳng bằng URL để tới mọi nơi cần đến, việc thiếu `Referer` một cách nhất quán tự nó là một tín hiệu rõ ràng hơn nhiều so với việc thỉnh thoảng thiếu ở một request đơn lẻ. Buộc mọi hành động phải "ghé qua" một cú click Home thật trước khi đi tiếp giúp các bước điều hướng sau đó luôn mang đúng `Referer` như người dùng thật.

**Hai ngoại lệ được phép đi thẳng bằng URL (đều có lý do, không phải tuỳ tiện):**

* Lớp 4 (phương án dự phòng cuối cùng) khi vào nhóm — chỉ dùng sau khi 3 lớp điều hướng thật đã thử và không xác nhận được đúng nhóm.
* Bình luận/trả lời trực tiếp vào một bài viết cụ thể — người dùng thật cũng thường đến thẳng một bài cụ thể từ thông báo, link được chia sẻ, hoặc kết quả tìm kiếm, nên `goto` thẳng vào đây mới chính là hành vi bình thường, không phải đường tắt.

Quy tắc này ban đầu từng bị hiểu quá đà (một bản nháp sớm hơn đề xuất luôn đi thẳng bằng URL cho mọi trường hợp để giảm rủi ro selector gãy) — chủ dự án đã trực tiếp yêu cầu chỉnh lại đúng như trên sau khi trao đổi, và tài liệu kỹ thuật đã được sửa lại cho khớp.

# 4\. Chi tiết các hạng mục đã hoàn thành

## 4.1. Đăng bài lên tường cá nhân (2026-09-02, thêm đối tượng xem 2026-09-10)

Luồng đầy đủ: mở khung đăng bài, gõ nội dung theo tốc độ/nhịp gõ tự nhiên (mục 4.4), chọn đối tượng xem (Public/Friends/Only me — trước đây bị ép cứng "Only me" cho mọi bài, đã sửa để nhận tham số `audience` xuyên suốt từ API tới giao diện đăng bài), và **xác minh thật** bài đã đăng thành công thay vì đoán (mục 4.8).

## 4.2. Đăng bài vào nhóm — 4 lớp dự phòng (2026-09-03 – 2026-09-04)

Hạng mục phức tạp nhất của dự án. Một người dùng thật không phải lúc nào cũng vào một nhóm theo đúng một cách — hệ thống mô phỏng đúng điều đó bằng một **chuỗi 4 phương án**, thử lần lượt, dừng ngay khi một phương án xác nhận đúng nhóm:

1. **Lối tắt đã ghim** (Shortcuts ở trang chủ) — nhanh và giống người nhất, nhưng chỉ có nếu tài khoản đó đã ghim sẵn nhóm.
2. **Danh sách "Your groups"** — vào tab Groups → "Your groups" (nhãn thật của giao diện tiếng Anh — bản nháp đầu tiên đoán nhầm là "Groups you've joined", đã sửa lại sau khi đối chiếu giao diện thật), dò tìm đúng nhóm trong danh sách đã tham gia.
3. **Tìm kiếm Facebook** — gõ tên nhóm vào ô tìm kiếm, lọc theo "My groups", chọn đúng kết quả. Đây là lớp dễ vỡ nhất (thứ hạng kết quả có thể đổi, nhiều nhóm trùng tên).
4. **Vào thẳng bằng URL nhóm** — phương án bảo đảm luôn vào được, luôn kèm `referer` tường minh thay vì để trống.

**Vì sao phải làm cả 4 lớp thay vì chỉ dùng URL trực tiếp (đơn giản hơn nhiều):** phiên bản thiết kế đầu tiên từng đề xuất chỉ dùng lớp 4 cho gọn. Chủ dự án đã chỉ ra một điểm quan trọng: làm *đúng một cách*, *y hệt nhau*, ở *mọi lần* đăng nhóm — chính bản thân sự lặp lại đó là một dấu hiệu bất thường, vì người dùng thật không bao giờ vào nhóm theo đúng một kiểu mỗi lần.

**Cách chọn đúng nhóm không dựa vào tên hiển thị.** Tên nhóm hiển thị trên giao diện Facebook có thể bị cắt ngắn ("CHUYỂN VIỆC KỸ SƯ TẠI NH…") hoặc trùng giữa nhiều nhóm — nên việc khớp nhóm dựa vào **ID/slug** lấy thẳng từ đường dẫn (`href`) của link, theo đúng yêu cầu cụ thể của chủ dự án ("dò ID nhóm trùng với ID nhóm được yêu cầu đăng"). Sau mỗi lần bấm vào một nhóm ở lớp 1-3, hệ thống còn kiểm tra lại URL trang vừa vào để xác nhận lần nữa — nếu sai, tự động rơi xuống lớp kế tiếp thay vì lỡ đăng nhầm nhóm.

**Hai lỗi thật phát hiện trong lúc test lớp 1 (Lối tắt):** có lúc bấm vào đúng nhóm rồi lại tự thoát ra ngoài, và có lúc thấy nhóm hiện ở lối tắt nhưng không bấm được. Cả hai đã được xác định nguyên nhân và khắc phục trong lúc ghi lại Codegen.

**Bug xác nhận bằng bằng chứng thật (2026-09-10), fix xác nhận qua Codegen (chưa qua bot thật):** task `20260910T150503Z_80e521d1` (post_to_group, group "Việc làm Kỹ Sư Nhật Bản (Uy tín hàng đầu)", nhóm bật duyệt bài) chạy thật lúc 19:48 — owner chụp ảnh Facebook hiện toast "Thanks for your post! It's been submitted to group admins for approval.", nhưng `scheduled/posted/20260910T150503Z_80e521d1.result.txt` lúc đó ghi `posted_to_group` (không phải `posted_to_group_pending_approval`). Xác nhận danh sách `_PENDING_APPROVAL_TEXT_SIGNALS` cũ (`pending approval`, `awaiting approval`, `post is being reviewed`, `will be visible once`) chưa từng bắt được ca chờ duyệt thật nào — `success=True` vẫn đúng, chỉ sai message. Đã thêm `"submitted to group admins for approval"` làm signal đầu tiên.

Sau đó ghi lại **Codegen thật** (`codegen_verify_pending_approval.py`, account `tu_iizuki`, cùng group) để kiểm chứng cả text lẫn timing: dòng
`page.get_by_text("Thanks for your post! It's").click()` — Codegen tự ghi lại thao tác này vì owner bấm được ngay vào dòng toast, xác nhận text nằm trong DOM dưới dạng text thường (không phải canvas/ảnh), Playwright định vị được bằng `get_by_text`/`inner_text`. Owner quan sát toast tồn tại khoảng **3-5 giây** trước khi tự ẩn. Code hiện gọi `_looks_like_pending_approval()` (đọc `page.inner_text("body")`) ngay sau khi `post_button.wait_for(state="hidden")` hoàn tất — gần như tức thời sau submit, còn dư nhiều thời gian trong khung 3-5s. Kết luận: cả text lẫn timing của fix đều hợp lý.

**Vẫn còn một bước cuối chưa làm:** chưa chạy lại một task `post_to_group` thật qua chính bot (không phải Codegen tay) vào nhóm chờ duyệt để xác nhận `result.txt` ra đúng `posted_to_group_pending_approval` — Codegen xác nhận text/timing đúng về nguyên lý, nhưng chưa chứng minh `_looks_like_pending_approval()` chạy đúng trong luồng thật end-to-end.

## 4.3. Bình luận vào bài trong nhóm (`comment_on_group_post`) (2026-09-08)

Ghi Codegen và xác nhận sống trên đúng nhóm tài khoản đã tham gia thật, comment hiện lên sau khi tải lại trang để xác nhận. Có thêm bước kiểm tra lại dấu hiệu bất thường khi bước xác minh gửi comment bị timeout — cùng nguyên tắc với đăng bài (mục 4.8). Selector khung nhập cũng đã mở rộng để khớp cả bài dạng Hỏi-Đáp (Q&A) của Facebook, hiển thị "Write an answer…" thay vì "Write a comment…" như bài thường — phát hiện qua một lần chạy thật bị timeout 30 giây trước khi sửa.

**Phát hiện link chết (bài/nhóm không còn khả dụng) TRƯỚC KHI thử comment, không phải sau khi timeout (2026-09-08).** Trước đó, comment vào một bài đã bị xoá/ẩn/nhóm không còn xem được sẽ khiến hệ thống tìm mãi khung nhập comment không bao giờ xuất hiện, timeout ~30 giây rồi mới báo lỗi. Giờ nhận diện ngay trang "nội dung này không khả dụng" của Facebook trước khi cố thao tác, báo lỗi rõ ràng ngay lập tức — khác hẳn với việc phát hiện tài khoản bị Facebook hạn chế (mục 4.7): đây là nội dung mục tiêu biến mất, không phải dấu hiệu tài khoản mình có vấn đề, nên không kích hoạt tạm dừng tài khoản.

**3 hành động còn lại** (`comment_on_friend_post`, `like_post`, `read_recent_comments`) **được chủ dự án chủ động yêu cầu tạm ngưng** — không phải vì vướng lỗi kỹ thuật, mà vì chưa cần cho nhu cầu hiện tại. Sẽ làm lại nếu sau này thật sự cần.

## 4.4. Mô phỏng hành vi con người — vì sao phải làm kỹ đến vậy (2026-09-03)

Đây là phần được đầu tư nghiên cứu nhiều nhất của dự án, dựa trên đọc các nguồn nghiên cứu/tài liệu thật về cách các hệ thống chống bot hiện đại phát hiện tự động hoá (cside.com — bài về phát hiện AI agent và phát hiện Playwright/browserless qua con trỏ chuột; browser-use.com — bài về bot detection; thư viện `ghost-cursor` cho Puppeteer/Playwright; một bài nghiên cứu học thuật về phát hiện bot qua nhịp gõ phím — xem đầy đủ nguồn ở mục 8), thay vì chỉ đoán mò.

**Phát hiện cốt lõi từ nghiên cứu:** các hệ chống bot hiện đại không chỉ nhìn *một* tín hiệu — họ kết hợp nhiều tín hiệu hành vi cùng lúc: độ cong đường di chuột + các lần "sửa hướng" nhỏ gần đích, tốc độ cuộn trang (tăng-giữ-giảm tốc so với cuộn đều/nhảy cóc), độ dao động khoảng cách giữa các lần gõ phím + có/không có phím Backspace, và (riêng cho agent chạy bằng LLM) một kiểu "khoảng dừng vì đang suy luận AI" đặc trưng, khác hẳn khoảng dừng "đọc/nghĩ" của người thật. Vì pipeline của dự án không dùng LLM trong luồng chạy chính (mục 1), tín hiệu cuối này không áp dụng trực tiếp — nhưng kết luận rút ra vẫn quan trọng: **mọi khoảng nghỉ của hệ thống phải dao động ngẫu nhiên, không được cố định**.

Cụ thể đã triển khai:

* **Di chuột:** không nhảy thẳng tới điểm cần bấm, mà di chuyển theo đường cong Bézier (mô phỏng theo thư viện `ghost-cursor`) với 1 điểm điều khiển lệch về một phía (tránh đường zig-zag phi tự nhiên nếu lệch cả hai phía), tốc độ di chuyển theo định luật Fitts (khoảng cách xa/đích nhỏ → di chuyển chậm và cẩn thận hơn), có "rung tay" ngẫu nhiên ±1.5px ở các điểm giữa, và điểm bấm cuối cùng là một toạ độ **ngẫu nhiên bên trong** vùng phần tử, không phải luôn chính giữa.
* **Thời gian giữ chuột khi click (dwell time):** thêm độ trễ 40-120ms giữa lúc nhấn và nhả chuột, thay vì gần như 0ms như một cú click do script tạo ra — nghiên cứu chỉ ra đây là một tín hiệu phân biệt người/bot khá rõ.
* **Cuộn trang có giảm tốc:** dùng sự kiện wheel thật của Playwright (`page.mouse.wheel()`), chia nhiều bước co dần theo khoảng cách còn lại, thay vì nhảy thẳng tức thời tới vị trí cần cuộn.
* **Gõ chữ:** tốc độ theo WPM có dao động ngẫu nhiên, thêm khoảng nghỉ sau mỗi từ/dấu câu, và hiệu ứng "mỏi tay" khiến tốc độ chậm dần theo độ dài nội dung.
* **Gõ sai rồi tự sửa (ký tự ASCII):** thỉnh thoảng gõ nhầm phím kế bên trên bàn phím QWERTY rồi một lúc sau mới xoá sửa lại.
* **Gõ sai rồi tự sửa (từ có dấu tiếng Việt) — xử lý khác hẳn, có lý do kỹ thuật cụ thể:** dấu tiếng Việt không phải một phím vật lý đơn — chúng được bộ gõ (Unikey, VNI...) ghép từ nhiều phím theo kiểu Telex/VNI. Playwright gửi thẳng ký tự Unicode đã ghép sẵn qua giao thức CDP, **không đi qua bộ gõ IME thật của hệ điều hành** — nên không thể mô phỏng "gõ sai kiểu Telex" ở tầng bàn phím. Giải pháp: mô phỏng đúng *hành vi* quan sát được ở người thật — thỉnh thoảng gõ đúng cả một từ, "nhận ra sai", xoá nguyên từ, gõ lại — luôn đảm bảo văn bản cuối cùng đúng tuyệt đối, không tạo ra chữ tiếng Việt lỗi vô nghĩa.
* **Các khoảng đợi có ngữ cảnh, không phải một con số cố định:** đợi sau khi trang vừa tải xong, đợi sau khi mở khung soạn bài, đợi giữa các bước chọn (VD: chọn quyền riêng tư), và đặc biệt là khoảng "đọc lại trước khi đăng" — thời gian đợi trước khi bấm Post **tỉ lệ theo độ dài nội dung vừa gõ** (bài dài đợi lâu hơn), mô phỏng đúng việc một người thật đọc lại bài trước khi đăng.

**Đã cân nhắc và CHỦ ĐỘNG QUYẾT ĐỊNH CHƯA LÀM: điều khiển chuột thật ở tầng hệ điều hành (2026-09-08).** Có tính tới phương án dùng `pyautogui`/`pynput` để điều khiển con trỏ chuột vật lý thật của máy, thay vì `page.mouse.*` của Playwright — về lý thuyết loại bỏ hẳn giới hạn "movementX/Y luôn bằng 0" và "không có mẫu toạ độ tần số cao" vốn có của CDP (giao thức Playwright dùng để điều khiển Chrome). Quyết định KHÔNG làm, vì 5 lý do vận hành cụ thể: (1) bắt buộc máy phải luôn có phiên desktop thật, mở khoá, còn màn hình — mất khả năng chạy nền 24/7 không người trông; (2) không dùng máy song song được vì chuột OS là tài nguyên vật lý dùng chung; (3) mất khả năng chạy nhiều tài khoản cùng lúc (mỗi tài khoản hiện có "chuột ảo" riêng qua CDP, chuột OS thì chỉ có đúng 1 con trỏ); (4) dễ vỡ nếu có cửa sổ/thông báo nào che khuất Chrome đúng lúc click; (5) khoá cứng vĩnh viễn vào "phải có màn hình thật", không bao giờ chuyển sang chạy headless được nữa. Sau khi nghiên cứu thêm, các hệ chống bot tinh vi ngoài đời thực tế vẫn xem cách làm hiện tại (CDP + làm mượt hành vi như 4 điểm trên) là đủ tốt cho production — lợi ích thêm từ chuột OS thật là biên rất nhỏ so với chi phí vận hành phải đánh đổi. Chủ dự án đồng ý ghi lại quyết định này, chưa triển khai.

## 4.5. Đa dạng hoá "dấu vân tay" trình duyệt (fingerprint) theo từng tài khoản — đã làm gì, và cố tình CHƯA làm gì (2026-09-10)

Mỗi tài khoản Facebook đã chạy trên một tiến trình Chromium riêng (không share trình duyệt giữa các tài khoản), nhưng ban đầu mọi tiến trình đều dùng chung **y hệt** một cấu hình màn hình mặc định — nghĩa là dưới góc nhìn của Facebook, mọi tài khoản vẫn "trông giống" cùng một loại thiết bị. Đã khắc phục bằng cách băm `account_id` (SHA256) để chọn ra một cấu hình cố định trong số 5 cấu hình màn hình phổ biến ngoài đời thật (kết hợp độ phân giải + tỉ lệ scale phù hợp thực tế, VD: MacBook 1440x900 thường đi kèm @2x, màn ngoài 1920x1080 thường @1x) — **ổn định qua mọi lần restart**, không đổi ngẫu nhiên mỗi lần mở, vì đổi liên tục còn là tín hiệu bot rõ ràng hơn cả việc dùng chung một cấu hình.

**Ba việc liên quan cố tình CHƯA làm, mỗi việc đều có lý do kỹ thuật cụ thể, không phải bỏ sót:**

1. **User-agent:** đổi riêng `navigator.userAgent` mà không đổi luôn "Client Hints" thật của Chromium (`Sec-CH-UA-*`, `navigator.userAgentData`) sẽ tạo ra sự sai lệch giữa 2 nguồn — bản thân sự sai lệch đó là tín hiệu bot còn rõ hơn cả dùng UA mặc định giống nhau ở mọi tài khoản. Muốn làm đúng cần tắt hẳn Client Hints hoặc có một lớp "stealth-patch" mà dự án hiện chưa có.
2. **Múi giờ/vị trí địa lý:** cần khớp với địa chỉ IP thật (qua proxy) của từng tài khoản — nếu chưa có proxy riêng theo tài khoản mà đổi múi giờ thì múi giờ lệch với IP còn là tín hiệu tệ hơn dùng chung múi giờ.
3. **Proxy/IP riêng theo tài khoản — chưa làm, và đây mới là hướng cải thiện có tác động thực tế lớn nhất nếu mở rộng quy mô nhiều tài khoản** (nhiều tài khoản cùng chạy chung 1 IP nhà/VPS là tín hiệu liên kết mạnh hơn nhiều so với sự khác biệt về trình duyệt) — nhưng tốn phí mua proxy nên chưa triển khai, chờ quyết định khi cần scale.

Cũng chưa dùng thư viện `playwright-stealth` hay tương đương.

## 4.6. Giới hạn tần suất hành động (rate limiting), phân theo "tuổi" tài khoản, và "hạ nhiệt" sau khi kích hoạt lại (2026-09-08, retune 2026-09-10)

**Vì sao cần:** Điều khoản sử dụng của Facebook cấm hành vi tự động thay thế người dùng thật, và hệ thống chống lạm dụng của họ đặc biệt chú ý tới *khuôn mẫu lặp lại*: tốc độ đều đặn, hoạt động 24/24, khoảng cách giữa các lần thao tác đều tăm tắp — đây là tín hiệu bot rõ hơn bất kỳ một hành động đơn lẻ nào.

**Sự cố thật đã xảy ra khiến việc này được siết lại:** khoảng nghỉ tối thiểu giữa 2 hành động (`min_delay_seconds`/`max_delay_seconds`) ban đầu chỉ được *khai báo* trong code nhưng **chưa từng được thực sự gọi tới ở đâu** — một lỗ hổng dead-code. Sau khi tham khảo thêm báo cáo bên ngoài cho rằng ngay cả 10-20 phút giữa các hành động Facebook cũng có thể bị coi là tự động hoá, khoảng nghỉ mặc định được nâng lên **1-2 giờ** và **thật sự được enforce**: nếu chưa đủ thời gian, hệ thống **từ chối thẳng tác vụ ngay lập tức** (không chờ/xếp hàng) thay vì cố chạy.

Khoảng nghỉ này được tính **riêng theo từng loại hành động** (đăng bài / comment / thả cảm xúc) — trước đó dùng chung 1 đồng hồ cho cả tài khoản, nghĩa là 1 comment vừa chạy xong sẽ vô tình chặn luôn 1 bài đăng ngay sau đó dù chúng thuộc 2 hạn mức hoàn toàn khác nhau.

**5 mức giới hạn theo "tuổi" tài khoản Facebook** (dưới 1 / 3 / 6 / 12 tháng, trên 12 tháng) — chọn được ngay khi đăng ký tài khoản, hoặc áp dụng sau bằng nút "quick-apply" khi tài khoản đã "lớn tuổi" hơn — thay vì phải gõ tay từng con số cho mỗi tài khoản mỗi lần cần nới/siết.

**Phát hiện + sửa lỗi thật (2026-09-10):** trong lúc điều tra vì sao backlog job/candidate của một tài khoản thật không bao giờ giảm dù đồng bộ liên tục (56 job/14 candidate cứ lấy đi lấy lại, chỉ ~8 bài/lượt thật sự được lên lịch), phát hiện ra khoảng nghỉ tối thiểu giữa 2 hành động (`min_delay_seconds`/`max_delay_seconds`) tuy đã tách riêng theo LOẠI hành động (đăng bài không còn bị comment chặn nhầm — mục ngay trên) nhưng vẫn dùng **chung 1 cặp con số cho cả đăng bài lẫn comment**. Vì hạn mức comment/ngày ở mọi mức tuổi luôn được đặt CAO HƠN hạn mức bài đăng/ngày, dùng chung 1 khoảng nghỉ khiến việc nhét đủ số comment vào 1 ngày là bất khả thi về mặt toán học — dù bài đăng có khi vẫn nhét vừa.

**Đã tách hẳn thành 2 cặp khoảng nghỉ độc lập — riêng cho bài đăng, riêng cho comment** — và người dùng tự tính toán lại cả 5 mức tuổi theo đúng nhu cầu thực tế, sau khi tôi kiểm tra tính khả thi (số lượng cần đăng × khoảng nghỉ tối đa có nhét vừa một ngày hoạt động ~18 tiếng hay không, sau khi trừ giờ ngủ 2h-6h sáng) và hạ bớt trần khoảng nghỉ ở 3 mức cao cho khớp:

| Mức tuổi | Bài/ngày | Comment/ngày | Giãn cách bài đăng | Giãn cách comment |
|---|---|---|---|---|
| Dưới 1 tháng | 5 | 7 | 2–3.5 giờ | 1.5–3 giờ |
| Dưới 3 tháng | 8 | 10 | 1.75–2.5 giờ | 1–2 giờ |
| Dưới 6 tháng | 12 | 15 | 1.25–1.6 giờ | 0.6–1.25 giờ |
| Dưới 12 tháng | 20 | 25 | 0.75–0.95 giờ | 0.35–0.75 giờ |
| Trên 12 tháng | 30 | 35 | 0.5–0.62 giờ | 0.25–0.5 giờ |

Đồng thời đổi giờ yên tĩnh mặc định từ 1h-6h sáng thành **2h-6h sáng**, theo yêu cầu chủ dự án.

**Sự cố thật xảy ra trong lúc thao tác migrate cấu hình:** khi cập nhật giờ yên tĩnh cho cấu hình thật đang chạy, gọi nhầm hàm lưu cấu hình chỉ với 1 field duy nhất — hàm này **thay thế toàn bộ phần cấu hình đồng bộ dữ liệu thay vì merge**, xoá mất toàn bộ override khác đã lưu trước đó (chu kỳ đồng bộ, khoảng cách đăng bài/comment, 2 công tắc AI...). Phát hiện ngay lập tức khi đọc lại, khôi phục đủ nguyên trạng bằng giá trị đã ghi nhớ được trong hội thoại — không mất dữ liệu vĩnh viễn, nhưng là bài học: mọi hàm lưu cấu hình dạng này đều cần đọc giá trị hiện tại rồi merge tay trước khi ghi, không được gọi với chỉ một phần dữ liệu.

**"Hạ nhiệt" tự động sau khi kích hoạt lại một tài khoản bị tạm dừng** — bổ sung sau khi tham khảo một báo cáo thực tế được chia sẻ trong một nhóm về vận hành Facebook: một người vận hành cố tình im lặng thêm 1 tuần sau khi hạn chế được gỡ, báo cáo 3 tháng sạch sẽ tiếp theo; một người khác đăng chéo bài ngay khi hạn chế vừa gỡ thì bị hạn chế lại ngay lập tức. Vì vậy, bấm "Kích hoạt lại" không đưa tài khoản về tốc độ đầy đủ ngay, mà chạy ở giới hạn thấp hơn trong một số ngày cấu hình được, rồi mới tự phục hồi về mức trước khi bị tạm dừng.

**Phát hiện thật (2026-09-11) — "1 ngày" ở lớp lên lịch và "1 ngày" ở lớp enforcement là 2 khái niệm khác nhau, có thể vượt hạn mức dù lớp lên lịch chưa từng làm sai.** Owner thấy báo cáo `rate_limited:comments_per_day limit reached` xuất hiện, hỏi vì sao lên lịch đã kiểm tra slot rồi mà vẫn dư. Điều tra kỹ: `data_sync.py`'s `_count_scheduled_actions_by_day()` (lớp lên lịch) đếm đúng theo **ngày dương lịch UTC** và chưa từng xếp quá hạn mức cho tài khoản `tu_iizuki` (kiểm tra thật: 1/6/4 comment cho 3 ngày liên tiếp, đúng cả, không vượt 7/ngày). Nhưng `safety.py`'s `RateLimiter.can_proceed()` (lớp enforcement, quyết định có thật sự cho đăng hay không) đếm theo **cửa sổ trượt 24 giờ tính từ lúc kiểm tra**, không phải ngày dương lịch. Vì `auto_fire_enabled` tắt phần lớn thời gian nên task dồn thành pending qua nhiều ngày; khi cuối cùng bắn hàng loạt (bật auto-fire tạm hoặc bấm tay dồn dập), các comment lên lịch cho 2 ngày dương lịch KHÁC NHAU có thể rơi vào CÙNG 1 cửa sổ 24h thực tế lúc đăng, cộng dồn vượt hạn mức dù mỗi ngày dương lịch riêng lẻ đều hợp lệ — xác nhận bằng log thật: 7 comment tính vào cửa sổ trượt trải dài `2026-09-10T08:12` → `2026-09-11T00:18` (~16 tiếng thực tế). Cùng bản chất với vụ va chạm x₁/x_safety đã ghi nhận ở mục 4.13, nhưng lần này là cho GIỚI HẠN SỐ LƯỢNG chứ không phải khoảng nghỉ. **Chưa sửa lớp lệch pha này** — theo yêu cầu owner, chỉ ghi nhận nguyên nhân thật ở đây.

**Bug thật ĐÃ sửa cùng lúc: dính hard cap (posts/comments per day/hour) nhưng hệ thống vẫn cứ thử đăng lại mỗi phút.** Cheap pre-check trong `fire_due_tasks()` (mục 4.13) vốn chỉ được thiết kế để tránh gọi `run_task()` lặp lại vô ích cho trường hợp SOFT gap (`min_delay_seconds`) — hoàn toàn không biết gì về hard cap. Hậu quả thật: 1 tài khoản dính `comments_per_day` vẫn bị thử lại mỗi 60 giây, mỗi lần tốn 1 lệnh gọi AI thật (soạn lại nội dung reply) TRƯỚC KHI mới bị chặn — 44 lần trong 24 phút, hoàn toàn lãng phí vì kết quả luôn giống hệt nhau và có thể kéo dài tới hết cả cửa sổ 24h nếu cứ để auto-fire bật. Thêm `safety.py`'s `rate_limit_hard_cap_message()` — phát hiện riêng biệt các hard cap này, trả về câu gợi ý dời lịch tiếng Việt (không tính giờ chính xác vì bản chất cửa sổ trượt không có 1 mốc "hết hạn" cố định, chỉ nói chung "dời sang thời điểm khác"). Wire vào pre-check của `fire_due_tasks()` để **skip hẳn** `run_task()` (và bước AI tốn tiền) ngay khi phát hiện hard cap, giống hệt cách đã làm cho soft gap. Áp dụng đồng bộ cho `schedule_fire_now()` ("Đăng ngay") và `reports_repost()` ("Đăng lại") ở `admin.py`. Kiểm tra riêng `posts_per_day` — cùng lỗi y hệt (2 dòng thật trong DB), sửa chung 1 chỗ cho mọi loại action.

## 4.7. Tự phát hiện tài khoản bị Facebook hạn chế và tự tạm dừng (2026-09-06 – 2026-09-07)

**Sự cố thật xác nhận hệ thống hoạt động đúng:** tài khoản `tu_iizuki` từng bị Facebook đưa ra màn hình "confirm your identity" thật (đang thao tác tay ghi Codegen, không phải lúc chạy tự động) — mức độ trung bình, chỉ chặn một số hành động, xác minh qua app Facebook trên điện thoại là xong. Đây là lần đầu tiên bộ dấu hiệu phát hiện bất thường trong code được đối chiếu với ảnh chụp màn hình thật thay vì chỉ dựa vào suy đoán — cả 2 cụm chữ đã có sẵn ("confirm your identity", "unusual activity") khớp đúng y hệt màn hình thật, và một cụm thứ 3 ("certain actions have been restricted") được thêm vào để chắc chắn hơn.

**Cơ chế:** khi phát hiện bất kỳ dấu hiệu nào trong danh sách trên (cả dạng chữ lẫn dạng cấu trúc như captcha, bị đá về trang login dù phiên vẫn còn hợp lệ), hệ thống dừng ngay tác vụ đang chạy — **không thử lại, không cố tự giải captcha hay xác minh danh tính** — và chuyển tài khoản đó sang trạng thái Tạm dừng **bền vững qua cả việc restart service**, chặn mọi tác vụ tiếp theo ngay từ đầu cho tới khi một người vận hành thật vào `/admin/accounts` bấm "Kích hoạt lại".

**Giới hạn đã biết, chủ đích không sửa:** cơ chế tự tạm dừng chỉ hoạt động khi chạy qua pipeline tự động — lúc thao tác tay bằng Playwright Codegen (như sự cố `tu_iizuki` trên), hệ thống không hề biết tài khoản vừa bị cảnh báo. Từng cân nhắc thêm cảnh báo vào tài liệu hướng dẫn ghi Codegen để nhắc tự tay tạm dừng tài khoản trước khi ghi, nhưng chủ dự án quyết định không cần thiết — được ghi lại như một rủi ro đã biết và chấp nhận, không phải lỗ hổng cần vá ngay.

**Còn thiếu so với thiết kế đầy đủ của Safety Monitor:** hành vi #2 (chủ động giảm tốc khi sắp chạm giới hạn, không đợi tới lúc thất bại hẳn) và hành vi #3 (báo động ra ngoài qua Slack/email/Telegram khi có tài khoản bị tạm dừng — hiện tại chỉ biết được khi tự vào `/admin` xem banner cảnh báo).

## 4.8. Xác minh bài đăng thật sự thành công \+ chụp ảnh bằng chứng mỗi lần chạy (2026-09-07)

**Vì sao cần làm lại:** trước đây, sau khi bấm Post, hệ thống chỉ đợi cứng 2 giây rồi luôn báo thành công — không kiểm tra gì cả. Một sự cố thật đã xảy ra đúng kiểu lỗi này: ảnh bị gắn nhầm vào input ẩn khác, hệ thống vẫn báo thành công dù ảnh không hề xuất hiện trên bài đăng thật.

**Đã sửa tận gốc:** sau khi bấm Post, hệ thống chủ động đợi cho tới khi nút "Post" **thật sự biến mất khỏi màn hình** (dấu hiệu Facebook đã nhận submit), tối đa 15 giây — hết giờ mà nút vẫn còn thì báo thất bại thật, không đoán mò. Bước đính kèm ảnh cũng đợi cho tới khi ảnh thumbnail thật sự hiện ra trong khung soạn trước khi tiếp tục, bắt lỗi ngay tại thời điểm xảy ra thay vì âm thầm đăng bài không kèm ảnh.

**Chụp ảnh bằng chứng mọi lần chạy — cả thành công lẫn thất bại** — lưu theo từng tài khoản, tự dọn sau 30 ngày, xem trực tiếp được từ trang Báo cáo (`/admin/reports`).

**Còn cần xác nhận sống:** 2 cơ chế xác minh trên (nút Post biến mất, ảnh thumbnail xuất hiện) được viết theo suy luận hợp lý từ cấu trúc trang đã biết, nhưng chưa chạy thử trực tiếp đủ nhiều lần trên Facebook thật để loại trừ khả năng báo "thất bại" giả cho một bài thực ra đã đăng thành công.

## 4.9. Đính kèm ảnh/video khi đăng bài (2026-09-04)

Tự động đính kèm 1 ảnh cho mỗi bài đăng (cả tường cá nhân lẫn nhóm), bật/tắt được qua trang quản trị (mặc định bật). Nếu bài đăng có ảnh riêng do bên B cung cấp thì luôn ưu tiên dùng ảnh đó; nếu không, hệ thống tự chọn ngẫu nhiên 1 ảnh từ kho ảnh mẫu có sẵn trong dự án. Playwright không thao tác hộp thoại chọn file của hệ điều hành (không làm được), mà chặn ngay cú click và gán file trực tiếp vào input ẩn — cách làm chuẩn của Playwright cho việc upload file.

## 4.10. AI soạn/viết lại nội dung — job đăng nhóm và reply ứng viên (Content Strategist Agent) (2026-09-04, viết lại kiến trúc + đa nhà cung cấp 2026-09-10)

**Vì sao cần AI ở đúng chỗ này:** nghiên cứu về cách các công cụ tự động hoá nhóm Facebook bị phát hiện chỉ ra rằng **nội dung giống hệt nhau đăng vào nhiều nhóm/nhiều người trong thời gian ngắn là dấu hiệu bị gắn cờ nhanh nhất**. Vì hệ thống thật sự phát tán một tin tuyển dụng vào mọi nhóm đã tham gia và trả lời hàng loạt ứng viên bằng cùng một bộ câu mẫu, việc có một lớp AI biến tấu nội dung là **yêu cầu bắt buộc**, không phải tính năng "cho đẹp".

**Thay đổi kiến trúc quan trọng (2026-09-10): AI chuyển từ "lúc vừa nhận dữ liệu" sang "đúng lúc bài sắp đăng thật".** Bản đầu (2026-09-05) gọi AI ngay khi vừa lấy được 1 tin tuyển dụng mới từ bên B, soạn 1 lần cho toàn bộ nhóm sẽ đăng cùng lúc — ưu điểm là chắc chắn N nhóm khác chữ (AI thấy hết N nhóm trong 1 lần gọi), nhược điểm là tốn tiền gọi AI ngay cả khi bài đó sau này bị sửa/huỷ trước khi đăng. Bản mới: dữ liệu vừa nhận chỉ được soạn tạm bằng **mẫu cố định** (không AI, không tốn phí) để hiện ngay trên trang lịch đăng; AI chỉ thật sự được gọi **ngay trước khi bài thật sự đăng lên Facebook**, mỗi lần gọi ứng với đúng 1 bài cho đúng 1 nhóm. **Đánh đổi đã được chủ dự án chấp nhận:** không còn đảm bảo chắc chắn N nhóm khác chữ nhau (vì không còn gọi 1 lần cho cả nhóm cùng lúc) — dựa vào AI tự biến tấu độc lập mỗi lần gọi; live-test thực tế cho thấy vẫn đọc khác nhau một cách tự nhiên. Cách gọi cũ (1 lần cho cả batch nhóm) **được giữ lại trong code, không xoá**, chỉ đánh dấu "không còn được gọi ở đâu" — để dùng lại nếu sau này cần.

**Mẫu (template) không-AI cũng được viết lại kỹ hơn nhiều** — trước chỉ có 3 câu mở đầu cố định và 1 lỗi thật (thuộc tính dạng danh sách của bên B bị in thẳng ra bài đăng dưới dạng `['Shizuoka']`, lộ cả dấu ngoặc vuông của Python): giờ có pool 8 câu mở đầu ngẫu nhiên, nhãn địa điểm/visa/lương đều có nhiều cách gọi khác nhau (random mỗi lần — nhãn "lương" gồm "Lương", "Mức lương", "Thu nhập", "Đãi ngộ", "Về tay"; **riêng lương tính THEO NĂM có thêm 2 lựa chọn "Nenshuu"/"年収"**, 2 từ mượn tiếng Nhật quen thuộc với cộng đồng đi làm ở Nhật — chỉ dùng cho lương năm vì đây là nghĩa gốc của từ, gắn cho lương tháng/giờ sẽ sai nghĩa chứ không chỉ khác văn phong), tên visa (mã thô bên B như `gijinkoku`) được map sang tên tiếng Việt/kanji thông dụng, lương tháng/năm bằng yên được đổi qua đơn vị dân gian "man"/tiếng lóng Việt "lá"/"tờ", và **không bao giờ chèn link vào bài** — link được thay bằng câu mời nhắn tin/inbox.

3 ví dụ thật (chạy trực tiếp `content_strategist._draft_job_post_placeholder()` với dữ liệu mẫu khác nhau, để thấy rõ mức độ biến tấu):

```
TÌM NHÂN SỰ - Kỹ sư cơ khí
Công ty: Công ty ABC Corp
Địa chỉ: Shizuoka
Visa Gijinkoku
Yêu cầu JLPT: N3
Lương: dao động 22-28 lá/tháng
Inbox mình để được tư vấn kỹ hơn
```

```
TUYỂN GẤP - Nhân viên chế biến thực phẩm
Công ty: Nihon Food Co.
Địa điểm làm việc: Aichi
Visa Kỹ Năng Đặc Định
Thông tin lương — ib để biết thêm
Nhắn tin mình để mình gửi thêm thông tin
```
*(ví dụ trên: thiếu lương trong dữ liệu bên B → tự thêm câu mời nhắn tin hỏi thêm thay vì bỏ trống im lặng)*

```
CƠ HỘI VIỆC LÀM - Phụ bếp nhà hàng Nhật
Công ty: Sushi Taro
Vị trí: Osaka
Yêu cầu JLPT: N4
Đãi ngộ: 1300-1500 JPY/giờ
Thông tin visa — nhắn mình để rõ hơn
Ai quan tâm nhắn tin mình nhé
```
*(ví dụ trên: lương theo GIỜ nên giữ nguyên số yên gốc, không đổi qua man/lá/tờ — quy tắc đó chỉ áp dụng cho lương tháng/năm)*

**Mở rộng sang cả nội dung trả lời ứng viên (trước đây chưa làm):** giờ có pipeline 3 tầng — mẫu cố định → gọi API `/reply` của bên B (bên B tự chạy AI riêng của họ) → AI (nhà cung cấp đang chọn ở `/admin/config`) của chính hệ thống viết lại từ mẫu, tối đa khoảng 200 ký tự. **Hai bước gọi AI (bên B và của mình) không bao giờ chạy cùng lúc cho 1 ứng viên** — nếu AI của mình đang bật và có API key thì bỏ hẳn bước gọi bên B, tránh trả tiền cho 2 lượt soạn AI cho cùng 1 câu trả lời.

3 ví dụ thật (mỗi lần random chọn 1 trong 10 mẫu cố định ở `data_sync._CANDIDATE_REPLY_TEMPLATES`, `data_sync._draft_candidate_reply_placeholder()`):

```
Chào bạn, mình thấy bạn đang tìm kỹ sư cơ khí ở khu vực Shizuoka, bên mình đang có một số vị trí có thể phù hợp, bạn nhắn tin trao đổi thêm nhé.
```

```
Alo bạn, bên mình có một số đơn hàng điều dưỡng ở khu vực Tokyo đang cần người, bạn qtam thì nhắn mình nhé.
```

```
Hii, bên mình đang tuyển lắp ráp linh kiện điện tử, ib mình gửi chi tiết nhé.
```
*(ví dụ trên: ứng viên không có "khu vực mong muốn" trong dữ liệu → cụm "ở khu vực ..." tự động bỏ hẳn, không để trống/lỗi câu)*

**Cả hai nhánh AI (job và reply ứng viên) đều có công tắc bật/tắt riêng ở `/admin/config`**, độc lập với việc có cấu hình API key hay không — tắt được ngay không cần sửa `.env`/khởi động lại service, phòng khi cần kiểm soát chi phí hoặc muốn quay lại dùng mẫu cố định tạm thời.

**Đã xác nhận sống với AI thật (Anthropic, sau khi nạp lại credit) — 2 ví dụ thật, cùng 1 tin tuyển dụng (Kỹ sư đóng tàu/Cơ khí, Ehime, visa Gijinkoku, lương khởi điểm 22 man/tháng, không yêu cầu JLPT) nhưng đăng vào 2 nhóm khác nhau:**

```
Anh chị nào đang tìm hướng chuyển việc mới thì để ý nhé!
Bên mình đang tuyển vị trí Kỹ sư đóng tàu/Cơ khí tại Ehime. Lương khởi điểm 22 man/tháng, visa Gijinkoku (技術・人文知識・国際業務). Không yêu cầu JLPT nên phù hợp với bạn nào tiếng chưa mạnh lắm nhưng có tay nghề vững.
Ehime là tỉnh ven biển miền Tây Nhật, môi trường làm việc ngành tàu thuyền khá ổn định. Nếu quan tâm thì inbox mình trao đổi thêm chi tiết nhé!
```

```
Chào cả nhóm! Có tin tuyển cho anh em làm cơ khí muốn sang Nhật ổn định nè.
Vị trí: Kỹ sư đóng tàu/Cơ khí
Địa điểm: Ehime (vùng Shikoku)
Mức lương: từ 220,000 yên/tháng
Visa: Kỹ sư (技人国) - không cần chứng chỉ tiếng
Ngành đóng tàu ở Nhật khá thiếu người nên cơ hội thăng tiến tốt. Bạn nào đã có kinh nghiệm cơ khí/hàn xì/lắp ráp thì rất hợp. Muốn biết thêm về công ty và quy trình thì nhắn tin cho mình nha!
```

Đúng đủ các luật đã đặt ra trong `_SYSTEM_PROMPT`: hai bài đọc hoàn toàn khác nhau (mở đầu, giọng văn, thậm chí khác cả cách trình bày — bài 1 viết văn xuôi liền mạch, bài 2 tách gạch đầu dòng theo từng trường thông tin), lương đổi đúng qua "man" lẫn giữ nguyên số yên gốc tuỳ bài, tên visa gọi theo 2 cách khác nhau (kanji đầy đủ vs. viết tắt "技人国"), không bài nào chèn link, và không bài nào bịa thêm thông tin ngoài dữ liệu tin tuyển dụng gốc.

**Đa nhà cung cấp AI, chọn được ngay trên Admin UI (2026-09-10, thêm sau khi phát hiện giới hạn trên):** ban đầu hệ thống gọi cứng Anthropic Messages API — dán API key của OpenAI hay bất kỳ hãng nào khác vào ô cấu hình cũ không có tác dụng gì, vì request vẫn được gửi thẳng tới `api.anthropic.com` với key sai định dạng (kết quả: lỗi xác thực 401, tự động rơi về mẫu cố định, không báo lỗi rõ cho người quản trị). Theo yêu cầu owner muốn "linh hoạt đổi qua lại nhiều model", đã tách phần **gọi API** (khác nhau giữa các hãng: URL, header xác thực, cấu trúc request/response) ra khỏi phần **soạn nội dung/kiểm tra kết quả** (giống nhau dù dùng hãng nào) — file mới `human_bot/ai_client.py` chỉ lo phần đầu, `content_strategist.py` giữ nguyên toàn bộ prompt tiếng Việt và luật kiểm tra (đếm ký tự, đúng số bài, không rỗng...) như cũ. 4 nhà cung cấp hỗ trợ sẵn: **Anthropic (Claude), OpenAI (GPT), Google Gemini, và một lựa chọn "Tuỳ chỉnh"** (endpoint bất kỳ nói được chuẩn OpenAI Chat Completions — dùng được cho DeepSeek/Groq/OpenRouter/LLM chạy nội bộ...). Mỗi nhà cung cấp có ô key + tên model riêng, không dùng chung 1 ô như trước — đổi qua lại không cần nhập lại key đã lưu cho hãng cũ. **Lưu ý quan trọng đã báo owner:** tên model là định danh kỹ thuật của API (ví dụ `gpt-4o-mini`, `gemini-2.5-flash`), phải gõ đúng chính xác từng ký tự kể cả chữ hoa/thường — gõ sai không làm sập hệ thống, chỉ khiến lệnh gọi AI thất bại và tự động rơi về mẫu cố định (có ghi log lỗi thật để dò). **Chưa test end-to-end với key thật của OpenAI/Gemini/custom** — mới kiểm tra logic lưu/đọc cấu hình bằng script nội bộ, chưa có key thật của các hãng này để xác nhận nội dung AI trả về đúng định dạng mong đợi.

**2 lần tinh chỉnh giao diện theo phản hồi trực tiếp sau khi xem UI:** (1) ô nhập API key ban đầu không có viền, khó phân biệt với nền — do thiếu `input[type=password]` trong danh sách selector CSS chung của trang, chỉ là sót chứ không cố ý, đã bổ sung; (2) ô nhập tên model ban đầu có thêm 1 dropdown "chọn nhanh" riêng đặt cạnh ô nhập tự do — hiện 2 control cho cùng 1 giá trị bị nhận xét là rối mắt, nên đã gộp lại thành **1 ô input duy nhất dùng `<datalist>`** (tính năng chuẩn của HTML): bấm vào ô hiện gợi ý 3 model phổ biến để chọn nhanh, nhưng vẫn gõ/sửa tự do bình thường trong đúng 1 ô, không cần thêm JS để đồng bộ giữa 2 control.

**Sửa lỗi thật: AI lỗi/thiếu key lúc đăng bài từng làm MẤT nội dung admin đã tự tay sửa ở Lịch đăng (2026-09-10).** Owner phát hiện qua thực tế: sửa nội dung 1 bài ở `/admin/schedule`, nhưng nếu công tắc "Dùng AI soạn bài" đang bật mà AI gọi lỗi hoặc hết key, `draft_single_post()` khi đó lại tự soạn một bản template HOÀN TOÀN MỚI (chọn ngẫu nhiên câu mở đầu khác) thay vì giữ nguyên bản đã hiển thị trên lịch — nội dung admin vừa sửa tay bị âm thầm ghi đè mất, mãi tới lúc đăng mới lộ ra. Đã sửa để hàm này luôn nhận thêm nội dung ĐANG có trên lịch (kể cả bản admin đã sửa tay) và trả về **nguyên xi** nội dung đó ở mọi trường hợp không dùng được AI (tắt công tắc / thiếu key / gọi AI lỗi) — chỉ thay bằng bài AI soạn khi AI thực sự gọi thành công. Cùng nguyên tắc "không bao giờ mất nội dung đã có" mà nhánh viết lại reply ứng viên vốn đã áp dụng từ trước, giờ áp dụng nhất quán cho cả nhánh job post.

Cũng còn thiếu so với kế hoạch gốc: một bộ chuẩn hoá tín hiệu đầu vào (`normalize_signal()`), và các "guardrail" chống trùng lặp/từ cấm bằng code (hiện mới chỉ có trong system prompt gửi cho AI, chưa có lớp kiểm tra cứng bằng code) — riêng độ dài đầu ra thì đã có chặn cứng bằng code (không chỉ dặn trong prompt).

## 4.11. Đăng nhập tài khoản mới qua web, thay cho chạy lệnh tay trong terminal (2026-09-10)

Trước đây thêm tài khoản Facebook mới bắt buộc phải tự chạy `python3 human_bot/bootstrap_login.py <account_id>` trong terminal, một cửa sổ trình duyệt thật mở ra để tự tay đăng nhập, rồi quay lại terminal bấm Enter. Giờ có thêm lựa chọn qua `/admin/accounts`: tài khoản nào có badge đỏ "chưa có phiên đăng nhập" giờ có nút "Đăng nhập & lưu phiên" — mở đúng một cửa sổ trình duyệt thật như cách cũ, chỉ khác là xác nhận xong việc đăng nhập thì bấm nút trên web thay vì Enter trong terminal. **Giới hạn:** chỉ dùng được khi service đang chạy trên máy có màn hình thật — cửa sổ trình duyệt mở ra nằm trên máy đang chạy service, không phải máy đang xem trang quản trị; nếu chạy service trên server không màn hình thì vẫn phải dùng cách chạy lệnh tay như cũ.

**Sự cố thật phát hiện trong lúc làm, đã sửa cùng lúc:** đăng ký một tài khoản ở `/admin/accounts` trước khi đăng nhập xong (tài khoản chưa có phiên đăng nhập) khiến **toàn bộ service sập ngay lúc khởi động**, không chỉ riêng tài khoản đó — đã sửa để một tài khoản thiếu phiên đăng nhập chỉ tự nó không hoạt động được, không kéo sập tài khoản khác hay cả service.

## 4.12. Quản lý tài khoản, nhóm, lịch đăng, cấu hình và báo cáo qua Admin UI (2026-09-02, nhiều đợt hoàn thiện tới 2026-09-10)

Đã viết lại hoàn toàn từ một trang "đăng trực tiếp" đơn giản (không khác gì tự vào Facebook đăng tay) thành một hệ thống quản trị đầy đủ:

* **Quản lý tài khoản** (`/admin/accounts`): đăng ký/Tạm dừng/Kích hoạt lại/Xoá — áp dụng được cho mọi tài khoản kể cả loại khai báo sẵn trong code; chỉnh giới hạn tốc độ riêng từng tài khoản; cảnh báo ngay trên dashboard nếu có tài khoản đang Tạm dừng. Thêm cột **"Tuổi tài khoản"** hiện ngay trong danh sách (so khớp `posts_per_day`/`comments_per_day` hiện tại với 5 tier, hoặc "Tuỳ chỉnh" nếu không khớp — 2026-09-11, không cần mở modal mới biết). Nút "Áp nhanh theo tuổi tài khoản" trong modal "⏱️ Giới hạn" **không còn tự lưu ngay khi bấm** (2026-09-11, owner phát hiện qua chính 1 buổi làm việc — hạn mức đổi mà không nhớ đã bấm gì) — giờ chỉ điền số vào form, phải bấm "Lưu" mới ghi thật.
* **Soạn & lên lịch đăng** (`/admin/post` → `/admin/schedule`): **mọi bài đều phải qua bước lịch đăng để duyệt trước khi thật sự chạy** — không còn nút "đăng ngay lập tức" nào bỏ qua bước này, kể cả muốn đăng ngay cũng chỉ là để trống giờ rồi bấm "Đăng ngay" ở trang lịch. Hỗ trợ nhiều khối nội dung khác nhau cho nhiều tập nhóm khác nhau trong cùng một lượt soạn. Trang lịch có bộ lọc, phân trang, hiển thị giờ theo múi giờ Nhật Bản, cảnh báo ngay trên từng dòng nếu bài đang bị chặn bởi rate-limit. **Phân trang bổ sung nút "Trang đầu"/"Trang cuối" + ô nhảy thẳng tới số trang bất kỳ + chọn số item/trang (2026-09-11, 2 đợt cùng ngày)** — trước đó chỉ có Trang trước/Trang sau, bất tiện khi danh sách dài (VD từ trang 1 muốn tới trang 10 hoặc trang cuối phải bấm nhiều lần), và không có cách nào biết/đổi mỗi trang hiển thị bao nhiêu item (cố định 20). Ô nhảy trang gộp thành 1 khối "Trang `[_]`/N `[Đi]`" duy nhất (đợt đầu làm 3 phần tử rời rạc, owner phản hồi chưa đẹp, gộp lại ở đợt 2); dropdown "Hiển thị" chọn 10/20/50/100 item/trang, đặt cạnh bộ lọc tài khoản, đổi là áp dụng ngay không cần bấm gì thêm.
* **Quản lý nhóm** (`/admin/groups`): nhập/sửa/xoá danh sách nhóm đã tham gia theo từng tài khoản, không cần sửa code.
* **Báo cáo** (`/admin/reports`): tổng quan nhanh (tổng số/thành công/thất bại/tỉ lệ/số tài khoản hoạt động) hiển thị dạng lưới 5 ô chia đều, lọc theo khoảng thời gian, xem ảnh chụp bằng chứng từng lần chạy. Bảng "Tỉ lệ thành công/thất bại theo hành động" hiển thị 1 dòng/hành động với 2 cột riêng Thành công/Thất bại (2026-09-11, trước đó lặp 2 dòng/hành động). Bảng "Hoạt động gần đây" có phân trang cùng kiểu với Lịch đăng (2026-09-11, 3 đợt chỉnh cùng ngày theo phản hồi owner) — nút Đầu/Cuối, ô nhảy trang gộp 1 khối, dropdown chọn 10/15/30/50/100 item/trang đặt cùng hàng với tiêu đề "🕒 Hoạt động gần đây" cùng số mục (không phải footer như bản đầu, không phải hàng lọc chung trên cùng như trước nữa — chỉ ảnh hưởng riêng khối này). Nút "Đăng lại" khi bị chính rate-limiter của hệ thống chặn hiển thị cảnh báo màu hổ phách (gợi ý giờ thử lại) thay vì bị tính chung là lỗi màu đỏ — cùng cách phân biệt "Đăng ngay" ở Lịch đăng đã làm từ trước. **Dữ liệu thống kê cũng đồng bộ theo quyết định này (2026-09-11)** — mọi task bị `rate_limited:` (từ auto-schedule, thủ công, hay "Đăng lại") trước đây ghi `success=0` giống hệt lỗi thật vào `action_log`, kéo lệch khối KPI và bảng "theo hành động". Giờ `db.py`'s `summary_stats()`/`action_type_counts()` loại các dòng này khỏi total/succeeded/failed (chưa từng thực sự thử làm gì — rate-limit chặn TRƯỚC khi mở trình duyệt), còn bảng "Hoạt động gần đây" vẫn hiện đủ (để còn "Đăng lại" được) nhưng đổi icon riêng (⏳ thay vì ⚠️ dùng chung với lỗi thật).
* **Cấu hình hành vi** (`/admin/config`): chỉnh mọi tham số mô phỏng con người, rate-limit, đồng bộ dữ liệu bên B — có hiệu lực ngay, không cần sửa `.env`/khởi động lại service. Mọi công tắc bật/tắt (cả 3 tab: hành vi/đồng bộ/AI) hiển thị dạng switch (nút gạt) thay vì checkbox thường (2026-09-10) — chỉ đổi giao diện, không đổi cách lưu.
* **Mọi chỗ hiển thị giờ trong toàn bộ Admin UI đồng bộ theo giờ trình duyệt đang mở (2026-09-11)** — trước đó vài nơi (trạng thái đồng bộ/tạm dừng/hạ nhiệt ở `/admin/accounts`, cột "Thời gian" ở bảng Hoạt động gần đây) còn gắn cứng JST hoặc UTC, không theo người xem thật. Đổi hết sang cơ chế đã có sẵn cho Lịch đăng (server render giờ JST làm dự phòng, JS ghi đè bằng giờ trình duyệt thật ngay khi trang tải xong). Việc sửa này trực tiếp giải quyết đúng vụ nhầm "chỉ thấy 2 nhóm/2 comment hôm nay" (thực ra 3/4) do đọc nhầm cột "Thời gian (UTC)" thay vì ngày nghiệp vụ thật.

## 4.13. Đồng bộ dữ liệu tự động từ hệ thống tuyển dụng (bên B) (2026-09-04, hardening 2026-09-08 – 2026-09-09)

Một vòng lặp nền tự động gọi API của bên B để lấy tin tuyển dụng mới (→ lên lịch đăng nhóm) và ứng viên mới (→ lên lịch trả lời), tự chống trùng theo ngày, tự giãn cách thời gian đăng ngẫu nhiên (không đăng dồn cục), và **chia đều công bằng** dữ liệu mới cho mọi tài khoản đang hoạt động thay vì chỉ tài khoản xử lý đầu tiên mỗi vòng nhận được (một lỗi thật đã phát hiện và sửa — xem mục 5). Có "khung giờ yên tĩnh" để không đăng vào ban đêm theo giờ Nhật Bản. **Cổng an toàn tự đăng (`auto_fire_enabled`) mặc định tắt** — bộ đồng bộ vẫn lấy dữ liệu/lên lịch bình thường, nhưng sẽ không tự bấm đăng lên Facebook cho tới khi chủ động bật cổng này; trong lúc chờ, có thể đăng thủ công từng bài từ trang lịch.

**Thực thi đúng giới hạn `posts_per_day` ngay khi tự động lên lịch (2026-09-08)** — bài tự động đăng nhóm do bộ đồng bộ tạo ra tôn trọng đúng hạn mức bài/ngày của từng tài khoản (mục 4.6): vượt quá thì tự tràn dồn sang ngày kế tiếp thay vì cố nhét hết vào 1 ngày hoặc bị bỏ luôn, cộng thêm khoảng cách tối thiểu giữa 2 bài đăng cùng vào 1 nhóm (tránh 2 bài liên tiếp rơi đúng vào 1 nhóm dù cách nhau đủ xa với các nhóm khác).

**Giới hạn số nhóm/1 job + loại tài khoản 0 nhóm khỏi phân phối (2026-09-11), sau khi owner chỉ ra "1 job phát vào TOÀN BỘ nhóm đã tham gia" là dấu hiệu spam rõ dù đã viết lại nội dung.** Điều tra sâu (test thật, không đoán) ra 2 lỗi + 1 điểm xác nhận đã đúng:

1. **Bug thật:** tài khoản 0 nhóm vẫn được `_water_fill_distribute()` chia job (chỉ tính `posts_per_day`, không kiểm tra có nhóm hay không) — job đó chạy 0 vòng lặp nhóm (không tạo task nào) nhưng vẫn bị `_mark_seen()` → **mất vĩnh viễn**, đồng thời cướp mất phần chia đáng lẽ dành cho tài khoản có nhóm thật. Sửa: loại thẳng tài khoản 0 nhóm khỏi `job_capacities`.
2. **Gap thật:** chưa từng có giới hạn số nhóm/job — `template_variants()` luôn trả đúng `len(groups)` biến thể (mọi nhóm đã tham gia). Thêm `RateLimits.max_groups_per_post` (mặc định 3) — **riêng từng tài khoản** (không phải cấu hình toàn cục), chỉnh ở modal "⏱️ Giới hạn" tại `/admin/accounts`, cùng chỗ với `posts_per_day`/`comments_per_day` (bản đầu để nhầm ở `DataSyncConfig`/tab "Đồng bộ" — toàn hệ thống dùng chung 1 số, owner phản hồi ngay cần riêng theo tài khoản vì tài khoản nhiều nhóm lâu năm có thể chịu được giới hạn cao hơn tài khoản mới ít nhóm, đã chuyển lại đúng chỗ). Chọn nhóm theo **round-robin ưu tiên nhóm lâu chưa đăng nhất** (tái dùng `_last_scheduled_time_per_group()` có sẵn) — không random (có thể bỏ quên nhóm) hay cố định N nhóm đầu (không xoay vòng). Nút "Áp nhanh theo tuổi tài khoản" (quick-apply tier) được sửa để **giữ nguyên** giá trị này khi bấm — tier preset không khai báo field này (khác trục với tốc độ/số lượng theo tuổi), nếu không giữ sẽ âm thầm reset về mặc định 3 mỗi lần bấm, mất tuỳ chỉnh riêng của admin.
3. **Đã kiểm tra, không phải bug:** lo ngại "1 job có thể bị phân phối cho >1 tài khoản" — test thật xác nhận KHÔNG xảy ra, `_water_fill_distribute()` + `_mark_seen()` (cache toàn cục theo id) đã đảm bảo đúng 1 job → đúng 1 tài khoản từ trước.

**Bật/tắt đồng bộ dữ liệu riêng theo từng tài khoản, độc lập với Tạm dừng/Kích hoạt (2026-09-08).** Một tài khoản đang ACTIVE nhưng bị tắt đồng bộ ở đây vẫn đăng bài/comment bình thường qua `/admin/post` — chỉ riêng việc tự động lấy job/candidate mới từ bên B cho tài khoản đó bị bỏ qua. Có theo dõi trạng thái lần đồng bộ gần nhất riêng theo từng tài khoản, xem tại `/admin/accounts` tab Đồng bộ.

**Lỗi thật phát hiện 2026-09-10 — comment lên lịch quá gần nhau giữa các lần poll khác nhau, và fix "kẹp sàn".** Owner phát hiện 3 comment cùng tài khoản, lên lịch chỉ cách nhau 5-20 phút dù `comment_min/max_delay_seconds` đang đặt 90-180 phút. Nguyên nhân: `next_comment_time` trong `sync_all()` chỉ được cộng dồn ngẫu nhiên (`+= random(gap)`) **trong phạm vi 1 lần gọi `sync_all()`** — sang lần poll kế tiếp (~15 phút sau), biến này khởi tạo lại từ `now` mới, không biết gì về comment đã lên lịch từ lần poll trước, nên 2 khoảng random độc lập có thể tình cờ rơi gần nhau.

Sửa bằng cách thêm `_last_scheduled_comment_time(account_id)` (soi lại comment pending/posted từ các lần poll trước, cùng ý tưởng với `_last_scheduled_time_per_group()` vốn đã dùng cho bài đăng nhóm — mục ngay trên, chỉ khác là comment kẹp theo TÀI KHOẢN chứ không theo từng nhóm/mục tiêu riêng, vì `RateLimits.comment_min/max_delay_seconds` vốn enforce theo tài khoản) và kẹp thêm sàn thứ hai là `RateLimiter(account).next_allowed_at("comment")` — giờ sớm nhất `safety.py` THẬT SỰ cho phép, tính từ lần comment gần nhất đã **thực sự đăng xong** (đọc log hành động, không ghi gì, an toàn để gọi trước khi lên lịch).

**Va chạm x₁/x_safety — ĐÃ SỬA (2026-09-11), đánh dấu TẠM THỜI theo quyết định chủ dự án.** Trước đó: mỗi khi 1 hành động đăng THẬT xong, `safety.py`'s `record()` tự random một khoảng gap MỚI (x_safety, trong `[gap_min, gap_max]`) làm mốc `next_allowed_at` cho hành động kế tiếp — độc lập hoàn toàn với con số random đã dùng để lên lịch (`x₁`, ở `data_sync.py`). Vì x_safety chỉ tồn tại SAU KHI hành động trước đó đăng xong (một sự kiện ở tương lai tại thời điểm lên lịch), không có cách nào biết trước để "kẹp sàn" tránh va chạm — nếu `x₁ < x_safety` (~50% xác suất), hành động kế tiếp tới giờ lên lịch vẫn bị `safety.py` chặn dù lịch tưởng đã ổn.

**Hướng đã chọn (trong 3 hướng từng cân nhắc — chấp nhận tự dò lại / gộp 2 lớp random / cố định x_safety=min):** cố định `x_safety = gap_min` thay vì random. Vì `x₁` luôn nằm trong `[gap_min, gap_max]` theo đúng định nghĩa, `x₁ ≥ x_safety` giờ là **chắc chắn toán học** (verify bằng mô phỏng 100,000 lần: 0 va chạm), không còn ~50% may rủi như trước — loại bỏ hoàn toàn va chạm cho mọi hành động đi qua `data_sync.py`'s scheduler. `next_allowed_at` giờ chỉ còn ý nghĩa "mốc nghỉ tối thiểu tuyệt đối" để các đường KHÔNG qua lịch biết mà né, không phải nguồn ngẫu nhiên chính (độ ngẫu nhiên thật nằm ở lớp lên lịch).

**Đánh đổi CHƯA giải quyết, ghi nhận rõ trong code:** mọi đường KHÔNG qua scheduler (vd nút "Đăng ngay"/"Đăng lại" ở `/admin/schedule`/`/admin/reports`) giờ có khoảng cách enforcement CỐ ĐỊNH mỗi lần — đúng kiểu "y hệt nhau mọi lần" mà [rate-limiting-pacing.md](docs/skills/rate-limiting-pacing.md) rule #3 khuyến cáo tránh. Rủi ro được đánh giá nhỏ (các đường đó do người thật bấm tay, không phải vòng lặp tự động lặp lại) nên chấp nhận đánh đổi TẠM THỜI — cần xem lại nếu sau này có thêm đường gọi tự động không qua lịch.

**Kẹp sàn SỐ LƯỢNG (posts_per_day/comments_per_day) theo cửa sổ trượt 24h thật — ĐÃ TRIỂN KHAI (2026-09-11), sau nhiều lượt trao đổi thiết kế.** Cùng vấn đề gốc như phần rate-limit theo GAP ở trên nhưng cho SỐ LƯỢNG: `data_sync.py`'s `job_capacities`/`comment_capacities` trước đây chỉ đếm "đã lên lịch cho ngày dương lịch nào" — không khớp với cách `safety.py` thật sự đếm (cửa sổ trượt 24h, không quan tâm ngày dương lịch), nên lịch trông hợp lệ (VD "hôm nay mới 1 comment") nhưng vẫn bị chặn khi chạy thật (7 comment trong 24h qua, tính cả tối hôm trước) — xem sự cố thật `comments_per_day` đã điều tra chi tiết.

**Đổi sang kẹp sàn** (`effective_used = max(theo ngày dương lịch, RateLimiter.recent_count() thật trong 24h)` — hàm `recent_count()` mới thêm vào `safety.py`, tách từ logic đếm sẵn có trong `can_proceed()`) — áp dụng cho cả `job_capacities` lẫn `comment_capacities`.

**Điều kiện bắt buộc đi kèm, không thể tách rời (đã phân tích kỹ qua nhiều lượt trao đổi):** phải bỏ HẲN cơ chế "tràn sang ngày mai" cho bài đăng (`_next_available_post_slot()`'s nhánh nhảy ngày) cùng lúc. Lý do: cách đếm theo ngày dương lịch cũ chỉ TĂNG (ngày "đầy" là đầy vĩnh viễn, giữ đúng thứ tự công bằng tự nhiên); cách đếm theo cửa sổ trượt thật CÓ THỂ GIẢM (khi hoạt động cũ trôi khỏi 24h) — nếu vẫn giữ tràn-ngày, 1 job bị đẩy sang ngày mai sẽ kẹt vĩnh viễn ở đó trong khi job MỚI hơn đến sau có thể "nẫng" mất slot vừa mở ra giữa ngày, đảo thứ tự cũ-mới. Bỏ tràn-ngày rồi thì không còn gì bị "khoá cứng" để đảo thứ tự — mỗi poll tính lại từ đầu.

**Hành vi mới khi hết slot giữa chừng (job phát nhiều nhóm) — theo ví dụ cụ thể owner đưa ra:** nếu `max_groups_per_post=3` nhưng chỉ còn 2 slot thật, đăng vào **2 nhóm** (không phải 0, không phải 3) — job coi như xử lý xong ngay (đánh dấu đã thấy), KHÔNG cố đăng nốt nhóm còn thiếu ở lần poll sau. Chỉ khi còn đúng **0 slot** mới hoãn cả job (không tạo task, không đánh dấu đã thấy, lấy lại nguyên vẹn ở poll sau — giống hệt cách xử lý tài khoản 0 nhóm đã sửa trước đó). Comment không cần logic "đăng vừa đủ" này vì 1 candidate luôn tạo đúng 1 task, không "nở" ra nhiều nhóm như job — chỉ cần sửa đúng con số capacity là `_water_fill_distribute()` đã tự defer đúng phần dư.

**Bug tự phát hiện khi cài đặt (không phải owner hỏi):** job bị hoãn BÊN TRONG vòng lặp (hết slot giữa chừng, khác với bị water-fill loại ngay từ đầu) không nằm trong danh sách `deferred_jobs` mà cơ chế giữ cursor bên B đang dùng — nếu không gộp vào, job đó có thể KHÔNG BAO GIỜ được lấy lại từ bên B (khác "chưa đánh dấu đã thấy" — nếu cursor trôi qua mốc thời gian của nó, API bên B sẽ không trả về nó nữa). Đã thêm bước gộp `deferred_jobs_inner` (theo từng tài khoản) vào `deferred_jobs` (danh sách ngoài) trước khi tính cursor.

Verify: mô phỏng lại chính xác công thức `available`/`groups_to_post` khớp đúng ví dụ owner đưa ra (2 slot, cap 3 → đăng 2; đầy hẳn → hoãn). 79 test vẫn pass. **Chưa chạy `sync_all()` thật qua service** — cần restart + có dữ liệu mới từ bên B mới quan sát được trực tiếp.

**Thay hẳn cơ chế enforcement SỐ LƯỢNG (`posts_per_day`/`comments_per_day`) từ cửa sổ trượt 24h sang "ngày nghiệp vụ" — file mới `human_bot/daily_limits.py` (2026-09-11).** Trong lúc bàn cách xử lý "còn thiếu slot thì set lịch chính xác vào giờ mở slot tiếp theo", owner tự phát hiện lỗ hổng: đặt cứng job vào đúng 1 giờ tính được (VD 19h) sẽ tạo khuôn mẫu lặp lại mỗi ngày (19h hôm qua, 19h hôm nay) — mất hẳn tính ngẫu nhiên, dấu hiệu bất thường còn rõ hơn cả việc thiếu slot. Bàn tiếp hướng đơn giản hoá triệt để: đổi luôn cách ĐẾM sang "ngày nghiệp vụ" cố định (2h sáng JST → 2h sáng JST hôm sau) thay vì cửa sổ trượt liên tục — khi đó không cần tính "giờ mở slot" động nữa, chỉ cần biết ngày nghiệp vụ hiện tại còn slot hay không.

**Vì sao chọn mốc 2h sáng, không phải nửa đêm:** 2h-6h sáng JST là khung giờ yên tĩnh có sẵn (`DataSyncConfig.quiet_hour_start_local`), không bao giờ có hoạt động nào diễn ra — reset đúng lúc đó nằm gọn trong "vùng chết", loại bỏ hẳn nguy cơ dồn cục 2 phía mốc reset (VD 7 bài trước 2h + 7 bài ngay sau 6h) mà nửa đêm (giữa giờ hoạt động) sẽ không tránh được — đây chính xác là kiểu khai thác mà cửa sổ trượt vốn sinh ra để ngăn. Cộng thêm khoảng nghỉ tối thiểu nhiều giờ giữa 2 hành động cùng loại (đã có sẵn) khiến việc dồn cục kiểu đó càng bất khả thi về mặt toán học — tài khoản không thể vừa đăng đủ 7 lần trong giờ trước 2h vừa đăng đủ 7 lần ngay sau 6h khi mỗi lần cách nhau hàng giờ.

**Quyết định kiến trúc của owner: `safety.py` GIỮ NGUYÊN, KHÔNG XOÁ gì cả** (`RateLimiter.can_proceed()`, `rate_limit_hard_cap_message()` — cả 2 còn nguyên trong file, chỉ thêm docstring "NOT CALLED ANYWHERE" trỏ sang module mới) — để đọc lại hoặc quay về sau nếu cần, không phải vì còn dùng. Phần GAP (`min_delay_seconds`, đã sửa x_safety=gap_min ở trên) và giới hạn theo GIỜ (`comments_per_hour`/`likes_per_hour`) **giữ nguyên qua `safety.py`, không đổi gì** — chỉ phần đếm theo NGÀY chuyển sang module mới. Thêm `RateLimiter.gap_ok()` — wrapper public nhỏ lộ phần gap-check để module mới tái dùng mà không cần đi qua `can_proceed()`.

Rà lại chính xác chỉ có **3 nơi thật sự gọi** cơ chế cũ (không phải 5 như ước lượng ban đầu, xác nhận bằng `grep`): `agent.py`'s `run_task()` (điểm chốt duy nhất mọi hành động thật đều đi qua), `admin.py`'s `schedule_fire_now()` + `reports_repost()`, `data_sync.py`'s `fire_due_tasks()` pre-check — cả 4 lượt gọi (2 trong `schedule_fire_now()`) đã đổi sang `daily_limits.can_proceed()`/`daily_limits.hard_cap_message()`.

Verify bằng dữ liệu THẬT `tu_iizuki`: đếm kiểu cũ (cửa sổ trượt) ra 7, đếm kiểu mới (ngày nghiệp vụ) ra 4 — khác nhau đúng như dự kiến; hàm mới chạy đúng cho cả 3 loại action (post đang bị chặn bởi gap mềm, không lẫn với hard cap). `grep` xác nhận sạch — không còn nơi nào gọi thẳng cơ chế cũ ngoài định nghĩa gốc. 79 test vẫn pass.

**Đồng bộ lớp LÊN LỊCH sang cùng "ngày nghiệp vụ", mang lại cơ chế tràn-ngày cho bài đăng (2026-09-11, cùng ngày).** Ngay sau khi đổi lớp enforcement, owner tự nhận ra hệ quả quan trọng: khi lớp lên lịch VÀ lớp enforcement cùng thống nhất 1 định nghĩa "ngày" duy nhất (ngày nghiệp vụ, cố định, không tự trôi như cửa sổ trượt), việc khoá 1 job vào "ngày nghiệp vụ mai" không còn rủi ro đảo thứ tự đã phân tích kỹ trước đó (lý do duy nhất khiến phải bỏ tràn-ngày hồi dùng cửa sổ trượt) — có thể bỏ hẳn cách "hoãn cả job, chờ poll sau tuỳ may rủi", biết chắc chắn và set lịch thẳng luôn.

Triển khai: `daily_limits.py` thêm `business_day_start()`/`business_day_key()` (public); `data_sync.py`'s `_count_scheduled_actions_by_day()` đổi key sang ngày nghiệp vụ (không còn ngày dương lịch UTC thô); `job_capacities`/`comment_capacities`'s kẹp sàn đổi nguồn "thật" từ cửa sổ trượt 24h sang `daily_limits.count_since_business_day_start()` (khớp đúng định nghĩa "ngày" với enforcement, không còn so 2 khái niệm khác nhau); hàm mới `_next_available_business_day()` đẩy sang ĐẦU ngày nghiệp vụ kế tiếp (2h sáng JST, không phải nửa đêm UTC như bản gốc) khi hết slot, lặp tối đa 60 ngày. Logic "đăng vừa đủ" (còn 2 slot, cap 3 → đăng 2, không cố đăng nốt) **giữ nguyên không đổi** — chỉ áp dụng cho đúng ngày mà `_next_available_business_day()` tìm ra.

Verify bằng test thật gọi trực tiếp hàm mới: "hôm nay đầy 3/3" → nhảy đúng sang ngày nghiệp vụ kế tiếp (full lại 3 slot), qua giờ yên tĩnh → ~6h24 sáng JST (không phải giờ cố định tuyệt đối, có biến thiên tự nhiên); "còn 2 slot, cap 3" → vẫn `available=2`, không tràn ngày, công thức "đăng vừa đủ" không bị ảnh hưởng. 79 test vẫn pass.

## 4.14. Bảo mật (2026-09-08, cảnh báo/xác nhận khi thiếu khoá 2026-09-10)

`POST /tasks` (API cho n8n/bên ngoài gọi vào) yêu cầu header `X-API-Key` khi đã đặt khoá trong cấu hình, so sánh bằng phương pháp an toàn chống timing attack (`secrets.compare_digest`). Trang quản trị hỗ trợ HTTP Basic Auth khi chạy ở nơi không phải máy cá nhân. **Chưa đặt khoá thật trong môi trường production** — cần làm trước khi mở các cổng này ra ngoài phạm vi máy/mạng nội bộ.

**Cả 2 lớp bảo vệ trên đều "im lặng tắt" nếu chưa cấu hình** — để trống `ADMIN_USERNAME`/`ADMIN_PASSWORD`/`TASKS_API_KEY` trong `.env` thì `/admin` và `/tasks` chạy hoàn toàn không xác thực, không có lỗi/cảnh báo nào trước đây. Vì `.env` bị gitignore (không đi theo khi clone/deploy sang máy khác), rủi ro thực tế là quên đặt lại 3 biến này ở môi trường mới mà không hề hay biết.

Thêm (2026-09-10) 2 lớp nhắc nhở lúc khởi động service (`human_bot/service.py`, chạy trong `lifespan()`, mỗi lần `uvicorn human_bot.service:app` start):
1. Ghi cảnh báo vào `logs/human_bot.log` (`_warn_if_auth_unconfigured()`) — bản đầu tiên, nhưng owner phản hồi cảnh báo chỉ nằm trong file log thì dễ bỏ lỡ ngay lúc đang nhìn terminal khởi động.
2. **Hỏi xác nhận y/n ngay trên terminal** (`_confirm_startup_or_abort()`) — nếu thiếu bất kỳ biến nào VÀ đang chạy trên một terminal thật có người ngồi gõ lệnh (`sys.stdin.isatty()`), in cảnh báo ra màn hình rồi hỏi "Vẫn tiếp tục khởi động? [y/N]:" — gõ gì khác "y" (kể cả Enter trống hay Ctrl-D) thì **service dừng hẳn, không khởi động, không phục vụ request nào**. Nếu service đang chạy nền không có ai trả lời được (systemd, Docker, `nohup ... &`, CI) thì tự động bỏ qua bước hỏi này — chỉ giữ cảnh báo ghi log, tránh treo service vô thời hạn chờ một câu trả lời sẽ không bao giờ tới.

Việc tự đặt giá trị thật cho 3 biến này trong `.env` production vẫn là thao tác thủ công chủ dự án cần tự làm — 2 lớp nhắc nhở này chỉ đảm bảo không ai vô tình bỏ lỡ việc đó, không tự động hoá việc đặt khoá.

## 4.15. Ghi log & lịch sử hành động (2026-09-04, ghi thêm ra file 2026-09-08)

Mọi lần chạy một hành động — dù từ thao tác tay, từ lịch, hay tự động từ bên B, dù thành công hay thất bại — đều đi qua đúng một điểm ghi log duy nhất trong code, nên không sót trường hợp nào. Có cả log dạng file (`logs/human_bot.log`) lẫn lịch sử có cấu trúc trong SQLite phục vụ trang Báo cáo.

## 4.16. Bộ test tự động đầu tiên cho dự án (2026-09-10)

**Trước đây dự án hoàn toàn không có test tự động nào** — chỉ có 4 script chạy tay (`human_bot/test_run_task.py`, `test_service_api.py`, `test_post_own_profile_media.py`, `test_post_to_group_manual.py`), tất cả đều cần một phiên Facebook thật đang đăng nhập và không có assertion nào — chạy xong phải tự mắt nhìn kết quả. Một đợt rà soát toàn dự án (dùng agent tự động đối chiếu code với `tasks.md`) xác nhận tài liệu tiến độ khớp đúng với code thật, nhưng phát hiện đây là lỗ hổng duy nhất chưa từng được ghi nhận ở đâu.

Đã thêm bộ test bằng `pytest`, tập trung vào **phần logic thuần, không cần trình duyệt hay Facebook thật** — nơi một lỗi âm thầm (tính sai rate-limit, đổi lương sai đơn vị, cấu hình admin không thật sự có hiệu lực) trước đây chỉ phát hiện được khi tự nhìn thấy bài đăng sai trên Facebook:

* `human_bot/safety.py` — toàn bộ toán rate-limit (chặn theo số lượng/ngày/giờ, khoảng cách tối thiểu giữa 2 hành động cùng loại, `ignore_gap` chỉ bỏ qua đúng phần pacing chứ không bao giờ bỏ qua giới hạn số lượng) và phát hiện dấu hiệu bất thường/nội dung đã mất.
* `human_bot/runtime_config.py` — logic merge override từ `/admin/config` với giá trị mặc định trong code, và toàn bộ đường fallback key/model theo nhà cung cấp AI (mục 4.10) vừa thêm.
* `human_bot/content_strategist.py` — mọi quy tắc soạn template (đổi lương qua man/lá/tờ đúng điều kiện, tên visa, gộp dòng "thiếu visa/lương", xử lý danh sách/chuỗi không còn lộ lỗi `['Shizuoka']` từng gặp — mục 4.10) và các nhánh an toàn "rơi về mẫu khi AI lỗi/tắt/thiếu key".
* `human_bot/ai_client.py` — dùng `httpx.MockTransport` (không gọi mạng thật) xác nhận đúng định dạng request cho cả 4 nhà cung cấp AI, để chắc chắn tính năng đa nhà cung cấp mới thêm không âm thầm gửi sai header/URL cho một hãng nào đó.
* `human_bot/daily_limits.py` (mới, 2026-09-11 — xem mục 4.13) — mốc "ngày nghiệp vụ" 2h sáng JST đúng ở 3 ca biên (đúng ranh giới/ngay trước ranh giới/giữa ngày), `can_proceed()` đếm theo ngày nghiệp vụ THẬT SỰ khác rolling window (verify cả 2 chiều: dòng ngay sau mốc 2h sáng có tính, dòng ngay trước mốc không tính), `comments_per_hour` vẫn giữ nguyên rolling window không đổi, `ignore_gap` chỉ bỏ gap chứ không bỏ daily cap.
* `human_bot/data_sync.py` (mới, 2026-09-11 — trước đây chưa có test nào) — `_next_available_post_slot()` (giờ yên tĩnh, gap cùng/khác nhóm), `_next_available_business_day()` (tràn-ngày đúng khi đầy, không tràn khi còn slot — khớp đúng ví dụ owner đưa ra: 5 slot dùng 3 còn 2, cap 3 → đăng 2; ngày tương lai không tính hoạt động thật của hôm nay; điểm rơi sau tràn đúng 2h sáng JST không phải nửa đêm UTC), `_count_scheduled_actions_by_day()` (dùng `monkeypatch` trên `schedule_store` — test quan trọng nhất: 1 task lúc 16:30 UTC, tức 01:30 JST hôm sau TRƯỚC mốc 2h sáng, phải tính đúng vào ngày nghiệp vụ hôm trước chứ không phải ngày UTC thô, đúng ca cách tính cũ từng đếm sai).

**110 test, chạy trong dưới 1 giây, không có test nào đụng vào Facebook thật hay file cấu hình thật** (`runtime_config.json`, `accounts/`, `data_sync_cache/`) — mọi test cần đọc/ghi cấu hình đều được chuyển hướng sang file tạm qua `monkeypatch`, xác nhận lại bằng cách so `md5sum runtime_config.json` trước/sau khi chạy toàn bộ suite (giống hệt nhau). Chạy bằng `pip install -r requirements.txt -r requirements-dev.txt && pytest -q`. (10 trong số đó là `tests/test_service_auth_warning.py`, thêm cùng lúc với tính năng cảnh báo/xác nhận khởi động ở mục 4.14; 1 test khác thêm cùng lúc với việc tách giãn cách post/comment ở mục 4.6; 3 test thêm cùng lúc với nhãn "Nenshuu" và fix giữ nguyên nội dung lịch khi AI lỗi, cùng ở mục 4.10; 29 test — 17 `test_daily_limits.py` + 12 `test_data_sync.py` — thêm cùng lúc với đợt đổi "ngày nghiệp vụ" + tràn-ngày ở mục 4.13, phát hiện và sửa 1 lỗi TRONG chính bộ test lúc viết — datetime giả lập ban đầu có timezone trong khi log thật của `safety.py` luôn ghi naive datetime — không phải bug production; 2 test mới nhất trong `test_data_sync.py` là test hồi quy cho bug `sync_all()` crash mỗi poll ở mục 5 ngay dưới.)

**Vẫn còn thiếu:** chưa test phần đụng tới Playwright/trình duyệt thật (đúng bản chất — cần trình duyệt + tài khoản Facebook thật, không unit-test được theo nghĩa thông thường), và `data_sync.py`'s `sync_all()`/`_water_fill_distribute()` end-to-end (logic chia đều dữ liệu cho nhiều tài khoản) vẫn chưa có test — mới test được các hàm con thuần logic tách riêng.

# 5\. Một số sự cố thực tế đã phát hiện và xử lý trong quá trình test

Phần này liệt kê để cho thấy mức độ test thực tế của dự án — không chỉ chạy thử một lần rồi coi là xong, mà có một quy trình phát hiện lỗi → xác định nguyên nhân gốc → sửa → xác nhận lại bằng chạy thật, lặp lại nhiều lần trong suốt quá trình phát triển:

* **Checkpoint Facebook thật** trên tài khoản `tu_iizuki` ("confirm your identity") — xác nhận đúng bộ dấu hiệu phát hiện bất thường trong code khớp với màn hình thật (mục 4.7).
* **Ảnh gắn nhầm input, báo đăng thành công nhưng ảnh không lên bài** — dẫn tới việc xây lại toàn bộ cơ chế xác minh + chụp ảnh bằng chứng (mục 4.8).
* **"Đói job" nhiều tài khoản:** khi có nhiều tài khoản cùng đồng bộ dữ liệu từ bên B, chỉ tài khoản xử lý đầu tiên mỗi vòng thực sự nhận được job mới — các tài khoản còn lại âm thầm không nhận được gì vì thấy dữ liệu đã bị đánh dấu "đã thấy". Sửa bằng cách gộp lấy dữ liệu 1 lần/vòng rồi chia công bằng cho mọi tài khoản.
* **Lệch múi giờ trong "khung giờ yên tĩnh":** so sánh giờ Nhật Bản người dùng chọn trực tiếp với giờ UTC mà không quy đổi, khiến giờ yên tĩnh bị lệch — chọn 10:00 sáng giờ Nhật có thể vô tình rơi vào khung bị coi là "yên tĩnh".
* **Service sập toàn bộ khi khởi động** nếu một tài khoản active chưa từng đăng nhập (thiếu file phiên đăng nhập) — một tài khoản lỗi kéo sập cả service thay vì chỉ tài khoản đó không khởi động được.
* **Session trình duyệt "chết" không được phát hiện lại** (VD: người dùng tự tay đóng cửa sổ Chrome đang hiển thị) khiến mọi tác vụ sau đó cứ fail liên tục cho tới khi phải khởi động lại cả service.
* **Lỗi cắt cụt nội dung khi sửa bài trong lịch đăng** — ô sửa vô tình dùng lại giá trị đã bị cắt ngắn để hiển thị gọn, làm mất nội dung thật khi lưu.
* **Cấu hình sai chỗ khiến bài lên lịch thủ công không tự đăng** — cổng bật/tắt tự đăng bị đặt nhầm trong mục cấu hình "đồng bộ bên B", khiến người vận hành tìm mãi không thấy trong mục "lịch đăng".
* **Timeout phía client quá ngắn khi test `human_bot/service.py` qua HTTP thật** — lúc xác nhận `GET /health`/`POST /tasks` hoạt động đúng qua HTTP thật (không chỉ gọi hàm trực tiếp), phát hiện thời gian chờ mặc định của client ngắn hơn thời gian đăng bài thật cần (pacing giống người cố tình chậm, có bài mất hơn 60 giây tuỳ độ dài nội dung) — client bị timeout trước khi server kịp trả kết quả dù việc đăng vẫn thành công bình thường ở phía server.
* **`sync_all()` crash âm thầm mỗi chu kỳ poll (2026-09-11)** — owner restart service, đặt chu kỳ đồng bộ 5 phút để test, "không thấy gì xảy ra". Tra log thật thấy `TypeError: can't compare offset-naive and offset-aware datetimes` — `RateLimiter.next_allowed_at()` (`safety.py`) luôn trả naive datetime (mọi timestamp trong log ghi bằng `datetime.utcnow()`, không timezone), trong khi `next_comment_time` ở `data_sync.py` lại aware (`datetime.now(timezone.utc)`) — so sánh bằng `max()` ném lỗi ngay lập tức. Lỗi này thêm vào từ SỚM HƠN trong ngày (đợt "kẹp sàn" comment gap), nhưng "ngủ yên" vì chỉ kích hoạt khi tài khoản đã có ít nhất 1 comment từng đăng thật — `tu_iizuki` hội đủ điều kiện từ lâu trong buổi nên crash ngay khi restart. `service.py`'s vòng lặp poll chỉ log lỗi rồi tiếp tục, không hiển thị gì trên `/admin` — trông y hệt "chạy nhưng không có gì mới" thay vì "đang crash liên tục". Sửa bằng cách chuẩn hoá sang aware UTC trước khi so sánh, thêm 2 test hồi quy khoá chặt hợp đồng "`next_allowed_at()` luôn naive".

# 6\. Đang triển khai / chưa hoàn thiện

* **Content Strategist Agent — đã mở rộng sang cả job đăng nhóm và trả lời ứng viên, đa nhà cung cấp AI (2026-09-10), đã xác nhận sống với Anthropic** (2 ví dụ thật ở mục 4.10) — OpenAI/Gemini/custom vẫn chưa test end-to-end với key thật; vẫn thiếu guardrail chống trùng lặp/từ cấm bằng code (chỉ mới trong prompt gửi AI, riêng độ dài đầu ra thì đã chặn cứng bằng code).
* **Safety Monitor — hành vi #2/#3:** chưa có throttle sớm khi sắp chạm giới hạn, chưa có báo động tự động ra kênh ngoài (Slack/email/Telegram) khi một tài khoản bị tạm dừng.
* **Cơ chế dự phòng khi selector bị Facebook đổi giao diện làm gãy:** mỗi bước hiện chỉ dùng đúng 1 selector đã ghi sẵn — nếu Facebook đổi UI, hành động đó sẽ fail hoàn toàn cho tới khi ghi lại. Phương án dùng AI/LLM "nhìn" trang khi selector gãy đã thiết kế (`human_bot/llm.py`) nhưng **chưa được nối vào luồng chạy thật** ở bất kỳ đâu — cần quyết định có làm hay không, và áp dụng cho hành động nào trước.
* **Chống fingerprint đầy đủ hơn:** user-agent/Client Hints đồng bộ, múi giờ khớp IP thật, và quan trọng nhất — proxy/IP riêng theo từng tài khoản (mục 4.5) — đều chưa làm, chờ quyết định khi cần mở rộng quy mô.
* **Thiết lập môi trường vận hành thật:** khoá API bên B thật, `TASKS_API_KEY` thật, proxy — chưa điền vào cấu hình production.
* **Chọn nhóm theo chủ đề** (bài IT → nhóm IT, bài Tokutei → nhóm Tokutei...) thay vì luôn phát tán vào mọi nhóm đã tham gia — đang cân nhắc thêm.
* **Báo cáo xem theo từng LẦN ĐĂNG (theo job), chưa làm — ghi chú theo yêu cầu owner 2026-09-11:** bảng "Hoạt động gần đây" hiện tại chỉ hiện từng dòng hành động rời rạc (1 dòng/1 nhóm), không có cách nào xem gộp "1 lần đăng job X đã phát vào bao nhiêu nhóm, mỗi nhóm nội dung gì, nhóm nào thành/bại, nội dung gốc trước khi soạn lại là gì". Phần lớn dữ liệu đã có sẵn trong `action_log` (gom theo `source_id`), riêng "nội dung gốc" thì CHƯA lưu vào DB (chỉ có trong file JSON `schedule_store`, không nối ngược lại được vì `action_log` chưa lưu `task_id`) — cần quyết định hướng trước khi làm (xem chi tiết ở tasks.md).

# 7\. Kế hoạch tiếp theo

* Xác nhận sống các điểm còn "chưa xác nhận thật" đã liệt kê ở trên (xác minh đăng bài thành công, selector "Friends" khi chọn đối tượng xem) — riêng dấu hiệu chờ duyệt bài nhóm: bug đã xác nhận bằng bằng chứng thật 2026-09-10, **fix vẫn cần chạy lại thật một lần nữa để xác nhận hoạt động** (mục 4.2).
* Quyết định và triển khai proxy/IP riêng theo tài khoản khi cần mở rộng số lượng tài khoản chạy song song.
* Xem xét kiến trúc đa tiến trình nếu cần chạy nhiều tài khoản trên nhiều máy khác nhau (hiện tại chỉ an toàn với đúng 1 tiến trình).
* Cân nhắc mức giới hạn tần suất đăng bài phù hợp trước khi vận hành thật (hiện đang nới lỏng để thuận tiện test).

# 8\. Nguồn nghiên cứu đã tham khảo

Một phần lý do dự án đưa ra được các quyết định thiết kế cụ thể (mục 4.4-4.6) thay vì đoán mò là nhờ tham khảo trực tiếp các nguồn sau trong quá trình phát triển:

* cside.com — "Catching AI agents' behavioral signals" và "Catching Playwright and browserless bots by the cursor".
* browser-use.com — bài viết về cách hệ thống chống bot phát hiện AI browser agent.
* `ghost-cursor` (thư viện mô phỏng chuột cho Puppeteer/Playwright) và các bản port liên quan.
* Một nghiên cứu học thuật về phát hiện bot qua nhịp gõ phím (keystroke dynamics).
* Các bài viết/kho mã nguồn mở về tự động hoá đăng bài nhóm Facebook và lý do các công cụ đó bị Facebook gắn cờ trong thực tế (rimiti/facebook-automation, ByamB4/fb-group-auto-post, multiplegroupposter.com, roihacks.com).
* Báo cáo thực tế được chia sẻ trong nội bộ dự án về việc tài khoản bị hạn chế lại sau khi resume hoạt động quá sớm — dẫn tới thiết kế cơ chế "hạ nhiệt" ở mục 4.6.

# 9\. Thông tin thêm / lưu ý vận hành

* Tài khoản Facebook dùng cho bot cần đặt giao diện tiếng Anh (English US) trước khi chạy — mọi selector trong code được ghi lại theo giao diện tiếng Anh, tài khoản hiển thị ngôn ngữ khác sẽ khiến hành động timeout ngay bước đầu. Nội dung bài đăng vẫn viết tiếng Việt bình thường, chỉ giao diện Facebook cần là tiếng Anh.
* Tài khoản cần đã tham gia sẵn các nhóm mục tiêu trước khi dùng tính năng đăng nhóm/comment nhóm.
* Dự án dùng Playwright với script cố định — chọn phần tử theo selector, theo đúng thứ tự bước đã ghi lại — chứ không dùng một AI agent kiểu "browser-use" để tự nhìn màn hình và tự quyết định bước tiếp theo mỗi lần chạy (lý do đầy đủ ở mục 1). Hệ quả thực tế: nếu Facebook đổi giao diện, cần ghi lại (Codegen) và cập nhật code cho hành động bị ảnh hưởng — đây chính là lý do cơ chế dự phòng bằng AI ở mục 6 được đặt ra cho tương lai.
