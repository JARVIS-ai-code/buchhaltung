#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("'"$ROOT_DIR"'/version.json").read_text(encoding="utf-8"))["version"])')"
PKG_NAME="jarvis-buchhaltung"
BUILD_DIR="$ROOT_DIR/dist/deb"
PKG_DIR="$BUILD_DIR/${PKG_NAME}_${VERSION}_amd64"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/opt/jarvis-buchhaltung"
mkdir -p "$PKG_DIR/opt/jarvis-buchhaltung/assets/icons"
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/applications"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$PKG_DIR/usr/share/icons/hicolor/scalable/apps"

cat > "$PKG_DIR/DEBIAN/control" <<EOF2
Package: $PKG_NAME
Version: $VERSION
Section: office
Priority: optional
Architecture: amd64
Depends: python3, python3-pyside6.qtwidgets | python3-pyside6
Maintainer: JARVIS-ai-code
Description: Desktop-Buchhaltung fuer Linux/Windows
 Native Buchhaltungs-App mit separatem Linux/Windows UI.
EOF2

cp "$ROOT_DIR/app.py" "$PKG_DIR/opt/jarvis-buchhaltung/app.py"
cp "$ROOT_DIR/app_qt.py" "$PKG_DIR/opt/jarvis-buchhaltung/app_qt.py"
cp "$ROOT_DIR/app_gtk.py" "$PKG_DIR/opt/jarvis-buchhaltung/app_gtk.py"
cp "$ROOT_DIR/version.json" "$PKG_DIR/opt/jarvis-buchhaltung/version.json"
cp "$ROOT_DIR/assets/icons/jarvis-buchhaltung.png" "$PKG_DIR/opt/jarvis-buchhaltung/assets/icons/jarvis-buchhaltung.png"
cp "$ROOT_DIR/assets/icons/jarvis-buchhaltung.svg" "$PKG_DIR/opt/jarvis-buchhaltung/assets/icons/jarvis-buchhaltung.svg"
cp "$ROOT_DIR/assets/icons/jarvis-buchhaltung.png" "$PKG_DIR/usr/share/icons/hicolor/256x256/apps/jarvis-buchhaltung.png"
cp "$ROOT_DIR/assets/icons/jarvis-buchhaltung.svg" "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/jarvis-buchhaltung.svg"

cat > "$PKG_DIR/usr/bin/jarvis-buchhaltung" <<'EOF2'
#!/usr/bin/env bash
exec python3 /opt/jarvis-buchhaltung/app.py "$@"
EOF2
chmod 755 "$PKG_DIR/usr/bin/jarvis-buchhaltung"

cp "$ROOT_DIR/packaging/linux/jarvis-buchhaltung.desktop" "$PKG_DIR/usr/share/applications/jarvis-buchhaltung.desktop"

cat > "$PKG_DIR/DEBIAN/postinst" <<'EOF2'
#!/usr/bin/env bash
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
EOF2
chmod 755 "$PKG_DIR/DEBIAN/postinst"

cat > "$PKG_DIR/DEBIAN/postrm" <<'EOF2'
#!/usr/bin/env bash
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
EOF2
chmod 755 "$PKG_DIR/DEBIAN/postrm"

mkdir -p "$BUILD_DIR"
OUTPUT_DEB="$BUILD_DIR/${PKG_NAME}_${VERSION}_amd64.deb"
dpkg-deb --build "$PKG_DIR" "$OUTPUT_DEB"

echo "Fertig: $OUTPUT_DEB"
