# Alt

Dieser Ordner enthält die alte native Oberfläche und alte Verpackungsschritte, die nach dem Electron-Umbau nicht mehr vom Hauptprojekt verwendet werden.

- `app_gtk.py`: frühere Linux-GTK/Libadwaita-Oberfläche
- `app_qt.py`: frühere Windows-PySide6-Oberfläche
- `packaging/windows/`: früherer PySide6/PyInstaller/Inno-Setup-Build

Die aktive App läuft jetzt über Electron (`electron/`, `web/`) mit Python/SQLite-Core (`buchhaltung_core/`, `app_backend.py`).
