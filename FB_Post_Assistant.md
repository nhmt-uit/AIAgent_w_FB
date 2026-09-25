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
- Chưa có kênh báo động tự động (VD nhắn Slack/email) khi một tài khoản bị Facebook
  khoá — hiện phải tự vào trang quản trị để thấy.
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

## Tuần 3 (14/09 – nay): Ưu tiên tin trả tiền + dọn hàng loạt lỗi thật

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
  (đúng 1, vẫn cấu hình trong file `.env` như trước) và **MOD** (tối đa 4 tài
  khoản phụ, do ADMIN tự thêm/xoá/đổi mật khẩu qua 1 trang quản lý riêng). Cả
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
- Chạy thử ưu tiên "tin trả tiền" với dữ liệu thật ngay khi bên B triển khai xong
  phần của họ.
- Thêm kênh báo động (Slack/email) khi có tài khoản bị Facebook khoá, thay vì phải
  tự vào xem trang quản trị.
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

**Từ đợt rà soát tổng thể (2026-09-24), chưa làm — xếp theo mức độ ưu tiên:**

- **[ĐÃ LÀM, 2026-09-25]** Bật đăng nhập thật cho `/admin` — owner đã tự điền
  `ADMIN_USERNAME`/`ADMIN_PASSWORD` vào `.env` và khởi động lại, đăng nhập đã
  có hiệu lực.
- **[Quan trọng, chủ dự án tự làm được ngay]** Chuyển giao diện Facebook của
  `nhtu00` sang tiếng Anh theo đúng quy định (mục 5) — vẫn là hướng xử lý chính,
  phần "hiểu cả tiếng Việt" chỉ là lưới an toàn phụ.
- **[ĐANG LÀM DẦN, Phase 2/4 xong 2026-09-25]** Viết test tự động cho trang
  quản trị (~5949 dòng, trước đó chỉ phần đăng nhập có test). Đã lên kế hoạch
  4 giai đoạn theo mức độ rủi ro, ưu tiên khu vực hay đổi nhất trước.
  - Phase 1 (`/admin/schedule`, đúng khu vực từng dính 2 lỗi thật tuần này)
    xong: 22 bài test HTTP + 17 bài test hàm thuần, gồm test hồi quy riêng
    cho 2 lỗi cũ. Phát hiện thêm 1 lỗi tiềm ẩn (chưa xảy ra thật) ở nút
    "Đăng ngay" phiên bản gốc — owner chọn sửa luôn.
  - Phase 2 (`/admin/reports`) xong: 17 bài test HTTP + 12 bài test hàm
    thuần cho phần thống kê/đăng lại/lên lịch lại. Không phát hiện lỗi thật
    mới, chỉ có 2 test viết sai giả định ban đầu (tưởng bảng "Hoạt động gần
    đây" hiện nội dung bài đăng, thực ra chỉ hiện kết quả chạy) — tự phát
    hiện qua chạy thử fail, sửa lại test cho đúng thay vì đổi code.
  - Còn 2 phase nữa (`/admin/accounts`, phần còn lại: groups/config/post) —
    làm dần, không vội.
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
- Cơ sở dữ liệu báo cáo (`human_bot.db`) chưa có cơ chế dọn định kỳ như các nơi
  khác — hiện còn nhỏ nên chưa gấp, nhưng sẽ phình to dần theo thời gian.
- Nút "Chọn tất cả" ở tab "Task quá hạn" hiện chỉ chọn được task đang hiển thị
  trên trang, không phải toàn bộ kết quả đang lọc qua nhiều trang — chưa quyết
  định có cần sửa thành "chọn thật sự tất cả" hay không.
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
