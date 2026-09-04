# Kho ảnh meme / Meme image pool

VI: Thả file ảnh (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`) trực tiếp vào
thư mục này. Khi đăng bài (`post_to_own_profile` hoặc `post_to_group`) mà
không có `media_path` nào được truyền vào rõ ràng (ví dụ: dữ liệu từ bên B
không kèm ảnh riêng), `human_bot/media.py`'s `pick_random_meme()` sẽ chọn
ngẫu nhiên một ảnh trong thư mục này để đính kèm — bật/tắt qua công tắc
"Tự động đính kèm ảnh" ở `/admin/config` (mặc định: BẬT).

Nếu dữ liệu từ bên B có kèm ảnh riêng cho bài đăng đó, ảnh của bên B luôn
được ưu tiên dùng thay vì random ảnh ở đây (xem `human_bot/agent.py`'s
`run_task()` — chỉ tự chọn ảnh ngẫu nhiên khi `media_path` chưa được đặt).

EN: Drop image files (`.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`) directly
into this folder. When posting (`post_to_own_profile` or `post_to_group`)
without an explicit `media_path` (e.g. side B's data has no image of its
own for that item), `human_bot/media.py`'s `pick_random_meme()` picks one
at random from here — toggle this via "Tự động đính kèm ảnh" in
`/admin/config` (default: ON).

If side B's data does include its own image for a given post, that image
always takes priority over a random one from here — see
`human_bot/agent.py`'s `run_task()`, which only auto-picks a random meme
when `media_path` is still unset.

NOTE (2026-09-04): the actual browser step that attaches a file to the
Facebook composer ("Photo/video" button → file chooser) has NOT been
recorded via Playwright Codegen yet — `post_to_own_profile` and
`post_to_group` currently receive a resolved `media_path` but silently
skip attaching it (see the `if media_path:` TODO blocks in
`human_bot/actions.py`). This folder/picker/toggle is the Python-side half
only; the actual attach-photo Codegen recording is still pending.
