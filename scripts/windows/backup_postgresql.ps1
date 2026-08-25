# Безопасный ежедневный backup PostgreSQL и runtime-контрактов портала.
#
# ВАЖНО: задача запускается только от отдельной малопривилегированной учётной
# записи backup. SYSTEM и identity IIS Application Pool запрещены. Каталог
# BackupStateRoot заранее создаётся администратором вне PortalRoot с отключённым
# наследованием ACL; web/application identity не должна иметь в нём write/delete.

[CmdletBinding()]
param(
    [string]$PortalRoot = "C:\inetpub\portal",
    [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin",
    [string]$DbHost = "127.0.0.1",
    [string]$DbPort = "5432",
    [string]$DbName = "local_business_suite",
    [string]$DbUser = "local_business_app",
    [int]$RetentionDays = 7,
    [string]$BackupStateRoot = "C:\ProgramData\LocalBusinessSuite",
    [Parameter(Mandatory = $true)]
    [string]$ExpectedBackupIdentity,
    [string]$ApplicationIdentity = "IIS APPPOOL\DefaultAppPool"
)

$ErrorActionPreference = "Stop"
$OwnedBackupNamePattern = '^(local_business_suite-\d{8}-\d{6}\.dump|contracts-\d{8}-\d{6}\.zip)$'
function Get-NormalizedPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.TrimEnd('\') -eq $root.TrimEnd('\')) {
        return $root
    }
    return $full.TrimEnd('\')
}

function Assert-NoReparsePoint([string]$Path) {
    $cursor = Get-NormalizedPath $Path
    $root = [System.IO.Path]::GetPathRoot($cursor)
    while ($cursor -and $cursor.Length -ge $root.TrimEnd('\').Length) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Небезопасный reparse point в пути backup: $cursor"
            }
        }
        if ($cursor.TrimEnd('\') -eq $root.TrimEnd('\')) { break }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { break }
        $cursor = $parent.TrimEnd('\')
    }
}

function Assert-PrivateBackupAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) {
        throw "BackupStateRoot обязан иметь отключённое наследование ACL: $Path"
    }
    try {
        $ownerAccount = New-Object -TypeName System.Security.Principal.NTAccount -ArgumentList $acl.Owner
        $ownerSid = $ownerAccount.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        throw "Не удалось проверить SID владельца BackupStateRoot."
    }
    $TrustedOwnerSids = @(
        "S-1-5-18",      # SYSTEM
        "S-1-5-32-544"   # BUILTIN\Administrators
    )
    if ($TrustedOwnerSids -notcontains $ownerSid) {
        throw "Недоверенный владелец BackupStateRoot: $ownerSid"
    }

    $writeMask = [int64]0
    @(
        [System.Security.AccessControl.FileSystemRights]::Write,
        [System.Security.AccessControl.FileSystemRights]::Modify,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.FileSystemRights]::Delete,
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles,
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions,
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    ) | ForEach-Object { $writeMask = $writeMask -bor [int64]$_ }

    $backupIdentityCanWrite = $false
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            continue
        }
        try {
            $sid = $rule.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
        }
        catch {
            throw "Не удалось проверить SID ACL backup: $($rule.IdentityReference.Value)"
        }
        $ruleCanWrite = (([int64]$rule.FileSystemRights -band $writeMask) -ne 0)
        if ($ruleCanWrite -and $AllowedWriteSids -notcontains $sid) {
            throw "Недоверенный SID $sid имеет write/delete в BackupStateRoot."
        }
        if (
            $sid -eq $currentIdentity.User.Value -and
            $ruleCanWrite
        ) {
            $backupIdentityCanWrite = $true
        }
    }
    if (-not $backupIdentityCanWrite) {
        throw "Backup identity не имеет явного write-доступа к BackupStateRoot."
    }
}

function Assert-TrustedAnchorParentAcl([string]$Path) {
    $parent = Split-Path -Parent (Get-NormalizedPath $Path)
    if (-not $parent) {
        throw "У BackupStateRoot отсутствует проверяемый родительский каталог."
    }
    Assert-NoReparsePoint $parent
    $acl = Get-Acl -LiteralPath $parent
    try {
        $ownerAccount = New-Object -TypeName System.Security.Principal.NTAccount -ArgumentList $acl.Owner
        $ownerSid = $ownerAccount.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        throw "Не удалось проверить владельца родителя BackupStateRoot."
    }
    $trustedParentSids = @("S-1-5-18", "S-1-5-32-544")
    if ($trustedParentSids -notcontains $ownerSid) {
        throw "Недоверенный владелец родителя BackupStateRoot: $ownerSid"
    }
    $deleteChild = [int64][System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            continue
        }
        $inheritOnly = (
            $rule.PropagationFlags -band
            [System.Security.AccessControl.PropagationFlags]::InheritOnly
        ) -ne 0
        if ($inheritOnly) { continue }
        $sid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        if (
            (([int64]$rule.FileSystemRights -band $deleteChild) -ne 0) -and
            $trustedParentSids -notcontains $sid
        ) {
            throw "Недоверенный SID $sid может удалить/заменить BackupStateRoot через родителя."
        }
    }
}

function Assert-TrustedBackupChildAcl([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    try {
        $ownerAccount = New-Object -TypeName System.Security.Principal.NTAccount -ArgumentList $acl.Owner
        $ownerSid = $ownerAccount.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
    }
    catch {
        throw "Не удалось проверить владельца backup-каталога: $Path"
    }
    if ($AllowedWriteSids -notcontains $ownerSid) {
        throw "Недоверенный владелец backup-каталога $Path: $ownerSid"
    }

    $writeMask = [int64]0
    @(
        [System.Security.AccessControl.FileSystemRights]::Write,
        [System.Security.AccessControl.FileSystemRights]::Modify,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.FileSystemRights]::Delete,
        [System.Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles,
        [System.Security.AccessControl.FileSystemRights]::ChangePermissions,
        [System.Security.AccessControl.FileSystemRights]::TakeOwnership
    ) | ForEach-Object { $writeMask = $writeMask -bor [int64]$_ }
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            continue
        }
        $sid = $rule.IdentityReference.Translate(
            [System.Security.Principal.SecurityIdentifier]
        ).Value
        if (
            (([int64]$rule.FileSystemRights -band $writeMask) -ne 0) -and
            $AllowedWriteSids -notcontains $sid
        ) {
            throw "Недоверенный SID $sid имеет write/delete в backup-каталоге $Path."
        }
    }
}

$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($currentIdentity.User.Value -eq "S-1-5-18") {
    throw "Backup запрещено запускать от SYSTEM. Используйте отдельную backup identity."
}
if (-not $currentIdentity.Name.Equals(
    $ExpectedBackupIdentity,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "Текущая identity '$($currentIdentity.Name)' не совпадает с ожидаемой backup identity."
}
$AllowedWriteSids = @(
    "S-1-5-18",      # SYSTEM: host recovery/administration
    "S-1-5-32-544",  # BUILTIN\Administrators
    $currentIdentity.User.Value
)
try {
    $applicationAccount = New-Object -TypeName System.Security.Principal.NTAccount -ArgumentList $ApplicationIdentity
    $applicationSid = $applicationAccount.Translate(
        [System.Security.Principal.SecurityIdentifier]
    ).Value
}
catch {
    throw "Не удалось определить SID application identity '$ApplicationIdentity'."
}
if ($applicationSid -eq $currentIdentity.User.Value) {
    throw "Backup identity не должна совпадать с application identity."
}

$PortalRoot = Get-NormalizedPath $PortalRoot
$BackupStateRoot = Get-NormalizedPath $BackupStateRoot
if (
    $BackupStateRoot.Equals($PortalRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
    $BackupStateRoot.StartsWith(
        $PortalRoot + '\',
        [System.StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "BackupStateRoot должен находиться вне PortalRoot и runtime data."
}
if (-not (Test-Path -LiteralPath $BackupStateRoot -PathType Container)) {
    throw "BackupStateRoot должен быть заранее создан администратором: $BackupStateRoot"
}

Assert-NoReparsePoint $BackupStateRoot
Assert-TrustedAnchorParentAcl $BackupStateRoot
Assert-PrivateBackupAcl $BackupStateRoot

$BackupDir = Join-Path $BackupStateRoot "postgresql"
$LogDir = Join-Path $BackupStateRoot "logs"
$SecretDir = Join-Path $BackupStateRoot "secrets"
$SecretFile = Join-Path $SecretDir "pg_backup_password.txt"
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $SecretDir -PathType Container)) {
    throw "Защищённый каталог secrets должен быть заранее создан администратором."
}
Assert-NoReparsePoint $BackupDir
Assert-NoReparsePoint $LogDir
Assert-NoReparsePoint $SecretFile
Assert-TrustedBackupChildAcl $BackupDir
Assert-TrustedBackupChildAcl $LogDir
Assert-TrustedBackupChildAcl $SecretDir

$LogFile = Join-Path $LogDir "backup_postgresql.log"
function Write-Log([string]$Message) {
    Assert-NoReparsePoint $LogDir
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $SecretFile -PathType Leaf)) {
    Write-Log "ОШИБКА: нет файла пароля в защищённом backup-каталоге"
    throw "Файл пароля backup не найден."
}

$env:PGPASSWORD = (Get-Content -LiteralPath $SecretFile -Raw).Trim()
try {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Assert-NoReparsePoint $BackupDir

    $dumpFile = Join-Path $BackupDir "local_business_suite-$stamp.dump"
    & (Join-Path $PgBin "pg_dump.exe") -h $DbHost -p $DbPort -U $DbUser -d $DbName -Fc -f $dumpFile
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump завершился с кодом $LASTEXITCODE"
    }
    $dumpMb = [math]::Round((Get-Item -LiteralPath $dumpFile).Length / 1MB, 2)
    Write-Log "OK: создан PostgreSQL dump ($dumpMb МБ)"

    $contractsDir = Join-Path $PortalRoot "data\contracts"
    if (Test-Path -LiteralPath $contractsDir -PathType Container) {
        Assert-NoReparsePoint $contractsDir
        Assert-NoReparsePoint $BackupDir
        $contractsZip = Join-Path $BackupDir "contracts-$stamp.zip"
        Compress-Archive -Path (Join-Path $contractsDir "*") -DestinationPath $contractsZip -CompressionLevel Optimal
        Write-Log "OK: создан архив runtime-контрактов"
    }

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Assert-NoReparsePoint $BackupDir
    Get-ChildItem -LiteralPath $BackupDir -File | Where-Object {
        $_.Name -match $OwnedBackupNamePattern -and $_.LastWriteTime -lt $cutoff
    } | ForEach-Object {
        if (($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Ротация отказалась удалять reparse point: $($_.FullName)"
        }
        Remove-Item -LiteralPath $_.FullName -Force
        Write-Log "ротация: удалён собственный backup $($_.Name)"
    }
}
catch {
    Write-Log "ОШИБКА: $($_.Exception.Message)"
    throw
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
