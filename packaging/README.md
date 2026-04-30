# Packaging

## Version pflegen

Die App-Version kommt aus `version.json`.

## Linux (.deb)

```bash
npm install
chmod +x packaging/linux/build_deb.sh
packaging/linux/build_deb.sh
```

Ergebnis:
- `dist/deb/jarvis-buchhaltung_<version>_amd64.deb`

## Windows

Die neue Windows-EXE wird über Electron Builder erzeugt.

Auf Windows in PowerShell:

```powershell
npm install
npm run dist:win
```

Was passiert dabei:
- `scripts/build-backend-win.js` baut zuerst `app_backend.py` mit PyInstaller zu `dist/backend/JarvisBuchhaltungBackend.exe`
- `electron-builder` erstellt danach den NSIS-Installer (`.exe`)

Ergebnis:
- `dist/electron/jarvis-buchhaltung-<version>-setup.exe`
- `dist/electron/jarvis-buchhaltung-<version>-portable.exe`

Wenn der Setup-Installer auf einem System durch Richtlinien/Defender blockiert wird:

```powershell
npm run dist:win:portable
```

Dann direkt die `portable.exe` starten (ohne Installation).

Hinweis:
- Der alte PySide6/Inno-Setup-Build liegt weiterhin nur zur Referenz unter `alt/packaging/windows`.
