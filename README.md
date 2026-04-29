# Buchhaltung (Linux/Windows Desktop)

Native Buchhaltungs-App mit separaten Oberflächen je Betriebssystem:
- Linux: GTK/Libadwaita (`app_gtk.py`)
- Windows: PySide6 (`app_qt.py`)
- Einstiegspunkt: `app.py` (OS-Dispatcher)

## Entwicklung starten

```bash
python3 app.py
```

## Datenspeicherung

Die Daten werden lokal benutzerbezogen in SQLite gespeichert:
- Linux: `~/.local/share/JarvisBuchhaltung/buchhaltung.db`
- Windows: `%APPDATA%\JarvisBuchhaltung\buchhaltung.db`

## Updates

- Versionsquelle: `version.json`
- Update-Prüfung über GitHub Releases (`JARVIS-ai-code/buchhaltung`)

## Installer bauen

Siehe `packaging/README.md`.
