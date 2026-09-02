#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("'"$ROOT_DIR"'/version.json").read_text(encoding="utf-8"))["version"])')"
PKG_NAME="finanz-cockpit"
BUILD_DIR="$ROOT_DIR/dist/deb"
PKG_DIR="$BUILD_DIR/${PKG_NAME}_${VERSION}_amd64"

rm -rf "$PKG_DIR"
mkdir -p "$PKG_DIR/DEBIAN"
mkdir -p "$PKG_DIR/opt/finanz-cockpit"
mkdir -p "$PKG_DIR/opt/finanz-cockpit/assets/icons"
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
Depends: python3, libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0, libgbm1, libdrm2, libxkbcommon0, libasound2 | libasound2t64
Maintainer: Finanz Cockpit
Description: Finanz Cockpit mit Electron und Python/SQLite
 Lokale Finanz-App mit Electron-Oberflaeche und Python/SQLite-Core.
EOF2

if [ ! -x "$ROOT_DIR/node_modules/electron/dist/electron" ]; then
  (cd "$ROOT_DIR" && npm install)
fi

cp "$ROOT_DIR/app.py" "$PKG_DIR/opt/finanz-cockpit/app.py"
cp "$ROOT_DIR/app_backend.py" "$PKG_DIR/opt/finanz-cockpit/app_backend.py"
cp "$ROOT_DIR/version.json" "$PKG_DIR/opt/finanz-cockpit/version.json"
cp "$ROOT_DIR/package.json" "$PKG_DIR/opt/finanz-cockpit/package.json"
cp "$ROOT_DIR/package-lock.json" "$PKG_DIR/opt/finanz-cockpit/package-lock.json"
cp -a "$ROOT_DIR/finanz_cockpit_core" "$PKG_DIR/opt/finanz-cockpit/finanz_cockpit_core"
cp -a "$ROOT_DIR/electron" "$PKG_DIR/opt/finanz-cockpit/electron"
cp -a "$ROOT_DIR/web" "$PKG_DIR/opt/finanz-cockpit/web"
cp -a "$ROOT_DIR/scripts" "$PKG_DIR/opt/finanz-cockpit/scripts"
cp -a "$ROOT_DIR/node_modules" "$PKG_DIR/opt/finanz-cockpit/node_modules"
cp "$ROOT_DIR/assets/icons/finanz-cockpit.png" "$PKG_DIR/opt/finanz-cockpit/assets/icons/finanz-cockpit.png"
cp "$ROOT_DIR/assets/icons/finanz-cockpit.svg" "$PKG_DIR/opt/finanz-cockpit/assets/icons/finanz-cockpit.svg"
cp "$ROOT_DIR/assets/icons/finanz-cockpit.png" "$PKG_DIR/usr/share/icons/hicolor/256x256/apps/finanz-cockpit.png"
cp "$ROOT_DIR/assets/icons/finanz-cockpit.svg" "$PKG_DIR/usr/share/icons/hicolor/scalable/apps/finanz-cockpit.svg"

cat > "$PKG_DIR/usr/bin/finanz-cockpit" <<'EOF2'
#!/usr/bin/env bash
exec python3 /opt/finanz-cockpit/app.py "$@"
EOF2
chmod 755 "$PKG_DIR/usr/bin/finanz-cockpit"

cp "$ROOT_DIR/packaging/linux/finanz-cockpit.desktop" "$PKG_DIR/usr/share/applications/finanz-cockpit.desktop"

cat > "$PKG_DIR/DEBIAN/postinst" <<'EOF2'
#!/usr/bin/env bash
set -e

chrome_sandbox="/opt/finanz-cockpit/node_modules/electron/dist/chrome-sandbox"
if [ -f "$chrome_sandbox" ]; then
  chown root:root "$chrome_sandbox" || true
  chmod 4755 "$chrome_sandbox" || true
fi

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
