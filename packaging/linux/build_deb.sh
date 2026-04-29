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
mkdir -p "$PKG_DIR/usr/bin"
mkdir -p "$PKG_DIR/usr/share/applications"

cat > "$PKG_DIR/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Section: office
Priority: optional
Architecture: amd64
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1
Maintainer: JARVIS-ai-code
Description: Desktop-Buchhaltung fuer Linux
 Native GTK4-App fuer private Buchhaltung mit Konten, Dauerzahlungen und Analyse.
EOF

cp "$ROOT_DIR/app.py" "$PKG_DIR/opt/jarvis-buchhaltung/app.py"
cp "$ROOT_DIR/version.json" "$PKG_DIR/opt/jarvis-buchhaltung/version.json"

cat > "$PKG_DIR/usr/bin/jarvis-buchhaltung" <<'EOF'
#!/usr/bin/env bash
exec python3 /opt/jarvis-buchhaltung/app.py "$@"
EOF
chmod 755 "$PKG_DIR/usr/bin/jarvis-buchhaltung"

cp "$ROOT_DIR/packaging/linux/jarvis-buchhaltung.desktop" "$PKG_DIR/usr/share/applications/jarvis-buchhaltung.desktop"

mkdir -p "$BUILD_DIR"
OUTPUT_DEB="$BUILD_DIR/${PKG_NAME}_${VERSION}_amd64.deb"
dpkg-deb --build "$PKG_DIR" "$OUTPUT_DEB"

echo "Fertig: $OUTPUT_DEB"
