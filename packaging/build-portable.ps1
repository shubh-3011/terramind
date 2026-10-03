<#
.SYNOPSIS
    Assembles the portable TerraMind Beta 1 Windows bundle from the built app and
    the analyzer sources, then (optionally) zips it for release.

.DESCRIPTION
    The shipped ZIP unzips into a single self-contained folder:

        TerraMind-beta1-win32-x64-full/
          TerraMind.exe            the desktop app (Code-OSS workbench)
          resources/               app + the terramind-core extension
          ... (Chromium/Electron runtime files)
          analyzer/
            runtime/               portable Python 3.13
            app/                   the FastAPI analyzer source
            terramind_ml/          feature extraction + risk endpoints
            models/                empty; the GGUF is downloaded on first run
            run-analyzer.bat       starts uvicorn with the bundled Python
          TerraMind.bat            the launcher (first-run download + start)
          README-FIRST.txt

    The ~940 MB GGUF model is deliberately NOT bundled; TerraMind.bat downloads it
    on first run into %USERPROFILE%\.terramind\models\. See packaging/README.md.

    Steps performed here:
      1. Stage a clean output folder.
      2. Copy the built desktop app (minus its old analyzer/launcher/readme).
      3. Copy a portable Python 3.13 runtime into analyzer\runtime.
      4. pip install --target the analyzer deps (CPU llama-cpp-python wheel) so
         every package lands INSIDE the bundle, not the user profile.
      5. Copy the analyzer sources (app/, terramind_ml/, pyproject.toml).
      6. Drop in our launcher, readme and analyzer starter.
      7. Optionally compress the bundle into a release ZIP.

.PARAMETER SourceApp
    Folder containing the built desktop app (TerraMind.exe + resources/ + runtime
    DLLs). Defaults to the sibling "VSCode-win32-x64" folder next to this repo.

.PARAMETER PythonSource
    A full CPython install to copy as the portable runtime. Must be 3.13 (or at
    least 3.11-3.13). Defaults to C:\Python313.

.PARAMETER OutputDir
    Where the bundle is assembled. Defaults to <repo>\build\packaging\<name>.

.PARAMETER Zip
    Also produce <OutputDir>.zip next to the bundle folder.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build-portable.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build-portable.ps1 -Zip
#>
[CmdletBinding()]
param(
    [string]$SourceApp,
    [string]$PythonSource = "C:\Python313",
    [string]$OutputDir,
    [switch]$Zip
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve paths. $PSScriptRoot is this packaging/ folder; the repo root is its
# parent, and the built app normally sits in a sibling of the repo root.
# ---------------------------------------------------------------------------
$PackagingDir = $PSScriptRoot
$RepoRoot     = Split-Path $PackagingDir -Parent
$BundleName   = "TerraMind-beta1-win32-x64-full"

if (-not $SourceApp) {
    $SourceApp = Join-Path (Split-Path $RepoRoot -Parent) "VSCode-win32-x64"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $RepoRoot "build\packaging\$BundleName"
}

$AnalyzerSrc = Join-Path $RepoRoot "services\analyzer-api"
$BundleAnalyzer = Join-Path $OutputDir "analyzer"
$RuntimeDir  = Join-Path $BundleAnalyzer "runtime"
$SitePackages = Join-Path $RuntimeDir "Lib\site-packages"
$RuntimePython = Join-Path $RuntimeDir "python.exe"

# CPU-only llama-cpp-python wheel index (small, ~12 MB, GitHub-release friendly).
$LlamaCpuIndex = "https://abetlen.github.io/llama-cpp-python/whl/cpu"

# The analyzer's runtime dependencies. llama-cpp-python is pinned; the rest float
# within a compatible range.
$PythonPackages = @(
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.30,<1.0",
    "python-hcl2>=7.3,<8",
    "httpx>=0.27,<1.0",
    "python-multipart",
    "llama-cpp-python==0.3.36"
)

# ---------------------------------------------------------------------------
# Helper: copy a tree with robocopy (robust for deep site-packages paths).
# robocopy exit codes 0-7 mean success; 8+ is a real error.
# ---------------------------------------------------------------------------
function Copy-Tree {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [string[]]$ExcludeDirs  = @(),
        [string[]]$ExcludeFiles = @()
    )
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $roboArgs = @($Source, $Destination, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:2", "/W:1")
    if ($ExcludeDirs.Count  -gt 0) { $roboArgs += "/XD"; $roboArgs += $ExcludeDirs }
    if ($ExcludeFiles.Count -gt 0) { $roboArgs += "/XF"; $roboArgs += $ExcludeFiles }
    & robocopy @roboArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed (exit $LASTEXITCODE) copying '$Source' -> '$Destination'"
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# ---------------------------------------------------------------------------
# Validate inputs before touching anything.
# ---------------------------------------------------------------------------
Write-Step "Validating inputs"
if (-not (Test-Path (Join-Path $SourceApp "TerraMind.exe"))) {
    throw "TerraMind.exe not found in '$SourceApp'. Build the app first or pass -SourceApp."
}
if (-not (Test-Path (Join-Path $PythonSource "python.exe"))) {
    throw "python.exe not found in '$PythonSource'. Pass -PythonSource with a full CPython install."
}
if (-not (Test-Path (Join-Path $AnalyzerSrc "app"))) {
    throw "Analyzer source not found at '$AnalyzerSrc\app'."
}
Write-Host "  App source   : $SourceApp"
Write-Host "  Python source: $PythonSource"
Write-Host "  Analyzer src : $AnalyzerSrc"
Write-Host "  Output       : $OutputDir"

# ---------------------------------------------------------------------------
# 1. Stage a clean output folder.
# ---------------------------------------------------------------------------
Write-Step "Staging clean output folder"
if (Test-Path $OutputDir) {
    Write-Host "  Removing existing $OutputDir"
    Remove-Item -Recurse -Force $OutputDir
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

# ---------------------------------------------------------------------------
# 2. Copy the built desktop app. Exclude the old analyzer plus any launcher and
#    readme that shipped with the app; we provide our own below.
# ---------------------------------------------------------------------------
Write-Step "Copying the desktop app"
Copy-Tree -Source $SourceApp -Destination $OutputDir `
    -ExcludeDirs @("analyzer") `
    -ExcludeFiles @("TerraMind.bat", "README-FIRST.txt")

# ---------------------------------------------------------------------------
# 3. Copy the portable Python runtime. __pycache__ is stripped to keep the ZIP
#    small; the runtime must keep python.exe, DLLs, Lib/ and Lib/site-packages.
# ---------------------------------------------------------------------------
Write-Step "Copying portable Python runtime"
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Copy-Tree -Source $PythonSource -Destination $RuntimeDir `
    -ExcludeDirs @("__pycache__", "test", "tests", "Doc", "Tools")

# ---------------------------------------------------------------------------
# 4. Install the analyzer dependencies INTO the bundle. --target is the crucial
#    flag: without it pip would install into the build machine's user profile.
# ---------------------------------------------------------------------------
Write-Step "Installing analyzer dependencies (CPU llama-cpp-python)"
# Ensure the copied runtime has pip; a full CPython install does, but be safe.
& $RuntimePython -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  pip not found in the runtime; bootstrapping with ensurepip"
    & $RuntimePython -m ensurepip --default-pip
}

& $RuntimePython -m pip install `
    --disable-pip-version-check `
    --no-warn-script-location `
    --target $SitePackages `
    --extra-index-url $LlamaCpuIndex `
    @PythonPackages
if ($LASTEXITCODE -ne 0) {
    throw "pip install failed (exit $LASTEXITCODE)."
}
Write-Host "  Installed $($PythonPackages.Count) packages into $SitePackages"

# ---------------------------------------------------------------------------
# 5. Copy the analyzer source. app/ is what uvicorn serves; terramind_ml/ holds
#    the feature/risk helpers imported by app.main.
# ---------------------------------------------------------------------------
Write-Step "Copying analyzer sources"
Copy-Tree -Source (Join-Path $AnalyzerSrc "app")         -Destination (Join-Path $BundleAnalyzer "app")         -ExcludeDirs @("__pycache__")
Copy-Tree -Source (Join-Path $AnalyzerSrc "terramind_ml") -Destination (Join-Path $BundleAnalyzer "terramind_ml") -ExcludeDirs @("__pycache__")
Copy-Item (Join-Path $AnalyzerSrc "pyproject.toml") (Join-Path $BundleAnalyzer "pyproject.toml") -Force

# models/ is intentionally empty; the launcher downloads the GGUF on first run.
New-Item -ItemType Directory -Force -Path (Join-Path $BundleAnalyzer "models") | Out-Null

# ---------------------------------------------------------------------------
# 6. Drop in the versioned launcher, readme and analyzer starter from this
#    packaging/ folder so the bundle always matches these sources.
# ---------------------------------------------------------------------------
Write-Step "Adding launcher, readme and analyzer starter"
Copy-Item (Join-Path $PackagingDir "TerraMind.bat")           $OutputDir -Force
Copy-Item (Join-Path $PackagingDir "readme-first.txt")        (Join-Path $OutputDir "README-FIRST.txt") -Force
Copy-Item (Join-Path $PackagingDir "analyzer\run-analyzer.bat") $BundleAnalyzer -Force

# ---------------------------------------------------------------------------
# 7. Report the result, then optionally zip it for release.
# ---------------------------------------------------------------------------
Write-Step "Build complete"
$bundleSize = (Get-ChildItem -Recurse -File $OutputDir | Measure-Object -Property Length -Sum).Sum
Write-Host ("  Bundle : {0}" -f $OutputDir)
Write-Host ("  Size   : {0:N1} MB" -f ($bundleSize / 1MB))
Write-Host "  Model  : NOT bundled (downloaded on first run)"

if ($Zip) {
    Write-Step "Compressing release ZIP"
    $zipPath = "$OutputDir.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    # Compress-Archive is fine up to 2 GB; the app+analyzer bundle stays well below.
    Compress-Archive -Path (Join-Path $OutputDir "*") -DestinationPath $zipPath -CompressionLevel Optimal
    Write-Host ("  ZIP    : {0} ({1:N1} MB)" -f $zipPath, ((Get-Item $zipPath).Length / 1MB))
}

Write-Host ""
Write-Host "Smoke test (optional):" -ForegroundColor DarkGray
Write-Host ('  $env:PYTHONNOUSERSITE="1"; $env:TERRAMIND_GGUF_N_GPU_LAYERS="0"') -ForegroundColor DarkGray
Write-Host ('  & "{0}" -m uvicorn app.main:app --port 8010' -f $RuntimePython) -ForegroundColor DarkGray
Write-Host '  curl.exe -s http://127.0.0.1:8010/health   # -> {"status":"ok"}' -ForegroundColor DarkGray
