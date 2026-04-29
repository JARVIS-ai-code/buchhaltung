# Buchhaltung (Linux Desktop)

Native Buchhaltungs-App fuer Linux mit Python, GTK4 und Libadwaita.

## Starten

```bash
python3 app.py
```

Voraussetzungen:
- `python3`
- `python3-gi`
- GTK4 + Libadwaita (bei dir bereits vorhanden)

## Funktionen

- `Start`: Lohneingaenge und Einkuenfte aus Nebentaetigkeiten dokumentieren
- `Einstellungen`: Grundeinstellungen (Waehrung, Monatsbudget) und Konten anlegen
- `Konten`: Fokusansicht je Konto mit Dauerzahlungen, Kategorien-Karten und Donut-Chart
- `Analyse`: Interaktive Donut-Charts, KPI-Karten und Monatsauswertung
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
- Windows `Setup.exe` Build-Skript (PyInstaller + Inno Setup)
