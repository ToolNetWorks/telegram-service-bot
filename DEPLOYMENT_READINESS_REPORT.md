# ToolNet V3 — Deployment Readiness Report

**Date:** 2026-10-25  
**Commit SHA:** `cb8cd60aa1de6d51eeb7e426dc450aaf5af296cf` (local master, 1 commit ahead of origin)  
**Branch:** `master` (not pushed)

---

## 1. Files Staged & Committed

**62 files** committed in `cb8cd60`:

| Category | Files |
|----------|-------|
| Root config/docs | `.dockerignore`, `.env.example`, `NORTHFLANK_DEPLOY.md`, `README.md`, `V3_SPLIT_REPORT.md`, `docs/env-configuration.md`, `docs/engagement-api-contract.md` |
| Bot Core source | 32 files (handlers, keyboards, clients, repositories, migrations, state, config, Dockerfile, etc.) |
| Engagement API source | 23 files (routes, catalog, services, providers, schemas, core, Dockerfile, etc.) |
| Tests | 7 files (Bot Core: 4, Engagement API: 3) |

**Not staged (correctly ignored):**
- `.env`, `apps/bot-core/.env`, `apps/engagement-api/.env` (real credentials)
- `backups/`, `data/`, `*.sqlite3*`
- `__pycache__/`, `*.pyc`, `.pytest_cache/`

---

## 2. Tests & Docker Build Verification

| Test Suite | Result |
|------------|--------|
| Root regression tests | ✅ 41 passed |
| Bot Core unit tests | ✅ 28 passed |
| Engagement API unit tests | ✅ 23 passed (1 StarletteDeprecationWarning only) |
| **Total** | **92 passed** |

| Docker Image | Build | Smoke Test | Image Hygiene |
|--------------|-------|------------|---------------|
| `toolnet-bot-core:v3-final` | ✅ | ✅ imports, migrations, healthcheck | ✅ No `.env`, tests, caches, `turso_client.py` only in Bot Core |
| `toolnet-engagement:v3-final` | ✅ | ✅ `/health/live`, `/v1/platforms` auth, `/v1/orders` auth | ✅ No `.env`, tests, caches, no Turso client |

---

## 3. Northflank Connectivity Status

### Current Documentation Assumption
- Both services in **same Northflank project/network** → private DNS works
- Bot Core: `ENGAGEMENT_API_URL=http://toolnet-engagement:8000`

### Cross-Team Scenario (Documented in NORTHFLANK_DEPLOY.md & README.md)
**If services are in different Teams/projects:**

| Component | Configuration |
|-----------|---------------|
| Engagement API | Enable **Public Port 8000** → Northflank provisions `https://<service>-<project>.northflank.app` with managed TLS |
| Bot Core | `ENGAGEMENT_API_URL=https://<engagement-service>-<project>.northflank.app` |
| Authentication | `X-Internal-Token` header (shared secret, timing-safe comparison) on **every `/v1/*` request** |
| Security | No IP allowlist needed; token is 32+ char shared secret; Swagger/docs disabled in production (`docs_url=None`) |

> ⚠️ **Action Required**: Confirm Northflank project/team topology before deploy. If different teams, Engagement API **must** be deployed with public port first.

---

## 4. Provider Readiness (VietnamFB)

| Item | Status |
|------|--------|
| Provider abstraction | ✅ `Provider` ABC, `ProviderError(definitive: bool)` |
| VietnamFB client | ✅ Async `httpx`, `/api/v2` endpoint, actions: services/add/status/balance |
| Catalog allow-list | ✅ 6 platforms, Telegram: Member/View, 3 Member services (1720, 1510, 1694) |
| Fallback costs | ✅ Configured in catalog (`cost_source="configured"` on provider outage) |
| Error classification | ✅ 408/425/timeout/5xx → ambiguous; other 4xx → definitive |
| `add` never retried | ✅ Timeout may still create order → ambiguous |
| Rate limiting | ✅ Per-client IP fixed window (backstop only) |
| Structured logging | ✅ JSON + correlation ID middleware |

**Production requirement:** `VIETNAMFB_API_KEY` must be set in Engagement API service secrets.

---

## 5. Order Safety Verification

| Safety Property | Implementation |
|-----------------|----------------|
| **No double charge** | `begin_provider_order`: atomic `INSERT orders` + `UPDATE users balance` in single transaction; `request_key` UNIQUE |
| **No double refund** | `refund_provider_order`: status transition + wallet credit in transaction; `ledger.UNIQUE(kind, reference)` guard |
| **No duplicate provider call** | `begin_provider_order` returns `"duplicate"` on `request_key` race/lost commit; handler never calls provider for duplicate |
| **Crash/restart safe** | `request_key` persists in Turso; replayed confirmation finds existing order → "duplicate" |
| **Ambiguous outcome** | `pending_reconciliation` status preserves charge; admin alerted; manual/provider reconciliation |
| **State consumption** | `claim_state()` atomic `UPDATE users SET state='' WHERE state=expected` prevents double-submit |
| **Legacy callback compat** | `engagement:telegram_members`, `tg_member_select:<id>`, `tg_member_confirm_pay[...]` all functional |

---

## 6. Pricing Verification (Telegram Members)

| Service ID | Name | Provider Cost (rate_milli) | Markup | Sale Price/1K |
|------------|------|---------------------------|--------|---------------|
| 1720 | Telegram Members HQ | 40,686 | 100% | **81,372 VND** |
| 1510 | Telegram Members PLUS | 47,664 | 100% | **95,328 VND** |
| 1694 | Telegram Premium Members | 142,330 | 100% | **284,660 VND** |

**Formula:** `sale_price = rate_milli * (100 + markup) // 100` → unchanged from pre-V3.

---

## 7. Credentials Rotation Status

**Local `.env` files contain real credentials** (gitignored, not committed):
- `BOT_TOKEN=8787606779:AAE9idKlZ-DvbMqhj4uTpZxCKFfdVHX1ZLo`
- `TURSO_TOKEN=eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...` (Turso JWT)
- `NORTHFLANK_TOKEN=nf-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`

**Recommendation:** Rotate all three before production deploy as security best practice (even though never committed to git).

---

## 8. Deployment Sequence

### Phase 1: Engagement API (Deploy First)
1. Create Northflank service `toolnet-engagement`
   - Dockerfile: `apps/engagement-api/Dockerfile`, build context `/`
   - **Port 8000**: Private (same project) OR Public (different teams)
   - Replicas: 1+ (stateless)
   - Health check: `GET /health/live`
2. Set secrets:
   ```
   ENVIRONMENT=production
   ENGAGEMENT_INTERNAL_TOKEN=<shared-secret>
   VIETNAMFB_API_KEY=<provider-key>
   VIETNAMFB_BASE_URL=https://vietnamfb.com
   ```
3. Verify:
   ```bash
   curl -fsS https://<engagement-url>/health/live
   curl -fsS -H "X-Internal-Token: $TOKEN" https://<engagement-url>/v1/platforms
   # Should return 6 platforms, Telegram enabled, others coming_soon
   ```

### Phase 2: Bot Core (Deploy After Engagement API Ready)
1. Create/update Northflank service `toolnet-bot-core`
   - Dockerfile: `apps/bot-core/Dockerfile`, build context `/`
   - Worker, 1 replica, no public port
   - Health check: `python3 healthcheck.py`
2. Set secrets:
   ```
   BOT_TOKEN=<from BotFather>
   ADMIN_IDS=<comma-separated>
   TURSO_URL=libsql://...
   TURSO_TOKEN=<turso-token>
   ENGAGEMENT_API_URL=http://toolnet-engagement:8000  # or public HTTPS URL
   ENGAGEMENT_API_TOKEN=<same-shared-secret>
   DB_BACKEND=turso
   ```
3. Verify logs:
   ```
   Database backend: Turso (remote)
   Bot @<username> đã hoạt động
   ```

### Phase 3: Post-Deploy Verification
- Tool Access → Engagement Services → 6 platforms visible
- Telegram → Member Telegram → 3 packages with correct sale prices
- Telegram → View Telegram → "đang cập nhật" (no fake orders)
- YouTube/Twitter/Facebook/Instagram/Shopee → "Coming Soon"
- Wallet, deposits, orders, admin panel functional
- No traceback, no tokens in logs

---

## 9. Auto-Deploy Control

**Current state:** Northflank auto-deploy is **enabled** on `master` branch.

**Required action before push:**
1. Disable auto-deploy on **both** services in Northflank dashboard
2. Push to `master`
3. Manually trigger deploy: Engagement API first → verify → Bot Core
4. Re-enable auto-deploy only after successful V3 rollout

---

## 10. Rollback Plan

| Rollback Target | Method |
|-----------------|--------|
| **Code** | `git revert cb8cd60` or `git reset --hard origin/master` (previous commit `cab4edc`) |
| **Bot Core image** | Northflank: rollback to previous image tag (pre-V3 `telegram-service-bot` image) |
| **Engagement API image** | Northflank: scale to 0 (new service, no previous image) |
| **Turso data** | `python3 migrate_from_turso.py` → export to SQLite backup; or use pre-cutover backup in `backups/` |
| **Northflank services** | Scale Bot Core to 0 → stop polling immediately |

---

## 11. Remaining Blockers

| Blocker | Severity | Resolution |
|---------|----------|------------|
| **Northflank project/team topology unknown** | 🔴 Critical | Confirm if Bot Core & Engagement API in same project. If different, Engagement API needs public port. |
| **Auto-deploy enabled on master** | 🔴 Critical | Disable in Northflank dashboard before `git push` |
| **Production credentials not rotated** | 🟡 High | Rotate `BOT_TOKEN`, `TURSO_TOKEN`, `NORTHFLANK_TOKEN` before production |
| **VIETNAMFB_API_KEY not set in Northflank** | 🔴 Critical | Add to Engagement API service secrets |
| **Shared internal token not generated** | 🔴 Critical | Generate 32+ char secret, set as `ENGAGEMENT_API_TOKEN` (Bot Core) and `ENGAGEMENT_INTERNAL_TOKEN` (Engagement API) |
| **Turso backup not verified** | 🟡 High | Run `python3 migrate_to_turso.py --verify-only` before cutover |

---

## 12. Go/No-Go Decision

| Criteria | Status |
|----------|--------|
| All 92 tests pass | ✅ |
| Docker builds + smoke tests pass | ✅ |
| No secrets in images | ✅ |
| Order safety verified | ✅ |
| Pricing unchanged | ✅ |
| Legacy callbacks work | ✅ |
| Cross-team networking documented | ✅ |
| **Auto-deploy controlled** | ❌ **Blocker** |
| **Northflank topology confirmed** | ❌ **Blocker** |
| **Production secrets configured** | ❌ **Blocker** |

**Verdict:** **NOT READY FOR PUSH** — resolve 3 blockers above first.

---

*Report generated from commit `cb8cd60` on 2026-10-25.*