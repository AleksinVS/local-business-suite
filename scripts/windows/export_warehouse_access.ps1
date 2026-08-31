<#
Read-only ACE OLE DB export transport.  It intentionally has no knowledge of
warehouse table semantics: the Django profile supplies the table allowlist.
No source path, connection string or source values from secret-like columns are
written into its manifest.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir,

    [Parameter(Mandatory = $true)]
    [string[]]$Tables,

    [ValidateRange(0, 20)]
    [int]$SampleSize = 5,

    [switch]$InspectOnly,

    [ValidateSet("Microsoft.ACE.OLEDB.16.0", "Microsoft.ACE.OLEDB.12.0")]
    [string]$Provider
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Text)
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Test-SecretColumn {
    param([string]$Name)
    $normalised = $Name.Trim().ToLowerInvariant()
    return $normalised -eq "pass" -or $normalised -eq "password" -or $normalised -eq "pwd" -or
        $normalised -match "secret|token"
}

function Quote-AccessIdentifier {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name -match "[\x00\r\n]") {
        throw "Некорректный идентификатор Access-таблицы."
    }
    return "[" + $Name.Replace("]", "]]" ) + "]"
}

function Convert-AccessValue {
    param($Value)
    if ($null -eq $Value -or $Value -is [System.DBNull]) { return $null }
    if ($Value -is [datetime]) { return $Value.ToString("o", [Globalization.CultureInfo]::InvariantCulture) }
    if ($Value -is [decimal]) { return $Value.ToString([Globalization.CultureInfo]::InvariantCulture) }
    if ($Value -is [double] -or $Value -is [single]) {
        return ([System.Convert]::ToString($Value, [Globalization.CultureInfo]::InvariantCulture))
    }
    if ($Value -is [byte[]]) { return [System.Convert]::ToBase64String($Value) }
    return $Value
}

function Open-ReadOnlyConnection {
    param([string]$SourcePath, [string]$RequestedProvider)
    $providers = if ($RequestedProvider) { @($RequestedProvider) } else { @("Microsoft.ACE.OLEDB.16.0", "Microsoft.ACE.OLEDB.12.0") }
    $lastError = $null
    foreach ($candidate in $providers) {
        try {
            $connection = New-Object System.Data.OleDb.OleDbConnection
            $connection.ConnectionString = "Provider=$candidate;Data Source=$SourcePath;Mode=Read;Persist Security Info=False;"
            $connection.Open()
            return @{ Connection = $connection; Provider = $candidate }
        } catch {
            $lastError = $_
            if ($connection) { $connection.Dispose() }
        }
    }
    throw "ACE_PROVIDER_UNAVAILABLE: установите Microsoft Access Database Engine нужной разрядности для PowerShell."
}

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "ACCESS_SOURCE_NOT_FOUND"
}

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$tablesPath = Join-Path $outputPath "tables"
New-Item -ItemType Directory -Force -Path $tablesPath | Out-Null

$fingerprintBefore = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$opened = Open-ReadOnlyConnection -SourcePath $sourcePath -RequestedProvider $Provider
$connection = $opened.Connection

try {
    $availableRows = $connection.GetSchema("Tables") | Where-Object {
        $_.TABLE_TYPE -in @("TABLE", "VIEW") -and $_.TABLE_NAME
    }
    $available = @{}
    foreach ($row in $availableRows) { $available[$row.TABLE_NAME.ToString().ToLowerInvariant()] = $row.TABLE_NAME.ToString() }
    $manifestTables = @()
    foreach ($requestedTable in $Tables) {
        $tableKey = $requestedTable.Trim().ToLowerInvariant()
        if (-not $available.ContainsKey($tableKey)) {
            $manifestTables += [ordered]@{ name = $requestedTable; missing = $true; columns = @(); indexes = @(); row_count = 0; sample = @() }
            continue
        }
        $tableName = $available[$tableKey]
        $columns = @()
        try { $columnRows = $connection.GetSchema("Columns", @($null, $null, $tableName, $null)) } catch { $columnRows = @() }
        foreach ($column in $columnRows) {
            $name = $column.COLUMN_NAME.ToString()
            if (-not (Test-SecretColumn $name)) { $columns += $name }
        }
        $indexes = @()
        try {
            $indexRows = $connection.GetSchema("Indexes", @($null, $null, $tableName))
            foreach ($index in $indexRows) {
                if ($index.INDEX_NAME) { $indexes += [ordered]@{ name = $index.INDEX_NAME.ToString(); primary_key = [bool]$index.PRIMARY_KEY; unique = [bool]$index.UNIQUE } }
            }
        } catch { }
        $escapedTable = Quote-AccessIdentifier $tableName
        $countCommand = $connection.CreateCommand()
        $countCommand.CommandText = "SELECT COUNT(*) FROM $escapedTable"
        $count = [int]$countCommand.ExecuteScalar()
        $query = if ($InspectOnly) { "SELECT TOP $SampleSize * FROM $escapedTable" } else { "SELECT * FROM $escapedTable" }
        $command = $connection.CreateCommand()
        $command.CommandText = $query
        $reader = $command.ExecuteReader()
        $sample = @()
        $writer = $null
        $relativeFile = "tables/$tableName.jsonl"
        if (-not $InspectOnly) {
            $writer = New-Object System.IO.StreamWriter((Join-Path $tablesPath "$tableName.jsonl"), $false, (New-Object System.Text.UTF8Encoding($false)))
        }
        try {
            while ($reader.Read()) {
                $payload = [ordered]@{}
                for ($position = 0; $position -lt $reader.FieldCount; $position++) {
                    $columnName = $reader.GetName($position)
                    if (-not (Test-SecretColumn $columnName)) { $payload[$columnName] = Convert-AccessValue $reader.GetValue($position) }
                }
                if ($InspectOnly) { $sample += $payload } else { $writer.WriteLine(([ordered]@{ payload = $payload } | ConvertTo-Json -Compress -Depth 8)) }
            }
        } finally {
            $reader.Close()
            if ($writer) { $writer.Dispose() }
        }
        $tableResult = [ordered]@{ name = $tableName; missing = $false; columns = $columns; indexes = $indexes; row_count = $count }
        if ($InspectOnly) { $tableResult.sample = $sample } else { $tableResult.file = $relativeFile }
        $manifestTables += $tableResult
    }
} finally {
    $connection.Close()
    $connection.Dispose()
}

$fingerprintAfter = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    schema_version = "ace-legacy-transport-v1"
    source_name = [System.IO.Path]::GetFileName($sourcePath)
    source_fingerprint = $fingerprintBefore
    source_changed_during_extract = ($fingerprintBefore -ne $fingerprintAfter)
    provider = $opened.Provider
    inspect_only = [bool]$InspectOnly
    tables = $manifestTables
}
Write-Utf8NoBom -Path (Join-Path $outputPath "transport-manifest.json") -Text ($manifest | ConvertTo-Json -Depth 10)
