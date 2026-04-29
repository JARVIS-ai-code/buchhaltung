# Packaging

## Version pflegen

Die App-Version kommt aus `version.json`.
Vor jedem Release zuerst diese Datei anpassen, z. B. `1.2.0`.

## Linux (.deb)

```bash
chmod +x packaging/linux/build_deb.sh
packaging/linux/build_deb.sh
```

Ergebnis:
- `dist/deb/jarvis-buchhaltung_<version>_amd64.deb`

Installieren:

```bash
sudo dpkg -i dist/deb/jarvis-buchhaltung_<version>_amd64.deb
```

## Windows (Setup.exe)

Auf Windows in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\windows\build_windows.ps1
```

Voraussetzungen:
- Python
- `pyinstaller`
- Inno Setup 6

Ergebnis:
- `dist/windows/jarvis-buchhaltung-<version>-setup.exe`
