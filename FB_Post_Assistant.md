**BÁO CÁO TIẾN ĐỘ DỰ ÁN**

Hệ thống tự động hoá Facebook cho tuyển dụng lao động Việt Nam tại Nhật Bản (AIAgent\_w\_FB)

*(Cập nhật lần này: 2026-09-09. Bản trước mô tả trạng thái ngày 2026-09-04 —
từ đó tới nay dự án đã đi thêm một quãng đáng kể: đăng nhóm, comment nhóm,
quản lý tài khoản/nhóm/lịch đăng qua web, đồng bộ dữ liệu tự động từ hệ
thống tuyển dụng, và cả một tầng "phòng vệ" nhiều lớp chống bị Facebook
phát hiện là bot — phần lớn nội dung mới trong báo cáo này.)*

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
| Content Strategist Agent (AI viết nội dung khác nhau cho mỗi nhóm) | Hoàn thành **một phần hẹp** — chỉ áp dụng khi 1 tin đăng vào nhiều nhóm cùng lúc |
| Cơ chế dự phòng khi 1 selector bị Facebook đổi giao diện làm gãy | Đã thiết kế (dùng AI/LLM "nhìn" trang), **chưa nối vào luồng chạy thật** |
| Thiết lập môi trường vận hành thật (proxy/IP riêng theo tài khoản, khoá API bên B thật) | Chưa làm — cần trước khi chạy ngoài phạm vi máy cá nhân |

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

## 4.1. Đăng bài lên tường cá nhân

Luồng đầy đủ: mở khung đăng bài, gõ nội dung theo tốc độ/nhịp gõ tự nhiên (mục 4.4), chọn đối tượng xem (Public/Friends/Only me — trước đây bị ép cứng "Only me" cho mọi bài, đã sửa để nhận tham số `audience` xuyên suốt từ API tới giao diện đăng bài), và **xác minh thật** bài đã đăng thành công thay vì đoán (mục 4.8).

## 4.2. Đăng bài vào nhóm — 4 lớp dự phòng

Hạng mục phức tạp nhất của dự án. Một người dùng thật không phải lúc nào cũng vào một nhóm theo đúng một cách — hệ thống mô phỏng đúng điều đó bằng một **chuỗi 4 phương án**, thử lần lượt, dừng ngay khi một phương án xác nhận đúng nhóm:

1. **Lối tắt đã ghim** (Shortcuts ở trang chủ) — nhanh và giống người nhất, nhưng chỉ có nếu tài khoản đó đã ghim sẵn nhóm.
2. **Danh sách "Your groups"** — vào tab Groups → "Your groups" (nhãn thật của giao diện tiếng Anh — bản nháp đầu tiên đoán nhầm là "Groups you've joined", đã sửa lại sau khi đối chiếu giao diện thật), dò tìm đúng nhóm trong danh sách đã tham gia.
3. **Tìm kiếm Facebook** — gõ tên nhóm vào ô tìm kiếm, lọc theo "My groups", chọn đúng kết quả. Đây là lớp dễ vỡ nhất (thứ hạng kết quả có thể đổi, nhiều nhóm trùng tên).
4. **Vào thẳng bằng URL nhóm** — phương án bảo đảm luôn vào được, luôn kèm `referer` tường minh thay vì để trống.

**Vì sao phải làm cả 4 lớp thay vì chỉ dùng URL trực tiếp (đơn giản hơn nhiều):** phiên bản thiết kế đầu tiên từng đề xuất chỉ dùng lớp 4 cho gọn. Chủ dự án đã chỉ ra một điểm quan trọng: làm *đúng một cách*, *y hệt nhau*, ở *mọi lần* đăng nhóm — chính bản thân sự lặp lại đó là một dấu hiệu bất thường, vì người dùng thật không bao giờ vào nhóm theo đúng một kiểu mỗi lần.

**Cách chọn đúng nhóm không dựa vào tên hiển thị.** Tên nhóm hiển thị trên giao diện Facebook có thể bị cắt ngắn ("CHUYỂN VIỆC KỸ SƯ TẠI NH…") hoặc trùng giữa nhiều nhóm — nên việc khớp nhóm dựa vào **ID/slug** lấy thẳng từ đường dẫn (`href`) của link, theo đúng yêu cầu cụ thể của chủ dự án ("dò ID nhóm trùng với ID nhóm được yêu cầu đăng"). Sau mỗi lần bấm vào một nhóm ở lớp 1-3, hệ thống còn kiểm tra lại URL trang vừa vào để xác nhận lần nữa — nếu sai, tự động rơi xuống lớp kế tiếp thay vì lỡ đăng nhầm nhóm.

**Hai lỗi thật phát hiện trong lúc test lớp 1 (Lối tắt):** có lúc bấm vào đúng nhóm rồi lại tự thoát ra ngoài, và có lúc thấy nhóm hiện ở lối tắt nhưng không bấm được. Cả hai đã được xác định nguyên nhân và khắc phục trong lúc ghi lại Codegen.

**Vẫn còn một điểm chưa xác minh thật:** dấu hiệu "bài đang chờ duyệt" (khi nhóm bật chế độ duyệt bài trước khi hiển thị) mới được viết theo suy luận hợp lý, chưa test với một nhóm thật có bật duyệt bài — Facebook không công khai tài liệu về dấu hiệu DOM chính xác cho trạng thái này, nên cần tự quan sát trực tiếp khi có dịp.

## 4.3. Bình luận vào bài trong nhóm (`comment_on_group_post`)

Ghi Codegen và xác nhận sống trên đúng nhóm tài khoản đã tham gia thật, comment hiện lên sau khi tải lại trang để xác nhận. Có thêm bước kiểm tra lại dấu hiệu bất thường khi bước xác minh gửi comment bị timeout — cùng nguyên tắc với đăng bài (mục 4.8). Selector khung nhập cũng đã mở rộng để khớp cả bài dạng Hỏi-Đáp (Q&A) của Facebook, hiển thị "Write an answer…" thay vì "Write a comment…" như bài thường — phát hiện qua một lần chạy thật bị timeout 30 giây trước khi sửa.

**3 hành động còn lại** (`comment_on_friend_post`, `like_post`, `read_recent_comments`) **được chủ dự án chủ động yêu cầu tạm ngưng** — không phải vì vướng lỗi kỹ thuật, mà vì chưa cần cho nhu cầu hiện tại. Sẽ làm lại nếu sau này thật sự cần.

## 4.4. Mô phỏng hành vi con người — vì sao phải làm kỹ đến vậy

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

## 4.5. Đa dạng hoá "dấu vân tay" trình duyệt (fingerprint) theo từng tài khoản — đã làm gì, và cố tình CHƯA làm gì

Mỗi tài khoản Facebook đã chạy trên một tiến trình Chromium riêng (không share trình duyệt giữa các tài khoản), nhưng ban đầu mọi tiến trình đều dùng chung **y hệt** một cấu hình màn hình mặc định — nghĩa là dưới góc nhìn của Facebook, mọi tài khoản vẫn "trông giống" cùng một loại thiết bị. Đã khắc phục bằng cách băm `account_id` (SHA256) để chọn ra một cấu hình cố định trong số 5 cấu hình màn hình phổ biến ngoài đời thật (kết hợp độ phân giải + tỉ lệ scale phù hợp thực tế, VD: MacBook 1440x900 thường đi kèm @2x, màn ngoài 1920x1080 thường @1x) — **ổn định qua mọi lần restart**, không đổi ngẫu nhiên mỗi lần mở, vì đổi liên tục còn là tín hiệu bot rõ ràng hơn cả việc dùng chung một cấu hình.

**Ba việc liên quan cố tình CHƯA làm, mỗi việc đều có lý do kỹ thuật cụ thể, không phải bỏ sót:**

1. **User-agent:** đổi riêng `navigator.userAgent` mà không đổi luôn "Client Hints" thật của Chromium (`Sec-CH-UA-*`, `navigator.userAgentData`) sẽ tạo ra sự sai lệch giữa 2 nguồn — bản thân sự sai lệch đó là tín hiệu bot còn rõ hơn cả dùng UA mặc định giống nhau ở mọi tài khoản. Muốn làm đúng cần tắt hẳn Client Hints hoặc có một lớp "stealth-patch" mà dự án hiện chưa có.
2. **Múi giờ/vị trí địa lý:** cần khớp với địa chỉ IP thật (qua proxy) của từng tài khoản — nếu chưa có proxy riêng theo tài khoản mà đổi múi giờ thì múi giờ lệch với IP còn là tín hiệu tệ hơn dùng chung múi giờ.
3. **Proxy/IP riêng theo tài khoản — chưa làm, và đây mới là hướng cải thiện có tác động thực tế lớn nhất nếu mở rộng quy mô nhiều tài khoản** (nhiều tài khoản cùng chạy chung 1 IP nhà/VPS là tín hiệu liên kết mạnh hơn nhiều so với sự khác biệt về trình duyệt) — nhưng tốn phí mua proxy nên chưa triển khai, chờ quyết định khi cần scale.

Cũng chưa dùng thư viện `playwright-stealth` hay tương đương.

## 4.6. Giới hạn tần suất hành động (rate limiting), phân theo "tuổi" tài khoản, và "hạ nhiệt" sau khi kích hoạt lại

**Vì sao cần:** Điều khoản sử dụng của Facebook cấm hành vi tự động thay thế người dùng thật, và hệ thống chống lạm dụng của họ đặc biệt chú ý tới *khuôn mẫu lặp lại*: tốc độ đều đặn, hoạt động 24/24, khoảng cách giữa các lần thao tác đều tăm tắp — đây là tín hiệu bot rõ hơn bất kỳ một hành động đơn lẻ nào.

**Sự cố thật đã xảy ra khiến việc này được siết lại:** khoảng nghỉ tối thiểu giữa 2 hành động (`min_delay_seconds`/`max_delay_seconds`) ban đầu chỉ được *khai báo* trong code nhưng **chưa từng được thực sự gọi tới ở đâu** — một lỗ hổng dead-code. Sau khi tham khảo thêm báo cáo bên ngoài cho rằng ngay cả 10-20 phút giữa các hành động Facebook cũng có thể bị coi là tự động hoá, khoảng nghỉ mặc định được nâng lên **1-2 giờ** và **thật sự được enforce**: nếu chưa đủ thời gian, hệ thống **từ chối thẳng tác vụ ngay lập tức** (không chờ/xếp hàng) thay vì cố chạy.

Khoảng nghỉ này được tính **riêng theo từng loại hành động** (đăng bài / comment / thả cảm xúc) — trước đó dùng chung 1 đồng hồ cho cả tài khoản, nghĩa là 1 comment vừa chạy xong sẽ vô tình chặn luôn 1 bài đăng ngay sau đó dù chúng thuộc 2 hạn mức hoàn toàn khác nhau.

**5 mức giới hạn theo "tuổi" tài khoản Facebook** (dưới 1 / 3 / 6 / 12 tháng, trên 12 tháng) — chọn được ngay khi đăng ký tài khoản, hoặc áp dụng sau bằng nút "quick-apply" khi tài khoản đã "lớn tuổi" hơn — thay vì phải gõ tay 6 con số cho từng tài khoản mỗi lần cần nới/siết.

**"Hạ nhiệt" tự động sau khi kích hoạt lại một tài khoản bị tạm dừng** — bổ sung sau khi tham khảo một báo cáo thực tế được chia sẻ trong một nhóm về vận hành Facebook: một người vận hành cố tình im lặng thêm 1 tuần sau khi hạn chế được gỡ, báo cáo 3 tháng sạch sẽ tiếp theo; một người khác đăng chéo bài ngay khi hạn chế vừa gỡ thì bị hạn chế lại ngay lập tức. Vì vậy, bấm "Kích hoạt lại" không đưa tài khoản về tốc độ đầy đủ ngay, mà chạy ở giới hạn thấp hơn trong một số ngày cấu hình được, rồi mới tự phục hồi về mức trước khi bị tạm dừng.

## 4.7. Tự phát hiện tài khoản bị Facebook hạn chế và tự tạm dừng

**Sự cố thật xác nhận hệ thống hoạt động đúng:** tài khoản `tu_iizuki` từng bị Facebook đưa ra màn hình "confirm your identity" thật (đang thao tác tay ghi Codegen, không phải lúc chạy tự động) — mức độ trung bình, chỉ chặn một số hành động, xác minh qua app Facebook trên điện thoại là xong. Đây là lần đầu tiên bộ dấu hiệu phát hiện bất thường trong code được đối chiếu với ảnh chụp màn hình thật thay vì chỉ dựa vào suy đoán — cả 2 cụm chữ đã có sẵn ("confirm your identity", "unusual activity") khớp đúng y hệt màn hình thật, và một cụm thứ 3 ("certain actions have been restricted") được thêm vào để chắc chắn hơn.

**Cơ chế:** khi phát hiện bất kỳ dấu hiệu nào trong danh sách trên (cả dạng chữ lẫn dạng cấu trúc như captcha, bị đá về trang login dù phiên vẫn còn hợp lệ), hệ thống dừng ngay tác vụ đang chạy — **không thử lại, không cố tự giải captcha hay xác minh danh tính** — và chuyển tài khoản đó sang trạng thái Tạm dừng **bền vững qua cả việc restart service**, chặn mọi tác vụ tiếp theo ngay từ đầu cho tới khi một người vận hành thật vào `/admin/accounts` bấm "Kích hoạt lại".

**Giới hạn đã biết, chủ đích không sửa:** cơ chế tự tạm dừng chỉ hoạt động khi chạy qua pipeline tự động — lúc thao tác tay bằng Playwright Codegen (như sự cố `tu_iizuki` trên), hệ thống không hề biết tài khoản vừa bị cảnh báo. Từng cân nhắc thêm cảnh báo vào tài liệu hướng dẫn ghi Codegen để nhắc tự tay tạm dừng tài khoản trước khi ghi, nhưng chủ dự án quyết định không cần thiết — được ghi lại như một rủi ro đã biết và chấp nhận, không phải lỗ hổng cần vá ngay.

**Còn thiếu so với thiết kế đầy đủ của Safety Monitor:** hành vi #2 (chủ động giảm tốc khi sắp chạm giới hạn, không đợi tới lúc thất bại hẳn) và hành vi #3 (báo động ra ngoài qua Slack/email/Telegram khi có tài khoản bị tạm dừng — hiện tại chỉ biết được khi tự vào `/admin` xem banner cảnh báo).

## 4.8. Xác minh bài đăng thật sự thành công \+ chụp ảnh bằng chứng mỗi lần chạy

**Vì sao cần làm lại:** trước đây, sau khi bấm Post, hệ thống chỉ đợi cứng 2 giây rồi luôn báo thành công — không kiểm tra gì cả. Một sự cố thật đã xảy ra đúng kiểu lỗi này: ảnh bị gắn nhầm vào input ẩn khác, hệ thống vẫn báo thành công dù ảnh không hề xuất hiện trên bài đăng thật.

**Đã sửa tận gốc:** sau khi bấm Post, hệ thống chủ động đợi cho tới khi nút "Post" **thật sự biến mất khỏi màn hình** (dấu hiệu Facebook đã nhận submit), tối đa 15 giây — hết giờ mà nút vẫn còn thì báo thất bại thật, không đoán mò. Bước đính kèm ảnh cũng đợi cho tới khi ảnh thumbnail thật sự hiện ra trong khung soạn trước khi tiếp tục, bắt lỗi ngay tại thời điểm xảy ra thay vì âm thầm đăng bài không kèm ảnh.

**Chụp ảnh bằng chứng mọi lần chạy — cả thành công lẫn thất bại** — lưu theo từng tài khoản, tự dọn sau 30 ngày, xem trực tiếp được từ trang Báo cáo (`/admin/reports`).

**Còn cần xác nhận sống:** 2 cơ chế xác minh trên (nút Post biến mất, ảnh thumbnail xuất hiện) được viết theo suy luận hợp lý từ cấu trúc trang đã biết, nhưng chưa chạy thử trực tiếp đủ nhiều lần trên Facebook thật để loại trừ khả năng báo "thất bại" giả cho một bài thực ra đã đăng thành công.

## 4.9. Đính kèm ảnh/video khi đăng bài

Tự động đính kèm 1 ảnh cho mỗi bài đăng (cả tường cá nhân lẫn nhóm), bật/tắt được qua trang quản trị (mặc định bật). Nếu bài đăng có ảnh riêng do bên B cung cấp thì luôn ưu tiên dùng ảnh đó; nếu không, hệ thống tự chọn ngẫu nhiên 1 ảnh từ kho ảnh mẫu có sẵn trong dự án. Playwright không thao tác hộp thoại chọn file của hệ điều hành (không làm được), mà chặn ngay cú click và gán file trực tiếp vào input ẩn — cách làm chuẩn của Playwright cho việc upload file.

## 4.10. AI viết nội dung khác nhau khi 1 tin đăng vào nhiều nhóm (Content Strategist Agent — bản đầu tiên)

**Vì sao cần AI ở đúng chỗ này:** nghiên cứu về cách các công cụ tự động hoá nhóm Facebook bị phát hiện chỉ ra rằng **nội dung giống hệt nhau đăng vào nhiều nhóm trong thời gian ngắn là dấu hiệu bị gắn cờ nhanh nhất**. Vì hệ thống thật sự phát tán một tin tuyển dụng vào mọi nhóm mà tài khoản đã tham gia (không phải giả định), việc AI viết lại nội dung khác nhau cho mỗi nhóm là **yêu cầu bắt buộc**, không phải tính năng "cho đẹp".

Theo đúng phạm vi chủ dự án yêu cầu: chỉ áp dụng cho trường hợp **một tin đăng vào nhiều nhóm cùng lúc**, gọi thẳng Anthropic API — nếu không có API key hoặc gọi lỗi thì tự rơi về mẫu (template) cũ, không văng lỗi, không chặn lịch đăng. **Chưa làm** cho đăng tường cá nhân (gõ tay, đăng 1 lần, không cần biến tấu — theo đúng yêu cầu chủ dự án) và **chưa làm** cho nội dung trả lời ứng viên (vẫn dùng mẫu, tuy đã có 10 biến thể ngẫu nhiên để tránh lặp y hệt chữ). Cũng còn thiếu so với kế hoạch gốc: một bộ chuẩn hoá tín hiệu đầu vào (`normalize_signal()`), và các "guardrail" chống trùng lặp/từ cấm bằng code (hiện mới chỉ có trong system prompt gửi cho AI, chưa có lớp kiểm tra cứng bằng code).

## 4.11. Quản lý tài khoản, nhóm, lịch đăng, cấu hình và báo cáo qua Admin UI

Đã viết lại hoàn toàn từ một trang "đăng trực tiếp" đơn giản (không khác gì tự vào Facebook đăng tay) thành một hệ thống quản trị đầy đủ:

* **Quản lý tài khoản** (`/admin/accounts`): đăng ký/Tạm dừng/Kích hoạt lại/Xoá — áp dụng được cho mọi tài khoản kể cả loại khai báo sẵn trong code; chỉnh giới hạn tốc độ riêng từng tài khoản; cảnh báo ngay trên dashboard nếu có tài khoản đang Tạm dừng.
* **Soạn & lên lịch đăng** (`/admin/post` → `/admin/schedule`): **mọi bài đều phải qua bước lịch đăng để duyệt trước khi thật sự chạy** — không còn nút "đăng ngay lập tức" nào bỏ qua bước này, kể cả muốn đăng ngay cũng chỉ là để trống giờ rồi bấm "Đăng ngay" ở trang lịch. Hỗ trợ nhiều khối nội dung khác nhau cho nhiều tập nhóm khác nhau trong cùng một lượt soạn. Trang lịch có bộ lọc, phân trang, hiển thị giờ theo múi giờ Nhật Bản, cảnh báo ngay trên từng dòng nếu bài đang bị chặn bởi rate-limit.
* **Quản lý nhóm** (`/admin/groups`): nhập/sửa/xoá danh sách nhóm đã tham gia theo từng tài khoản, không cần sửa code.
* **Báo cáo** (`/admin/reports`): tổng quan nhanh (tổng số/thành công/thất bại/tỉ lệ/số tài khoản hoạt động), lọc theo khoảng thời gian, xem ảnh chụp bằng chứng từng lần chạy.
* **Cấu hình hành vi** (`/admin/config`): chỉnh mọi tham số mô phỏng con người, rate-limit, đồng bộ dữ liệu bên B — có hiệu lực ngay, không cần sửa `.env`/khởi động lại service.

## 4.12. Đồng bộ dữ liệu tự động từ hệ thống tuyển dụng (bên B)

Một vòng lặp nền tự động gọi API của bên B để lấy tin tuyển dụng mới (→ lên lịch đăng nhóm) và ứng viên mới (→ lên lịch trả lời), tự chống trùng theo ngày, tự giãn cách thời gian đăng ngẫu nhiên (không đăng dồn cục), và **chia đều công bằng** dữ liệu mới cho mọi tài khoản đang hoạt động thay vì chỉ tài khoản xử lý đầu tiên mỗi vòng nhận được (một lỗi thật đã phát hiện và sửa — xem mục 5). Có "khung giờ yên tĩnh" để không đăng vào ban đêm theo giờ Nhật Bản. **Cổng an toàn tự đăng (`auto_fire_enabled`) mặc định tắt** — bộ đồng bộ vẫn lấy dữ liệu/lên lịch bình thường, nhưng sẽ không tự bấm đăng lên Facebook cho tới khi chủ động bật cổng này; trong lúc chờ, có thể đăng thủ công từng bài từ trang lịch.

## 4.13. Bảo mật

`POST /tasks` (API cho n8n/bên ngoài gọi vào) yêu cầu header `X-API-Key` khi đã đặt khoá trong cấu hình, so sánh bằng phương pháp an toàn chống timing attack (`secrets.compare_digest`). Trang quản trị hỗ trợ HTTP Basic Auth khi chạy ở nơi không phải máy cá nhân. **Chưa đặt khoá thật trong môi trường production** — cần làm trước khi mở các cổng này ra ngoài phạm vi máy/mạng nội bộ.

## 4.14. Ghi log & lịch sử hành động

Mọi lần chạy một hành động — dù từ thao tác tay, từ lịch, hay tự động từ bên B, dù thành công hay thất bại — đều đi qua đúng một điểm ghi log duy nhất trong code, nên không sót trường hợp nào. Có cả log dạng file (`logs/human_bot.log`) lẫn lịch sử có cấu trúc trong SQLite phục vụ trang Báo cáo.

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

# 6\. Đang triển khai / chưa hoàn thiện

* **Content Strategist Agent — mở rộng phạm vi:** hiện chỉ áp dụng cho đăng nhóm đa tài khoản; chưa mở rộng sang trả lời ứng viên và chưa có lớp guardrail bằng code (chỉ mới trong prompt gửi AI).
* **Safety Monitor — hành vi #2/#3:** chưa có throttle sớm khi sắp chạm giới hạn, chưa có báo động tự động ra kênh ngoài (Slack/email/Telegram) khi một tài khoản bị tạm dừng.
* **Cơ chế dự phòng khi selector bị Facebook đổi giao diện làm gãy:** mỗi bước hiện chỉ dùng đúng 1 selector đã ghi sẵn — nếu Facebook đổi UI, hành động đó sẽ fail hoàn toàn cho tới khi ghi lại. Phương án dùng AI/LLM "nhìn" trang khi selector gãy đã thiết kế (`human_bot/llm.py`) nhưng **chưa được nối vào luồng chạy thật** ở bất kỳ đâu — cần quyết định có làm hay không, và áp dụng cho hành động nào trước.
* **Chống fingerprint đầy đủ hơn:** user-agent/Client Hints đồng bộ, múi giờ khớp IP thật, và quan trọng nhất — proxy/IP riêng theo từng tài khoản (mục 4.5) — đều chưa làm, chờ quyết định khi cần mở rộng quy mô.
* **Thiết lập môi trường vận hành thật:** khoá API bên B thật, `TASKS_API_KEY` thật, proxy — chưa điền vào cấu hình production.
* **Chọn nhóm theo chủ đề** (bài IT → nhóm IT, bài Tokutei → nhóm Tokutei...) thay vì luôn phát tán vào mọi nhóm đã tham gia — đang cân nhắc thêm.

# 7\. Kế hoạch tiếp theo

* Xác nhận sống các điểm còn "chưa xác nhận thật" đã liệt kê ở trên (xác minh đăng bài thành công, dấu hiệu chờ duyệt bài nhóm, selector "Friends" khi chọn đối tượng xem).
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
