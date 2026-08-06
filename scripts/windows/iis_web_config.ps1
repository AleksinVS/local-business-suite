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

function Test-IisFaviconAnonymousBypass {
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
            if (-not $path.Equals("favicon.ico", [System.StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            $anonymous = $location.SelectSingleNode(
                "./system.webServer/security/authentication/anonymousAuthentication"
            )
            $windows = $location.SelectSingleNode(
                "./system.webServer/security/authentication/windowsAuthentication"
            )
            if (
                $null -ne $anonymous -and
                ([string]$anonymous.enabled).Equals("true", [System.StringComparison]::OrdinalIgnoreCase) -and
                $null -ne $windows -and
                ([string]$windows.enabled).Equals("false", [System.StringComparison]::OrdinalIgnoreCase)
            ) {
                return $true
            }
        }
        return $false
    } catch {
        return $false
    }
}

function Add-IisXmlChild {
    param(
        [Parameter(Mandatory = $true)]
        [System.Xml.XmlNode]$Parent,
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $node = $Parent.SelectSingleNode("./$Name")
    if ($null -eq $node) {
        $node = $Parent.OwnerDocument.CreateElement($Name)
        $Parent.AppendChild($node) | Out-Null
    }
    return $node
}

function Set-IisFaviconFastCgiBypassXml {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [xml]$WebConfig,
        [switch]$HandlersOnly
    )

    $configuration = $WebConfig.SelectSingleNode("/configuration")
    if ($null -eq $configuration) {
        throw "web.config не содержит корневой элемент <configuration>."
    }

    $before = $WebConfig.OuterXml
    $matches = @()
    foreach ($candidate in $WebConfig.SelectNodes("/configuration/location")) {
        $path = ([string]$candidate.path).TrimStart("/")
        if ($path.Equals("favicon.ico", [System.StringComparison]::OrdinalIgnoreCase)) {
            $matches += $candidate
        }
    }

    if ($matches.Count -eq 0) {
        $location = $WebConfig.CreateElement("location")
        $appSettings = $configuration.SelectSingleNode("./appSettings")
        if ($null -ne $appSettings) {
            $configuration.InsertBefore($location, $appSettings) | Out-Null
        } else {
            $configuration.AppendChild($location) | Out-Null
        }
    } else {
        $location = $matches[0]
        for ($index = 1; $index -lt $matches.Count; $index++) {
            $configuration.RemoveChild($matches[$index]) | Out-Null
        }
    }

    $location.SetAttribute("path", "favicon.ico")
    $location.SetAttribute("inheritInChildApplications", "false")
    $systemWebServer = Add-IisXmlChild -Parent $location -Name "system.webServer"
    $handlers = Add-IisXmlChild -Parent $systemWebServer -Name "handlers"
    $handlers.RemoveAll()
    $handlers.AppendChild($WebConfig.CreateElement("clear")) | Out-Null

    if (-not $HandlersOnly) {
        $security = Add-IisXmlChild -Parent $systemWebServer -Name "security"
        $authentication = Add-IisXmlChild -Parent $security -Name "authentication"
        $anonymous = Add-IisXmlChild -Parent $authentication -Name "anonymousAuthentication"
        $anonymous.SetAttribute("enabled", "true")
        $windows = Add-IisXmlChild -Parent $authentication -Name "windowsAuthentication"
        $windows.SetAttribute("enabled", "false")
    }

    return [PSCustomObject]@{
        Changed = ($before -ne $WebConfig.OuterXml)
        RemovedDuplicateLocations = [Math]::Max(0, $matches.Count - 1)
    }
}
