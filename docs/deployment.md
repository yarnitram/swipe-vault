# SwipeVault — Deployment, Backup & Restore Runbook

## 1. Local & Proxmox Docker Compose Deployment

1. Copy `.env.example` to `.env` and replace placeholder secrets (`POSTGRES_PASSWORD`, `DATABASE_URL`, `SESSION_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`).
2. Start the stack:
   ```powershell
   docker compose up --build -d --wait
   ```
3. Verify service health:
   ```powershell
   docker compose ps
   curl http://127.0.0.1:2100/api/v1/health/live
   curl http://127.0.0.1:2100/api/v1/health/ready
   ```
4. Open `http://127.0.0.1:2100` and sign in with `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`.

### Network Isolation

- Only `frontend` binds to the host (`127.0.0.1:2100:8080` by default via `WEB_BIND_HOST` and `WEB_PORT`).
- `postgres`, `redis`, `api`, and `worker` stay on the internal Docker bridge network with **no** public port mappings (`AC-01`).
- For Proxmox LXC/VM access across a private LAN or Cloudflare Access tunnel, point your reverse proxy or tunnel at `127.0.0.1:2100` and set `SESSION_COOKIE_SECURE=true` when served over HTTPS.

## 2. Backup & Restore (`AC-15`)

SwipeVault state lives in two persistent Docker volumes:
- `postgres_data` — PostgreSQL 16 database (offers, swipes, versions, provenance, review events, jobs, audit logs)
- `asset_data` — Content-addressed original vendor files mounted at `/data/assets`

### Create a Backup

Run `scripts/backup.ps1` (or the equivalent `pg_dump` + `tar` commands on Linux):

```powershell
pwsh ./scripts/backup.ps1 -OutputDir ./data/backups
```

This produces a timestamped directory containing:
- `postgres.dump` (`pg_dump -Fc` custom-format archive)
- `assets.tar.gz` (tarball of `/data/assets`)
- `manifest.sha256` (SHA-256 checksums of both archives)

### Restore from a Backup

```powershell
pwsh ./scripts/restore.ps1 -BackupDir ./data/backups/<timestamp>
```

The restore script verifies `manifest.sha256`, restores `/data/assets`, drops and recreates the `public` schema, runs `pg_restore --no-owner`, and runs `alembic upgrade head` to ensure schema consistency.
