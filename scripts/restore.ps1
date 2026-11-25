param(
    [Parameter(Mandatory = $true)]
    [string]$BackupDir
)

$ErrorActionPreference = "Stop"
$dbDump = Join-Path $BackupDir "postgres.dump"
$assetsTar = Join-Path $BackupDir "assets.tar.gz"

if (!(Test-Path $dbDump) -or !(Test-Path $assetsTar)) {
    throw "Backup directory must contain postgres.dump and assets.tar.gz"
}

Write-Host "Restoring private asset storage from $assetsTar ..."
Get-Content -AsByteStream $assetsTar | docker compose exec -T api tar -C /data -xzf -

Write-Host "Restoring PostgreSQL database from $dbDump ..."
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
Get-Content -AsByteStream $dbDump | docker compose exec -T postgres sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose exec -T api alembic upgrade head

Write-Host "Restore complete from $BackupDir"
