#Requires -Version 5.1
<#
.SYNOPSIS
    Downloads the TerraMind Terraform GGUF model from a GitHub release asset.

.DESCRIPTION
    Downloads a single .gguf asset from a GitHub Releases URL of the form
        https://github.com/<Repo>/releases/download/<Tag>/<AssetName>
    verifies its SHA-256, and prints the environment variables and editor setting
    needed to run TerraMind's bundled llama.cpp engine. The GGUF is never committed
    to git; it is hosted as a release asset (see docs/OPEN_SOURCE.md and
    docs/RUNNING_LOCAL_MODEL.md).

    The script never overwrites an existing valid file. If the destination already
    exists and matches -Sha256 it is left untouched; if it exists and does not match,
    the script stops and tells you what to do. Use -Force to replace it.

.PARAMETER Repo
    GitHub repository in owner/name form. Default: shubh-3011/terramind.

.PARAMETER Tag
    Release tag that holds the asset. Default: terramind-v0.1.0-model.

.PARAMETER AssetName
    Release asset file name to download. Default is the current Q4_K_M build.

.PARAMETER OutDir
    Directory to store the .gguf. Default: %LOCALAPPDATA%\TerraMind\models.

.PARAMETER Sha256
    Expected SHA-256 of the asset (hex, case-insensitive). Strongly recommended.
    Without it the script cannot verify the download.

.PARAMETER Force
    Re-download and overwrite even if a file already exists at the destination.

.EXAMPLE
    .\scripts\get_model.ps1 `
        -Repo shubh-3011/terramind `
        -Tag terramind-v0.1.0-model `
        -AssetName terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf `
        -OutDir "$env:LOCALAPPDATA\TerraMind\models" `
        -Sha256 6917bf571e822b5739b671509c37e32c66800c78af9d54c6546326e13fec7906

.NOTES
    Requires only Windows PowerShell 5.1+ and network access to github.com.
#>
[CmdletBinding()]
param(
    [string]$Repo = "shubh-3011/terramind",

    [string]$Tag = "terramind-v0.1.0-model",

    [string]$AssetName = "terramind-qwen2.5-coder-1.5b-terraform-merged-Q4_K_M.gguf",

    [string]$OutDir = (Join-Path $env:LOCALAPPDATA "TerraMind\models"),

    [string]$Sha256 = "",

    [switch]$Force
)

$ErrorActionPreference = "Stop"
# Suppress the per-chunk progress bar; it slows large downloads on Windows PowerShell.
$ProgressPreference = "SilentlyContinue"

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Show-NextSteps {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModelPath
    )
    Write-Host ""
    Write-Host "Model ready: $ModelPath"
    Write-Host ""
    Write-Host "Set these before starting the TerraMind analyzer:"
    Write-Host '  $env:TERRAMIND_GENERATION_ENGINE = "gguf"'
    Write-Host "  `$env:TERRAMIND_GGUF_MODEL = `"$ModelPath`""
    Write-Host ""
    Write-Host "In the editor, set terramind.generationEngine to `"gguf`"."
    Write-Host "Full guide: docs/RUNNING_LOCAL_MODEL.md"
}

$expected = $Sha256.Trim().ToLowerInvariant()

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$outPath = Join-Path -Path $OutDir -ChildPath $AssetName
$url = "https://github.com/$Repo/releases/download/$Tag/$AssetName"

# Do not overwrite an existing file unless explicitly forced.
if ((Test-Path -LiteralPath $outPath) -and (-not $Force)) {
    if ($expected) {
        $found = Get-FileSha256 -Path $outPath
        if ($found -eq $expected) {
            Write-Host "Existing file already matches -Sha256; not downloading."
            Show-NextSteps -ModelPath (Resolve-Path -LiteralPath $outPath).Path
            return
        }
        throw @"
Existing file does not match -Sha256.
  Path:     $outPath
  Expected: $expected
  Actual:   $found
Delete the file or re-run with -Force to replace it.
"@
    }
    throw @"
File already exists and no -Sha256 was provided, so it cannot be verified.
  Path: $outPath
Pass -Sha256 to verify it, or -Force to replace it.
"@
}

Write-Host "Downloading $url"
Write-Host "  -> $outPath"

try {
    Invoke-WebRequest -Uri $url -OutFile $outPath -UseBasicParsing -MaximumRedirection 5
}
catch {
    if (Test-Path -LiteralPath $outPath) {
        Remove-Item -LiteralPath $outPath -Force -ErrorAction SilentlyContinue
    }
    throw @"
Download failed for $url
Check -Repo, -Tag, and -AssetName, confirm the release and asset exist, and verify network access.
Underlying error: $($_.Exception.Message)
"@
}

if ((-not (Test-Path -LiteralPath $outPath)) -or ((Get-Item -LiteralPath $outPath).Length -eq 0)) {
    if (Test-Path -LiteralPath $outPath) {
        Remove-Item -LiteralPath $outPath -Force -ErrorAction SilentlyContinue
    }
    throw "Download reported success but the file is missing or empty: $outPath"
}

if ($expected) {
    $actual = Get-FileSha256 -Path $outPath
    if ($actual -ne $expected) {
        Remove-Item -LiteralPath $outPath -Force
        throw @"
SHA-256 mismatch; the downloaded file was removed.
  Expected: $expected
  Actual:   $actual
"@
    }
    Write-Host "SHA-256 verified: $actual"
}
else {
    Write-Warning "No -Sha256 was provided; the download was NOT verified. Compare it with model-manifest.json before use."
}

Show-NextSteps -ModelPath (Resolve-Path -LiteralPath $outPath).Path
