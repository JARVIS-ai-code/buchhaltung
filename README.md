# Buchhaltung (Electron + Python/SQLite)

Desktop-App mit Electron-Oberfläche und Python-Core:
- Oberfläche: Electron + HTML/CSS/JS (`electron/`, `web/`)
- Verarbeitung und SQLite: Python (`buchhaltung_core/`, `app_backend.py`)
- Datenbank bleibt lokal benutzerbezogen in SQLite.

Die alten nativen GTK/PySide-Dateien liegen zur Referenz unter `alt/`.

## Entwicklung starten

```bash
npm install
npm start
```

Alternativ startet `python3 app.py` dieselbe Electron-App, sobald `npm install` ausgeführt wurde.

## Datenspeicherung

Die Daten werden lokal benutzerbezogen in SQLite gespeichert:
- Linux: `~/.local/share/JarvisBuchhaltung/buchhaltung.db`
- Windows: `%APPDATA%\JarvisBuchhaltung\buchhaltung.db`

## Updates

- Versionsquelle: `version.json`
- Update-Prüfung über GitHub Releases (`JARVIS-ai-code/buchhaltung`)

## Installer bauen

Siehe `packaging/README.md`.

Schnellstart Windows-Installer (auf Windows ausführen):

```powershell
npm install
npm run dist:win
```
