# Northflank Deployment Guide — ToolNet Telegram Service Bot (Turso)

## 1. Kiến trúc production

- **Northflank Worker service**, Telegram **long polling**.
- **Không public port**.
- **Đúng 1 replica** (không bao giờ chạy 2 nơi cùng `getUpdates`).
- **Không cần Persistent Volume** cho database: dữ liệu nằm trên **Turso**.
- Container chạy non-root, có `SIGTERM` graceful shutdown, health check DB.
- Nếu `TURSO_URL` + `TURSO_TOKEN` được đặt, bot **chỉ** dùng Turso.
  Không có fallback âm thầm sang SQLite. Turso lỗi → bot dừng và để
  Northflank restart; dữ liệu không bị ghi nhầm vào file local.

```
Telegram  <--long poll-->  Northflank Worker (1 replica)
                                  |
                                  +--> Turso (libSQL, HTTPS/Hrana v2)
                                  +--> VietnamFB API (đặt đơn)
```

> **Chọn region Northflank gần Turso** (database đang ở
> `aws-eu-west-1`). Nên chọn Europe/EU. Mỗi truy vấn Turso là một HTTPS
> request; đặt worker ở EU giúp giảm độ trễ từ ~1s (VPS châu Á) xuống
> vài chục ms.

---

## 2. Biến môi trường trên Northflank

### Secrets (bắt buộc)

| Biến | Ý nghĩa |
|---|---|
| `BOT_TOKEN` | Token BotFather |
| `ADMIN_IDS` | Danh sách user ID admin, phân tách bằng dấu phẩy |
| `VIETNAMFB_API_KEY` | API key VietnamFB |
| `TURSO_URL` | `libsql://...` hoặc `https://...` của database |
| `TURSO_TOKEN` | Token Turso (quyền đọc/ghi) |

### Config (không bí mật)

| Biến | Mặc định |
|---|---|
| `BOT_NAME` | `ToolNet Services` |
| `SUPPORT_USERNAME` | (rỗng) |
| `LOG_LEVEL` | `INFO` |
| `BANK_NAME`, `BANK_ACCOUNT`, `BANK_OWNER` | (rỗng — chỉ mở nạp tiền khi đủ 3) |
| `VIETNAMFB_BASE_URL` | `https://vietnamfb.com` |

Không cần đặt `DB_PATH` khi dùng Turso. `DB_PATH` chỉ dùng cho dev/test
hoặc rollback SQLite.

**Không commit `.env`, backup, database hay token vào git.**

---

## 3. Kiểm tra trước khi deploy

Chạy trên VPS (bot production vẫn đang chạy trong bước này):

```bash
cd ~/telegram-service-bot
python3 -m unittest discover -s tests -v          # 32 test, không gọi API thật
python3 tests/turso_live_check.py                 # kết nối + transaction thật
python3 tests/turso_app_check.py                  # end-to-end với provider mock
python3 migrate_to_turso.py --verify-only         # so sánh SQLite ↔ Turso
```

Kết quả mong đợi: tất cả `OK`, `MIGRATE THÀNH CÔNG`, không có token
trong log.

Build và smoke test Docker:

```bash
sudo docker build -t telegram-service-bot .
sudo ./docker-smoke-test.sh
```

---

## 4. Migrate dữ liệu SQLite → Turso

Script tạo backup WAL-safe trước, giữ nguyên ID, ví, referral, đơn,
provider order, nạp tiền, ledger, ticket và settings.

```bash
# Xem trước số bản ghi, không ghi gì
python3 migrate_to_turso.py --dry-run

# Lần đầu / đồng bộ lại toàn bộ (xoá dữ liệu nghiệp vụ trên Turso rồi copy)
python3 migrate_to_turso.py --replace --yes

# Kiểm tra lại
python3 migrate_to_turso.py --verify-only
```

Script **từ chối** ghi đè nếu Turso đã có users/orders/ledger mà không
có `--replace`. SQLite gốc không bao giờ bị xoá/sửa.

---

## 5. Tạo service trên Northflank

1. **Create service → Worker**.
2. **Repository**: `ToolNetWorks/telegram-service-bot`, branch `master`.
3. **Build**: Dockerfile.
4. **Ports**: không tạo public port.
5. **Replicas**: `1` (cố định).
6. **Persistent volume**: không cần.
7. **Region**: Europe (gần Turso `aws-eu-west-1`).
8. **Restart policy**: `Always` / `On failure`.
9. **Termination grace period**: `30s` (long poll timeout 25s).
10. Thêm toàn bộ Secrets/Config ở mục 2.
11. **Health check**: Dockerfile đã có
    `HEALTHCHECK CMD ["python3","healthcheck.py"]`.
    Nếu Northflank hỗ trợ command health check, dùng:
    `python3 healthcheck.py` (timeout 15s, interval 60s).
12. **Logging**: stdout/stderr; không log token/URL.

Deploy nhưng **chưa start** (hoặc start với replicas=0) cho đến bước
cutover.

### 5.1 Trạng thái production hiện tại (2026-10-24)

| Mục | Giá trị |
|---|---|
| Northflank project | `default` (team `telegram-service-bots-team`) |
| Service | `telegram-service-bot` |
| Region | `europe-west` (GCP `europe-west2`) |
| Plan | `nf-compute-20` (0.2 vCPU / 512 MB) |
| Build | GitHub `ToolNetWorks/telegram-service-bot`, branch `master`, `/Dockerfile` |
| Image commit | `29c4bf7` |
| Replicas | `1` |
| Public port | Không |
| CI | Đã tắt (`disabledCI=true`) để tránh auto-deploy ngoài ý muốn |
| Rollout | `recreate` — container cũ dừng trước khi container mới start |
| Health check | CMD `python3 healthcheck.py`, liveness, 60s/lần, timeout 20s, 3 lần fail |
| Turso | `aws-eu-west-1` |
| VPS | Đã dừng bot; `botctl.sh start` bị chặn nếu `TURSO_URL` có trong `.env` |

Backup trước cutover: `backups/bot.sqlite3.20261024-024100.backup`
Rollback snapshot sau cutover: `backups/rollback-20261024-024459.sqlite3`

> Sau cutover, **Turso là nguồn dữ liệu chính**. Không chạy
> `migrate_to_turso.py --replace` từ SQLite VPS nữa (SQLite đã cũ).
> Nếu cần rollback, dùng `migrate_from_turso.py` để export Turso → SQLite.

---

## 6. Cutover an toàn (một chiều)

> Điều kiện tiên quyết: Docker tests PASS, `--verify-only` PASS, đã có
> backup SQLite, Northflank service sẵn sàng.

```bash
# 1. Trên VPS: dừng bot, đảm bảo không còn process polling
cd ~/telegram-service-bot
./botctl.sh stop
./botctl.sh status
pgrep -af "python3 -m bot" || echo "VPS bot stopped"

# 2. Backup cuối cùng (WAL-safe)
./backup-sqlite.sh

# 3. Đồng bộ snapshot cuối lên Turso
python3 migrate_to_turso.py --replace --yes
python3 migrate_to_turso.py --verify-only

# 4. Trên Northflank: scale service lên 1 replica / bấm Deploy
#    (chỉ sau khi bước 1 đã xác nhận VPS không còn polling)

# 5. Theo dõi log Northflank
#    "Database backend: Turso (remote)"
#    "Bot @ToolNettBot đã hoạt động, admin count=1"
```

> Quy trình trên chỉ dùng cho **lần cutover đầu tiên**. Sau khi Northflank
> đã chạy, không migrate SQLite → Turso nữa; SQLite VPS đã cũ. Xem mục 5.1.

### Kiểm tra sau cutover

- `/start` → xác minh captcha → menu inline.
- Ví, Tool Access, Engagement, Telegram Members (chỉ mở báo giá;
  **không bấm xác nhận** khi API balance = 0).
- Đơn của tôi, ngôn ngữ, Admin `/admin`.
- Log không có traceback Turso, không có token.

### Quy tắc tuyệt đối

- Không bật Northflank khi VPS còn polling.
- Không bật lại VPS khi Northflank đang chạy.
- Nếu cần kiểm tra song song, chỉ dùng môi trường test với bot token
  khác.

---

## 7. Rollback

```bash
# 1. Northflank: scale về 0 (dừng polling ngay)

# 2. Nếu Northflank đã phát sinh giao dịch mới: export Turso -> SQLite
cd ~/telegram-service-bot
python3 migrate_from_turso.py
# -> backups/rollback-YYYYmmdd-HHMMSS.sqlite3 (đã verify)

# 3. VPS: khôi phục database và chạy lại bằng SQLite
./botctl.sh stop
./restore-sqlite.sh backups/rollback-YYYYmmdd-HHMMSS.sqlite3
DB_BACKEND=sqlite ./botctl.sh start
```

- `DB_BACKEND=sqlite` là lựa chọn **tường minh** để bỏ qua Turso khi
  rollback. Không đặt biến này trên Northflank.
- Nếu không có giao dịch mới trên Turso, có thể dùng backup SQLite
  trước cutover thay cho bước export.
- Luôn giữ backup trước cutover ở `backups/` (đã được `.gitignore`).
- Sau rollback, xác nhận Northflank đã scale 0 và không còn gọi
  `getUpdates`.

---

## 8. Vận hành & sự cố

| Triệu chứng | Kiểm tra |
|---|---|
| Bot không trả lời, log `Turso từ chối xác thực` | Sai/hết hạn `TURSO_TOKEN` |
| Log `Turso lỗi kết nối` | Mạng Northflank → Turso, region, timeout |
| Bot restart liên tục | `healthcheck.py` fail hoặc thiếu ENV bắt buộc |
| `Không kết nối được Turso` lúc start | Không fallback SQLite; sửa ENV rồi restart |
| Đơn provider “Chờ đối soát” | Admin kiểm tra panel; hoàn tiền bằng `/reject <order_id>` nếu provider chưa nhận |
| Hai bot tranh `getUpdates` | Scale Northflank 0 hoặc stop VPS ngay |

### Bảo vệ giao dịch

- `claim_state` nguyên tử: bấm xác nhận 2 lần chỉ tạo 1 đơn.
- Order nội bộ + trừ ví + ledger nằm trong **một transaction** Turso.
- `request_key` UNIQUE chống trùng; ledger có UNIQUE(kind, reference).
- Provider trả order id → mới ghi `provider_orders`.
- Provider từ chối rõ ràng → hoàn tiền đúng 1 lần.
- Timeout/mất kết nối provider → giữ tiền, đánh dấu
  `pending_reconciliation`, cảnh báo admin; không hoàn tiền mù.
- Provider đã nhận đơn nhưng lỗi ghi DB → không hoàn tiền; admin đối soát.
