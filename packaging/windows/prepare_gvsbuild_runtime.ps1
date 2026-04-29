param(
  [string]$Prefix = "C:\gtk"
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Target = Join-Path $Root "dist\JarvisBuchhaltung\runtime"

if (!(Test-Path $Prefix)) {
  throw "gvsbuild Prefix nicht gefunden: $Prefix"
}

Write-Host "Bereite Runtime für Distribution vor ..."
if (Test-Path $Target) {
  Remove-Item $Target -Recurse -Force
}

$folders = @(
  "bin",
  "lib\girepository-1.0",
  "lib\gtk-4.0",
  "lib\gdk-pixbuf-2.0",
  "share\glib-2.0\schemas",
  "share\icons",
  "share\themes"
)

foreach ($folder in $folders) {
  $src = Join-Path $Prefix $folder
  if (Test-Path $src) {
    $dst = Join-Path $Target $folder
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item -Path (Join-Path $src "*") -Destination $dst -Recurse -Force
  }
}

$glibCompileSchemas = Join-Path $Prefix "bin\glib-compile-schemas.exe"
$schemasDir = Join-Path $Target "share\glib-2.0\schemas"
if ((Test-Path $glibCompileSchemas) -and (Test-Path $schemasDir)) {
  & $glibCompileSchemas $schemasDir
}

Write-Host "Runtime vorbereitet unter: $Target"
