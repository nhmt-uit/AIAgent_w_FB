# Nghiên cứu: browser-use (cho human_bot)

Nguồn: https://github.com/browser-use/browser-use | https://docs.browser-use.com

## 1. Tóm tắt

browser-use là thư viện Python mã nguồn mở (MIT license, ~79k+ sao GitHub) cho phép
AI agent điều khiển trình duyệt thật (Chromium qua Playwright) như con người: mở
trang, click, gõ chữ, điền form, cuộn trang, đọc nội dung DOM và trích xuất dữ liệu.
Agent nhận một "task" mô tả bằng ngôn ngữ tự nhiên, LLM (Claude/GPT/Gemini/model cục
bộ qua Ollama...) sẽ lập kế hoạch và gọi các "action" (click, type, scroll, extract...)
để hoàn thành.

Đây là ứng viên phù hợp làm "bộ não hành động" cho `human_bot` — phần thực thi thao
tác trên Facebook (đăng bài, comment, like, trả lời tin nhắn) thay vì dùng Facebook
Graph API (vốn bị giới hạn nhiều với tài khoản cá nhân/group thường).

## 2. Cài đặt & sử dụng cơ bản

- Yêu cầu Python >= 3.11
- Cài: `uv add browser-use` hoặc `pip install browser-use`
- Cần Playwright cài kèm trình duyệt Chromium
- Cấu hình API key LLM trong `.env` (Anthropic/OpenAI/Google/hoặc ChatBrowserUse
  của chính họ)

Ví dụ tối giản:
```python
import asyncio
from browser_use import Agent, ChatBrowserUse

async def main():
    agent = Agent(
        task="Đăng nhập Facebook và đăng một bài viết với nội dung X",
        llm=ChatBrowserUse(model='openai/gpt-5.5'),
    )
    await agent.run()

asyncio.run(main())
```

## 3. Kiến trúc chính

- **Agent**: vòng lặp lập kế hoạch — quan sát DOM/screenshot, gọi LLM để quyết định
  action tiếp theo, thực thi, lặp lại tới khi xong task hoặc đạt max steps.
- **BrowserSession**: quản lý phiên trình duyệt (Playwright), có thể cấu hình
  `user_data_dir` / profile để giữ trạng thái đăng nhập, cookie giữa các lần chạy —
  quan trọng để không phải đăng nhập lại Facebook mỗi lần agent chạy.
- **Tools/Controller**: tập hành động chuẩn (click, type, scroll, extract_content,
  go_to_url...) và cho phép định nghĩa **custom actions/tools** riêng — ví dụ có thể
  viết action riêng "post_to_group(group_url, content)" để chuẩn hoá thao tác đăng bài.
- Hỗ trợ chạy nhiều agent song song, ghi log, chụp ảnh màn hình từng bước để debug.

## 4. Tích hợp với n8n

Có community node chính thức: `n8n-nodes-browser-use`
(docs: https://docs.browser-use.com/open-source/development/n8n-integration).

Hai hướng tích hợp:
1. **Qua Browser Use Cloud API** (cách tài liệu n8n node mô tả mặc định): n8n gọi
   API cloud của browser-use bằng credentials, gửi task bằng ngôn ngữ tự nhiên, nhận
   kết quả/trạng thái/media về. Đơn giản nhất nhưng phụ thuộc dịch vụ cloud của họ
   (có phí, dữ liệu đi qua bên thứ ba — cần cân nhắc vì liên quan tài khoản Facebook).
2. **Tự host** (khuyến nghị cho dự án này): viết một service Python nhỏ (FastAPI/
   Flask) bọc quanh `browser_use.Agent`, expose endpoint HTTP (vd `POST /run-task`),
   n8n gọi vào service này qua node HTTP Request thông thường. Cách này giữ toàn bộ
   agent + phiên đăng nhập Facebook trong hạ tầng riêng, kiểm soát được rủi ro bảo
   mật tài khoản, và dễ mở rộng thêm custom actions cho human_bot.

## 5. Rủi ro & lưu ý khi dùng cho Facebook

- **Chính sách Facebook**: Facebook cấm rõ trong Điều khoản việc dùng bot/automation
  giả làm hành vi người dùng thật (đăng bài, comment, tương tác hàng loạt) — tài
  khoản có thể bị hạn chế, checkpoint hoặc khoá nếu hành vi bất thường (tốc độ thao
  tác quá nhanh, hoạt động 24/7, nhiều action giống nhau lặp lại).
- **Giảm rủi ro về kỹ thuật** (không đảm bảo tuyệt đối, chỉ giảm khả năng bị phát
  hiện):
  - Dùng `user_data_dir` cố định để duy trì cùng một "browser fingerprint" và phiên
    đăng nhập, tránh đăng nhập lại liên tục.
  - Giới hạn tốc độ hành động (delay ngẫu nhiên giữa các bước, giới hạn số bài
    đăng/comment mỗi giờ/ngày).
  - Chạy trên IP ổn định (không đổi proxy liên tục), lý tưởng là dùng đúng IP/thiết
    bị mà tài khoản vẫn hay đăng nhập.
  - Không chạy song song nhiều action trên cùng một tài khoản.
- **Khuyến nghị**: cân nhắc dùng tài khoản Facebook thật do chính người dùng/doanh
  nghiệp sở hữu và đã "warm-up" tự nhiên, thay vì tài khoản mới tạo hàng loạt — rủi ro
  khoá tài khoản là có thật và là giới hạn cố hữu của cách tiếp cận automation trình
  duyệt (không phải giới hạn riêng của browser-use).

## 6. Đề xuất kiến trúc sơ bộ cho human_bot

```
n8n (điều phối workflow, lịch trình, trigger)
   │  HTTP Request
   ▼
FastAPI service (wrap browser-use Agent) — "human_bot"
   │  Playwright + BrowserSession (user_data_dir riêng cho từng tài khoản FB)
   ▼
Chromium thật → Facebook (đăng bài / comment / tương tác)
```

- n8n giữ vai trò lên lịch, sinh nội dung (có thể gọi LLM riêng để soạn bài/comment),
  quản lý hàng đợi task, retry, log kết quả.
- Service human_bot chỉ nhận task cụ thể (đăng bài với nội dung X vào group Y, trả
  lời comment Z...) và thực thi bằng browser-use, trả kết quả (thành công/thất bại,
  screenshot, log) về cho n8n.
- Mỗi tài khoản Facebook nên có một `user_data_dir`/profile Playwright riêng để tách
  biệt phiên đăng nhập và fingerprint.

## 7. Việc cần làm tiếp theo

- [ ] Quyết định: tự host service hay dùng Browser Use Cloud API cho bản thử nghiệm
      đầu tiên.
- [ ] Thử nghiệm đăng nhập Facebook thủ công 1 lần để lưu `user_data_dir`, sau đó cho
      agent tái sử dụng phiên đó.
- [ ] Viết custom action `post_to_facebook`, `comment_on_post` chuẩn hoá thay vì để
      agent tự suy luận từ mô tả ngôn ngữ tự nhiên mỗi lần (nhanh, ổn định, ít rủi ro
      hơn).
- [ ] Thiết kế giới hạn tốc độ (rate limit) và cơ chế log/giám sát khi tài khoản có
      dấu hiệu bị hạn chế.
- [ ] Dựng service FastAPI wrapper + Dockerfile để n8n gọi vào.

## Nguồn tham khảo

- https://github.com/browser-use/browser-use
- https://docs.browser-use.com/open-source/introduction
- https://docs.browser-use.com/open-source/development/n8n-integration
- https://docs.browser-use.com/open-source/customize/browser/all-parameters
- https://n8n.io/integrations/browser-use/
