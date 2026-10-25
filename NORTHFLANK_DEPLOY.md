# Northflank Deployment Guide — ToolNet V3 (Bot Core + Engagement API)

## 1. Kiến trúc production

V3 tách thành **hai service độc lập** trong cùng Northflank project:

```
Telegram
   |
   v
toolnet-bot-core (Worker, 1 replica)
   |-- Turso (users, wallet, orders, ledger, deposits, settings)
   |
   +--> toolnet-engagement (private HTTP :8000)
             |
             +--> VietnamFB API (provider orders/status)
```

- **Bot Core**: Telegram long polling, không public port, đúng **1 replica**.
- **Engagement API**: FastAPI **stateless**, chỉ mở port nội bộ `8000`, có thể chạy 1+ replica.
- Bot Core **không** giữ `VIETNAMFB_API_KEY` và không hardcode provider/service ID.
- Engagement API **không** giữ Turso token và không lưu đơn hàng/customer data.
- Durable idempotency và toàn bộ giao dịch tài chính nằm ở Bot Core/Turso.
- Nếu `TURSO_URL` + `TURSO_TOKEN` được đặt, Bot Core chỉ dùng Turso; không fallback SQLite âm thầm.

> Chọn region Northflank gần Turso (database đang ở `aws-eu-west-1`, nên dùng Europe/EU).
> Mỗi truy vấn Turso là một HTTPS request; đặt worker gần DB giúp giảm độ trễ.

---

## 2. Biến môi trường trên Northflank

### 2.1 Bot Core (`toolnet-bot-core`)

Secrets bắt buộc:

| Biến | Ý nghĩa |
|---|---|
| `BOT_TOKEN` | Token BotFather |
| `ADMIN_IDS` | Danh sách user ID admin, phân tách bằng dấu phẩy |
| `TURSO_URL` | `libsql://...` hoặc `https://...` của database |
| `TURSO_TOKEN` | Token Turso (quyền đọc/ghi) |
| `ENGAGEMENT_API_TOKEN` | Shared secret gọi Engagement API |

Config:

| Biến | Mặc định |
|---|---|
| `BOT_NAME` | `ToolNet Services` |
| `SUPPORT_USERNAME` | (rỗng) |
| `LOG_LEVEL` | `INFO` |
| `BANK_NAME`, `BANK_ACCOUNT`, `BANK_OWNER` | (rỗng — chỉ mở nạp tiền khi đủ 3) |
| `ENGAGEMENT_API_URL` | `http://toolnet-engagement:8000` |
| `DB_BACKEND` | `turso` |

**Không đặt trên Bot Core:** `VIETNAMFB_API_KEY`, `VIETNAMFB_BASE_URL`,
`ENGAGEMENT_INTERNAL_TOKEN`.

### 2.2 Engagement API (`toolnet-engagement`)

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `ENVIRONMENT` | Có | `production` (fail-fast nếu thiếu provider key) |
| `ENGAGEMENT_INTERNAL_TOKEN` | Có | Phải trùng `ENGAGEMENT_API_TOKEN` của Bot Core |
| `VIETNAMFB_API_KEY` | Có (production) | API key VietnamFB |
| `VIETNAMFB_BASE_URL` | Không | Mặc định `https://vietnamfb.com` |
| `HOST` | Không | `0.0.0.0` |
| `PORT` | Không | `8000` |
| `LOG_LEVEL` | Không | `INFO` |
| `REQUEST_TIMEOUT` / `CONNECT_TIMEOUT` | Không | `20` / `5` giây |
| `MAX_RETRIES` | Không | `2` (chỉ cho call đọc; **không retry** `add`) |
| `PROVIDER_CACHE_TTL` | Không | `300` giây |

**Không đặt trên Engagement API:** `TURSO_URL`, `TURSO_TOKEN`,
`DATABASE_URL`, `DATABASE_TOKEN`, `BOT_TOKEN`, `ADMIN_IDS`.

**Không commit `.env`, backup, database hay token vào git.**

---

## 3. Kiểm tra trước khi deploy

```bash
cd ~/telegram-service-bot

# Bot Core: UI, order safety, client -> API -> mock provider
cd apps/bot-core && python3 -m pytest tests -q && cd ../..

# Engagement API: contract, auth, catalog, provider classification
cd apps/engagement-api && ENVIRONMENT=test \
  ENGAGEMENT_INTERNAL_TOKEN=test_token python3 -m pytest tests -q && cd ../..

# Legacy root bot regression tests
python3 -m pytest tests -q

# Turso connectivity (không in token)
python3 tests/turso_live_check.py
python3 migrate_to_turso.py --verify-only
```

Kết quả mong đợi: tất cả test PASS, `--verify-only` PASS, không có token trong log.

Build và smoke test Docker:

```bash
docker build -t toolnet-bot-core -f apps/bot-core/Dockerfile .
docker build -t toolnet-engagement -f apps/engagement-api/Dockerfile .
```

Smoke test Engagement API (không gọi provider thật):

```bash
docker run --rm -d --name engagement-smoke \
  -e ENVIRONMENT=test \
  -e ENGAGEMENT_INTERNAL_TOKEN=smoke-token \
  -e VIETNAMFB_API_KEY=smoke-key \
  -p 18000:8000 toolnet-engagement
curl -fsS http://127.0.0.1:18000/health/live
curl -fsS -H "X-Internal-Token: smoke-token" http://127.0.0.1:18000/v1/platforms
docker rm -f engagement-smoke
```

Smoke test Bot Core nên dùng bot token test riêng và **không** bấm xác nhận đơn provider.

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

> V3 không tạo database riêng cho Engagement API. Không chạy migration
> engagement catalog trên Turso nữa; catalog do Engagement API quản lý.

---

## 5. Tạo service trên Northflank

### 5.1 Bot Core

1. **Create service → Worker**.
2. **Repository**: `ToolNetWorks/telegram-service-bot`, branch `master`.
3. **Build**: Dockerfile `apps/bot-core/Dockerfile`, build context `/`.
4. **Ports**: không tạo public port.
5. **Replicas**: `1` (cố định).
6. **Persistent volume**: không cần.
7. **Region**: Europe (gần Turso `aws-eu-west-1`).
8. **Restart policy**: `Always` / `On failure`.
9. **Termination grace period**: `30s` (long poll timeout 25s).
10. Thêm toàn bộ Secrets/Config ở mục 2.1.
11. **Health check**: dùng `python3 healthcheck.py` nếu Northflank hỗ trợ
    command health check; Dockerfile cũng có `HEALTHCHECK`.
12. **Logging**: stdout/stderr; không log token/URL.

### 5.2 Engagement API

1. **Create service → Worker/Service** (không public).
2. **Repository**: `ToolNetWorks/telegram-service-bot`, branch `master`.
3. **Build**: Dockerfile `apps/engagement-api/Dockerfile`, build context `/`.
4. **Port**: `8000`, **internal/private only**.
5. **Replicas**: `1` hoặc nhiều hơn (stateless).
6. **Persistent volume**: không cần.
7. **Health check**: `GET /health/live` (Dockerfile đã có `HEALTHCHECK`).
8. Thêm toàn bộ Secrets/Config ở mục 2.2.
9. **Không** thêm Turso credentials.

### 5.3 Kết nối nội bộ

**Trường hợp 1: Cùng Northflank project/team (khuyên dùng)**
- Hai service cùng project → private DNS hoạt động.
- Bot Core dùng `ENGAGEMENT_API_URL=http://toolnet-engagement:8000`.
- `ENGAGEMENT_API_TOKEN` (Bot Core) = `ENGAGEMENT_INTERNAL_TOKEN` (Engagement API).
- Kiểm tra từ Bot Core container:

```bash
curl -fsS -H "X-Internal-Token: $ENGAGEMENT_API_TOKEN" \
  http://toolnet-engagement:8000/v1/platforms
```

**Trường hợp 2: Khác Northflank project/team (private DNS KHÔNG hoạt động)**
- Northflank private networking **chỉ hoạt động trong cùng project**.
- Phải expose Engagement API qua **public HTTPS endpoint** có authentication.
- Cấu hình Engagement API:
  - Bật **Public Port** `8000` trên Northflank.
  - Northflank tự cấp domain `https://<service>-<project>.northflank.app` + TLS.
- Cấu hình Bot Core:
  - `ENGAGEMENT_API_URL=https://<engagement-service>-<project>.northflank.app`
  - Token `ENGAGEMENT_API_TOKEN` vẫn phải khớp `ENGAGEMENT_INTERNAL_TOKEN`.
- Kiểm tra từ Bot Core container:

```bash
curl -fsS -H "X-Internal-Token: $ENGAGEMENT_API_TOKEN" \
  https://<engagement-service>-<project>.northflank.app/v1/platforms
```

> ⚠️ **Bảo mật**: Engagement API **chỉ** chấp nhận request có header `X-Internal-Token` hợp lệ. Không cần IP allowlist thêm vì token đã đủ mạnh (shared secret 32+ chars, so sánh timing-safe). Không public Swagger/docs ở production (`docs_url=None` khi `ENVIRONMENT=production`).

### 5.4 Trạng thái production trước V3 (tham khảo lịch sử)

| Mục | Giá trị cũ |
|---|---|
| Northflank project | `default` (team `telegram-service-bots-team`) |
| Service | `telegram-service-bot` |
| Region | `europe-west` (GCP `europe-west2`) |
| Build | GitHub `ToolNetWorks/telegram-service-bot`, branch `master`, `/Dockerfile` |
| Replicas | `1` |
| Public port | Không |
| Rollout | `recreate` |
| Turso | `aws-eu-west-1` |

Đây là cấu hình **single-service cũ**. V3 cần service Engagement API riêng và
Bot Core chuyển sang Dockerfile `apps/bot-core/Dockerfile`. Không thay đổi
Northflank cho đến khi có approval và đã xác minh CI/CD.

---

## 6. Rollout V3 an toàn

> Điều kiện tiên quyết: Docker builds PASS, test PASS, đã có backup Turso,
> service Engagement API đã tạo và health check OK.

```bash
# 1. Trên VPS: dừng bot cũ, đảm bảo không còn process polling
cd ~/telegram-service-bot
./botctl.sh stop
./botctl.sh status
pgrep -af "python3 -m bot" || echo "VPS bot stopped"

# 2. Backup cuối cùng (WAL-safe)
./backup-sqlite.sh

# 3. Đồng bộ snapshot cuối lên Turso (chỉ lần đầu)
python3 migrate_to_turso.py --replace --yes
python3 migrate_to_turso.py --verify-only

# 4. Deploy Engagement API trước, kiểm tra /health/ready và /v1/platforms
# 5. Deploy Bot Core với ENGAGEMENT_API_URL trỏ tới service mới
# 6. Theo dõi log Bot Core:
#    "Database backend: Turso (remote)"
#    "Bot @... đã hoạt động"
```

### Kiểm tra sau rollout

- `/start` → xác minh captcha → menu inline.
- **Tool Access → Engagement Services** hiển thị đủ 6 nền tảng.
- **Telegram → Member Telegram** hiển thị đúng gói và giá sale (markup).
- **Telegram → View Telegram** hiển thị “đang cập nhật”, không tạo đơn giả.
- Các nền tảng chưa có provider hiển thị Coming Soon.
- Ví, nạp tiền, đơn của tôi, ngôn ngữ, Admin `/admin`.
- Không bấm xác nhận đơn provider thật khi chưa kiểm tra balance/provider.
- Log không có traceback Turso, không có token.

### Quy tắc tuyệt đối

- Không bật Northflank Bot Core khi VPS còn polling.
- Không bật lại VPS khi Northflank đang chạy.
- Nếu cần kiểm tra song song, chỉ dùng môi trường test với bot token khác.
- Không đặt `VIETNAMFB_API_KEY` trên Bot Core.
- Không đặt `TURSO_TOKEN` trên Engagement API.

---

## 7. Rollback

```bash
# 1. Northflank: scale Bot Core về 0 (dừng polling ngay)

# 2. Nếu Northflank đã phát sinh giao dịch mới: export Turso -> SQLite
cd ~/telegram-service-bot
python3 migrate_from_turso.py
# -> backups/rollback-YYYYmmdd-HHMMSS.sqlite3 (đã verify)

# 3. VPS: khôi phục database và chạy lại bằng SQLite
./botctl.sh stop
./restore-sqlite.sh backups/rollback-YYYYmmdd-HHMMSS.sqlite3
DB_BACKEND=sqlite ./botctl.sh start
```

- `DB_BACKEND=sqlite` là lựa chọn **tường minh** để bỏ qua Turso khi rollback.
  Không đặt biến này trên Northflank production.
- Nếu không có giao dịch mới trên Turso, có thể dùng backup SQLite trước
  rollout thay cho bước export.
- Luôn giữ backup trước rollout ở `backups/` (đã được `.gitignore`).
- Sau rollback, xác nhận Northflank đã scale 0 và không còn gọi `getUpdates`.

---

## 8. Vận hành & sự cố

| Triệu chứng | Kiểm tra |
|---|---|
| Bot không trả lời, log `Turso từ chối xác thực` | Sai/hết hạn `TURSO_TOKEN` |
| Log `Turso lỗi kết nối` | Mạng Northflank → Turso, region, timeout |
| Bot restart liên tục | `healthcheck.py` fail hoặc thiếu ENV bắt buộc |
| Menu Engagement báo tạm thời không khả dụng | `ENGAGEMENT_API_URL`, token, service Engagement API |
| `/health/ready` trả 503 | Thiếu `VIETNAMFB_API_KEY` hoặc catalog lỗi |
| `/health/dependencies` báo provider `error` | Provider outage; catalog vẫn dùng fallback cost |
| Đơn provider “Chờ đối soát” | Admin kiểm tra panel; nếu provider chưa nhận, hoàn tiền thủ công theo quy trình đối soát (không dùng `/reject` — lệnh đó dành cho deposit) |
| Hai bot tranh `getUpdates` | Scale Northflank 0 hoặc stop VPS ngay |
| `401 Invalid internal token` | `ENGAGEMENT_API_TOKEN` ≠ `ENGAGEMENT_INTERNAL_TOKEN` |

### Bảo vệ giao dịch

- `claim_state` nguyên tử: bấm xác nhận 2 lần chỉ tạo 1 đơn.
- Order nội bộ + trừ ví + ledger nằm trong **một transaction** Turso.
- `orders.request_key` UNIQUE chống trùng; ledger có UNIQUE(kind, reference).
- Provider trả order id → mới ghi `provider_orders`.
- Provider từ chối rõ ràng → hoàn tiền đúng 1 lần.
- Timeout/mất kết nối provider → giữ tiền, đánh dấu
  `pending_reconciliation`, cảnh báo admin; không hoàn tiền mù.
- Provider đã nhận đơn nhưng lỗi ghi DB → không hoàn tiền; admin đối soát.
- `POST /v1/orders` không bao giờ retry ở provider; chỉ retry call đọc.
