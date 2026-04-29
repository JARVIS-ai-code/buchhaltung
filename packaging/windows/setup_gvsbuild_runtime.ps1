param(
  [string]$TargetRoot = "C:\gtk"
)

$ErrorActionPreference = "Stop"

$downloadUrl = "https://github.com/wingtk/gvsbuild/releases/latest/download/GTK4_Gvsbuild_latest_x64.zip"
$tempDir = Join-Path $env:TEMP "gvsbuild-gtk4-runtime"
$zipPath = Join-Path $tempDir "GTK4_Gvsbuild_latest_x64.zip"
$extractDir = Join-Path $tempDir "extract"

Write-Host "Lade aktuelle GTK4-Runtime (gvsbuild): $downloadUrl"

if (Test-Path $tempDir) {
  Remove-Item $tempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $tempDir | Out-Null

Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$runtimeRoot = Get-ChildItem -Path $extractDir -Recurse -Directory |
  Where-Object {
    (Test-Path (Join-Path $_.FullName "bin\libgtk-4-1.dll")) -and
    (Test-Path (Join-Path $_.FullName "lib\girepository-1.0"))
  } |
  Sort-Object { $_.FullName.Length } |
  Select-Object -First 1

if (-not $runtimeRoot) {
  if ((Test-Path (Join-Path $extractDir "bin\libgtk-4-1.dll")) -and (Test-Path (Join-Path $extractDir "lib\girepository-1.0"))) {
    $runtimeRoot = [pscustomobject]@{ FullName = $extractDir }
  }
}

if (-not $runtimeRoot) {
  throw "GTK Runtime-Struktur nicht gefunden (libgtk-4-1.dll / girepository fehlt)."
}

if (Test-Path $TargetRoot) {
  Remove-Item $TargetRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $TargetRoot | Out-Null

Write-Host "Kopiere Runtime von $($runtimeRoot.FullName) nach $TargetRoot"
Copy-Item -Path (Join-Path $runtimeRoot.FullName "*") -Destination $TargetRoot -Recurse -Force

$wheelCandidates = @()
if (Test-Path (Join-Path $runtimeRoot.FullName "wheels")) {
  $wheelCandidates += Get-ChildItem -Path (Join-Path $runtimeRoot.FullName "wheels") -Recurse -File -Filter "*.whl"
}
if (Test-Path (Join-Path $TargetRoot "wheels")) {
  $wheelCandidates += Get-ChildItem -Path (Join-Path $TargetRoot "wheels") -Recurse -File -Filter "*.whl"
}

$pygObjectWheel = $wheelCandidates | Where-Object { $_.Name -match '(?i)^pygobject.*\.whl$' } | Sort-Object Name -Descending | Select-Object -First 1
$pyCairoWheel = $wheelCandidates | Where-Object { $_.Name -match '(?i)^pycairo.*\.whl$' } | Sort-Object Name -Descending | Select-Object -First 1

if ($pygObjectWheel -and $pyCairoWheel) {
  Write-Host "Installiere Wheels: $($pygObjectWheel.Name), $($pyCairoWheel.Name)"
  python -m pip install --upgrade pip
  python -m pip install --force-reinstall "$($pygObjectWheel.FullName)"
  python -m pip install --force-reinstall "$($pyCairoWheel.FullName)"
} else {
  Write-Warning "PyGObject/pycairo Wheels im Runtime-ZIP nicht gefunden. Versuche pip fallback."
  python -m pip install --upgrade pip
  python -m pip install pycairo PyGObject
}

Write-Host "gvsbuild Runtime ist bereit: $TargetRoot"
