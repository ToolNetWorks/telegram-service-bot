# Northflank Path Rules Configuration — ToolNet V3 Monorepo

**Pattern:** 1 GitHub repo (`ToolNetWorks/telegram-service-bot`) + 1 branch (`master`) + 2 independent Northflank services (like douyin-youtube)

**Verified:** 2026-10-25 via Northflank API (both team tokens)

---

## Current State (Verified 2026-10-25)

| Service | Project | Team | Dockerfile | Build Context | CI | CD | Path Rules |
|---------|---------|------|------------|---------------|----|----|------------|
| **Bot Core** | `default` | `telegram-service-bots-team` | `/apps/bot-core/Dockerfile` | `/` (repo root) | **ON** (`disabledCI: false`) | **ON** (`disabledCD: null`) | ❌ None (`pathIgnoreRules: []`, `isAllowList: false`) |
| **Engagement API** | `bot-toolnet-engagement` | `douyinyoutubes-team` | `/apps/engagement-api/Dockerfile` | `/` (repo root) | **ON** (`disabledCI: false`) | **ON** (`disabledCD: null`) | ❌ None (`pathIgnoreRules: []`, `isAllowList: false`) |

**Problem:** Both services watch **all changes** on `master` → every push triggers **both** builds/deploys.

**Note:** `disabledCD: null` means CD is enabled (default). Northflank API returns `null` for enabled CD, `false` for explicitly disabled.

---

## Architecture: Dual Turso Databases

| Service | Turso Database | Purpose |
|---------|----------------|---------|
| **Bot Core** | `libsql://lebatan220997-telegram-service-bot.aws-eu-west-1.turso.io` | Users, wallet, orders, deposits, referrals, admin, audit logs — **all durable state** |
| **Engagement API** | `libsql://checkpass001-bottelegram-checkpass.aws-eu-west-1.turso.io` | **Separate database** — reserved for future catalog persistence, provider sync logs, rate limiting state (currently unused by code) |

**Key Principle:** Each service owns its Turso. Engagement API code currently **does not use** its DATABASE_URL/TOKEN (stateless design), but the database exists for future migration needs.

---

## Required Path Rules (Allow List Mode)

### North 1 — Bot Core
**Project:** `default` | **Team:** `telegram-service-bots-team` | **Service:** `telegram-service-bot`

```json
{
  "buildConfiguration": {
    "pathIgnoreRules": [
      "apps/bot-core/**",
      "turso_client.py",
      "assets/**"
    ],
    "isAllowList": true,
    "ciIgnoreFlagsEnabled": false,
    "ciIgnoreFlags": [],
    "ignoreEmptyCommits": false
  }
}
```

**Rationale (from Dockerfile COPY commands):**
| Path | Reason |
|------|--------|
| `apps/bot-core/**` | Main application code + requirements.txt |
| `turso_client.py` | Copied to `/app/turso_client.py` (Turso transport — only DB driver) |
| `assets/**` | Copied to `/app/assets/` (static assets: images, templates) |

**Explicitly excluded (do NOT trigger Bot Core):**
- `apps/engagement-api/**` → Engagement API code
- `packages/contracts/**` → Not imported yet (future shared)
- Root files: `*.md`, `*.sh`, `Dockerfile`, `.env*`, `*.py` (bot.py, db.py, healthcheck.py, etc.), `database/**`, `scripts/**`, `docs/**`

---

### North 2 — Engagement API
**Project:** `bot-toolnet-engagement` | **Team:** `douyinyoutubes-team` | **Service:** `telegram-service-bot`

```json
{
  "buildConfiguration": {
    "pathIgnoreRules": [
      "apps/engagement-api/**"
    ],
    "isAllowList": true,
    "ciIgnoreFlagsEnabled": false,
    "ciIgnoreFlags": [],
    "ignoreEmptyCommits": false
  }
}
```

**Rationale (from Dockerfile COPY commands):**
| Path | Reason |
|------|--------|
| `apps/engagement-api/**` | Main application code + requirements.txt |

**Explicitly excluded (do NOT trigger Engagement API):**
- `apps/bot-core/**` → Bot Core code
- `turso_client.py`, `assets/**` → Bot Core only
- `packages/contracts/**` → Not imported yet (future shared)
- Root files, scripts, docs, etc.

---

## Shared Files Analysis (Verified by Code Audit)

| File/Directory | Used by Bot Core | Used by Engagement API | Action |
|----------------|------------------|------------------------|--------|
| `apps/bot-core/**` | ✅ Yes (COPY) | ❌ No | Bot Core only |
| `apps/engagement-api/**` | ❌ No | ✅ Yes (COPY) | Engagement API only |
| `turso_client.py` | ✅ Yes (COPY) | ❌ No | Bot Core only |
| `assets/**` | ✅ Yes (COPY) | ❌ No | Bot Core only |
| `packages/contracts/**` | ❌ Not imported | ❌ Not imported | **Future: add to both allow lists when used** |
| Root `*.py` (`bot.py`, `db.py`, `healthcheck.py`, `i18n.py`, `migrate_*.py`, `turso_client.py`, `vietnamfb_api.py`) | ❌ Not in Docker COPY | ❌ No | Neither (dev/ops only) |
| `database/**`, `scripts/**`, `docs/**`, `*.md`, `*.sh`, `Dockerfile` (root) | ❌ No | ❌ No | Neither |
| `packages/contracts/api.py` | ❌ Not imported | ❌ Not imported | Shared contracts — **add to both when adopted** |

---

## CI/CD Status (Verified)

| Service | CI | CD | Decision |
|---------|----|----|----------|
| Bot Core | **ON** (`disabledCI: false`) | **ON** (`disabledCD: null`) | **Keep ON** — Path Rules will filter |
| Engagement API | **ON** (`disabledCI: false`) | **ON** (`disabledCD: null`) | **Keep ON** — Path Rules will filter |

**Do NOT disable CI/CD** — Path Rules replace the need to disable. With correct Path Rules:
- Push to `master` changing only `apps/bot-core/` → **Only Bot Core builds**
- Push to `master` changing only `apps/engagement-api/` → **Only Engagement API builds**
- Push changing both → **Both build** (correct)
- Push changing only docs/scripts/root files → **Neither builds** (correct)

---

## How to Configure (Manual — Dashboard)

### North 1 — Bot Core (Project: `default`, Team: `telegram-service-bots-team`)
1. Open Northflank Dashboard → Team `telegram-service-bots-team` → Project `default` → Service `telegram-service-bot`
2. Settings → **Build** → **Build Configuration**
3. Set:
   - **Path rules mode:** `Allow list` (`isAllowList: true`)
   - **Paths that trigger build:**
     ```
     apps/bot-core/**
     turso_client.py
     assets/**
     ```
4. Save → Next push to `master` will only build Bot Core if these paths change.

### North 2 — Engagement API (Project: `bot-toolnet-engagement`, Team: `douyinyoutubes-team`)
1. Open Northflank Dashboard → Team `douyinyoutubes-team` → Project `bot-toolnet-engagement` → Service `telegram-service-bot`
2. Settings → **Build** → **Build Configuration**
3. Set:
   - **Path rules mode:** `Allow list` (`isAllowList: true`)
   - **Paths that trigger build:**
     ```
     apps/engagement-api/**
     ```
4. Save → Next push to `master` will only build Engagement API if these paths change.

---

## Verification Commands (API)

```bash
# Bot Core token (team: telegram-service-bots-team)
TOKEN_BOT=$(grep NORTHFLANK_TOKEN apps/bot-core/.env | cut -d'=' -f2)

# Engagement API token (team: douyinyoutubes-team)
TOKEN_ENG=$(grep NORTHFLANK_TOKEN apps/engagement-api/.env | cut -d'=' -f2)

# Verify Bot Core buildConfiguration
curl -H "Authorization: Bearer $TOKEN_BOT" \
  "https://api.northflank.com/v1/projects/default/services/telegram-service-bot?includeConfig=true" \
  | jq '.data.buildConfiguration'

# Verify Engagement API buildConfiguration
curl -H "Authorization: Bearer $TOKEN_ENG" \
  "https://api.northflank.com/v1/projects/bot-toolnet-engagement/services/telegram-service-bot?includeConfig=true" \
  | jq '.data.buildConfiguration'
```

**Expected output after config:**
```json
// Bot Core
{
  "pathIgnoreRules": ["apps/bot-core/**", "turso_client.py", "assets/**"],
  "isAllowList": true,
  "ciIgnoreFlagsEnabled": false,
  "ciIgnoreFlags": [],
  "ignoreEmptyCommits": false
}

// Engagement API
{
  "pathIgnoreRules": ["apps/engagement-api/**"],
  "isAllowList": true,
  "ciIgnoreFlagsEnabled": false,
  "ciIgnoreFlags": [],
  "ignoreEmptyCommits": false
}
```

---

## Trigger Testing (Verification Plan — No Production Test Commits)

> **Requirement:** Không tạo commit thử nghiệm trên production master. Ưu tiên kiểm tra cấu hình và thử trên môi trường không ảnh hưởng khách hàng.

### Verification Method: Northflank Preview Deployments
Northflank supports **Preview Environments** for pull requests. Configure in Dashboard:
- Enable "Preview deployments" for each service
- Create a test PR with changes to `apps/bot-core/` only → Verify only Bot Core preview builds
- Create a test PR with changes to `apps/engagement-api/` only → Verify only Engagement API preview builds
- Create a test PR with changes to `README.md` only → Verify **neither** builds

### Test Matrix (to verify after Path Rules configured)

| Scenario | Changed Paths | Expected Bot Core | Expected Engagement API |
|----------|---------------|-------------------|------------------------|
| Bot Core only | `apps/bot-core/**` | ✅ Build | ❌ Skip |
| Engagement API only | `apps/engagement-api/**` | ❌ Skip | ✅ Build |
| Both apps | `apps/bot-core/**` + `apps/engagement-api/**` | ✅ Build | ✅ Build |
| Shared contracts (future) | `packages/contracts/**` | ✅ Build (when added) | ✅ Build (when added) |
| Docs/scripts only | `README.md`, `*.sh`, `docs/**` | ❌ Skip | ❌ Skip |
| Root config only | `.env.example`, `Dockerfile` (root) | ❌ Skip | ❌ Skip |

---

## Rollback Independence (Verified)

| Scenario | Rollback Method |
|----------|-----------------|
| Bot Core bad deploy | Dashboard → Bot Core service → Deployments → Select previous SHA → Deploy |
| Engagement API bad deploy | Dashboard → Engagement API service → Deployments → Select previous SHA → Deploy |
| Both bad | Rollback each independently — different SHAs, different projects, different teams |

**Key:** Each service tracks its own `deployedSHA`. Rollback one does not affect the other.

---

## Blocker Status

| Blocker | Status | Resolution |
|---------|--------|------------|
| API cannot update buildConfiguration (GET-only endpoint) | ⚠️ **Manual required** | Configure via Dashboard (both teams) |
| Token scope may lack write perms for buildConfiguration | ✅ Verified read works | Dashboard is correct path |
| `packages/contracts` not yet shared | 📋 Future | Add `packages/contracts/**` to both allow lists when adopted |
| Cross-team Dashboard access | ✅ Two tokens provided | Each token accesses its team's project |
| Engagement API has unused DATABASE_URL/TOKEN in env | ⚠️ Cleanup recommended | Remove from Dashboard env vars (code doesn't use) |

---

## Quick Reference — Files to Watch (from Dockerfile COPY)

### Bot Core (`apps/bot-core/Dockerfile`):
```
apps/bot-core/requirements.txt
apps/bot-core/ (entire dir)
turso_client.py
assets/
```

### Engagement API (`apps/engagement-api/Dockerfile`):
```
apps/engagement-api/requirements.txt
apps/engagement-api/ (entire dir)
```

---

## Douyin-Youtube Comparison

| Aspect | douyin-youtube | ToolNet V3 |
|--------|----------------|------------|
| Repo structure | `backend/`, `backend_audio/`, `backend_facebook/`, `dashboard/` | `apps/bot-core/`, `apps/engagement-api/` |
| Build context | `/backend` (per service) | `/` (repo root, both) |
| Dockerfile | `/backend/Dockerfile` | `/apps/bot-core/Dockerfile`, `/apps/engagement-api/Dockerfile` |
| Path Rules | Implicit via build context | **Explicit Allow List required** |
| Teams | `douyin-feed-apis-team` | `telegram-service-bots-team` + `douyinyoutubes-team` |
| Turso/DB | Supabase Postgres (shared) | **Separate Turso per service** |

---

## Verification Results Summary

| Check | Bot Core | Engagement API |
|-------|----------|----------------|
| CI enabled | ✅ `disabledCI: false` | ✅ `disabledCI: false` |
| CD enabled | ✅ `disabledCD: null` | ✅ `disabledCD: null` |
| Correct Dockerfile | ✅ `/apps/bot-core/Dockerfile` | ✅ `/apps/engagement-api/Dockerfile` |
| Build context | ✅ `/` (root) | ✅ `/` (root) |
| Path Rules configured | ❌ Empty (allow list needed) | ❌ Empty (allow list needed) |
| Own Turso database | ✅ `lebatan220997-...` | ✅ `checkpass001-...` (configured, unused) |
| Rollback independent | ✅ Yes | ✅ Yes |

---

## Manual Configurations Still Needed

| # | Action | Service | Location |
|---|--------|---------|----------|
| 1 | Set Path Rules Allow List: `apps/bot-core/**`, `turso_client.py`, `assets/**` | Bot Core | Dashboard → Project `default` → Service → Build Config |
| 2 | Set Path Rules Allow List: `apps/engagement-api/**` | Engagement API | Dashboard → Project `bot-toolnet-engagement` → Service → Build Config |
| 3 | (Optional) Remove unused `DATABASE_URL`, `DATABASE_TOKEN` | Engagement API | Dashboard → Project `bot-toolnet-engagement` → Service → Environment |
| 4 | (Future) Add `packages/contracts/**` to both allow lists | Both | When `packages/contracts` is imported by either service |

---

## Next Steps

1. **Manual Dashboard Config** (both teams — requires Dashboard access):
   - Bot Core: Allow List = `apps/bot-core/**`, `turso_client.py`, `assets/**`
   - Engagement API: Allow List = `apps/engagement-api/**`

2. **Verify via API** (commands above)

3. **Test via Preview Deployments** (create test PRs, not master commits):
   - PR with `apps/bot-core/` changes → only Bot Core preview builds
   - PR with `apps/engagement-api/` changes → only Engagement API preview builds
   - PR with `README.md` changes → neither builds

4. **Confirm Rollback** — Deploy each to previous SHA independently

5. **When `packages/contracts` is adopted** → Add `packages/contracts/**` to **both** allow lists

---

## Files in This Repo

| File | Purpose |
|------|---------|
| `NORTHFLANK_SETUP_NOTES.md` | Full setup notes (tokens, env, deploy sequence) |
| `NORTHFLANK_DEPLOY.md` | Original deploy guide |
| `NORTHFLANK_PATH_RULES_CONFIG.md` | **This file — Path Rules reference (updated)** |
| `DEPLOYMENT_READINESS_REPORT.md` | Pre-deploy checklist |
| `V3_SPLIT_REPORT.md` | Architecture split details |