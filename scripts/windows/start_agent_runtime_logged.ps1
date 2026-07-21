# Запуск Agent Runtime с персистентными логами в .local/.
#
# Этот скрипт-обёртка нужен, потому что scheduled task
# ``Portal Agent Runtime`` раньше запускал ``python.exe -m uvicorn``
# напрямую, без перенаправления stdout/stderr. В итоге все события
# runtime (включая стек-трейсы при падении) терялись в Task Scheduler.
#
# Теперь action запланированной задачи зовёт PowerShell с этим файлом:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File \
#       scripts\windows\start_agent_runtime_logged.ps1
#
# Поведение:
#   - PYTHONUNBUFFERED=1, чтобы в логах был flush построчно;
#   - stdout и stderr пишутся в .local\agent_runtime.log и
#     .local\agent_runtime.err.log соответственно, append-only;
#   - процесс живёт, пока жив uvicorn; код выхода пробрасывается наружу,
#     чтобы watch­dog scheduled task видел non-zero exit и рестартовал.
#
# Этот скрипт безопасно запускать и вручную — он не делает ничего, кроме
# синхронного запуска uvicorn в рабочей директории проекта.

param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8090,
    [string]$ProjectRoot = "",
    [int]$KeepAliveSeconds = 300
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Python виртуального окружения не найден: $venvPython"
}

$logDir = Join-Path $ProjectRoot ".local"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

$stdoutLog = Join-Path $logDir "agent_runtime.log"
$stderrLog = Join-Path $logDir "agent_runtime.err.log"

# PYTHONUNBUFFERED важен: иначе uvicorn буферизует логи и при падении
# они теряются.
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

Set-Location $ProjectRoot

$arguments = @(
    "-m", "uvicorn", "services.agent_runtime.app:app",
    "--host", $BindHost, "--port", "$Port",
    "--timeout-keep-alive", "$KeepAliveSeconds",
    "--log-level", "info"
)

$stdoutLine = "[{0}] Launching: {1} {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $venvPython, ($arguments -join " ")
$stdoutLine | Out-File -FilePath $stdoutLog -Append -Encoding utf8

try {
    # Синхронный запуск с редиректом. Используем Start-Process + -Wait:
    #   - совместимо с PowerShell 5.1 (на Windows Server стоит именно он);
    #   - ``-RedirectStandardOutput/-RedirectStandardError`` открывают
    #     файлы на запись из родителя, ребёнок пишет туда без буфера PS;
    #   - ``-Wait`` держит процесс PowerShell до выхода uvicorn, чтобы
    #     scheduled task увидел время жизни.
    $proc = Start-Process -FilePath $venvPython `
        -ArgumentList $arguments `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    if ($null -eq $proc) {
        throw "Start-Process не вернул описатель процесса"
    }
    # Кодируем, что скрипт держит ребёнка
    Write-Host ("uvicorn запущен: PID={0} logs out={1} err={2}" -f $proc.Id, $stdoutLog, $stderrLog)
    $proc | Wait-Process
    $exitCode = $proc.ExitCode
    $line = "[{0}] uvicorn exited with code {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $exitCode
    $line | Out-File -FilePath $stdoutLog -Append -Encoding utf8
    exit $exitCode
} catch {
    $line = "[{0}] FAIL: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message
    $line | Out-File -FilePath $stderrLog -Append -Encoding utf8
    throw
}
