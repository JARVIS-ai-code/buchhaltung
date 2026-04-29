$ErrorActionPreference = "Stop"

$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$VersionJson = Get-Content "$Root\version.json" -Raw | ConvertFrom-Json
$Version = $VersionJson.version

Write-Host "Baue Windows-App Version $Version ..."

Set-Location $Root
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name JarvisBuchhaltung `
  --icon "assets/icons/jarvis-buchhaltung.ico" `
  --add-data "version.json;." `
  app.py

Write-Host "Bündle GTK Runtime für Windows ..."
$Bash = "C:\msys64\usr\bin\bash.exe"
if (Test-Path $Bash) {
  & $Bash "$Root\packaging\windows\prepare_msys2_runtime.sh"
} else {
  Write-Warning "MSYS2 bash nicht gefunden. Runtime-Bündelung wurde übersprungen."
}

Write-Host "Erzeuge Installer (Inno Setup) ..."
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (!(Test-Path $Iscc)) {
  throw "ISCC.exe nicht gefunden. Bitte Inno Setup 6 installieren."
}

& $Iscc "/DMyAppVersion=$Version" "$Root\packaging\windows\jarvis-buchhaltung.iss"
Write-Host "Fertig. Installer liegt unter dist\windows."
