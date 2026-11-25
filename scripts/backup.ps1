param(
    [string]$OutputDir = "./data/backups"
)

$ErrorActionPreference = "Stop"
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$target = Join-Path $OutputDir $timestamp
New-Item -ItemType Directory -Force $target | Out-Null

$dbDump = Join-Path $target "postgres.dump"
$assetsTar = Join-Path $target "assets.tar.gz"
$manifest = Join-Path $target "manifest.sha256"

Write-Host "Backing up PostgreSQL database to $dbDump ..."
docker compose exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > $dbDump

Write-Host "Backing up private asset storage to $assetsTar ..."
docker compose exec -T api tar -C /data -czf - assets > $assetsTar

$dbHash = (Get-FileHash -Algorithm SHA256 $dbDump).Hash.ToLower()
$assetsHash = (Get-FileHash -Algorithm SHA256 $assetsTar).Hash.ToLower()
@(
    "$dbHash  postgres.dump",
    "$assetsHash  assets.tar.gz"
) | Set-Content -Encoding UTF8 $manifest

Write-Host "Backup complete: $target"
