# Rebuild the VS Code native modules now that Spectre mitigation is disabled.
$ErrorActionPreference = "Continue"
Set-Location "C:\Users\shubh\Downloads\terramind"

# Restore the real policy-watcher entry point (it was stubbed only because the
# binding could not be built). It is rebuilt below.
$stub = "node_modules\@vscode\policy-watcher\index.js.orig"
if (Test-Path $stub) {
  Copy-Item $stub "node_modules\@vscode\policy-watcher\index.js" -Force
}

$modules = @(
  '@vscode/spdlog',
  '@vscode/deviceid',
  '@vscode/fs-copyfile',
  '@vscode/native-watchdog',
  '@vscode/sqlite3',
  '@vscode/windows-ca-certs',
  '@vscode/windows-mutex',
  '@vscode/windows-registry',
  '@vscode/policy-watcher',
  'native-keymap',
  'native-is-elevated',
  'windows-foreground-love',
  'kerberos'
)

$index = 0
foreach ($module in $modules) {
  $index++
  Write-Host ("=== [{0}/{1}] rebuilding {2} ===" -f $index, $modules.Count, $module)
  & npm rebuild $module 2>&1 | Select-Object -Last 3
}

Write-Host ""
Write-Host "=== verification: which modules now have a .node binary? ==="
foreach ($module in $modules) {
  $path = "node_modules\$module"
  $count = (Get-ChildItem $path -Recurse -Filter '*.node' -ErrorAction SilentlyContinue | Measure-Object).Count
  Write-Host ("{0,-32} .node={1}" -f $module, $count)
}
Write-Host "=== rebuild complete ==="
