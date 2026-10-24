# ToolNet Telegram Service Bot — V2

Bot cửa hàng dịch vụ Telegram theo luồng giao diện tham khảo RektNow. Sử dụng **Python 3 (chỉ standard library)**, SQLite, Telegram Bot API (long polling). Không cần mở cổng, tạo domain hay cài thư viện Python bổ sung.

**Phạm vi:** tiếp nhận yêu cầu rà soát vi phạm có thật, bằng chứng, quản lý đơn và phần mềm hợp pháp. Không gửi mass-report, giả lập báo cáo, khóa tài khoản tự động hoặc bảo đảm nền tảng gỡ tài khoản của người khác.

## Giao diện và nghiệp vụ V2

1. Người mới gửi `/start` -> toán CAPTCHA 1–9 + 1–9 (hết hạn sau 5 phút, đổi câu hỏi sau 3 lần sai).
2. Xác minh thành công -> chọn **2 ngôn ngữ**: Tiếng Việt và English. Menu và luồng tiếp nhận chính có bản dịch cho mỗi ngôn ngữ; **các thông báo nghiệp vụ chuyên sâu sử dụng tiếng Anh hoặc tiếng Việt**. Dùng `/language` để chọn lại.
3. `/start` sau khi xác minh CAPTCHA và chọn ngôn ngữ sẽ hiển thị `assets/gifs/welcome.gif` kèm lời chào và menu chính. Admin có thể ghi đè bằng `/setbanner`; nếu thiếu tệp hoặc Telegram không gửi được media, bot tự chuyển sang tin nhắn văn bản.
4. Menu: Wallet / Tool Access / Support / Referral / FAQ / Changelogs / My Orders / Language.
5. Tool Access mở menu con kèm ảnh `assets/gifs/tools.gif`: **Send Report / Engagement Services / Buy Tool Access / My Subscription / Back to Main Menu**. Send Report -> chọn **Telegram / TikTok / YouTube / Facebook / Instagram** -> chọn loại yêu cầu -> chọn **profile / channel / group / post/video** (tùy nền tảng) -> gửi URL/@username/ID công khai -> mô tả dấu hiệu vi phạm -> bằng chứng. Engagement Services -> **Member Telegram** -> hiển thị 3 gói member Telegram kèm giá/member, min–max, tốc độ và bảo hành; khách liên hệ Admin để đặt.
6. Khách theo dõi đơn và thanh toán từ ví VND; Admin báo giá, nhận chứng từ chuyển khoản và xác minh thủ công, duyệt hồ sơ, cập nhật trạng thái, hoàn tiền vào ví.
7. Support tickets, referral, quản trị bằng Telegram commands. 1 tài khoản tối đa 5 đơn đang mở, 3 khoản nạp đang chờ và 5 ticket/24h.

**Giới hạn Telegram:** không thể thay đổi màu nền/nút/hình dạng bàn phím gốc của Telegram Bot. Có thể dùng GIF hoặc ảnh logo riêng, tin nhắn caption và inline keyboard. Muốn giao diện Web App đầy đủ cần phát triển Mini App riêng.

## Cài mới trên Ubuntu VPS (Termius)

Tạo bot với [@BotFather](https://t.me/BotFather) qua lệnh `/newbot`. Tải ZIP lên `/home/ubuntu` bằng SFTP trong Termius:

```bash
cd /home/ubuntu
unzip ToolNet-Telegram-Service-Bot-v2.zip
cd telegram-service-bot
cp .env.example .env
nano .env
chmod 600 .env
python3 -m unittest discover -s tests -v
python3 bot.py
```

Cấu hình bắt buộc `BOT_TOKEN` từ BotFather và `ADMIN_IDS` (ID Telegram dạng số, hỗ trợ nhiều Admin ngăn cách bởi dấu phẩy). Cấu hình tên bot qua `BOT_NAME`.

GIF chào mừng mặc định nằm tại `assets/gifs/welcome.gif` và được gửi sau khi người dùng xác minh CAPTCHA, chọn ngôn ngữ rồi dùng `/start`. Ảnh menu Tool Access nằm tại `assets/gifs/tools.gif`. Bot tự tải từng tệp lên Telegram ở lần đầu và lưu `file_id` riêng vào SQLite; khi thay tệp, bot tự nhận diện và tải lại. Admin có thể ghi đè ảnh `/start` bằng `/setbanner`; nếu thiếu tệp hoặc gửi media lỗi, bot fallback sang tin nhắn văn bản.

Các biến nhận tiền `BANK_NAME`, `BANK_ACCOUNT`, `BANK_OWNER` cần đủ cả ba để mở tính năng chuyển khoản. Admin **phải tự đối chiếu giao dịch thực tế trên ứng dụng ngân hàng trước khi dùng** `/approvedep` (chứng từ ảnh có thể bị giả).

### Chạy nền bằng systemd

```bash
cd /home/ubuntu/telegram-service-bot
sudo chown -R ubuntu:ubuntu /home/ubuntu/telegram-service-bot
sudo cp telegram-service-bot.service.example /etc/systemd/system/telegram-service-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-service-bot
sudo systemctl status telegram-service-bot --no-pager
sudo journalctl -u telegram-service-bot -n 50 --no-pager
```

Ví dụ unit đặt `User=ubuntu` và `WorkingDirectory=/home/ubuntu/telegram-service-bot`. Nếu chạy với tên Linux user/path khác, phải chỉnh unit tương ứng. **Chỉ chạy một instance trên mỗi Bot Token/DB**.

## Nâng cấp từ V1 (không mất DB)

Tắt bot cũ và sao lưu SQLite bằng SQLite Backup API, **không chỉ chép file DB đang hoạt động**:

```bash
sudo systemctl stop telegram-service-bot
cd /home/ubuntu/telegram-service-bot
python3 - <<'PY'
import sqlite3
from pathlib import Path
p = Path('data/bot.sqlite3')
if not p.exists():
    raise SystemExit('Không tìm thấy data/bot.sqlite3. Kiểm tra DB_PATH trong .env')
with sqlite3.connect(str(p)) as src, sqlite3.connect(str(p.with_suffix('.backup.sqlite3'))) as dst:
    src.backup(dst)
print('Đã sao lưu DB')
PY
cd /home/ubuntu
mkdir -p /tmp/toolnet-bot-v2
unzip -o ToolNet-Telegram-Service-Bot-v2.zip -d /tmp/toolnet-bot-v2
cp /tmp/toolnet-bot-v2/telegram-service-bot/{bot.py,db.py,i18n.py,README.md} /home/ubuntu/telegram-service-bot/
cp -r /tmp/toolnet-bot-v2/telegram-service-bot/tests /home/ubuntu/telegram-service-bot/
cd /home/ubuntu/telegram-service-bot
python3 -m unittest discover -s tests -v
sudo systemctl start telegram-service-bot
sudo journalctl -u telegram-service-bot -n 50 --no-pager
```

Nếu dùng bài kiểm thử V1 cũ (còn kỳ vọng 4 dịch vụ và bỏ qua CAPTCHA), hãy cập nhật cả thư mục `tests/` từ V2 trước khi chạy test. Sau khi nâng cấp, DB có thêm 2 cột trong `users` và một cột `platform` trong `services`; dữ liệu ví, báo giá, đơn và ID cũ được giữ nguyên. User cũ cần xác minh lần đầu và chọn ngôn ngữ.

Không giải nén `.env` từ máy khác và không xóa thư mục `data/`. Cập nhật mã nguồn khi bot đã tắt.

## Admin commands

| Lệnh | Chức năng |
|---|---|
| `/admin` | Thống kê và danh sách lệnh |
| `/ordersadmin` | Xem các đơn mới |
| `/deposits` | Xem yêu cầu nạp chờ xác minh |
| `/setprice 5 500000` | Giá dịch vụ ID 5, đơn mới (0 = báo giá) |
| `/quote 10 500000` | Gửi báo giá cho đơn ID 10 |
| `/approve 10` | Xác nhận đã xét duyệt đơn trả tiền, chuyển xử lý |
| `/done 10` | Đánh dấu hoàn thành |
| `/reject 10` | Từ chối và hoàn về ví nếu đã trả |
| `/approvedep 4` | Đối chiếu ngân hàng xong mới cộng ví |
| `/rejectdep 4` | Từ chối khoản nạp |
| `/credit USER_ID 10000` | Ghi có thủ công có sổ cái |
| `/reply TICKET_ID nội_dung` | Trả lời ticket hỗ trợ |
| `/setbanner` | Reply vào ảnh hoặc GIF/animation để cài ảnh chào mừng |

## Bảo mật và vận hành

- Token BotFather chỉ nằm trong `.env`, tuyệt đối không đưa lên GitHub.
- Không yêu cầu mật khẩu, OTP, session cookies từ khách hàng.
- Chỉ dùng dữ liệu công khai và bằng chứng mà khách có quyền chia sẻ. Cần có chính sách lưu giữ/xóa dữ liệu cá nhân.
- Tiền lưu dưới dạng **số nguyên VND**, sổ cái và transaction kiểm tra trạng thái chống trừ/cộng hai lần.
- Báo cáo chỉ là hồ sơ hỗ trợ; việc xử lý nội dung thuộc quyền nền tảng.
- Ví không tích hợp cổng thanh toán online; mọi đối soát nạp là thủ công. `ADMIN_IDS` có quyền điều chỉnh ví nên cần bảo vệ nghiêm ngặt.
- Nếu lỗi Telegram API, xem `journalctl`. Nếu bot không trả lời, kiểm tra `BOT_TOKEN` đúng, chỉ có một process polling và quyền đọc/ghi DB.

Chạy kiểm thử:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile bot.py db.py i18n.py
```
