# Buchhaltung (Linux/Windows Desktop)

Native Buchhaltungs-App mit Python, GTK4 und Libadwaita.

## Starten (Entwicklung)

```bash
python3 app.py
```

Voraussetzungen (Linux):
- `python3`
- `python3-gi`
- GTK4 + Libadwaita

## Funktionen

- `Start`: Lohneingänge und Einkünfte aus Nebentätigkeiten dokumentieren
- `Einstellungen`: Grundeinstellungen (Währung, Monatsbudget) und Konten anlegen
- `Konten`: Fokusansicht je Konto mit Dauerzahlungen
- `Analyse`: Monatsauswertung, Kategorien und offene Beträge
- Modernes `Bento Grid`-Layout mit Dark UI, Glass-Sidebar und Micro-Interactions

## Datenspeicherung

Die Daten werden lokal benutzerbezogen gespeichert:
- Linux: `~/.local/share/JarvisBuchhaltung/buchhaltung.db` (oder `$XDG_DATA_HOME/JarvisBuchhaltung/`)
- Windows: `%APPDATA%\JarvisBuchhaltung\buchhaltung.db`

`data.json` im Projektordner wird nur noch als Legacy-Import beim ersten Start genutzt, falls alte Daten vorhanden sind.

## Updates

- Versionsquelle: `version.json`
- Update-Prüfung über GitHub Releases (`JARVIS-ai-code/buchhaltung`)
- Ein-Klick-Update aus der App (Download + Start des Installers/Pakets)

## Installer bauen

Siehe `packaging/README.md`:
- Linux `.deb` Build-Skript
- Windows `Setup.exe` Build-Skript (PyInstaller + MSYS2 GTK Runtime + Inno Setup)
