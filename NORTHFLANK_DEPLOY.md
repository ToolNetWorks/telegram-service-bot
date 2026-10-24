# Northflank Deployment Guide - ToolNet Telegram Service Bot

## Overview
This bot runs as a **Worker service** on Northflank with:
- No public port (long polling only)
- Persistent Volume at `/data` for SQLite database
- Environment variables via Northflank Secrets/Config
- Single instance (replicas=1)

---

## 1. Northflank Service Configuration

### Service Type: Worker
- **Repository**: Connect your GitHub repo `ToolNetWorks/telegram-service-bot`
- **Branch**: `master` (or your deployment branch)
- **Build**: Dockerfile (auto-detected)
- **Ports**: None (uncheck "Create public port")
- **Replicas**: 1 (critical - single instance for long polling)
- **Auto-deploy**: On push to branch (optional)

### Persistent Volume
- **Mount Path**: `/data`
- **Size**: 1 GiB (adjust as needed)
- **Volume Name**: `telegram-bot-data`
- This stores: `bot.sqlite3`, `bot.sqlite3-wal`, `bot.sqlite3-shm`

---

## 2. Environment Variables (Secrets/Config)

### Required Secrets (Mark as Secret in Northflank)
| Variable | Description | Example |
|----------|-------------|---------|
| `BOT_TOKEN` | Telegram BotFather token | `123456:ABC-DEF...` |
| `ADMIN_IDS` | Comma-separated admin user IDs | `1208342332` |
| `VIETNAMFB_API_KEY` | VietnamFB SMM Panel API key | `f3a36...` |

### Config Variables (Non-secret)
| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_NAME` | Bot display name | `ToolNet Services` |
| `SUPPORT_USERNAME` | Support contact (no @) | `` |
| `DB_PATH` | **Must be `/data/bot.sqlite3`** | `/data/bot.sqlite3` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `BANK_NAME` | Bank name for deposits | `` |
| `BANK_ACCOUNT` | Bank account number | `` |
| `BANK_OWNER` | Bank account owner name | `` |
| `VIETNAMFB_BASE_URL` | API base URL | `https://vietnamfb.com` |

---

## 3. Database Migration from VPS to Northflank

### Option A: Manual Backup/Restore (Recommended for first migration)

#### On VPS (Source):
```bash
# 1. Stop bot gracefully (ensure clean WAL checkpoint)
cd ~/telegram-service-bot
./stop_bot.sh  # or kill -TERM <pid>; wait for process to exit

# 2. Verify WAL is checkpointed (no -wal file or it's small)
ls -la data/

# 3. Create backup with WAL included
tar -czf bot-data-backup-$(date +%Y%m%d-%H%M%S).tar.gz data/

# 4. Download backup to local machine
scp ubuntu@your-vps:~/telegram-service-bot/bot-data-backup-*.tar.gz .
```

#### On Northflank (Target):
```bash
# Option 1: Using Northflank CLI (if available)
# northflank volume upload telegram-bot-data ./data/

# Option 2: Start service with empty volume, then use Northflank shell
# 1. Deploy service with empty /data volume
# 2. Open Northflank shell: `northflank service shell <service-name>`
# 3. Upload backup via base64 or use `nc`/`curl` to transfer
# 4. Extract to /data:
#    tar -xzf bot-data-backup-*.tar.gz -C /
# 5. Verify: ls -la /data/
# 6. Restart service
```

### Option B: Northflank Volume Import (if supported)
Use Northflank dashboard to import volume from backup file.

### Option C: Live Replication (Advanced)
Not recommended for SQLite. Use Option A.

---

## 4. Safe Cutover Procedure (Zero-Downtime Switch)

### Pre-requisites:
- Northflank service deployed and tested (see Section 5)
- VPS bot still running
- Database backup verified

### Cutover Steps:
```
1. VPS:        Stop bot gracefully (SIGTERM)
               ./stop_bot.sh
               # Wait for process to exit (checks logs: "Bot stopped")

2. VPS:        Final backup
               tar -czf final-backup.tar.gz data/

3. Northflank: Upload final backup to volume
               (Use Northflank shell or CLI)

4. Northflank: Start service (1 replica)
               # Bot begins long polling

5. Verify:     Test /start in Telegram
               Check all menus work
               Place test order (mock in test env)

6. Rollback (if needed):
               Northflank: Stop service (scale to 0)
               VPS: Restore backup, start bot
```

### Critical Rule:
**NEVER run both instances simultaneously** - Telegram will reject getUpdates from the second instance with "Conflict: terminated by other getUpdates request".

---

## 5. Local Docker Testing (Pre-deployment)

### Build Image:
```bash
cd ~/telegram-service-bot
docker build -t telegram-service-bot:test .
```

### Run Unit Tests in Container:
```bash
docker run --rm \
  -e BOT_TOKEN=100000:dummy \
  -e ADMIN_IDS=999 \
  -e BOT_NAME=Test \
  -e DB_PATH=/tmp/bot.sqlite3 \
  -e VIETNAMFB_API_KEY=test_key \
  -e VIETNAMFB_BASE_URL=https://test.vietnamfb.com \
  telegram-service-bot:test \
  python3 -m unittest tests.test_flows -v
```

### Smoke Test (Mock API):
```bash
docker run --rm \
  -e BOT_TOKEN=100000:dummy \
  -e ADMIN_IDS=999 \
  -e BOT_NAME=Test \
  -e DB_PATH=/data/bot.sqlite3 \
  -e VIETNAMFB_API_KEY=test_key \
  -e VIETNAMFB_BASE_URL=https://test.vietnamfb.com \
  -v $(pwd)/test-data:/data \
  telegram-service-bot:test \
  timeout 30 python3 -m bot || true
```

### Verify Image:
```bash
# Check image size
docker images telegram-service-bot:test

# Inspect layers
docker history telegram-service-bot:test
```

---

## 6. Northflank-Specific Files

### `northflank.yaml` (Optional - for Infrastructure as Code)
```yaml
services:
  - name: telegram-service-bot
    type: worker
    repo: ToolNetWorks/telegram-service-bot
    branch: master
    dockerfilePath: Dockerfile
    replicas: 1
    env:
      - key: BOT_NAME
        value: "ToolNet Services"
      - key: DB_PATH
        value: "/data/bot.sqlite3"
      - key: LOG_LEVEL
        value: "INFO"
      - key: VIETNAMFB_BASE_URL
        value: "https://vietnamfb.com"
    secrets:
      - BOT_TOKEN
      - ADMIN_IDS
      - VIETNAMFB_API_KEY
    volumes:
      - name: telegram-bot-data
        mountPath: /data
        size: 1Gi
```

---

## 7. Monitoring & Logs

### Northflank Logs:
- View real-time logs in Northflank dashboard
- Log format: `YYYY-MM-DD HH:MM:SS LEVEL name: message`

### Health Check:
- Built-in HEALTHCHECK runs every 60s
- Verifies Python can import bot modules
- Northflank will restart container if health check fails

### Key Metrics to Watch:
- Container restarts (should be 0)
- Memory usage (typically < 100MB)
- Log errors (API timeouts, DB locks)

---

## 8. Rollback Plan

### If Northflank Deployment Fails:
1. **Scale Northflank service to 0 replicas** (stops bot)
2. **On VPS**: Bot is still running (we never stopped it during prep)
3. **No data loss** - VPS database untouched

### If Cutover Fails (after VPS stopped):
1. **Northflank**: Scale to 0
2. **VPS**: Restore from `final-backup.tar.gz`
   ```bash
   tar -xzf final-backup.tar.gz -C /
   ./start_bot.sh
   ```
3. **Investigate**: Check Northflank logs, fix issue, retry

---

## 9. Post-Migration Verification

- [ ] `/start` shows welcome GIF and main menu
- [ ] Tool Access → Engagement Services → Telegram Group Members shows 3 packages
- [ ] Wallet shows correct balance
- [ ] My Orders (Đơn của tôi) shows history
- [ ] Admin commands work (`/ordersadmin`, `/deposits`, etc.)
- [ ] Language switch (vi/en) works
- [ ] Deposit flow works
- [ ] Referral system works

---

## 10. Troubleshooting

| Issue | Solution |
|-------|----------|
| "Conflict: terminated by other getUpdates" | Another instance running. Scale Northflank to 0, check VPS. |
| "Database is locked" | SQLite contention. Ensure single instance. Check WAL mode. |
| "VIETNAMFB_API_KEY not set" | Add secret in Northflank, redeploy. |
| "Permission denied /data" | Check volume mount, user permissions (botuser:botuser). |
| Health check fails | Check logs for import errors. Verify all .py files copied. |

---

## 11. File Checklist for Repository

Ensure these files are committed:
- [x] `Dockerfile`
- [x] `.dockerignore`
- [x] `.env.example` (updated with DB_PATH=/data/bot.sqlite3)
- [x] `bot.py`, `db.py`, `i18n.py`, `vietnamfb_api.py`
- [x] `tests/test_flows.py`, `tests/test_db.py`
- [x] `assets/` (GIFs, videos)
- [x] `README.md`
- [x] `NORTHFLANK_DEPLOY.md` (this file)
- [x] `.gitignore` (excludes .env, data/, logs/, backups/)

---

## 12. Contact & Support

For deployment issues, check:
1. Northflank service logs
2. This guide's troubleshooting section
3. Bot's internal logs (in `/app/logs/` inside container)