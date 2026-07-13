$ErrorActionPreference = "Stop"
$files = @("scripts\windows\export_portal.ps1", "scripts\windows\import_portal.ps1")
$hasErrors = $false

foreach ($f in $files) {
    $tokens = $null
    $errors = $null
    $path = (Resolve-Path $f).Path
    [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors) | Out-Null

    if ($errors -and $errors.Count -gt 0) {
        Write-Host "=== $f : PARSE ERRORS ===" -ForegroundColor Red
        foreach ($e in $errors) {
            Write-Host "  Line $($e.Extent.StartLineNumber): $($e.Message)" -ForegroundColor Red
        }
        $hasErrors = $true
    } else {
        Write-Host "=== $f : OK ===" -ForegroundColor Green
    }
}

if ($hasErrors) {
    exit 1
}