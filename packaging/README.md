# Packaging

## Version pflegen

Die App-Version kommt aus `version.json`.

## Linux (.deb)

```bash
chmod +x packaging/linux/build_deb.sh
packaging/linux/build_deb.sh
```

Ergebnis:
- `dist/deb/jarvis-buchhaltung_<version>_amd64.deb`

## Windows (Setup.exe)

Auf Windows in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\packaging\windows\build_windows.ps1
```

Der Windows-Build nutzt PySide6 + PyInstaller + Inno Setup.

Ergebnis:
- `dist/windows/jarvis-buchhaltung-<version>-setup.exe`
