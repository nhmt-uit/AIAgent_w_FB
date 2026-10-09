**BÁO CÁO DỰ ÁN — DÀNH CHO NGƯỜI CHƯA BIẾT GÌ VỀ DỰ ÁN**

Trợ lý tự động đăng tin tuyển dụng lên Facebook (AIAgent_w_FB)

*(Cập nhật lần này: 2026-09-17. File này viết lại hoàn toàn theo hướng dễ đọc, không
dùng từ chuyên ngành, có dòng thời gian theo tuần. Nếu cần xem chi tiết kỹ thuật
từng dòng code/số liệu test cho đội kỹ thuật, xem file `tasks.md` — nơi đó ghi đầy
đủ hơn nhiều)*

---

# 1. Dự án này làm gì?

Công ty tuyển lao động Việt Nam sang Nhật Bản. Hằng ngày có rất nhiều tin tuyển
dụng mới và rất nhiều ứng viên cần được liên hệ. Trước đây việc đăng tin lên các
hội nhóm Facebook và trả lời bình luận của ứng viên phải làm bằng tay — tốn thời
gian và dễ bỏ sót.

Dự án này xây dựng một **"nhân viên ảo"** tự động làm 3 việc trên Facebook:

1. **Đăng tin tuyển dụng vào các hội nhóm Facebook** — tự lấy tin mới từ hệ thống
   tuyển dụng nội bộ (gọi tắt là "bên B"), tự soạn nội dung và tự đăng.
2. **Bình luận trả lời bài đăng của ứng viên** trong các hội nhóm.
3. **Đăng bài lên tường Facebook cá nhân** khi cần.

Mọi việc đều có con người (chủ dự án, gọi tắt "owner") có thể xem lại lịch đăng trước —
hệ thống có thể bật/tắt tự động đăng, xem bài viết đã lên lịch tại phần "Lịch đăng".

**Vì sao khó hơn tưởng tượng?** Facebook có hệ thống tự động phát hiện và khoá
tài khoản có hành vi giống "bot" (tự động hoá). Nên phần lớn công sức của dự án
không chỉ là "bấm nút đăng bài", mà là làm sao để hành vi của "nhân viên ảo" này
giống một người thật đang gõ bàn phím và di chuột — từ đó tránh bị Facebook khoá
tài khoản của công ty.

---

# 2. Hệ thống hoạt động như thế nào? (nói đơn giản)

Hãy hình dung một dây chuyền 4 bước:

1. **Lấy dữ liệu**: cứ khoảng 15-20 phút (tuỳ cài đặt), hệ thống gọi đến bên B "có tin tuyển
   dụng mới hay ứng viên mới nào không?".
2. **Soạn nội dung**: một trợ lý AI viết lại nội dung tin tuyển dụng cho phù hợp
   để đăng lên từng nhóm (không đăng y hệt một câu ở mọi nhóm — trông sẽ giống
   máy đăng).
3. **Xếp lịch đăng**: hệ thống tự tính giờ đăng hợp lý (không đăng dồn dập, có
   nghỉ giữa các lần đăng, tôn trọng giờ giấc, không vượt quá số lượng cho phép
   mỗi ngày) rồi đưa vào "hàng chờ" để owner xem qua.
4. **Thực thi**: đến đúng giờ, hệ thống tự mở trình duyệt, giả lập một người
   dùng thật (gõ chữ có tốc độ tự nhiên, di chuột theo đường cong, dừng lại "đọc
   bài" trước khi đăng...) rồi đăng bài / bình luận thật lên Facebook, chụp lại
   ảnh màn hình làm bằng chứng và ghi log.

Song song đó có một bộ phận riêng chuyên **"canh chừng an toàn tài khoản"**: nếu
phát hiện Facebook đang cảnh báo hay hạn chế một tài khoản, hệ thống tự tạm dừng
ngay tài khoản đó, và khi tài khoản được kích hoạt lại thì tự động cho chạy "chậm
lại" một thời gian trước khi trở lại tốc độ bình thường.

Toàn bộ được quản lý qua một **trang web quản trị nội bộ** — nơi có thể xem/sửa
lịch đăng, quản lý tài khoản, xem báo cáo thành công/thất bại, bật tắt các tính
năng.

---

# 3. Đã làm được đến đâu? (tóm tắt bằng lời)

✅ **Đã hoàn thành và đang chạy thật:**
- Tự đăng bài vào hội nhóm Facebook, tự bình luận trả lời ứng viên.
- Tự lấy tin tuyển dụng/ứng viên mới từ bên B, không cần nhập tay.
- AI tự soạn/viết lại nội dung bài đăng và câu trả lời, viết vào đúng lúc sắp đăng
  (không viết trước rồi để lâu, tránh nội dung "cũ" khi bài lên).
- Giả lập hành vi người dùng thật (gõ chữ, di chuột, cuộn trang, nghỉ giữa các lần
  thao tác) để giảm rủi ro bị Facebook phát hiện.
- Giới hạn tốc độ đăng bài theo "độ tuổi" của tài khoản (tài khoản mới tạo được
  đăng ít hơn, giới hạn nới dần theo thời gian).
- Tự phát hiện tài khoản bị Facebook cảnh báo/hạn chế và tự tạm dừng ngay.
- Trang quản trị web đầy đủ: quản lý tài khoản, nhóm, lịch đăng, báo cáo.
- Có gần 200 bài kiểm tra tự động để đảm bảo các quy tắc trên luôn đúng, không bị
  hỏng ngầm khi sửa code sau này.

🔜 **Chưa làm / đang cân nhắc:**
- Kênh báo động tự động qua Telegram đã làm xong (2026-10-05, xem Tuần 5 ở
  mục 4) — chỉ còn thiếu owner cung cấp 1 bot Telegram thật để thử gửi/nhận
  tin sống lần cuối trước khi coi là hoàn tất 100%.
- Chưa thuê IP/proxy riêng cho từng tài khoản Facebook (khi mở rộng quy mô nhiều
  tài khoản, đây sẽ là việc quan trọng để tránh bị Facebook liên kết các tài khoản
  với nhau).
- Có một phương án dự phòng dùng AI để "nhìn" và tự thao tác khi giao diện Facebook
  đổi khác — đã thiết kế nhưng chưa lắp vào để chạy thật.
- Chưa nối vào quy trình chạy tự động hoàn chỉnh (n8n) theo lịch/hoặc theo tín hiệu
  từ bên B.

---

# 4. Nhật ký tiến độ theo tuần

## Tuần 1 (02/09 – 04/09): Xây nền móng

Đây là tuần khởi đầu — dựng bộ khung cho toàn bộ hệ thống.

- Xây dựng được khả năng đăng bài lên tường cá nhân và đăng bài vào hội nhóm
  Facebook một cách tự động, có mô phỏng thao tác người dùng thật (gõ chữ, di
  chuột, dừng đọc lại trước khi đăng).
- Vì vào một hội nhóm không phải lúc nào cũng theo đúng 1 cách (người dùng thật có
  lúc bấm lối tắt, có lúc tìm kiếm, có lúc vào thẳng link) — hệ thống được thiết kế
  thử nhiều cách vào nhóm khác nhau, giống hành vi thật, thay vì luôn đi đúng 1 con
  đường (dễ bị nghi ngờ là máy).
- Dựng trang quản trị web đầu tiên: đăng bài, xếp lịch, xem báo cáo.
- Bắt đầu có cơ chế phát hiện khi tài khoản bị Facebook cảnh báo và tự tạm dừng.
- Thêm bước "xác minh bài đã đăng thành công thật hay chưa" (chứ không đoán), kèm
  chụp ảnh làm bằng chứng cho mỗi lần đăng.

## Tuần 2 (07/09 – 12/09): An toàn tài khoản, tự lấy dữ liệu, AI viết bài

- Bắt đầu tự động lấy tin tuyển dụng và ứng viên mới từ hệ thống bên B, không cần
  ai nhập tay.
- Hoàn thiện tính năng tự động bình luận trả lời ứng viên trong nhóm.
- Xây cơ chế "giới hạn tốc độ đăng bài" thật sự có hiệu lực — trước đó giới hạn
  này có khai báo nhưng **chưa từng được áp dụng thật** (một lỗ hổng được phát
  hiện và vá ngay). Từ đây, khoảng nghỉ tối thiểu giữa 2 lần đăng được nâng lên
  1-2 tiếng và luôn được tôn trọng.
- Thêm cơ chế "hạ nhiệt" đầu tiên: tài khoản vừa được kích hoạt lại sau khi tạm
  dừng sẽ tự chạy chậm hơn bình thường một thời gian.
- Phát hiện và sửa một số lỗi khiến việc chia tin cho nhiều tài khoản bị "đói"
  (một số tài khoản không bao giờ nhận được việc), và lỗi tính giờ lệch múi giờ
  Nhật Bản.
- Thêm khả năng đăng nhập tài khoản Facebook mới ngay trên trang web (trước đó
  phải chạy lệnh dòng lệnh thủ công).
- Cho mỗi tài khoản Facebook một cấu hình trình duyệt hơi khác nhau (kích thước
  màn hình, độ phân giải) để không "trông giống hệt nhau" dưới góc nhìn của
  Facebook.
- AI được giao viết/viết lại nội dung tin tuyển dụng và câu trả lời ứng viên,
  đúng vào lúc sắp đăng thật (không soạn trước rồi để cũ). Hỗ trợ nhiều nhà cung
  cấp AI khác nhau, có nút bật/tắt riêng. Đã thử thành công với AI thật của
  Anthropic.
- Viết bộ kiểm tra tự động đầu tiên cho dự án (gần 80 bài kiểm tra) để đảm bảo
  các quy tắc quan trọng (giới hạn tốc độ, nội dung AI...) luôn đúng.
- Phát hiện và sửa một loạt lỗi thật quan trọng, ví dụ:
  - Giới hạn tốc độ đăng bài và bình luận trước đó dùng chung một "đồng hồ" — dẫn
    tới việc không thể nào nhét đủ số lượng bình luận cho phép trong 1 ngày vì bị
    đếm gộp nhầm với bài đăng.
  - Một hội nhóm Facebook bật chế độ "cần admin nhóm duyệt bài" nhưng hệ thống lại
    không đọc đúng thông báo đó, coi bài là "đã đăng xong" trong khi thực ra mới ở
    trạng thái chờ duyệt.
  - Hệ thống tự dừng chạy (crash) mỗi lần lấy dữ liệu mới, do một phép so sánh giờ
    bị lỗi kỹ thuật — sửa xong hệ thống chạy ổn định trở lại 24/7.
- Cải thiện trang quản trị: phân trang gọn hơn, báo cáo tách theo từng tin tuyển
  dụng / từng ứng viên, thêm nút "Đăng lại" khi có bài lỡ bị lỗi.

## Tuần 3 (14/09 – 23/09): Ưu tiên tin trả tiền + dọn hàng loạt lỗi thật

Đây là tuần tập trung rất nhiều vào việc rà soát kỹ và sửa các lỗi thật phát sinh
khi hệ thống đã chạy được một thời gian — chủ dự án trực tiếp phát hiện phần lớn
qua việc quan sát dữ liệu thật hằng ngày.

- **Không tự đăng bài "quá hạn" nếu hệ thống từng bị tắt một thời gian.** Trước
  đây nếu server tắt rồi bật lại, các bài lỡ giờ đăng có thể bị đăng dồn dập ngay
  lúc bật lại. Giờ những bài đó được đưa vào một danh sách riêng để owner tự xem
  và quyết định (đăng lại giờ mới, để hệ thống tự tìm giờ trống, hoặc xoá), thay
  vì tự động đăng.
- **Sửa lỗi đăng vượt quá số lượng cho phép mỗi ngày**, xảy ra khi một bài đăng
  vào nhiều nhóm bị "trôi" sang ngày khác giữa chừng mà không ai kiểm tra lại hạn
  mức của ngày đó.
- **Thêm yếu tố ngẫu nhiên khi chọn nhóm để đăng** — theo đúng yêu cầu rõ ràng của
  chủ dự án — để tránh việc lúc nào cũng đăng vào đúng một tổ hợp nhóm giống hệt
  nhau (dễ bị nghi ngờ là máy), đồng thời vẫn đảm bảo nhóm nào lâu chưa được đăng
  sẽ được ưu tiên trước.
- **Ưu tiên các tin tuyển dụng "trả tiền" (sponsored)**: bên B thêm tính năng đánh
  dấu một số tin là tin trả tiền cần đăng gấp và có hạn dùng. Hệ thống được dạy để
  luôn ưu tiên đăng các tin này trước (nhưng vẫn không vượt quá giới hạn an toàn
  mỗi ngày), tự bỏ qua tin đã hết hạn, và chia đều việc cho nhiều tài khoản thay vì
  dồn hết vào một tài khoản. Có thể chọn một số tài khoản chỉ chuyên đăng loại tin
  này. (Tính năng đã làm xong và kiểm tra kỹ, nhưng chưa chạy được với dữ liệu
  thật vì bên B chưa cập nhật xong phần của họ.)
- **Sửa lỗi hiển thị lịch đăng bị đảo thứ tự** — khi dời một bài quá hạn sang
  ngày khác, bài đó lại hiện lên đầu danh sách thay vì đúng vị trí theo ngày mới.
- **Sửa 2 lỗi khiến việc trả lời bình luận bị nhầm lẫn:**
  - Do một lỗi kỹ thuật, hệ thống bị "kẹt" và cứ lấy đi lấy lại đúng một khoảng dữ
    liệu cũ suốt 2 ngày liền — hậu quả là ít nhất 3 ứng viên bị nhận bình luận
    trùng lặp. Đã tìm ra nguyên nhân, sửa tận gốc, và dọn lại dữ liệu bị ảnh hưởng.
  - Một lỗi khác (may mắn chưa gây hậu quả) khiến tin tuyển dụng và ứng viên có
    cùng một mã số bị nhầm lẫn với nhau trong bộ nhớ "đã xử lý" của hệ thống — đã
    sửa để 2 loại luôn được phân biệt rõ ràng.
  - Nếu có cửa sổ chat Messenger đang mở trên màn hình đúng lúc hệ thống đang thao
    tác, có 2 trường hợp bị lỗi/click nhầm — hệ thống giờ tự đóng các cửa sổ chat
    trước khi đăng bài/bình luận.
- **Sửa lỗi giao diện web**: ô chọn giờ đăng bị hiện trống khi chuyển qua lại giữa
  các tab trên trang lịch đăng — nguyên nhân hoá ra là một dòng code đã bị lỗi từ
  rất lâu (một dòng chạy sai lúc trang web tải, khiến một cơ chế "làm mới hiển
  thị" không bao giờ hoạt động) — đã tìm ra và sửa tận gốc bằng cách quan sát trực
  tiếp qua trình duyệt thật.
- **Thêm bộ lọc theo loại hành động và theo ngày** cho trang lịch đăng, giúp dễ
  tìm bài cần xem hơn.
- **Thiết kế lại toàn bộ cơ chế "hạ nhiệt"** sau khi phát hiện một lỗi khiến mức
  giới hạn tốc độ gốc của một tài khoản bị mất vĩnh viễn nếu tài khoản đó bị tạm
  dừng/kích hoạt lại nhiều lần liên tiếp. Cơ chế mới kéo dài 2 tuần, tăng dần theo
  từng nấc, và đảm bảo không bao giờ còn có thể làm mất số liệu gốc nữa.
- **Ghi nhận (không phải lỗi của hệ thống này)**: phát hiện 2 tin tuyển dụng có nội
  dung giống hệt nhau nhưng mang 2 mã số khác nhau từ bên B — xác nhận đây là lỗi ở
  phía cung cấp dữ liệu (bên B), không phải lỗi ở hệ thống đăng bài. Đã báo lại cho
  bên B.
- **Sửa lỗi bình luận bị treo (timeout) trên tài khoản mới `nhtu00`**: tài khoản
  này bị lỗi ngay lần bình luận đầu tiên vì giao diện Facebook của nó đang để
  tiếng Việt, trong khi hệ thống chỉ nhận diện được ô nhập bình luận khi giao diện
  là tiếng Anh (quy định bắt buộc từ đầu dự án, xem mục 5). Đã thêm một **lớp an
  toàn dự phòng**: nhận diện được cả 2 ngôn ngữ (Anh/Việt) ở tất cả các nút/ô bấm
  liên quan đến bình luận và đăng bài vào nhóm, để hệ thống không bị "đứng hình"
  nếu một tài khoản nào đó lỡ chưa để đúng tiếng Anh. Quy định chính vẫn không đổi:
  mọi tài khoản bot phải để giao diện tiếng Anh — đây chỉ là lưới an toàn phụ. **Đã
  xác nhận chạy thật thành công** ngay lần bình luận kế tiếp của `nhtu00`.
- **Phát hiện thêm cùng nguyên nhân (UI tiếng Việt) ở chỗ khác: nút mở khung soạn
  bài khi đăng vào nhóm.** Sau khi sửa lỗi bình luận, `nhtu00` chuyển sang thử đăng
  bài vào nhóm và bị lỗi tương tự 4 lần liên tiếp — nút "viết gì đó..." trên trang
  nhóm cũng hiện tiếng Việt, chưa nằm trong lần sửa trước (lúc đó tài khoản này
  chưa từng thử đăng bài, chỉ mới thử bình luận). Đã bổ sung thêm vào đúng lưới an
  toàn dự phòng ở trên. Còn 1 nút cùng loại (mở khung soạn bài khi đăng lên tường
  cá nhân) nhiều khả năng cũng sẽ gặp lỗi y hệt nếu `nhtu00` thử đăng lên tường —
  chủ dự án đã cho trước chữ tiếng Việt thật của nút này ("Tú ơi, bạn đang nghĩ gì
  thế?") nên đã vá luôn trước khi lỗi thật xảy ra, dù chưa chạy thử để xác nhận.
- **Sửa tiếp lỗi thứ 4 cùng nguyên nhân: nút đính kèm ảnh/video.** Sau khi 2 lỗi
  trên được sửa, hệ thống mở đúng khung soạn bài nhưng lại kẹt ở bước đính kèm
  ảnh — hoá ra hệ thống có tính năng tự động gắn 1 ảnh vui ngẫu nhiên vào mỗi bài
  đăng nếu bài đó chưa có sẵn ảnh riêng, nên bước "bấm nút thêm ảnh" vẫn luôn chạy
  dù người dùng không yêu cầu đính kèm gì. Nút này trên UI tiếng Việt chỉ có icon,
  không có chữ, nên không đọc được từ ảnh chụp lỗi — chủ dự án đã tự kiểm tra trên
  trang thật và cho đúng chữ ("Ảnh/video"). Đã vá tương tự 3 lần trước. Sau khi
  restart lại hệ thống để nạp code mới, bài đăng nhóm đầu tiên của `nhtu00` đã
  đăng thành công thật (job công ty CMC Japan, nhóm "Chuyển việc kỹ sư").
- **Ghi nhận (chưa xử lý): 1 tin tuyển dụng có mức lương đọc sai đơn vị.** Tra lại
  thông tin gốc bài đăng thành công nói trên, chủ dự án phát hiện mức lương ghi
  "5.000.000 JPY/**giờ**" — con số phi lý (gấp hàng nghìn lần lương giờ thực tế),
  nhiều khả năng đúng ra là lương theo năm hoặc tháng nhưng bị đọc/gắn sai đơn vị.
  Chưa rõ lỗi nằm ở dữ liệu nguồn (bên B) hay ở bước AI trích xuất — cần điều tra
  thêm trước khi sửa, chưa có thay đổi nào cho mục này.
- **Sửa lỗi thật: hệ thống lấy quá nhiều tin về đăng cho 1 tài khoản trong 1 lần
  đồng bộ**, khiến lịch đăng bị đẩy xa hơn nhiều so với quy định. Chủ dự án phát
  hiện tài khoản `nhtu00` vừa đồng bộ xong đã có lịch đăng tới tận 3 ngày sau.
  Kiểm tra lại đúng công thức đã thống nhất từ trước (cộng số chỗ trống của hôm
  nay + 2 ngày tới, chia cho số nhóm tối đa mỗi bài được đăng) thì phát hiện phần
  này **chưa từng được lập trình đúng** — hệ thống trước giờ chỉ tính chỗ trống
  của MỘT MÌNH hôm nay rồi lấy tin về ngay bằng đúng số đó, không tính thêm 2 ngày
  tới và không chia cho số nhóm/bài — dẫn tới lấy dư rất nhiều tin (35 tin thay vì
  đúng ra chỉ nên 9 tin theo công thức) và đẩy lịch đăng dồn ra xa. Đã sửa đúng
  công thức, có tính cả phần chỗ trống của ngày mai/ngày mốt đã bị lần đồng bộ
  trước đó chiếm mất (không tính hớ). Đã viết thêm bài test khớp đúng ví dụ chủ
  dự án đưa ra để đảm bảo không tái diễn. Theo yêu cầu chủ dự án, đã dọn sạch luôn
  35 tin bị lấy dư của `nhtu00` (đã sao lưu lại đầy đủ trước khi xoá, đề phòng cần
  xem lại) — riêng 12 tin gốc phía sau 35 bài đăng đó cũng được "mở khoá" lại để
  lần đồng bộ tới có thể lấy về đúng theo công thức mới, thay vì bị coi là "đã xử
  lý" và mất luôn.
- **Phát hiện tiếp: fix trên chưa triệt để, lịch đăng vẫn lố thêm đúng 1 ngày.**
  Chủ dự án kiểm tra thấy `tu_iizuki` vẫn có lịch đăng tới tận 24/9. Tra kỹ thì có
  2 phần: phần lớn là dữ liệu CŨ bị lấy dư từ TRƯỚC lần sửa nói trên (chưa kịp
  dọn vì lần dọn trước chỉ làm cho `nhtu00`, đang chờ chủ dự án quyết định có dọn
  tiếp không) — còn với dữ liệu MỚI (sau khi đã sửa), vẫn có 1 lỗi nhỏ khác khiến
  vài bài lố thêm đúng 1 ngày so với quy định. Nguyên nhân: hệ thống có 2 bước
  tính riêng biệt — "tính SỐ LƯỢNG tin nên lấy" (đã sửa đúng ở trên) và "xếp MỖI
  tin vào ngày nào" (một cơ chế khác, có từ trước) — 2 bước này trước giờ không
  neo vào cùng 1 mốc ngày, nên khi xử lý nhiều tin liên tiếp trong 1 lần, tin
  cuối cùng có thể vẫn bị đẩy lố thêm. Đã sửa để cả 2 bước cùng neo vào đúng 1
  mốc ngày cố định, kèm bài test riêng. Chưa chạy thử trên hệ thống thật để xác
  nhận 100%.

## Tuần 4 (24/09 – 25/09): Hệ thống đăng nhập cho `/admin` + hoàn thiện tab "Task quá hạn"

Chỉ 2 ngày nhưng khối lượng việc lớn — chủ yếu do owner trực tiếp rà soát kỹ dữ
liệu thật hằng ngày và yêu cầu kiểm tra chéo lại mọi thứ trước khi xác nhận xong.

- **Điều tra thêm sau 6 ngày server tắt (18/9 → 24/9)**: kiểm tra lại toàn bộ dữ
  liệu thì phát hiện service từng tắt hoàn toàn suốt 6 ngày. Tin vui: đúng cơ chế
  an toàn đã làm từ trước ("không tự đăng bài quá hạn sau khi server tắt/mở lại")
  hoạt động đúng như thiết kế — 54 bài lẽ ra đã tới giờ đăng trong lúc server tắt
  đều được giữ lại chờ duyệt, không hề tự động đăng dồn. Chủ dự án đã tự vào duyệt
  và huỷ hết 54 bài đó ngay khi mở server lại — nên phần backlog cũ của `tu_iizuki`
  từng nhắc ở trên coi như đã được xử lý, không cần làm gì thêm.
- **Thêm tính năng mới cho khu vực "⚠️ Task quá hạn"**: trước đây bài quá hạn nằm
  chờ duyệt mãi mãi nếu không ai đụng tới, không có cách lọc theo mức độ quá hạn.
  Đã thêm: (1) bộ lọc xem bài quá hạn TỪ 3/5/7/30 ngày TRỞ LÊN (chọn "30 ngày" là
  xem đúng nhóm bài sắp/đang bị hệ thống tự dọn ở mục (2) — bàn qua lại 2 lần với
  chủ dự án mới chốt đúng chiều này: ban đầu định làm ngược lại (xem bài còn
  mới), nhưng nhóm này vốn đã hiện đầu danh sách sẵn rồi; quan trọng hơn là trang
  này có nút "chọn tất cả rồi xoá" — lọc "từ N ngày trở lên" đảm bảo chọn-tất-cả
  không bao giờ dính nhầm bài mới), và (2) cơ chế TỰ ĐỘNG dọn bài nào quá hạn HƠN
  30 ngày mà chưa ai xử lý — nhưng không xoá mất, chỉ chuyển sang mục "đã huỷ" để
  vẫn xem lại lịch sử được khi cần. Đã thêm dữ liệu giả để tự kiểm tra trên giao
  diện thật trước khi báo hoàn thành.
- **Sửa lỗi thật: chọn bộ lọc "Quá hạn" ra kết quả rỗng thì cả ô lọc biến mất
  luôn, phải bấm F5 mới lấy lại được.** Chủ dự án tự phát hiện khi thử lọc "≥30
  ngày" lúc đó không có bài nào khớp. Nguyên nhân: trước đây khi không có kết
  quả, trang chỉ hiện mỗi dòng "không có gì" mà bỏ luôn cả ô chọn bộ lọc phía
  trên — mất luôn cách đổi lại bộ lọc mà không tải lại trang. Đã sửa để ô lọc
  (và nút "Chọn tất cả"/"Xoá đã chọn") luôn hiển thị, chỉ phần danh sách bên
  dưới đổi thành dòng thông báo khi không có kết quả.
- **Sửa tiếp lỗi liên quan: chọn "Tất cả" ở ô lọc "Quá hạn" không quay về đúng
  danh sách đầy đủ.** Nguyên nhân kỹ thuật: hệ thống hiểu nhầm lựa chọn "Tất cả"
  là một con số, trong khi "Tất cả" thực ra là "không chọn số nào cả" — dẫn tới
  bị từ chối ngay từ đầu, trang không cập nhật lại được. Đã sửa để "Tất cả" được
  xử lý đúng là "bỏ lọc", không còn bị từ chối.
- **Rà soát tổng thể dự án theo yêu cầu chủ dự án** ("còn gì cần cải thiện
  không") — liệt kê đầy đủ ở mục 6 bên dưới theo mức độ ưu tiên. Trong đó, việc
  được chọn làm ngay: **thêm kiểm tra tự động (CI) trên GitLab** — từ nay mỗi
  lần đẩy code lên, hệ thống tự chạy lại toàn bộ 212 bài test và báo ngay nếu có
  gì hỏng, thay vì chỉ dựa vào việc nhớ tự chạy tay.
- **Thay các hộp thoại xác nhận (VD "Xoá tất cả mục đã chọn?") bằng giao diện tự
  làm**, thay vì dùng hộp thoại mặc định xấu của trình duyệt. Giờ mọi nút xoá/
  huỷ trong `/admin` đều hiện đúng kiểu popup đồng bộ với phần còn lại của
  trang, không cần đổi gì ở từng nút — chỉ 1 chỗ sửa chung cho toàn bộ trang.
- **Làm trang đăng nhập thật cho `/admin`, thay hẳn kiểu đăng nhập xấu của trình
  duyệt** — bàn kỹ qua nhiều bước với chủ dự án trước khi làm (đọc kỹ toàn bộ code
  liên quan trước, xác nhận lại 3 điểm còn mơ hồ trước khi viết dòng code nào).
  Kết quả: có 1 trang đăng nhập riêng do mình thiết kế; 2 loại tài khoản — **ADMIN**
  (đúng 1, vẫn cấu hình trong file `.env` như trước) và **MOD** (ban đầu giới hạn
  tối đa 4 tài khoản phụ, sau đó bỏ hẳn giới hạn này — xem mục 24/9 bên dưới), do
  ADMIN tự thêm/xoá/đổi mật khẩu qua 1 trang quản lý riêng. Cả
  ADMIN và MOD đều dùng được mọi chức năng như nhau, chỉ riêng trang quản lý tài
  khoản MOD đó là chỉ ADMIN mở được. Vẫn bật/tắt được y hệt trước (để trống thông
  tin trong `.env` là tắt hoàn toàn, vào thẳng không cần đăng nhập). Mật khẩu MOD
  được mã hoá trước khi lưu, không lưu ở dạng đọc được. Đã viết thêm test tự động
  kiểm tra kỹ luồng đăng nhập (bao gồm cả tình huống ADMIN xoá 1 tài khoản MOD
  ngay khi người đó đang đăng nhập — hệ thống phải đá họ ra ngay, không đợi tới
  lúc phiên hết hạn), toàn bộ chạy đúng ngay từ lần thử đầu tiên.
- **Rà soát lại tính năng đăng nhập vừa làm xong (2026-09-24)** — theo đúng yêu
  cầu của chủ dự án, dò lại từng điểm của kế hoạch xem có sai sót/thiếu gì không,
  báo cáo trước rồi mới sửa. Không chỉ đọc lại code mà **tự tay gửi request thật**
  qua từng luồng để kiểm chứng, nhờ vậy bắt được 3 lỗi thật sự có thể khai thác
  được (không phải chỉ là nghi ngờ trên giấy): (1) tên tài khoản MOD từng chấp
  nhận vài ký tự đặc biệt (`?`, `#`, `%`, `&`) làm hỏng luôn đường dẫn xoá/sửa
  tài khoản đó — tạo xong là kẹt, không xoá/sửa lại được qua giao diện; (2) trang
  đổi mật khẩu MOD trả sai kiểu phản hồi khi tắt JavaScript, vỡ giao diện dù mọi
  trang tương tự khác đều đúng; (3) độ dài mật khẩu tối thiểu chỉ được chặn ở
  giao diện, ai gửi thẳng dữ liệu bỏ qua form vẫn tạo được mật khẩu 1 ký tự. Đã
  sửa cả 3, cộng 2 điểm nhỏ hơn (một chỗ dựa vào sự trùng hợp thay vì logic rõ
  ràng, một chỗ nên đồng bộ cách so sánh cho nhất quán) — sửa điểm nhỏ thứ 2 lại
  lộ ra 1 lỗi khác mới tinh (username có dấu tiếng Việt lúc đăng nhập làm hệ
  thống báo lỗi thay vì chỉ báo "không tìm thấy"), bắt và sửa luôn trong cùng
  lượt kiểm tra thay vì để lọt. Mỗi lỗi sửa xong đều có bài test riêng xác nhận,
  tổng cộng thêm test này lên 239/239 bài chạy qua. Chưa đưa lên hệ thống chính
  thức (git) theo đúng yêu cầu của chủ dự án.
- **2 việc chỉnh sửa thêm cho tính năng đăng nhập, ngay sau đợt sửa lỗi trên
  (2026-09-24)**: (1) Bỏ hẳn giới hạn tối đa 4 tài khoản MOD — con số 4 lúc đầu
  chỉ là ước lượng khi mô tả yêu cầu, không phải luật cứng cần giữ, giờ tạo bao
  nhiêu tài khoản MOD cũng được (ADMIN vẫn đúng 1, không đổi). (2) Một lỗi hiển
  thị thật: ở màn hình vừa/nhỏ (khoảng 800-1024px chiều rộng, ví dụ cửa sổ trình
  duyệt không phóng to hết cỡ), thanh điều hướng trên cùng phải xuống dòng vì
  không đủ chỗ, nhưng khung chứa nó lại có chiều cao cố định — phần xuống dòng
  bị tràn ra ngoài và đè thẳng lên tiêu đề/danh sách MOD ngay bên dưới. Không
  phát hiện được bằng cách đọc code, phải tự chụp ảnh màn hình qua trình duyệt
  giả lập ở nhiều kích thước mới thấy rõ. Đã sửa xong, chụp lại xác nhận hết đè
  ở mọi kích thước màn hình đã thử — lỗi này ảnh hưởng chung cho MỌI trang
  `/admin`, không chỉ riêng trang quản lý MOD, chỉ là trang đó có nhiều mục
  trong menu nhất nên lộ ra rõ nhất.
- **Thêm nút "🚀 Đăng ngay" thẳng trong tab "⚠️ Task quá hạn"** — trước đây
  muốn đăng 1 task quá hạn phải đưa nó về hàng chờ bình thường trước
  ("Đặt lịch"/"Lên lịch lại"), giờ bấm thẳng được. Bấm vẫn kiểm tra đúng
  2 lớp như mọi nơi khác trong hệ thống: (1) hạn mức số lượng bài/ngày —
  hết hạn mức thì **không cho đăng, không có cách nào bỏ qua**; (2)
  khoảng cách tối thiểu giữa 2 lần đăng — nếu chỉ vướng mỗi cái này thì
  hiện cảnh báo cho xem trước, xác nhận "Vẫn đăng ngay" thì mới bỏ qua
  riêng phần đó. Trong lúc tự kiểm tra kỹ trước khi báo hoàn thành, phát
  hiện và sửa luôn 1 kẽ hở thật: bản viết đầu tiên, nếu bấm "Vẫn đăng
  ngay", vô tình bỏ qua LUÔN CẢ kiểm tra hạn mức số lượng (không chỉ mỗi
  khoảng cách) trong một số tình huống hiếm — đã sửa để hạn mức số lượng
  luôn được kiểm tra lại, không có ngoại lệ, y hệt như đã cam kết.
- **Thêm tag "💰 Sponsor"** ngay cạnh nhãn loại hành động ("Đăng vào
  nhóm"/"Comment bài trong nhóm") cho bài nào tới từ tin tuyển dụng trả
  phí (sponsored) — giúp nhận ra ngay từ danh sách, không cần bấm vào
  xem chi tiết.

## Tuần 5 (từ 28/09): Thời hạn tự dọn dữ liệu cũ

- **Rà soát "hệ thống đang ghi lại gì, bao giờ tự xoá"** rồi chốt 2 thay đổi
  theo yêu cầu owner (mọi thứ còn lại giữ nguyên): **ảnh chụp bằng chứng giữ
  60 ngày** (trước là 30) và **file lịch đăng đã xong/lỗi/huỷ giữ 6 tháng**
  (trước là 30 ngày). Đo thật trước khi chốt: ảnh ~200 MB ở mốc 60 ngày, file
  lịch chỉ ~8 MB sau 6 tháng — đều rất nhẹ. Bảng thời hạn hiện tại: log dịch
  vụ tự xoay vòng (tối đa ~30 MB); ảnh 60 ngày; file lịch 6 tháng; bộ nhớ
  chống trùng bên B 45 ngày; task quá hạn > 30 ngày tự huỷ; dữ liệu báo cáo
  (`human_bot.db`) giữ 6 tháng (xem mục ngay dưới); chỉ bộ nhớ "đã nhắn ứng
  viên" là không tự xoá (cố ý, để không nhắn trùng).
- **Đọc code phát hiện và sửa luôn 1 chỗ rò rỉ nhỏ:** khi 1 task quá hạn được
  xử lý xong, file ghi chú lý do quá hạn của nó ở lại mãi trong thư mục quá
  hạn mà không ai dọn (đã tích tụ 83 file). Nay được dọn cùng thời hạn 6
  tháng (chỉ dọn file ghi chú "mồ côi", không đụng file của task còn đang chờ
  duyệt).
- **Chỉnh thời hạn lưu ngay trên trang quản trị, không cần sửa file `.env`
  nữa:** trang **Báo cáo** có thêm tab **"⚙️ Cấu hình"** với 3 ô số (ảnh
  chụp, file lịch đăng, lịch sử báo cáo), mỗi ô ghi rõ hết hạn thì mất gì.
  Nhập **0 = không bao giờ tự xoá** loại đó. Lưu xong áp dụng từ lần dọn
  kế tiếp (không cần khởi động lại, và không xoá gì ngay lập tức). Giá trị
  nhập sai (trống, chữ, số âm, số quá lớn) bị từ chối và không lưu gì. Nhân
  dịp này cũng bỏ luôn cách chỉnh cũ qua biến trong `.env` (chưa ai đặt nên
  không mất gì).
- **Dữ liệu báo cáo cũng giữ 6 tháng rồi xoá** (owner chốt sau khi được cảnh
  báo rõ đánh đổi): các dòng lịch sử cũ hơn 180 ngày sẽ tự biến mất khỏi mọi
  báo cáo ở trang quản trị (thống kê, theo từng lần đăng/bình luận). Đây là
  việc dọn duy nhất xoá lịch sử báo cáo chứ không chỉ file bằng chứng. Kiểm
  tra trước: ngoài trang báo cáo không có gì đọc dữ liệu này, nên không ảnh
  hưởng việc lên lịch hay giới hạn tốc độ. Lần chạy đầu chưa xoá gì (dữ liệu
  hiện chỉ mới 3 tuần).
  Khi rà soát lại trước khi lưu còn sửa 2 điểm: (1) đặt thời hạn lưu = 0 trong
  cấu hình lẽ ra sẽ xoá sạch toàn bộ báo cáo — nay 0 nghĩa là "tắt tự xoá,
  giữ hết"; (2) trang báo cáo trước đó ghi "toàn bộ hành động" — nay ghi đúng
  khoảng thời gian đang lưu.
- **Rủi ro phát hiện qua đọc code (chưa xảy ra thật):** với mốc cũ 30 ngày,
  task tự huỷ sau 30 ngày quá hạn có thể bị xoá luôn ngay hôm sau thay vì
  được giữ lại xem lịch sử; mốc 6 tháng mới đã giải quyết điểm này.

- **Kiểm tra lần lấy bài từ bên B (28/09):** 14 tin + 1 ứng viên đều được xếp
  lịch đúng: tin trả tiền (sponsor) được xếp sớm nhất và chia đều cho 2 tài
  khoản, không vượt giới hạn/ngày, giờ giãn cách hợp lệ, không đăng vào giờ
  yên lặng. Chỉ có 2 tin chỉ đăng được 2 nhóm thay vì 3 vì hôm đó hết chỗ —
  đúng thiết kế, owner chọn không bù.
- **Lỗi bình luận của nhtu00 và cách sửa:** một bình luận báo lỗi "không tìm
  thấy ô nhập" vì tài khoản **chưa tham gia nhóm** đó nên Facebook hiện ô bình
  luận với chữ khác ("Bình luận dưới tên…"). Đã bổ sung cụm chữ này. Nút gửi
  của kiểu ô này tên "Đăng bình luận" (owner xác nhận), hệ thống đã nhận sẵn.
  Bình luận lỗi cũ được bỏ qua, không chạy lại.
- **Chia ứng viên ưu tiên tài khoản đã tham gia nhóm:** trước đây ứng viên
  được chia theo hạn mức còn lại, không quan tâm tài khoản đã vào nhóm chưa.
  Nay hệ thống ưu tiên tài khoản đã tham gia; nếu không có ai tham gia (hoặc
  người đó hết hạn mức) thì dùng tài khoản nào còn chỗ, vì nhóm công khai vẫn
  bình luận được.
- **Sửa lỗi ở tab Quản lý MOD:** sau khi thêm tài khoản, danh sách bị hiện
  lên trên đầu trang (F5 mới về đúng chỗ). Nguyên nhân là kết quả được đặt
  nhầm vào khung cửa sổ nhỏ (modal) thay vì thay thế danh sách. Đã sửa; đồng
  thời sửa luôn lỗi tương tự ở nút "Đổi mật khẩu" (cửa sổ không tự đóng, và khi
  nhập sai thì đè lên danh sách). Cần owner thử lại trên trình duyệt.
- **Menu:** bỏ tab "Trang chủ"; bấm chữ **human_bot** ở góc trái để về trang chủ
  `/admin`.
- **Đổi giờ đăng giữa 2 bài (giai đoạn 1):** tab "Lịch đăng" nay có nút
  "⇄ Đổi giờ" ở mỗi bài đang chờ đăng, cho phép tráo giờ đăng với 1 bài khác
  cùng tài khoản và cùng loại hành động (đăng bài, hoặc bình luận). Giai đoạn
  sau (chưa làm) sẽ mở rộng sang đổi giờ với 1 bài đang ở "Task quá hạn".
  Cần owner thử tay trên trình duyệt để xác nhận trước khi coi là xong.
- **Đổi giờ đăng giai đoạn 2:** tab "Task quá hạn" nay có nút "↩️ Mượn giờ" —
  task quá hạn lấy giờ của 1 task đang chờ (cùng tài khoản, cùng loại hành
  động), còn task đang chờ đó tự động dời sang giờ mới hợp lệ. Khác với "⇄
  Đổi giờ" (giai đoạn 1, không phải hoán đổi 2 chiều vì giờ của task quá hạn
  đã ở quá khứ). Owner tự thử trên trình duyệt và phát hiện đúng 2 lỗi thật
  trước khi kịp commit: (1) 1 ngày đã đủ 5 bài, mượn giờ xong thành 6 bài;
  (2) modal xem trước báo 1 ngày, nhưng bấm xác nhận thì hệ thống lại đăng
  vào ngày khác — cả 2 đều cùng 1 gốc (quên tính bài quá hạn sắp chiếm chỗ),
  đã sửa cả 2 nơi và thêm test riêng cho từng trường hợp.
- **Lọc dữ liệu tin tuyển dụng từ bên B trước khi đăng:** owner rà lại vài
  task đang chờ đăng, phát hiện 2 vấn đề về chất lượng dữ liệu bên B gửi
  sang, không phải lỗi code hiển thị:
  1. Bên B thỉnh thoảng gửi chữ **"unknown"** cho 1 trường (thay vì để
     trống) — hệ thống cũ không nhận ra đây là "chưa có thông tin" nên in
     thẳng nguyên chữ "unknown" vào bài đăng thật (VD: "Yêu cầu JLPT:
     unknown", "Visa: Unknown"). Nay hệ thống tự nhận diện và coi như chưa
     có thông tin, bỏ qua dòng đó (hoặc thay bằng câu mời nhắn tin thêm,
     đúng như khi trường đó trống thật sự).
  2. Có tin tuyển dụng gần như không có thông tin gì (chỉ có điểm tin cậy
     cao 0.88, không tên vị trí/công ty/địa điểm/lương/visa) nhưng vẫn
     được tự động lên lịch, ra bài đăng gần như trống nội dung. Nay hệ
     thống **loại hẳn** những tin kiểu này trước khi lên lịch — yêu cầu
     tối thiểu phải có tên vị trí VÀ ít nhất 1 trong (công ty/địa điểm/
     lương/visa) mới được đăng. Tin bị loại vẫn được **lưu lại đầy đủ
     trong cơ sở dữ liệu báo cáo** (bảng riêng, không tự xoá theo lịch
     dọn dẹp thông thường) để owner xem lại sau này nếu cần, chứ không
     mất hẳn như cách hệ thống đang xử lý các tin bị bỏ qua khác.
  Đã kiểm chứng lại đúng 3 tin thật gặp phải (job 703/577/776) qua bản sửa
  mới, kết quả đúng như mong đợi. **435/435 test pass.** Chưa thử qua
  trình duyệt/chưa chạy trên service thật, chưa commit.
  **Owner yêu cầu dò lại cẩn thận** trước khi coi là xong — cho AI tự soát
  lại chính bản vừa sửa, phát hiện thêm đúng 3 lỗ hổng thuộc cùng nhóm
  lỗi, chưa được che hết ở lần sửa đầu: (a) nếu "unknown" nằm LỒNG bên
  trong (VD `salary.currency`) thì vẫn lọt qua, ra "Lương: khoảng 20
  UNKNOWN/tháng"; (b) chữ "unknown" ở ngay TÊN VỊ TRÍ (không nằm trong
  phần thuộc tính) chưa được lọc; (c) tin chỉ có tên vị trí + yêu cầu JLPT
  (không có công ty/địa điểm/lương/visa) đáng lẽ đăng bình thường được lại
  bị liệt nhầm vào "thiếu nội dung" và bị loại oan. Đã sửa cả 3, kiểm tra
  lại không ảnh hưởng gì tới 3 tin thật đã xác nhận trước đó. **439/439
  test pass.**
- **Xác nhận đứng fix lỗi treo (timeout) khi bình luận vào bài trong nhóm
  — theo dõi 13 ngày, không cần chạy lại/Codegen thêm:** lỗi này (mở lần
  đầu 10/09) là bài toán khó xác nhận vì tần suất thấp (~1 lần/2-3 ngày)
  — Codegen ghi tay 1 lần gần như chắc chắn không rơi đúng lúc lỗi xảy
  ra, nên cách xác nhận đúng là để hệ thống chạy thật nhiều ngày rồi soi
  lại nhật ký. Trước khi sửa (17/09): lỗi tái diễn 4 lần trong 1 tuần
  trên 2 nhóm khác nhau — không phải sự cố mạng ngẫu nhiên mà là đặc
  tính của trang bài viết trong nhóm (Facebook giữ kết nối nền gần vô
  hạn khiến tín hiệu "tải xong" mặc định của trình duyệt tự động không
  bao giờ bắn). Sau khi đổi sang tín hiệu "tải xong" khác (17/09), soi
  lại nhật ký 13 ngày tiếp theo (17/09 → 30/09): **0 lần tái diễn** đúng
  lỗi gốc. Coi như xác nhận fix đứng.
  Phát sinh 2 lỗi timeout KHÁC loại trong 13 ngày đó (chờ 1 nút bấm
  không tìm thấy, không phải lỗi tải trang) — không phải lỗi cũ hồi lại,
  nhiều khả năng liên quan các lần sửa UI tiếng Việt sau đó. Chưa đào
  sâu, owner để sau (30/09).
- **Chỉnh câu chữ mẫu đăng bài vào nhóm theo yêu cầu owner:** thêm 1 câu
  mở đầu mới ("TÌM ĐỒNG CAM CỘNG KHỔ"), và giới hạn câu mở đầu "TÌM NHÂN
  TÀI" chỉ dùng cho tin có visa Kỹ Sư (gijinkoku) — ràng buộc chỉ 1
  chiều: tin visa Kỹ Sư vẫn xoay đủ mọi câu mở đầu bình thường, không bị
  ép luôn phải ra đúng câu này. Đổi thêm 1 câu mời nhắn tin và toàn bộ 5
  câu "thiếu visa/lương" theo đúng bản owner đưa. 441/441 test pass.
- **Rà lại quy trình ghi chép của chính assistant:** phát hiện 2 việc sửa
  câu chữ ở trên đã commit code nhưng quên ghi vào `tasks.md`/tài liệu
  này — bổ sung lại ngay khi owner hỏi tiếp phần "10 câu CTA" cho thấy
  thiếu sót. Đã bổ sung đầy đủ vào `tasks.md` (mục "Chỉnh opener + câu
  chữ mẫu đăng bài nhóm").
- **Rà soát Admin UI + đối chiếu công cụ tương tự trên thị trường, owner
  chốt ghi nhận cả 6 ý tưởng để bàn thêm (chưa làm, xem mục 6 bên dưới).**
- **Làm xong tính năng "Kho nội dung"** — trang quản trị giờ có chỗ tự sửa
  câu chữ hệ thống dùng khi đăng bài/bình luận (câu mở đầu, câu mời nhắn
  tin, mẫu bình luận, tên gọi visa...) mà không cần nhờ sửa code mỗi lần
  đổi 1 câu — kèm theo vài vòng owner tự dùng thử phát hiện lỗi thật
  (nút thừa, giao diện chọn nhiều lựa chọn xấu, 1 lỗi CSS khiến nút không
  ẩn được dù code đã đúng) và đã sửa hết. Chi tiết đầy đủ ở `tasks.md`.
- **Bug thật: bài đăng không lên, báo lỗi `post_button_still_visible_after_click`
  (nhtu00, 14:24 01/10) — owner tự kiểm tra trên Facebook xác nhận bài
  thật sự KHÔNG lên, không phải báo nhầm.** Tra lại cho thấy đây là lần
  đầu tiên lỗi này xuất hiện kể từ khi có cơ chế "chờ nút Đăng biến mất
  mới tin là thành công" (thêm từ 02-07/09, tới giờ mới gặp ca thật đầu
  tiên). Ảnh chụp lúc lỗi cho thấy khung soạn bài bị kẹt đang tải, không
  phải Facebook từ chối bài. Cùng tài khoản này ~1h45 sau bị đóng hẳn
  trình duyệt rồi tự mở lại đăng tiếp bình thường — một tài khoản khác
  vẫn đăng bình thường đúng lúc đó, nên không phải lỗi mạng chung mà có
  vẻ là phiên trình duyệt riêng của `nhtu00` hôm đó tự nhiên trục trặc.
  **Chưa sửa gì** — mới 1 lần, cần theo dõi thêm vài ngày xem có lặp lại
  không trước khi quyết định sửa (đúng cách đã làm với lỗi timeout bình
  luận trước đây). Chi tiết đầy đủ ở `tasks.md`.
  **Cập nhật 02/10:** thử "Đăng lại" cho task bị lỗi hôm đó → đăng thành
  công, không tái diễn thêm lần nào.
- **Làm xong "Bảng sức khoẻ tài khoản" ở trang chủ** (ý tưởng #3 trong
  10 ý đã note) — mỗi tài khoản giờ hiện ngay 5 thông tin: đang hoạt
  động/tạm dừng/hạ nhiệt, phiên trình duyệt có đang mở không, lần đồng
  bộ dữ liệu gần nhất, lần đăng/bình luận thành công gần nhất (cảnh báo
  nếu im lặng quá 48 giờ mà không có lý do), và phiên đăng nhập Facebook
  còn bao nhiêu ngày (cảnh báo nếu dưới 14 ngày — đọc thẳng từ file
  phiên đăng nhập đã lưu, trước giờ không ai biết thông tin này). Tài
  khoản có vấn đề hiện lên đầu danh sách. Owner chốt 2 mốc cảnh báo
  (48 giờ, 14 ngày) qua hỏi đáp trước khi code.
  **Tự phát hiện 1 lỗi thật khi verify bằng dữ liệu 2 tài khoản thật**:
  giao diện mới bị lồng sai bên trong khung danh sách cũ còn sót lại —
  chỉ lộ ra khi xem thử với dữ liệu thật, không phải lúc chạy test tự
  động (test chỉ kiểm tra có đủ chữ, không kiểm tra cấu trúc trang có
  đúng không). Đã sửa, cũng tiện phát hiện và vá luôn 1 lỗ hổng trong
  quy trình viết test (1 nơi lưu file lại không được cô lập đúng khỏi
  dữ liệu thật, sửa tận gốc cho mọi test sau này dùng chung). 21 test
  mới. Chi tiết đầy đủ ở `tasks.md`.
  **Owner xem qua trình duyệt thật, yêu cầu chỉnh layout**: 1 tài khoản
  thì thẻ giãn hết chiều ngang, 2 tài khoản thì chia đôi mỗi bên — đã
  đổi sang cách xếp tự co giãn theo đúng số tài khoản đang có.
- **Làm xong báo động qua Telegram + hỏi-đáp 2 chiều** (owner tự đề
  xuất sau khi xem "Bảng sức khoẻ tài khoản" ở trên — muốn được báo chủ
  động qua điện thoại, không phải tự mở trang quản trị ra xem). 3 phần
  đúng như owner yêu cầu:
  1. **Báo cáo âm thầm mọi lượt đăng/bình luận thật** — thành công hay
     thất bại đều có tin: tài khoản nào, đăng nội dung gì, vào nhóm
     nào, lý do nếu thất bại, kèm ảnh chụp bằng chứng nếu có. Loại tin
     này luôn "âm thầm" (điện thoại không kêu/rung) vì số lượng nhiều,
     chỉ để xem lại khi cần.
  2. **Báo động (có kêu) cho 5 loại sự cố thật**: tài khoản bị tạm dừng;
     đồng bộ dữ liệu với bên B lỗi liên tục (kèm lỗi); tài khoản im
     lặng quá 48 giờ không có lượt đăng/bình luận nào thành công; phiên
     đăng nhập Facebook sắp hết hạn (dưới 14 ngày); và cùng 1 hành động
     thất bại liên tiếp 3 lần. Mỗi loại chỉ báo đúng 1 lần ngay lúc vừa
     xảy ra, không báo lặp lại liên tục làm phiền trong khi sự cố vẫn
     còn đó.
  3. **Hỏi-đáp 2 chiều**: nhắn bất kỳ tin gì vào bot Telegram, hệ thống
     trả lời ngay bằng đúng bảng sức khoẻ hiện tại của mọi tài khoản
     (giống hệt thông tin hiện trên trang chủ quản trị). Chỉ trả lời
     đúng số điện thoại/tài khoản Telegram đã đăng ký, người lạ nhắn
     vào không được trả lời.
  Có thêm 1 công tắc bật/tắt ngay trên trang quản trị (mục Cấu hình) để
  owner tự tắt hết báo động bất cứ lúc nào mà không cần nhờ sửa code.
  **Tự kiểm tra lại code 5 vòng trước khi báo xong** (đúng quy trình đã
  thống nhất — không tin tưởng ngay lần viết đầu, tự rà soát lại như
  một người kiểm tra độc lập): tổng cộng phát hiện và sửa nhiều lỗi
  thật qua 5 vòng rà soát liên tiếp (danh sách đầy đủ ở `tasks.md`),
  đáng chú ý nhất là 1 lỗi khiến tài khoản đã hết hạn phiên đăng nhập
  THẬT SỰ (cần đăng nhập lại ngay) lại chỉ nhận được tin Telegram nói
  nhẹ "sắp hết hạn" thay vì đúng mức báo động khẩn — gốc là do code
  cảnh báo Telegram tự chép lại logic của trang quản trị thay vì dùng
  lại đúng 1 chỗ, nên 2 nơi lệch nhau. Đã sửa tận gốc (gộp về đúng 1
  hàm dùng chung), không còn lệch nữa. Thêm 19 test mới riêng cho các
  lỗi phát hiện ở vòng kiểm tra lại này. Toàn bộ 538/538 test pass.
  Chi tiết đầy đủ từng lỗi ở `tasks.md`.
  **Owner cung cấp bot token thật ngay trong lúc trao đổi (tạo qua
  @BotFather) — đã điền vào `.env` và gửi thử thành công** (bot tên
  @AIAgentSupport_bot), xác nhận toàn bộ chuỗi hoạt động đúng trên dữ
  liệu thật, không chỉ giả lập.
- **Owner yêu cầu thêm ngay sau đó: không chỉ 1 người nhận cố định, mà
  "ai cũng tự dùng Telegram của họ để lấy thông tin từ bot được, nhưng
  phải được cài đặt ở ADMIN"** — làm thêm trang **"📨 Telegram"** mới
  trên trang quản trị: thêm/xoá bất kỳ ai (dán chat ID Telegram của họ +
  đặt tên gợi nhớ), không cần sửa file `.env`/khởi động lại service mỗi
  lần thêm người mới. Mỗi dòng có nút **"🧪 Gửi thử"** để xác nhận ngay
  chat ID đó còn hoạt động hay không, báo đúng thành công/thất bại thật
  (không báo "đã gửi" giả nếu thật ra gửi lỗi). Owner đã có sẵn 1 chat
  ID (chính owner) từ lúc test trước — hệ thống tự động đưa chat ID đó
  vào danh sách ngay lần khởi động lại service kế tiếp, không cần owner
  tự thêm lại. Khi 1 người nhắn hỏi bot, chỉ đúng người đó nhận lại câu
  trả lời (không gửi luôn cho những người khác trong danh sách).
  Tự rà soát lại code 2 vòng trước khi báo xong, tìm và sửa 4 lỗi thật ở
  vòng 1 (đáng chú ý nhất: nút "Gửi thử" từng luôn báo thành công dù
  thật ra gửi lỗi — đã sửa để báo đúng kết quả thật). Thêm 35 test mới.
  **Toàn bộ 573/573 test pass.** Chi tiết đầy đủ ở `tasks.md`.
  **Owner tự khởi động lại service — xác nhận sống thành công**: chat
  ID 931000937 tự xuất hiện trong danh sách như thiết kế, không cần
  owner tự thêm lại.
- **Owner yêu cầu gọn lại 2 việc ngay sau đó**: (1) chuyển mục "📨
  Telegram" từ thanh điều hướng riêng vào làm 1 tab con bên trong trang
  "Tài khoản" (tên "Tài khoản Telegram") — gọn hơn, không thêm 1 mục
  điều hướng mới chỉ cho 1 danh sách nhỏ; (2) xoá chat ID 931000937
  khỏi file `.env` vì đã lưu chung chỗ với các chat ID khác trong danh
  sách quản trị rồi, không cần giữ 2 nơi. Cả 2 đã làm xong, kèm theo 1
  lỗi hiển thị thật tự phát hiện lúc chuyển tab (thông báo lỗi khi thêm
  sai chat ID từng render vào đúng khung đang ẩn, khiến người dùng
  không thấy lỗi dù lỗi vẫn ở đó) — đã sửa. **Toàn bộ 576/576 test
  pass**, xác nhận lại bằng cách gọi thẳng trang thật (chỉ xem, không
  ghi gì) — chat ID thật hiện đúng trong tab mới, không còn dấu vết
  trang cũ ở đâu. Chi tiết đầy đủ ở `tasks.md`.
- **Owner chỉ ra đúng 1 vấn đề thật trong hướng dẫn cũ**: hướng dẫn thêm
  người nhận cũ yêu cầu người dùng tự mở 1 đường link có kèm token bí
  mật lấy từ file `.env` trên máy chủ — nhưng 1 người chỉ được cấp
  quyền vào trang quản trị thì không hề có quyền đọc file đó, nên không
  thể tự làm theo được. Owner đề xuất đúng hướng: **để chính hệ thống
  (đã có sẵn token ở phía server) tự tìm người mới nhắn bot, không ai
  cần thấy token hay tự tra dữ liệu thô nữa.**
  Làm xong: tab "Tài khoản Telegram" giờ có thêm khu vực **"🔔 Người mới
  nhắn vào bot, chưa được thêm"** — ai vừa nhắn bất kỳ gì vào bot sẽ tự
  hiện tên + Chat ID ở đây trong vài giây, chỉ cần bấm đúng 1 nút
  "➕ Thêm" là xong, không cần gõ tay gì cả, không ai cần biết token là
  gì. Form nhập tay cũ vẫn còn, chỉ dùng khi đã biết sẵn Chat ID của ai
  đó từ trước.
  Tự rà soát lại trước khi báo xong, phát hiện và sửa 2 lỗi thật (đáng
  chú ý: tin nhắn đăng vào 1 "channel" Telegram — khác nhóm thường —
  từng không hiện được trong danh sách này do Telegram gửi loại tin đó
  theo cách khác, đã sửa để nhận cả 2 loại). Thêm 18 test mới.
  **Toàn bộ 594/594 test pass.** Chi tiết đầy đủ ở `tasks.md`.
- **Owner góp ý tiếp 2 điểm nhỏ trên tab vừa làm**: (1) form "Chat ID/Tên
  gợi nhớ" đang nằm lộ thiên ngay trên trang — nên bấm 1 nút mới hiện ra
  (giống mọi form "thêm" khác trong trang quản trị); (2) đoạn giải thích
  nên có link bấm thẳng tới trò chuyện với bot trên Telegram, không chỉ
  nói chữ suông.
  Làm xong cả 2: form giờ nằm trong 1 cửa sổ nhỏ (modal) sau khi bấm "➕
  Thêm thủ công"; đoạn giải thích có link bấm thẳng vào đúng bot (hệ
  thống tự hỏi Telegram tên bot 1 lần lúc khởi động, không ai cần biết
  token). Tự rà soát lại trước khi báo xong, phát hiện và sửa 3 lỗi
  thật — đáng chú ý nhất: 1 thông báo "Đã lưu" của tab Telegram từng bị
  "nướng" nhầm vào đúng khung của tab "Tài khoản" (do đổi tab chỉ ẩn/
  hiện trên trình duyệt, không tải lại) — bấm qua tab Tài khoản sau đó
  sẽ thấy thông báo giả dù chẳng có gì được lưu; đã sửa. Thêm 17 test
  mới. **Toàn bộ 611/611 test pass.** Chi tiết đầy đủ ở `tasks.md`.
- **Owner yêu cầu thêm 2 việc nhỏ**: (1) cho sửa lại tên gợi nhớ của 1
  người đã có trong danh sách (trước đây lỡ đặt tên sai phải xoá rồi
  thêm lại từ đầu); (2) đưa nút "➕ Thêm thủ công" lên đầu khu vực (trước
  nằm dưới cùng).
  Làm xong cả 2: mỗi dòng giờ có nút "✏️ Sửa" mở ra 1 cửa sổ nhỏ chỉ để
  đổi tên gợi nhớ (Chat ID không sửa được ở đây — muốn đổi Chat ID thì
  cần xoá người cũ, thêm người mới, vì Chat ID là thứ xác định "đây là
  ai"); nút thêm thủ công đã chuyển lên đầu. Tự rà soát lại trước khi
  báo xong, sửa 2 lỗi nhỏ (không ảnh hưởng tới owner, chỉ là code viết
  lặp lại 1 chỗ và thiếu cắt khoảng trắng dư ở Chat ID). Thêm 14 test
  mới. **Toàn bộ 625/625 test pass.** Chi tiết đầy đủ ở `tasks.md`.
  Chưa commit.
- **Bug thật nghiêm trọng: đồng bộ dữ liệu bên B âm thầm NGỪNG HOẠT ĐỘNG
  5 ngày liên tục (01/10 → 06/10), owner tự phát hiện khi để ý "lần
  đồng bộ gần nhất" trên trang quản trị không nhích lên dù đã khởi
  động lại server nhiều lần.**
  Đã loại hết các nghi vấn thường gặp (công tắc bật/tắt, mạng, token) —
  tất cả đều bình thường. Tìm ra nguyên nhân thật qua file log của
  service (vẫn ghi lại đều, chỉ chưa ai đọc tới): đúng 1 lỗi code —
  1 con số cấu hình ("số ngày được phép dồn bài sang ngày sau nếu hết
  chỗ") đang được lưu dưới dạng số có phần lẻ (ví dụ `2.0` thay vì
  `2`), và đoạn code tính "nên lấy bao nhiêu tin mới mỗi lần đồng bộ"
  không chấp nhận được dạng số đó — nên MỌI lần thử đồng bộ từ 01/10
  đều crash ngay trước khi kịp ghi lại kết quả (dù thành công hay thất
  bại), khiến trang quản trị tưởng như chẳng có gì chạy cả.
  Đã sửa, thêm 1 bài test riêng tái hiện chính xác kiểu dữ liệu đã gây
  lỗi (bài test cũ trước đây dùng số "sạch" nên không bắt được lỗi này).
- **Owner hỏi tiếp "vì sao có lỗi này, trước nay vẫn chạy đúng mà" —
  truy ngược tới tận gốc, không đoán, tìm ra đây là lỗi thật thứ 2, sâu
  hơn.** Con số cấu hình đó trong code LUÔN được khai báo đúng kiểu
  "số nguyên" từ đầu — không hề sai. Vấn đề nằm ở chính **nút "Lưu cấu
  hình" trên trang quản trị**: nút này có 1 đoạn code (thêm từ tháng 9,
  sau 1 lần sự cố tương tự ở chỗ khác) để giữ đúng kiểu số nguyên/số
  thực của từng ô khi lưu — nhưng đoạn giữ-đúng-kiểu đó lại có 1 lỗ hổng
  kỹ thuật khiến nó hoạt động đúng cho MỘT SỐ tab cấu hình nhưng không
  đúng cho tab "Đồng bộ dữ liệu bên B" (và vài tab khác nữa). Nên:
  **con số đó chỉ bị hỏng đúng vào lần ĐẦU TIÊN có ai bấm "Lưu cấu
  hình" ở tab đó** — trước lần bấm đó, mọi thứ vẫn đúng và chạy bình
  thường; sau lần đó, giá trị bị ghi sai dạng vĩnh viễn trong file cấu
  hình, và mọi lần đồng bộ từ đó crash — đúng khớp với việc "trước nay
  vẫn chạy đúng".
  Đã sửa tận gốc nút "Lưu cấu hình" (không chỉ riêng chỗ gây crash lần
  này) — áp dụng cho MỌI tab cấu hình khác dùng chung cơ chế, tránh lặp
  lại chuyện này ở chỗ khác về sau. Nhân lúc rà soát, phát hiện thêm tab
  "Hạ nhiệt sau khi kích hoạt lại tài khoản" cũng đang bị đúng kiểu lỗi
  này trong file cấu hình thật — nhưng CHƯA gây ra vấn đề gì (không có
  chỗ nào trong code dùng những số đó theo cách dễ vỡ như chỗ vừa sửa),
  nên không cần sửa file cấu hình đó ngay — lần tới owner lưu lại tab đó
  qua trang quản trị, nó sẽ tự lưu đúng lại.
  **Toàn bộ 627/627 test pass.** Chi tiết đầy đủ ở `tasks.md`. Đã commit
  + push lên remote.
  **[ĐÃ XÁC NHẬN SỐNG, 07/10]** Owner khởi động lại server — đồng bộ bên
  B tự chạy lại ngay như kỳ vọng: lấy về 70 job + 3 ứng viên mới, lên
  lịch 9 bài đăng + 2 bình luận. Hết hẳn tình trạng kẹt 5 ngày.
- **Thêm bước lọc job theo độ tin cậy trước khi tự lên lịch đăng (08/10).**
  Owner hỏi: hệ thống có đang ưu tiên job có "độ tin cậy" (một con số bên
  B gửi kèm mỗi job, thể hiện mức chắc chắn dữ liệu đó là thật/đúng) từ
  0.9 trở lên không? Trả lời: chưa — trước giờ job chỉ được kiểm tra có
  đủ thông tin để soạn bài hay không, chưa hề nhìn vào con số độ tin cậy
  này.
  Owner chỉnh lại đúng ý muốn: không phải ưu tiên, mà là **chặn hẳn việc
  tự đăng** đối với job có độ tin cậy dưới 0.9 (hoặc bên B không gửi kèm
  con số này luôn — coi như chưa đủ tin cậy, an toàn hơn là tự cho qua).
  Những job này vẫn phải được soạn sẵn nội dung như thường, chỉ khác là
  đưa vào một màn hình riêng để owner/admin tự xem và bấm duyệt mới thật
  sự lên lịch đăng — tránh việc dữ liệu chưa chắc đúng từ bên B lọt thẳng
  ra trang Facebook thật mà không ai kiểm lại.
  3 điều đã thống nhất trước khi làm: (1) lúc bấm duyệt, hệ thống tự tìm
  giờ đăng hợp lý nhất ngay lúc đó (không cần tự chọn giờ tay); (2) mốc
  0.9 này chỉnh được ngay trên trang quản trị (`/admin/config`), không
  phải sửa code; (3) job thiếu hẳn con số độ tin cậy cũng vào hàng chờ
  duyệt, không tự cho qua.
  Đã làm xong: thêm tab mới "🔍 Chờ duyệt" ngay trong trang `/admin/schedule`
  hiện có (cạnh "Đang chờ"/"Quá hạn") — mỗi job chờ duyệt hiện rõ nội
  dung đã soạn sẵn (sửa được trước khi duyệt), độ tin cậy thấp bao nhiêu,
  và dự kiến đăng vào tài khoản/nhóm nào; nút "Duyệt & lên lịch" tự tính
  giờ đăng hợp lệ ngay lúc bấm, nút "Bỏ qua" thì không đăng job đó (vẫn
  giữ lại để xem lại sau, không xoá mất).
  **Tự kiểm tra lại code trước khi báo xong** (quy trình chuẩn cho mọi
  việc, không phải chỉ việc này) — nhờ vậy bắt được 6 lỗi thật trước khi
  owner kịp gặp, đáng chú ý nhất: (1) job không tìm được tài khoản phù
  hợp nào sẽ bị mất vĩnh viễn khỏi hệ thống nếu không xử lý đúng; (2) bên
  B gửi độ tin cậy sai định dạng sẽ làm sập NGUYÊN lượt đồng bộ, không
  chỉ 1 job; (3) admin bấm 2 lần (hoặc mạng chập chờn gửi lại) nút "Duyệt"
  có thể làm đăng trùng cùng 1 bài 2 lần. Cả 3 đã sửa xong, kiểm lại lần 2
  xác nhận đúng. Thêm 35 test mới, toàn bộ test pass.
  **Owner xem qua giao diện, góp ý chỉnh tiếp 2 lần**: (1) 2 nút "Duyệt"/
  "Bỏ qua" đưa về cùng 1 hàng, 3 ô nội dung chia đều mỗi ô 1/3 hàng (ban
  đầu làm ngược — mỗi ô chiếm trọn 1 dòng — owner phản hồi lại đúng ý
  muốn là chia cột); (2) thêm bước xác nhận trước khi "Duyệt & lên lịch"
  thật sự chạy, kèm cho chọn LẠI tài khoản đăng ngay tại bước xác nhận đó
  (trước đây cố định đúng tài khoản đã chọn lúc soạn nội dung) — đổi tài
  khoản thì hệ thống tự chọn lại đúng nhóm của tài khoản mới, không dùng
  nhầm nhóm của tài khoản cũ. Thêm 5 test nữa, **toàn bộ 667/667 test
  pass**. Chi tiết kỹ thuật đầy đủ ở `tasks.md`. Chưa kiểm bằng tay trên
  trình duyệt thật (chưa có job độ tin cậy thấp thật từ bên B để thử
  ngay lúc này) — chỉ mới kiểm qua test tự động mô phỏng đúng luồng
  request/response. Chưa commit.

---

# 5. Những quyết định quan trọng đã bàn kỹ với chủ dự án

Một vài lựa chọn thiết kế đáng chú ý, được cân nhắc kỹ chứ không phải ngẫu nhiên:

- **Không dùng AI để "lái" trình duyệt cho mọi thao tác.** Mỗi hành động (đăng
  bài, bình luận...) được ghi lại sẵn một lần bằng cách làm thao tác thật, rồi máy
  lặp lại đúng y hệt mỗi lần cần — nhanh hơn, rẻ hơn, và ít rủi ro "AI hiểu nhầm
  rồi bấm sai" so với việc để AI tự suy nghĩ lại mỗi lần. AI chỉ được dùng ở chỗ
  thật sự cần "sáng tạo" — như viết nội dung bài đăng.
- **Không điều khiển chuột thật của máy tính** (dù về lý thuyết sẽ khó bị phát
  hiện hơn) — vì sẽ mất khả năng chạy nhiều tài khoản cùng lúc, chạy không cần
  người trông máy 24/7, và không chạy được nếu có cửa sổ khác che màn hình. Xét
  thấy cách làm hiện tại (mô phỏng hành vi qua trình duyệt) đã đủ tốt cho nhu cầu
  thực tế.
- **Chưa mua proxy/IP riêng cho từng tài khoản** — đây là việc có lợi ích lớn nhất
  nếu mở rộng quy mô, nhưng tốn chi phí nên tạm để sau, chờ quyết định khi cần scale
  lên nhiều tài khoản hơn.
- **Không thêm bước tự nhận diện "2 tin trùng nội dung"** ở hệ thống này khi bên B
  gửi trùng — vì rủi ro nhận nhầm 2 tin thật khác nhau là trùng cao hơn lợi ích, nên
  chọn cách báo lại cho bên B sửa từ gốc.

---

# 6. Việc cần làm tiếp theo

- **[ĐANG THEO DÕI]** Theo dõi thêm để chắc chắn các lỗi mới sửa (đặc biệt:
  tin trùng dữ liệu, đăng đúng giờ, cơ chế hạ nhiệt) chạy ổn định lâu dài với
  dữ liệu thật.
- **[ĐÃ XÁC NHẬN SỐNG, 2026-09-28]** Chạy thử ưu tiên "tin trả tiền" với dữ
  liệu thật — xem mục "Kiểm tra lần lấy bài từ bên B (28/09)" ở Tuần 5:
  tin sponsor được xếp sớm nhất và chia đều cho 2 tài khoản, đúng thiết kế.
- **[ĐÃ XÁC NHẬN SỐNG, 07/10]** Kênh báo động qua Telegram, cộng thêm
  trang quản lý nhiều người nhận ở `/admin` — xem Tuần 5 ở mục 4. Owner
  xác nhận chạy ổn sau khi khởi động lại service — toàn bộ tính năng
  (báo cáo mọi lượt đăng, 5 loại báo động, hỏi-đáp 2 chiều) đã thật sự
  hoạt động, không chỉ dừng ở test giả lập.
- **[ĐÃ XÁC NHẬN SỐNG, 07/10]** Bug đồng bộ bên B bị kẹt 5 ngày (01/10 →
  06/10) — đã sửa, owner khởi động lại server xác nhận đồng bộ chạy lại
  ngay (70 job + 3 ứng viên mới, 9 bài + 2 bình luận lên lịch). Xem Tuần
  5 + `tasks.md` để biết chi tiết nguyên nhân/cách sửa.
- Cân nhắc mua proxy/IP riêng cho từng tài khoản nếu mở rộng quy mô.
- Chuyển giao diện Facebook của tài khoản `nhtu00` sang tiếng Anh theo đúng quy
  định (mục 5) — đây vẫn là hướng xử lý chính; phần "hiểu cả tiếng Việt" vừa thêm
  chỉ là lưới an toàn dự phòng, không thay thế việc này.
- **[ĐÃ XÁC NHẬN SỐNG, 2026-09-25]** Lần đăng lên tường cá nhân đầu tiên của
  `nhtu00` — owner xác nhận nút mở khung soạn bài hoạt động đúng.
- **[ĐÃ XÁC NHẬN SỐNG, 2026-09-25]** Sửa lỗi "lấy quá nhiều tin" của `nhtu00`
  hoạt động đúng trên hệ thống thật — lần sync thật lúc 08:42 sáng 25/9 chỉ lấy
  về 4 tin mới (không phải 35 như lỗi cũ), đúng trong hạn mức tính ra tại thời
  điểm đó (tối đa 5, lấy 4 vì bên B không có đủ tin phù hợp, không phải lỗi
  tính toán). Toàn bộ tin đang chờ đăng của `nhtu00` đều nằm gọn trong đúng
  "hôm nay + 2 ngày" như thiết kế, không còn tin nào lố ra ngày thứ 4. Kiểm tra
  bằng cách gọi thẳng lại công thức tính hạn mức với đúng dữ liệu tồn kho tại
  thời điểm sync, không chỉ nhìn số lượng rồi đoán.
- **[ĐÃ XEM, 2026-09-25]** Giao diện "⚠️ Task quá hạn" trên trình duyệt thật —
  owner đã xem qua (nhân dịp này còn thêm nút "🚀 Đăng ngay" thẳng trong tab
  này, xem mục ngay trên).
- Lỗi mức lương "5.000.000 JPY/giờ" — **đã xác định là lỗi dữ liệu phía bên B**,
  không cần hệ thống này sửa gì, chỉ ghi nhận.
- Nối toàn bộ hệ thống vào quy trình tự động hoàn chỉnh (chạy theo lịch/tín hiệu
  từ bên B), thay vì cần thao tác tay ở một số bước.
- Cân nhắc thêm tính năng chọn nhóm đăng theo đúng chủ đề (VD tin ngành IT → nhóm
  về IT) thay vì đăng vào mọi nhóm đã tham gia.
- **[ĐÃ LÀM — cả 2 ý, 2026-09-29]** 2 ý tưởng cho trang "Lịch đăng" (nêu ra
  2026-09-25): đã triển khai xong cả 2, xem Tuần 5 ("Đổi giờ đăng giữa 2 bài
  (giai đoạn 1)" và "Đổi giờ đăng giai đoạn 2"):
  1. **Hoán đổi lịch đăng giữa 2 bài** → nút "⇄ Đổi giờ" ở mỗi bài đang chờ.
  2. **"Mượn" giờ của 1 bài đã lên lịch khác cho task quá hạn** → nút
     "↩️ Mượn giờ" ở tab "Task quá hạn", tự tìm giờ trống mới cho bài bị
     mượn. Owner tự thử tay phát hiện 2 lỗi thật (tính thiếu hạn mức ngày)
     trước khi kịp commit — đã sửa cả 2.

**Từ đợt rà soát tổng thể (2026-09-24), chưa làm — xếp theo mức độ ưu tiên:**

- **[ĐÃ LÀM, 2026-09-25]** Bật đăng nhập thật cho `/admin` — owner đã tự điền
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` vào `.env` và khởi động lại, đăng nhập đã
  có hiệu lực.
- **[Quan trọng, chủ dự án tự làm được ngay]** Chuyển giao diện Facebook của
  `nhtu00` sang tiếng Anh theo đúng quy định (mục 5) — vẫn là hướng xử lý chính,
  phần "hiểu cả tiếng Việt" chỉ là lưới an toàn phụ.
- **[ĐÃ XONG 4/4 PHASE, 2026-09-25]** Viết test tự động cho trang
  quản trị (~5949 dòng, trước đó chỉ phần đăng nhập có test). Đã lên kế hoạch
  4 giai đoạn theo mức độ rủi ro, ưu tiên khu vực hay đổi nhất trước.
  - Phase 1 (`/admin/schedule`, đúng khu vực từng dính 2 lỗi thật tuần này)
    xong: 22 bài test HTTP + 17 bài test hàm thuần, gồm test hồi quy riêng
    cho 2 lỗi cũ. Phát hiện thêm 1 lỗi tiềm ẩn (chưa xảy ra thật) ở nút
    "Đăng ngay" phiên bản gốc — owner chọn sửa luôn.
  - Phase 2 (`/admin/reports`) xong: 17 bài test HTTP + 12 bài test hàm
    thuần cho phần thống kê/đăng lại/lên lịch lại. Không phát hiện lỗi thật
    mới trong CODE, chỉ có 2 test viết sai giả định ban đầu (tưởng bảng
    "Hoạt động gần đây" hiện nội dung bài đăng, thực ra chỉ hiện kết quả
    chạy) — tự phát hiện qua chạy thử fail, sửa lại test cho đúng thay vì
    đổi code.
  - **Rà soát lại Phase 2 trước khi push (owner yêu cầu)**: phát hiện 1 sự
    cố thật — 1 bài test (kiểm tra tính năng "Lên lịch lại" từ báo cáo)
    vô tình tạo ra 1 thư mục thật trong dự án (`accounts/acc-a/`, rỗng,
    không có dữ liệu gì bên trong) do thiếu 1 bước cô lập. Phát hiện và
    dọn sạch ngay, sửa lại test để không lặp lại. Cũng củng cố thêm vài
    chỗ kiểm tra trong test cho chắc chắn hơn, không phát hiện thêm vấn đề
    nào khác sau khi chạy lại toàn bộ nhiều lần.
  - Phase 3 (`/admin/accounts`) xong: 24 bài test HTTP cho đăng ký/xoá tài
    khoản, tạm dừng/kích hoạt lại, bật/tắt đồng bộ, giới hạn số lượng/ngày,
    và luồng "Đăng nhập & lưu phiên" (mở trình duyệt Facebook). Tự phát
    hiện và sửa 2 vấn đề trong lúc viết (không đợi owner nhắc): 1 giá trị
    mặc định sai trong công cụ test dùng chung (viết từ Phase 1, chưa ai
    dùng thật tới giờ) khiến 1 trạng thái hiển thị sai; và xác nhận qua
    thử nghiệm thật rằng nút "Mở trình duyệt đăng nhập" chạy nền không
    đảm bảo xong kịp lúc — cách viết test ban đầu (không phụ thuộc vào
    việc đó) hoá ra đã đúng ngay từ đầu.
  - Phase 4 (cuối) xong: `/admin/groups` (CRUD nhóm theo tài khoản),
    `/admin/config` (lưu cấu hình, có test hồi quy riêng cho 1 lỗi thật cũ
    đã sửa 7/9 — ép sai kiểu số làm crash), `/admin/post` (form soạn bài
    thủ công). Phát hiện 1 lỗi thật, đã hỏi rõ thiết kế và sửa xong cùng
    ngày — xem mục ngay dưới. 4/4 phase kế hoạch test cho trang quản trị
    đã xong, tổng 134 bài test mới thêm riêng cho phần này (239 → 373,
    tính cả bài test thêm cho lần sửa lỗi "Cấu hình AI" ở mục dưới).
- **[ĐÃ SỬA, 2026-09-25]** Card "Cấu hình AI" ở `/admin/config`: để trống
  ô key của nhà cung cấp đang chọn rồi bấm Lưu từng âm thầm XOÁ MẤT key
  đó (dòng chú thích cũ ghi sai "để trống = giữ nguyên key hiện tại").
  Hỏi lại owner mới rõ thiết kế ban đầu: chỉ có đúng 1 key "đang dùng"
  tại 1 thời điểm (đổi qua nhà cung cấp khác thì mất key cũ là ĐÚNG Ý,
  không phải lỗi) — riêng việc để trống ô key rồi lưu, owner muốn **báo
  lỗi, không cho lưu** thay vì âm thầm xoá. Đã sửa đúng theo đó: để
  trống ô key giờ bị chặn lại, báo "Cần nhập API key...", không lưu gì
  cả (key cũ nếu có vẫn giữ nguyên) — muốn xoá hẳn key thì bấm đúng nút
  "Xoá key" riêng. Cập nhật lại dòng chú thích trên giao diện cho khớp.
- **[ĐÃ SỬA LẠI CHO ĐÚNG, 2026-09-25]** Nút "Xoá key" ở card "Cấu hình
  AI": lúc đầu tưởng nhầm là lỗi ("xoá key mà mất luôn cả nhà cung cấp
  đang chọn và model đã gõ"), tự sửa thành "chỉ xoá đúng key, giữ nguyên
  Provider/Model". Sau khi owner giải thích rõ hơn mới biết đó là **hiểu
  sai thiết kế** — Provider + Model + Key là 1 cụm đi cùng nhau: mặc
  định dùng bộ trong `.env`, lưu bộ mới thì dùng bộ mới, và "Xoá key"
  nghĩa là **bỏ hẳn cả cụm vừa lưu, quay lại dùng `.env`** — không phải
  chỉ xoá mỗi ô key. Đã sửa lại đúng theo ý này: bấm "Xoá key" giờ đưa
  cả Provider/Model/Key về lại mặc định gốc.
- **Rà soát lại Phase 1 trước khi làm Phase 2 (owner yêu cầu)** — phát hiện
  1 lỗi thật: 1 trong các đoạn code test tự viết ra vô tình làm rò rỉ trạng
  thái giữa các bài test với nhau (test A chạy xong làm ảnh hưởng sai tới
  kết quả của test B không liên quan) — đã sửa, xác nhận hết rò rỉ bằng cách
  cố tình tái hiện lại lỗi trước rồi sau khi sửa. Cộng 1 chỗ ghi chú
  (docstring) trong code test bị sai — không ảnh hưởng gì tới kết quả test
  hiện tại, nhưng nếu để nguyên sẽ dễ gây hiểu nhầm khi làm tiếp Phase 3 —
  đã viết lại cho đúng. Chạy lại toàn bộ test 2 lần + đổi thứ tự chạy các
  file để chắc chắn không còn rò rỉ nào khác — ổn định.
- **[ĐÃ SỬA, 2026-09-25]** Nút "🚀 Đăng ngay" gốc ở tab "Chờ đăng" (dùng từ
  2026-09-09) có cùng kẽ hở đã tìm và sửa cho bản tab "Task quá hạn" hôm nay:
  nếu ai đó gửi lại `force=1` mà không qua đúng nút bấm trên giao diện, có
  thể vô tình bỏ qua luôn cả kiểm tra hạn mức số lượng, không chỉ khoảng
  cách tối thiểu như đã cam kết. Không xảy ra được trong điều kiện dùng bình
  thường (chỉ bấm nút trên UI) — chỉ là kẽ hở lý thuyết, nhưng owner chọn sửa
  luôn cho chắc. Đã sửa xong, đồng bộ với bản kia, test tự động xác nhận đúng.
- **[ĐÃ LÀM, 2026-09-25]** Owner đã tự tay thử trang đăng nhập mới trên trình
  duyệt thật, xác nhận ổn.
- **[ĐÃ LÀM, 2026-09-28]** Cơ sở dữ liệu báo cáo (`human_bot.db`) giờ tự dọn:
  giữ 6 tháng, cũ hơn thì xoá (theo yêu cầu owner, dù file hiện chỉ 176 KB —
  quyết định về giới hạn lịch sử chứ không vì dung lượng).
- **[ĐÃ QUYẾT ĐỊNH, 2026-09-28: giữ nguyên]** Nút "Chọn tất cả" ở tab "Task quá
  hạn" chỉ chọn được task đang hiển thị trên trang, không phải toàn bộ kết quả
  đang lọc qua nhiều trang — owner chốt giữ nguyên như hiện tại.
- **[ĐÃ DỌN, 2026-09-25]** 5 bài dữ liệu giả dùng để test giao diện "Task quá
  hạn" — owner xác nhận test xong, đã xoá sạch cả 5 (kèm file `.result.txt` đi
  kèm).
- **Phát hiện thêm khi điều tra "Task quá hạn" hôm nay**: service từng tắt liên
  tục ~14 tiếng 37 phút (18:05 tối 24/9 → 08:42 sáng 25/9), khiến 23 task thật
  (comment/đăng bài đã lên lịch trong lúc tắt) bị dồn vào "Task quá hạn" cùng
  lúc khi bật lại — không phải lỗi hệ thống, chỉ vì service không chạy đủ lâu.
  Owner đã tự xem và xoá 23 task này. Đáng cân nhắc (chưa làm, chỉ nêu ý): một
  cảnh báo khi service downtime quá lâu (VD >1 tiếng) có thể giúp phát hiện sớm
  hơn lần sau, tránh dồn backlog lớn — nằm cùng nhóm với mục "thêm kênh báo
  động Slack/email" đã ghi ở trên.

**[MỚI, 2026-09-30] Rà soát Admin UI + đối chiếu công cụ social-media-scheduling
tương tự trên thị trường (Buffer, Hootsuite, Planable, Sprout Social) và các bot
auto-post nhóm Facebook cạnh tranh trực tiếp (NinjaPoster, Group Posting). Owner
đã xem và **chốt ghi nhận cả 6 ý để bàn thêm**, chưa cái nào được lên kế hoạch
triển khai cụ thể:**

1. **[Owner đánh giá "chính xác", ưu tiên bàn trước — ĐÃ LÀM 2026-10-01]**
   Trình soạn "kho câu chữ" ngay trên Admin UI — tab mới "📝 Kho nội dung" ở
   `/admin/config`, sửa trực tiếp 5 danh sách (câu mở đầu bài đăng nhóm có
   kèm giới hạn visa tuỳ chọn, câu mời nhắn tin, câu khi thiếu visa/lương,
   mẫu bình luận trả lời ứng viên, tên gọi các loại visa) và lưu vào
   `runtime_config.json`, có hiệu lực ngay cho lần đăng tiếp theo — không
   cần sửa code/chạy test/commit/deploy như trước. Có chặn lưu nếu dữ liệu
   nguy hiểm (danh sách rỗng, mẫu bình luận dùng sai placeholder, opener
   không còn dòng nào dùng được cho visa khác) — không bao giờ để 1 lần lưu
   sai làm sập việc đăng bài/bình luận thật. 18 test mới, verify thêm bằng
   tay toàn bộ chuỗi Admin UI → file cấu hình → bài đăng thật. Chi tiết đầy
   đủ ở `tasks.md`, mục "Kho nội dung — trình soạn câu chữ ngay trên Admin
   UI (2026-10-01)".
   **Tự soát lại (owner yêu cầu đóng vai tester) phát hiện thêm 5 lỗ hổng
   thật** (đáng chú ý nhất: mẫu bình luận dùng sai placeholder nếu file
   cấu hình bị sửa tay/hỏng sẽ CRASH ngay lúc đăng bình luận — đã thêm
   lưới an toàn rơi về mẫu mặc định, không khác gì cách mọi nhánh AI khác
   trong dự án đã làm) và 2 chỗ giao diện chưa thuận tiện (dropdown hiện
   mã visa thô khó đọc; 5 mục liệt kê ~40 dòng input cùng lúc không thu
   gọn được) — đã sửa hết, xem chi tiết đầy đủ ở `tasks.md`.
   **Owner tự mở trình duyệt thật dùng thử, phát hiện thêm 2 lỗi chỉ hiện
   ra khi nhìn trang thật** (review HTML tĩnh ở bước trên không bắt
   được): (1) thừa 1 nút — "Lưu cấu hình" (nút chung cho cả form) và "Lưu
   Kho nội dung" (nút riêng) cùng hiện, đã ẩn nút chung khi ở tab này;
   (2) tên gọi visa dài (vừa thêm ở bước trên) làm ô chọn "Giới hạn visa"
   nở rộng ra, ép ô nhập câu co lại gần như biến mất và đẩy nút "Xoá"
   tràn ra ngoài khung — đã giới hạn chiều rộng ô chọn + đặt sàn tối
   thiểu cho ô nhập + cho xuống dòng nếu vẫn không đủ chỗ. Đã sửa cả 2,
   thêm test hồi quy, chi tiết ở `tasks.md`.
   **Owner hỏi "Giới hạn visa" có chọn được nhiều mã cùng lúc không (thay
   vì đúng 1 mã như cũ) — hợp lý, đã đổi sang chọn nhiều.** Khi đổi, phát
   hiện file cấu hình THẬT trên máy (không phải test, không commit vào
   git) đã có sẵn dữ liệu owner lưu thử qua UI từ trước (bằng chứng khớp
   với lỗi "2 nút Lưu" ở trên — service lúc đó chạy code cũ) — đã viết
   script chuyển đổi 1 lần sang cấu trúc mới, không mất nội dung. Tiện
   thể phát hiện thêm 1 lỗ hổng trong CHÍNH quy trình viết test: vài bài
   test âm thầm đọc thẳng file cấu hình thật thay vì bản cô lập riêng cho
   test (đúng điều dự án luôn tránh) — chỉ lộ ra khi owner lưu dữ liệu
   thật làm 1 test tự nhiên fail. Đã sửa tận gốc cho cả file test liên
   quan, không chỉ vá từng chỗ lẻ. Toàn bộ chi tiết ở `tasks.md`.
   **Owner chê giao diện `<select multiple>` "xấu quá" và báo nút "Lưu
   cấu hình" vẫn còn sau khi đã restart server — sửa cả 2.** (1) Đổi hộp
   chọn nhiều nhìn cũ kỹ (phải giữ Ctrl/Cmd mới chọn được nhiều) sang
   đúng kiểu dropdown đẹp đã dùng sẵn ở mọi nơi khác trong trang — bấm
   thường là bật/tắt lựa chọn ngay, không cần biết phím tắt gì. (2) Hoá
   ra việc "restart vẫn không hết" không phải lỗi code Python — nút vẫn
   đúng là có đánh dấu "ẩn" trong mã nguồn, nhưng 1 rule CSS khác của
   trang (tự đặt kiểu hiển thị riêng) vô tình đè mất tác dụng ẩn đó, nên
   nút không bao giờ thật sự biến mất trên màn hình dù code đã đúng —
   cùng đúng loại lỗi từng gặp 1 lần trước đây ở chỗ khác của trang và đã
   tự sửa, giờ gặp lại ở chỗ mới. Rút kinh nghiệm: bài test tự động trước
   đó chỉ kiểm tra có chữ "ẩn" trong mã nguồn hay không, không kiểm được
   việc có ẩn thật trên màn hình hay không, nên không bắt được lỗi này dù
   đã chạy pass nhiều lần. Chi tiết đầy đủ ở `tasks.md`.
2. **[ĐÃ XÁC NHẬN SỐNG, 2026-10-05]** Kênh báo động qua Telegram khi
   tài khoản bị khoá/đồng bộ lỗi/im lặng quá lâu/phiên sắp hết hạn/fail
   liên tiếp, cộng thêm hỏi-đáp 2 chiều, giờ quản lý nhiều người nhận
   ngay trên trang quản trị — xem Tuần 5 + `tasks.md` để biết chi tiết.
   Chưa bao gồm riêng cảnh báo "service ngừng chạy hẳn" (downtime
   14h37 phút hồi 24-25/09) — bot không tự báo được lúc chính service nó
   chạy trên đó đã tắt; để sau nếu owner thấy cần.
3. **[ĐÃ LÀM, 2026-10-02]** Bảng "sức khoẻ tài khoản" ngay trên trang chủ —
   xem Tuần 5 + `tasks.md` để biết chi tiết.
4. Tìm kiếm (theo tên job/công ty/nhóm) + xuất CSV ở trang Báo cáo — hiện chỉ
   lọc được theo tài khoản + khoảng ngày.
5. Lịch sử thay đổi cấu hình (audit log cho `runtime_config.json`) — vì
   `save_*_overrides` ghi đè cả section chứ không merge, 1 lần lưu nhầm có thể
   âm thầm mất field khác; audit trail giúp phát hiện sớm.
6. Xem "Lịch đăng" dạng calendar kéo-thả đổi giờ, thay vì bảng danh sách +
   thao tác từng cặp "⇄ Đổi giờ"/"↩️ Mượn giờ" như hiện tại.

Đã đối chiếu để không đề xuất trùng: hệ thống hiện **đã vượt** nhiều tool
thương mại cùng loại ở khía cạnh chống phát hiện (mô phỏng chuột/cuộn người
thật, fingerprint riêng ổn định theo tài khoản, AI viết N bản khác nhau cho N
nhóm, phân quyền ADMIN/MOD, ảnh chụp bằng chứng) — không cần làm thêm ở mảng
đó.

**[MỚI, vòng 2, 2026-09-30] Đào sâu thêm vào schema dữ liệu + kiến trúc 2 hệ
thống (bot ↔ bên B), đối chiếu thêm nền tảng tuyển dụng đa kênh (Workable,
Greenhouse, Bullhorn) và tool approval-queue cho nội dung AI (Hootsuite,
FastSocial.ai). Owner đồng ý ghi nhận thêm 4 ý — cũng chưa lên kế hoạch triển
khai:**

7. Gắn nhãn "nguồn nội dung" (AI viết vs mẫu cứng/template) cho từng
   task/log — `action_log` hiện có cột `source` (ai/cái gì kích hoạt) nhưng
   không có cột nào ghi content do AI hay do `_draft_job_post_placeholder()`
   tạo ra. Không có cột này thì không thể lọc ra đúng tập bài AI viết để làm
   ý số 3 ở mục [tasks.md:763](tasks.md#L763) ("rà soát diện rộng nội dung
   AI") — đây là điều kiện tiên quyết cho việc đó, không phải ý độc lập.
8. Bảng "hiệu suất từng nhóm" ở trang Nhóm (`/admin/groups`) — hiện chỉ là
   CRUD phẳng, không thấy tỉ lệ thành công/chờ duyệt/timeout của riêng từng
   nhóm (báo cáo hiện gộp theo JOB chứ không gộp theo NHÓM).
9. Tự động tạm ngưng 1 nhóm khỏi vòng xoay nếu thất bại liên tục N lần
   (circuit breaker) — đi kèm ý 8, giảm rủi ro tiếp tục đăng vào nhóm đã
   hỏng (rời nhóm/bị chặn) mà không ai phát hiện kịp.
10. Callback/webhook báo lại kết quả đăng (thành công/thất bại) cho bên B —
    kiến trúc hiện tại 1 chiều (bot chỉ GET job/candidate từ bên B, không
    báo ngược lại). Phụ thuộc bên B có muốn nhận không, cần bàn với họ
    trước khi làm.

Cố tình KHÔNG đề xuất 2 hướng vì đi ngược tinh thần "giảm dấu vết bot": phân
tích engagement (like/comment nhận được — đòi hỏi bot quay lại đọc trang
nhiều hơn, tăng tín hiệu bot) và tự động phát hiện trùng lặp văn bản giữa các
bài AI viết (cùng nhóm rủi ro với quyết định đã chốt ở mục 5, dễ báo sai hơn
lợi ích).

---

# 7. Một vài từ hay gặp trong báo cáo, giải thích ngắn gọn

- **Bot / tự động hoá**: chương trình máy tính tự làm thay việc của con người.
  Facebook không thích và tìm cách phát hiện + khoá các tài khoản hoạt động kiểu
  này.
- **Rate limit (giới hạn tốc độ)**: quy định "tối đa được đăng/bình luận bao nhiêu
  lần trong 1 khoảng thời gian", để không đăng quá nhanh/quá nhiều trông giống máy.
  Ví dụ đăng tối đa 5 bài/ngày, cách nhau tối thiểu 2 tiếng.
- **Cooldown / hạ nhiệt**: giai đoạn "chạy chậm lại" bắt buộc sau khi một tài khoản
  vừa được kích hoạt lại sau khi bị tạm dừng.
- **Bên B**: hệ thống tuyển dụng nội bộ, nơi cung cấp danh sách tin tuyển dụng và
  ứng viên mới cho hệ thống này lấy về xử lý.
- **Admin UI / trang quản trị**: trang web nội bộ để xem và điều khiển toàn bộ hệ
  thống (không dành cho khách ngoài xem).
- **Sponsored (tin trả tiền)**: tin tuyển dụng được đánh dấu ưu tiên vì có trả phí,
  cần đăng sớm hơn các tin thường.

## Kiểm tra mạng trước khi chạy task (2026-10-09)

**Vấn đề:** khi máy mất mạng, các task đến giờ vẫn được chạy và đều thất bại,
tốn 1 lượt task + 1 dòng log cho một lỗi không liên quan đến task.

**Cách làm:** trước khi tự động chạy các task đến hạn, hệ thống kiểm tra mạng
bằng cách thử mở kết nối tới Facebook và 2 máy chủ DNS công cộng (chỉ cần 1 nơi
thông). Không có mạng thì thử lại 3 lần, cách nhau 10 giây (tổng khoảng 30
giây — đủ để vượt qua một lần chập chờn ngắn mà không bắt cả hàng đợi chờ quá
lâu). Vẫn không có mạng thì các task đến hạn được đưa vào mục **Task quá hạn**
với lý do "Mất mạng", để admin xem và lên lịch lại — cùng cơ chế với trường hợp
server bị tắt.

**Lưu ý:** chỉ áp dụng cho luồng tự động; "Đăng ngay" thủ công không bị chặn.
Mất mạng kéo dài sẽ đẩy mọi task đến hạn sang "Task quá hạn" (tự huỷ sau 30 ngày).
