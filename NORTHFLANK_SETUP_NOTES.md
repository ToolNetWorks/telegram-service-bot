# Northflank Setup Notes — ToolNet V3

## Kiến trúc: 2 Project, 2 Team, 2 Service riêng biệt

| Project | Team | Service | Dockerfile | Vai trò |
|---------|------|---------|------------|---------|
| `default` | `telegram-service-bots-team` | `telegram-service-bot` | `/apps/bot-core/Dockerfile` | **Bot Core** |
| `bot-toolnet-engagement` | `douyinyoutubes-team` | `telegram-service-bot` | `/apps/engagement-api/Dockerfile` | **Engagement API** |

---

## Token Northflank (KHÔNG CHUNG NHAU)

| File `.env` | Token scope | Project |
|-------------|-------------|---------|
| `apps/bot-core/.env` | `entityId: 6adc00d51fd130aa12f0e7e5` | `default` (Bot Core) |
| `apps/engagement-api/.env` | `entityId: 6add29befb8717a4961f9471` | `bot-toolnet-engagement` (Engagement API) |

**Mỗi token chỉ thấy project của nó.** Không dùng token Bot Core để call API project Engagement API và ngược lại.

---

## Environment Variables trên Northflank Dashboard

### Bot Core (Project `default`)
```bash
BOT_TOKEN=8787606779:AAE9idKlZ-DvbMqhj4uTpZxCKFfdVHX1ZLo
ADMIN_IDS=1208342332
BOT_NAME=ToolNet
TURSO_TOKEN=eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...
TURSO_URL=libsql://lebatan220997-telegram-service-bot.aws-eu-west-1.turso.io

# BẮT BUỘC (Engagement API integration)
ENGAGEMENT_API_URL=https://p01--telegram-service-bot--jcwt7hgrrh48.code.run  # public HTTPS của Engagement API
ENGAGEMENT_API_TOKEN=445a269522cc874560d9433932b30e0352f05836f18adf13a1d8f6e47e6a9378  # = ENGAGEMENT_INTERNAL_TOKEN
DB_BACKEND=turso  # BẮT BUỘC, không fallback sqlite
```

### Engagement API (Project `bot-toolnet-engagement`)
```bash
ENVIRONMENT=production
ENGAGEMENT_INTERNAL_TOKEN=445a269522cc874560d9433932b30e0352f05836f18adf13a1d8f6e47e6a9378  # = ENGAGEMENT_API_TOKEN
VIETNAMFB_API_KEY=f3a36a51caf98be589b1a2cba89c52340e8251474b2d3fe2d430cd918217dca9fa6d11779a14750fd69386695cdbc024c80b7dafc7a6008e68fb04fdd04cbcfb
VIETNAMFB_BASE_URL=https://vietnamfb.com/
LOG_LEVEL=INFO
TZ=Asia/Ho_Chi_Minh

# KHÔNG ĐƯỢC CÓ (stateless, không DB)
# DATABASE_URL
# DATABASE_TOKEN
```

---

## Shared Secret (Internal Auth)
**Một secret 32+ ký tự dùng cho cả hai:**
- Bot Core env: `ENGAGEMENT_API_TOKEN=<secret>`
- Engagement API env: `ENGAGEMENT_INTERNAL_TOKEN=<secret>`

Hiện tại: `445a269522cc874560d9433932b30e0352f05836f18adf13a1d8f6e47e6a9378`

---

## API Endpoints quan trọng

### Engagement API (Public HTTPS)
| Endpoint | Auth | Mô tả |
|----------|------|-------|
| `GET /health` | Không | Liveness probe |
| `GET /health/ready` | Không | Readiness probe |
| `GET /v1/platforms` | `X-Internal-Token` | Danh sách 6 platform |
| `GET /v1/platforms/{slug}/categories` | `X-Internal-Token` | Categories của platform |
| `GET /v1/categories/{id}/services` | `X-Internal-Token` | Services của category |
| `POST /v1/orders` | `X-Internal-Token` | Tạo order provider |
| `GET /v1/orders/{id}/status` | `X-Internal-Token` | Trạng thái order |

### Bot Core Internal Health
| Endpoint | Mô tả |
|----------|-------|
| `GET /health` | Bot Core health (DB, providers) |

---

## Deploy Sequence (QUAN TRỌNG)

### Đúng thứ tự:
1. **Engagement API trước** → verify `/health/ready` + `/v1/platforms`
2. **Bot Core sau** → verify `/health` + Telegram UI flow

### Trước khi deploy BẤT KỲ service nào:
- **TẮT CD (Auto Deploy)** trên Dashboard của service đó
- **TẮT CI** nếu không muốn auto build
- Verify `disabledCD: true` và `disabledCI: true` qua API

---

## Kiểm tra nhanh qua API

```bash
# Bot Core project (token từ apps/bot-core/.env)
TOKEN_BOT=$(grep NORTHFLANK_TOKEN apps/bot-core/.env | cut -d'=' -f2)
curl -H "Authorization: Bearer $TOKEN_BOT" https://api.northflank.com/v1/projects/default/services

# Engagement API project (token từ apps/engagement-api/.env)
TOKEN_ENG=$(grep NORTHFLANK_TOKEN apps/engagement-api/.env | cut -d'=' -f2)
curl -H "Authorization: Bearer $TOKEN_ENG" https://api.northflank.com/v1/projects/bot-toolnet-engagement/services
```

---

## Trạng thái hiện tại (2026-10-25)

| Service | CD | CI | SHA deployed | Health |
|---------|----|----|--------------|--------|
| Bot Core | **ON** | **ON** | `cb8cd60` (đang deploy) | Chờ verify |
| Engagement API | **ON** | **ON** | `cb8cd60aa1de6d51eeb7e426dc450aaf5af296cf` | ✅ Healthy |

**CẢNH BÁO:** Cả 2 service đang có CD=ON. Push lên `master` sẽ trigger **CẢ HAI** deploy cùng lúc.

---

## Checklist trước khi push production

- [ ] Bot Core: CD=OFF, CI=OFF trên Dashboard
- [ ] Engagement API: CD=OFF, CI=OFF trên Dashboard
- [ ] Bot Core: `DB_BACKEND=turso` đã set
- [ ] Engagement API: `DATABASE_URL`, `DATABASE_TOKEN` đã **xóa**
- [ ] Shared secret `ENGAGEMENT_API_TOKEN` = `ENGAGEMENT_INTERNAL_TOKEN` đã set đúng 2 chỗ
- [ ] Bot Core `ENGAGEMENT_API_URL` trỏ đúng public HTTPS của Engagement API
- [ ] Deploy thủ công: Engagement API trước → Bot Core sau
- [ ] Verify post-deploy: 6 platforms, Member Telegram có giá, View Telegram "coming soon", wallet/orders/admin OK

---

## File .env local (KHÔNG COMMIT)

| File | Chứa |
|------|------|
| `.env` (root) | Tất cả secret cho local dev |
| `apps/bot-core/.env` | Bot Core secrets (KHÔNG có VIETNAMFB_API_KEY) |
| `apps/engagement-api/.env` | Engagement API secrets (KHÔNG có TURSO) |

---

## Northflank API hữu ích

```bash
# List services
GET /v1/projects/{projectId}/services

# Service detail
GET /v1/projects/{projectId}/services/{serviceId}

# Deployment detail
GET /v1/projects/{projectId}/services/{serviceId}/deployment

# Trigger deploy (POST)
POST /v1/projects/{projectId}/services/{serviceId}/deployment
```

---

## Lưu ý quan trọng

1. **Không bao giờ** commit file `.env` vào git (đã trong `.gitignore`)
2. **Không bao giờ** print/log secret ra terminal
3. **Mỗi project** dùng token riêng — không cross-call
4. **Engagement API stateless** — không được gắn Turso credentials
5. **Bot Core owns Turso** — orders, users, wallet, idempotency keys ở Bot Core
6. **Cross-team networking** — Engagement API dùng public HTTPS + `X-Internal-Token` auth
7. **Dockerfile path cố định** — Northflank build `/apps/engagement-api/Dockerfile` và `/apps/bot-core/Dockerfile`, **không đổi tên thư mục**

---

## Git workflow

```bash
# Commit local
git add -A && git commit -m "message"

# Push (CHỈ KHI CẢ HAI SERVICE CD=OFF)
git push origin master

# Deploy thủ công trên Dashboard: Deploy → Latest commit
```