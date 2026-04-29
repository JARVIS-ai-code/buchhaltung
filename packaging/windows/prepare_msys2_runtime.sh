#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="${MSYS2_PREFIX:-/ucrt64}"
TARGET="$ROOT_DIR/dist/JarvisBuchhaltung/runtime"

if [ ! -d "$PREFIX" ]; then
  echo "MSYS2 Prefix nicht gefunden: $PREFIX"
  exit 1
fi

rm -rf "$TARGET"
mkdir -p "$TARGET/bin"
mkdir -p "$TARGET/lib/girepository-1.0"
mkdir -p "$TARGET/share/glib-2.0/schemas"
mkdir -p "$TARGET/share/icons"
mkdir -p "$TARGET/share/themes"

cp -f "$PREFIX"/bin/*.dll "$TARGET/bin/" || true
cp -f "$PREFIX"/bin/gspawn-win64-helper*.exe "$TARGET/bin/" 2>/dev/null || true
cp -f "$PREFIX"/lib/girepository-1.0/*.typelib "$TARGET/lib/girepository-1.0/" || true
cp -rf "$PREFIX"/share/glib-2.0/schemas/* "$TARGET/share/glib-2.0/schemas/" || true
cp -rf "$PREFIX"/share/icons/* "$TARGET/share/icons/" || true
cp -rf "$PREFIX"/share/themes/* "$TARGET/share/themes/" || true

if command -v glib-compile-schemas >/dev/null 2>&1; then
  glib-compile-schemas "$TARGET/share/glib-2.0/schemas" || true
fi

echo "MSYS2 GTK Runtime vorbereitet unter: $TARGET"
