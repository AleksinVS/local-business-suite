# Ежедневный резервный бэкап PostgreSQL-базы портала (ADR-0029, runbook
# docs/deployment/POSTGRESQL_MIGRATION.md: «регулярный backup»).
#
# Что делает:
#   1. pg_dump -Fc базы local_business_suite в data\backups\postgresql\
#   2. zip-копия runtime-контрактов data\contracts (файловые настройки)
#   3. ротация: файлы старше $RetentionDays (по умолчанию 7) удаляются
#
# Пароль берётся из .local\secrets\pg_backup_password.txt (вне git).
# Запуск: вручную или Scheduled Task "\Portal\Portal PostgreSQL Backup".

[CmdletBinding()]
param(
    [string]$PortalRoot   = "C:\inetpub\portal",
    [string]$PgBin        = "C:\Program Files\PostgreSQL\17\bin",
    [string]$DbHost       = "127.0.0.1",
    [string]$DbPort       = "5432",
    [string]$DbName       = "local_business_suite",
    [string]$DbUser       = "local_business_app",
    [int]$RetentionDays   = 7
)

$ErrorActionPreference = "Stop"

$BackupDir  = Join-Path $PortalRoot "data\backups\postgresql"
$SecretFile = Join-Path $PortalRoot ".local\secrets\pg_backup_password.txt"
$LogFile    = Join-Path $PortalRoot "data\logs\backup_postgresql.log"

New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $LogFile) -Force | Out-Null

function Write-Log($msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

if (-not (Test-Path $SecretFile)) {
    Write-Log "ОШИБКА: нет файла пароля $SecretFile"
    exit 1
}
$env:PGPASSWORD = (Get-Content $SecretFile -Raw).Trim()

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

# 1. Дамп базы (custom format: сжатие + выборочное восстановление pg_restore)
$dumpFile = Join-Path $BackupDir "local_business_suite-$stamp.dump"
& (Join-Path $PgBin "pg_dump.exe") -h $DbHost -p $DbPort -U $DbUser -d $DbName -Fc -f $dumpFile
if ($LASTEXITCODE -ne 0) {
    Write-Log "ОШИБКА: pg_dump завершился с кодом $LASTEXITCODE"
    exit $LASTEXITCODE
}
$dumpMb = [math]::Round((Get-Item $dumpFile).Length / 1MB, 2)
Write-Log "OK: дамп $dumpFile ($dumpMb МБ)"

# 2. Копия runtime-контрактов (ролевой контракт, лист ожидания и т.д.)
$contractsDir = Join-Path $PortalRoot "data\contracts"
if (Test-Path $contractsDir) {
    $contractsZip = Join-Path $BackupDir "contracts-$stamp.zip"
    Compress-Archive -Path (Join-Path $contractsDir "*") -DestinationPath $contractsZip -CompressionLevel Optimal
    Write-Log "OK: контракты $contractsZip"
}

# 3. Ротация
$cutoff = (Get-Date).AddDays(-$RetentionDays)
Get-ChildItem $BackupDir -File | Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
    Remove-Item $_.FullName -Force
    Write-Log "ротация: удалён $($_.Name)"
}

Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
exit 0
