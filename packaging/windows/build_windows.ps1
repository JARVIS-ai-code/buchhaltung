$ErrorActionPreference = "Stop"

function Convert-ToMsysPath([string]$windowsPath) {
  $full = (Resolve-Path $windowsPath).Path
  $drive = $full.Substring(0,1).ToLower()
  $rest = $full.Substring(2).Replace('\\','/')
  return "/$drive$rest"
}

$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$RootMsys = Convert-ToMsysPath $Root
$VersionJson = Get-Content "$Root\version.json" -Raw | ConvertFrom-Json
$Version = $VersionJson.version

Write-Host "Baue Windows-App Version $Version (MSYS2) ..."

$Bash = "C:\msys64\usr\bin\bash.exe"
if (!(Test-Path $Bash)) {
  throw "MSYS2 wurde nicht gefunden (erwartet: C:\msys64). Bitte zuerst MSYS2 installieren."
}

$msysBuild = @"
set -euo pipefail
export MSYSTEM=UCRT64
export CHERE_INVOKING=1
pacman -Sy --needed --noconfirm \
  mingw-w64-ucrt-x86_64-python \
  mingw-w64-ucrt-x86_64-python-gobject \
  mingw-w64-ucrt-x86_64-python-cairo \
  mingw-w64-ucrt-x86_64-gtk4 \
  mingw-w64-ucrt-x86_64-libadwaita \
  mingw-w64-ucrt-x86_64-pyinstaller
cd '$RootMsys'
/ucrt64/bin/python -V
/ucrt64/bin/pyinstaller --noconfirm --clean --windowed --name JarvisBuchhaltung --icon assets/icons/jarvis-buchhaltung.ico --add-data 'version.json;.' app.py
bash packaging/windows/prepare_msys2_runtime.sh
"@

& $Bash -lc $msysBuild

Write-Host "Erzeuge Installer (Inno Setup) ..."
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (!(Test-Path $Iscc)) {
  throw "ISCC.exe nicht gefunden. Bitte Inno Setup 6 installieren."
}

& $Iscc "/DMyAppVersion=$Version" "$Root\packaging\windows\jarvis-buchhaltung.iss"
Write-Host "Fertig. Installer liegt unter dist\windows."
