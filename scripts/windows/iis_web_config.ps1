# Общие проверки web.config для Windows/IIS deployment-скриптов.

function Test-IisFaviconFastCgiBypass {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$WebConfigPath
    )

    if (-not (Test-Path $WebConfigPath)) {
        return $false
    }

    try {
        [xml]$webConfig = Get-Content $WebConfigPath -Raw
        foreach ($location in $webConfig.SelectNodes("/configuration/location")) {
            $path = ([string]$location.path).TrimStart("/")
            if (
                $path.Equals("favicon.ico", [System.StringComparison]::OrdinalIgnoreCase) -and
                $null -ne $location.SelectSingleNode("./system.webServer/handlers/clear")
            ) {
                return $true
            }
        }
        return $false
    } catch {
        return $false
    }
}
