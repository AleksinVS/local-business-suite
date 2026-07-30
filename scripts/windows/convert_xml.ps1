# Convert XML to PDF/DOCX via Microsoft Word
# Конвертирует XML файлы в PDF или DOCX через Word COM
#
# Использование:
#   .\convert_xml.ps1 -XmlPath "C:\temp\data.xml" -OutputPath "C:\temp\output.pdf"
#   .\convert_xml.ps1 -XmlPath "C:\temp\data.xml" -OutputPath "C:\temp\output.docx" -Format Docx
#   .\convert_xml.ps1 -XmlPath "C:\temp\data.xml" -OutputPath "C:\temp\output" -Both
#
# Требования:
#   - Установленный Microsoft Word (Any version)
#   - Права на запись в выходную директорию

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$XmlPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [ValidateSet("Auto", "Pdf", "Docx")]
    [string]$Format = "Auto",

    [switch]$Both,
    [switch]$KeepWordOpen,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# --- HTML Entity Decoder (C# inline) -----------------------------------------
Add-Type -AssemblyName System.Web
Add-Type -TypeDefinition @"
using System;
using System.Text.RegularExpressions;
using System.Web;

public class HtmlEntityDecoder
{
    public static string Decode(string input)
    {
        if (string.IsNullOrEmpty(input))
            return input;

        // First decode named entities like &Fcy; &Icy; etc.
        string decoded = DecodeNamedEntities(input);

        // Then decode standard HTML entities
        decoded = HttpUtility.HtmlDecode(decoded);

        return decoded;
    }

    private static string DecodeNamedEntities(string input)
    {
        // Map common Cyrillic named entities
        var entityMap = new Dictionary<string, string>
        {
            // Uppercase
            {"Acy", "А"}, {"Bcy", "Б"}, {"Vcy", "В"}, {"Gcy", "Г"}, {"Dcy", "Д"},
            {"IEcy", "Е"}, {"IOcy", "Ё"}, {"Zhecyr", "Ж"}, {"Zcy", "З"},
            {"Icy", "И"}, {"Jseruk", "Й"}, {"Kcy", "К"}, {"Lcy", "Л"},
            {"Mcy", "М"}, {"Ncy", "Н"}, {"Ocy", "О"}, {"Pcy", "П"},
            {"Rcy", "Р"}, {"Scy", "С"}, {"Tcy", "Т"}, {"Ucy", "У"},
            {"Fcy", "Ф"}, {"KHcy", "Х"}, {"TScyr", "Ц"}, {"CHcy", "Ч"},
            {"SHcy", "Ш"}, {"SHCHcy", "Щ"}, {"HARDsign", "Ъ"}, {"Yeru", "Ы"},
            {"SOFTsign", "Ь"}, {"Ecy", "Э"}, {"YUcy", "Ю"}, {"YAcy", "Я"},
            // Lowercase
            {"acy", "а"}, {"bcy", "б"}, {"vcy", "в"}, {"gcy", "г"},
            {"dcy", "д"}, {"iecy", "е"}, {"iocy", "ё"}, {"zhecyr", "ж"},
            {"zcy", "з"}, {"icy", "и"}, {"jseruk", "й"}, {"kcy", "к"},
            {"lcy", "л"}, {"mcy", "м"}, {"ncy", "н"}, {"ocy", "о"},
            {"pcy", "п"}, {"rcy", "р"}, {"scy", "с"}, {"tcy", "т"},
            {"ucy", "у"}, {"fcy", "ф"}, {"khcy", "х"}, {"tscyr", "ц"},
            {"chcy", "ч"}, {"shcy", "ш"}, {"shchcy", "щ"}, {"hardsign", "ъ"},
            {"yeru", "ы"}, {"softsign", "ь"}, {"ecy", "э"}, {"yucy", "ю"},
            {"yacy", "я"},
            // Common symbols
            {"nbsp", " "}, {"ndash", "–"}, {"mdash", "—"},
            {"laquo", "«"}, {"raquo", "»"}, {"hellip", "…"}
        };

        // Match &Xcy; patterns
        decoded = Regex.Replace(input, "&([A-Za-z]+);", match => {
            string entityName = match.Groups[1].Value;
            if (entityMap.ContainsKey(entityName))
                return entityMap[entityName];
            return match.Value; // Keep original if not found
        });

        return decoded;
    }
}
"@

function Decode-HtmlEntities {
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    return [HtmlEntityDecoder]::Decode($Text)
}

function Write-Step($name) { Write-Host ""; Write-Host "[$name]" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg)  { Write-Host "  !   $msg" -ForegroundColor Yellow }
function Write-Fail($msg)  { Write-Host "  X   $msg" -ForegroundColor Red }

Write-Step "Check files"

if (-not (Test-Path $XmlPath)) {
    Write-Fail "XML file not found: $XmlPath"
    exit 1
}
Write-Ok "XML file: $XmlPath"

$xmlItem = Get-Item $XmlPath
$xmlFullPath = $xmlItem.FullName

if ($Format -eq "Auto") {
    $ext = [System.IO.Path]::GetExtension($OutputPath).ToLower()
    if ($ext -eq ".pdf") {
        $Format = "Pdf"
    } elseif ($ext -in @(".docx", ".doc")) {
        $Format = "Docx"
    } else {
        Write-Fail "Cannot determine format from extension: $ext"
        Write-Host "Use -Format Pdf or -Format Docx" -ForegroundColor Yellow
        exit 1
    }
}

$wdFormatPDF = 17
$wdFormatDOCX = 16

Write-Host "  Format: $Format" -ForegroundColor Gray

Write-Step "Check Microsoft Word"

try {
    $word = New-Object -ComObject Word.Application
    Write-Ok "Word found: $($word.Version)"
} catch {
    Write-Fail "Microsoft Word not installed or unavailable"
    Write-Host "Install Microsoft Office or use alternative methods" -ForegroundColor Yellow
    exit 1
}

$word.Visible = $false

try {
    Write-Step "Conversion"

    # Decode HTML entities before opening in Word
    Write-Host "  Decoding HTML entities..." -ForegroundColor Gray
    $xmlContent = Get-Content $xmlFullPath -Raw -Encoding UTF8
    $decodedContent = Decode-HtmlEntities $xmlContent

    # Create temp file with decoded content
    $tempXml = Join-Path $env:TEMP "converted_$(Get-Random).xml"
    $decodedContent | Out-File -FilePath $tempXml -Encoding UTF8 -Force
    Write-Ok "Decoded to temp file: $tempXml"

    Write-Host "  Opening decoded file..." -ForegroundColor Gray
    $doc = $word.Documents.Open($tempXml)

    if ($Both -or $Format -eq "Pdf") {
        if ($Both) {
            $pdfPath = [System.IO.Path]::ChangeExtension($OutputPath, ".pdf")
        } else {
            $pdfPath = $OutputPath
        }

        if ((Test-Path $pdfPath) -and -not $Force) {
            Write-Warn "PDF already exists: $pdfPath (use -Force)"
        } else {
            Write-Host "  Saving PDF: $pdfPath" -ForegroundColor Gray
            $doc.SaveAs([ref]$pdfPath, [ref]$wdFormatPDF)
            Write-Ok "PDF created: $pdfPath"
        }
    }

    if ($Both -or $Format -eq "Docx") {
        if ($Both) {
            $docxPath = [System.IO.Path]::ChangeExtension($OutputPath, ".docx")
        } else {
            $docxPath = $OutputPath
        }

        if ((Test-Path $docxPath) -and -not $Force) {
            Write-Warn "DOCX already exists: $docxPath (use -Force)"
        } else {
            Write-Host "  Saving DOCX: $docxPath" -ForegroundColor Gray
            $doc.SaveAs([ref]$docxPath, [ref]$wdFormatDOCX)
            Write-Ok "DOCX created: $docxPath"
        }
    }

    $doc.Close()

    Write-Step "Result"
    Write-Ok "Conversion completed successfully"

    if ($Both) {
        $pdfSize = if (Test-Path $pdfPath) { [math]::Round(((Get-Item $pdfPath).Length / 1KB), 2) } else { 0 }
        $docxSize = if (Test-Path $docxPath) { [math]::Round(((Get-Item $docxPath).Length / 1KB), 2) } else { 0 }
        Write-Host "  PDF:  $pdfPath ($pdfSize KB)" -ForegroundColor Gray
        Write-Host "  DOCX: $docxPath ($docxSize KB)" -ForegroundColor Gray
    } else {
        $outFile = if ($Format -eq "Pdf") { $pdfPath } else { $docxPath }
        $outSize = [math]::Round(((Get-Item $outFile).Length / 1KB), 2)
        Write-Host "  File: $outFile ($outSize KB)" -ForegroundColor Gray
    }

} finally {
    # Cleanup temp file
    if (Test-Path $tempXml -ErrorAction SilentlyContinue) {
        Remove-Item $tempXml -Force -ErrorAction SilentlyContinue
        Write-Host "  Temp file deleted" -ForegroundColor Gray
    }

    if (-not $KeepWordOpen) {
        Write-Host "  Closing Word..." -ForegroundColor Gray
        $word.Quit()
        [System.Runtime.Interopservices.Marshal]::ReleaseComObject($word) | Out-Null
    } else {
        Write-Warn "Word left open (for debugging)"
    }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
