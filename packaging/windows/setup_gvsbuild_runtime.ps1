$ErrorActionPreference = "Stop"

param(
  [string]$TargetRoot = "C:\gtk"
)

Write-Host "Lade aktuelle GTK4-Runtime (gvsbuild) ..."
$release = Invoke-RestMethod "https://api.github.com/repos/wingtk/gvsbuild/releases/latest"
$asset = $release.assets | Where-Object { $_.name -match '^GTK4_Gvsbuild_.*_x64\.zip$' } | Select-Object -First 1
if (-not $asset) {
  throw "Kein passendes GTK4_Gvsbuild_x64 Asset gefunden."
}

$tempDir = Join-Path $env:TEMP "gvsbuild-gtk4-runtime"
$zipPath = Join-Path $tempDir $asset.name
$extractDir = Join-Path $tempDir "extract"

if (Test-Path $tempDir) {
  Remove-Item $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

Write-Host "Download: $($asset.browser_download_url)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$sourceRoot = $extractDir
if (-not (Test-Path (Join-Path $sourceRoot "bin"))) {
  $candidate = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
  if ($candidate) {
    $sourceRoot = $candidate.FullName
  }
}

if (-not (Test-Path (Join-Path $sourceRoot "bin"))) {
  throw "GTK Runtime-Struktur nicht gefunden (bin-Verzeichnis fehlt)."
}

if (Test-Path $TargetRoot) {
  Remove-Item $TargetRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TargetRoot | Out-Null

Write-Host "Kopiere Runtime nach $TargetRoot"
Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $TargetRoot -Recurse -Force

$pygObjectWheel = Get-ChildItem -Path (Join-Path $TargetRoot "wheels") -Filter "PyGObject*.whl" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$pyCairoWheel = Get-ChildItem -Path (Join-Path $TargetRoot "wheels") -Filter "pycairo*.whl" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1

if (-not $pygObjectWheel -or -not $pyCairoWheel) {
  throw "PyGObject/pycairo Wheels in $TargetRoot\wheels nicht gefunden."
}

Write-Host "Installiere PyGObject/pycairo Wheels ..."
python -m pip install --upgrade pip
python -m pip install --force-reinstall "$($pygObjectWheel.FullName)"
python -m pip install --force-reinstall "$($pyCairoWheel.FullName)"

Write-Host "gvsbuild Runtime ist bereit: $TargetRoot"
