#!/usr/bin/env python3
import json
import traceback
import uuid
import html
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path

def _configure_windows_gtk_runtime() -> None:
    if os.name != "nt":
        return

    candidate_roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", str(exe_dir)))
        candidate_roots.extend([exe_dir, exe_dir / "runtime", meipass, meipass / "runtime"])
    else:
        here = Path(__file__).resolve().parent
        candidate_roots.extend([here, here / "runtime"])

    def unique_existing(paths: list[Path]) -> list[Path]:
        out: list[Path] = []
        seen: set[str] = set()
        for p in paths:
            key = str(p.resolve()) if p.exists() else str(p)
            if key in seen or (not p.exists()):
                continue
            seen.add(key)
            out.append(p)
        return out

    roots = unique_existing(candidate_roots)
    if not roots:
        return

    runtime_root: Path | None = None
    dll_dirs: list[Path] = []
    typelib_dirs: list[Path] = []
    share_dirs: list[Path] = []
    schema_dirs: list[Path] = []
    pixbuf_dirs: list[Path] = []
    pixbuf_cache_files: list[Path] = []
    gtk_module_dirs: list[Path] = []

    for root in roots:
        bin_dir = root / "bin"
        typelibs = root / "lib" / "girepository-1.0"
        share_dir = root / "share"
        schemas = share_dir / "glib-2.0" / "schemas"
        pixbuf_dir = root / "lib" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders"
        pixbuf_cache = root / "lib" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders.cache"
        gtk_mod_dir = root / "lib" / "gtk-4.0"

        if bin_dir.exists():
            if runtime_root is None:
                runtime_root = root
            dll_dirs.append(bin_dir)
        if typelibs.exists():
            typelib_dirs.append(typelibs)
        if share_dir.exists():
            share_dirs.append(share_dir)
        if schemas.exists():
            schema_dirs.append(schemas)
        if pixbuf_dir.exists():
            pixbuf_dirs.append(pixbuf_dir)
        if pixbuf_cache.exists():
            pixbuf_cache_files.append(pixbuf_cache)
        if gtk_mod_dir.exists():
            gtk_module_dirs.append(gtk_mod_dir)

    for dll_dir in dll_dirs:
        try:
            os.add_dll_directory(str(dll_dir))
        except (AttributeError, OSError):
            pass

    if dll_dirs:
        os.environ["PATH"] = os.pathsep.join([str(p) for p in dll_dirs] + [os.environ.get("PATH", "")])

    if typelib_dirs:
        current = os.environ.get("GI_TYPELIB_PATH", "")
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join([str(p) for p in typelib_dirs] + ([current] if current else []))

    if share_dirs:
        current = os.environ.get("XDG_DATA_DIRS", "")
        os.environ["XDG_DATA_DIRS"] = os.pathsep.join([str(p) for p in share_dirs] + ([current] if current else []))

    if schema_dirs and not os.environ.get("GSETTINGS_SCHEMA_DIR"):
        os.environ["GSETTINGS_SCHEMA_DIR"] = str(schema_dirs[0])

    if gtk_module_dirs and not os.environ.get("GTK_PATH"):
        os.environ["GTK_PATH"] = str(gtk_module_dirs[0])

    if pixbuf_dirs:
        os.environ["GDK_PIXBUF_MODULEDIR"] = str(pixbuf_dirs[0])

    if pixbuf_cache_files:
        os.environ["GDK_PIXBUF_MODULE_FILE"] = str(pixbuf_cache_files[0])
    elif runtime_root is not None:
        query_loaders = runtime_root / "bin" / "gdk-pixbuf-query-loaders.exe"
        loaders_cache = runtime_root / "lib" / "gdk-pixbuf-2.0" / "2.10.0" / "loaders.cache"
        if query_loaders.exists():
            try:
                loaders_cache.parent.mkdir(parents=True, exist_ok=True)
                proc = subprocess.run(
                    [str(query_loaders)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    loaders_cache.write_text(proc.stdout, encoding="utf-8")
                    os.environ["GDK_PIXBUF_MODULE_FILE"] = str(loaders_cache)
            except OSError:
                pass


_configure_windows_gtk_runtime()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango


APP_NAME = "JarvisBuchhaltung"
IS_WINDOWS = os.name == "nt"
PROJECT_DIR = Path(__file__).parent
APP_ICON_NAME = "jarvis-buchhaltung"
LEGACY_DATA_PATH = PROJECT_DIR / "data.json"
LEGACY_DB_PATH = PROJECT_DIR / "buchhaltung.db"
VERSION_FILE_PATH = PROJECT_DIR / "version.json"
GITHUB_REPO_URL = "https://github.com/JARVIS-ai-code/buchhaltung"
GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/JARVIS-ai-code/buchhaltung/releases/latest"


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", "").strip() or os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME


DATA_DIR = app_data_dir()
DATA_PATH = DATA_DIR / "data.json"
DB_PATH = DATA_DIR / "buchhaltung.db"


def load_app_version() -> str:
    try:
        payload = json.loads(VERSION_FILE_PATH.read_text(encoding="utf-8"))
        value = str(payload.get("version", "")).strip()
        if value:
            return value
    except (OSError, json.JSONDecodeError):
        pass
    return "0.1.0"


APP_VERSION = load_app_version()

DEFAULT_DATA = {
    "settings": {
        "currency": "EUR",
        "monthly_budget": 0.0,
        "income_sources": ["Lohn", "Nebentätigkeit", "Spesen"],
        "visible_month": "",
        "autostart_enabled": False,
        "autostart_open_window": False,
        "reminder_interval_minutes": 15,
        "auto_update_check": True,
        "update_check_interval_hours": 6,
    },
    "accounts": [],
    "recurring_payments": [],
    "expenses": [],
    "incomes": [],
    "meta": {"recurring_applied_months": [], "closed_months": []},
}

VIOLET = "#8A5CFF"
MINT = "#3DE8A5"
DEEP_CHARCOAL = "#121212"
DEFAULT_INCOME_SOURCES = ["Lohn", "Nebentätigkeit", "Spesen"]
RECURRING_FREQUENCY_OPTIONS = [
    ("Monatlich", "monthly"),
    ("Quartalszahlung", "quarterly"),
    ("Jährlich", "yearly"),
]

CATEGORY_COLORS = [
    "#8A5CFF",
    "#7A6CFF",
    "#4FC3F7",
    "#3DE8A5",
    "#F4C542",
    "#FF8A65",
    "#FF6FB5",
]


def month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def format_month_label(month: str) -> str:
    try:
        year_text, month_text = month.split("-")
        year = int(year_text)
        month_num = int(month_text)
        if not (1 <= month_num <= 12):
            raise ValueError
    except ValueError:
        return month
    return f"{month_num:02d}-{year}"


def parse_month_text(value: str) -> str:
    text = value.strip()
    for fmt in ("%m-%Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return f"{parsed.year}-{parsed.month:02d}"
        except ValueError:
            pass
    raise ValueError("Ungültiger Monat")


def iso_today() -> str:
    today = date.today()
    return f"{today.day:02d}-{today.month:02d}-{today.year}"


def parse_input_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Ungültiges Datum")


def month_key_from_date_text(value: str) -> str | None:
    try:
        d = parse_input_date(value)
    except ValueError:
        return None
    return month_key(d)


def parse_date_safe(value: str) -> date:
    try:
        return parse_input_date(value)
    except ValueError:
        return date.min


def parse_float(text: str) -> float:
    return float(text.strip().replace(",", "."))


def format_money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "yes", "ja", "on"):
            return True
        if raw in ("0", "false", "no", "nein", "off"):
            return False
    return default


def append_runtime_log(message: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / "runtime.log"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")
    except OSError:
        pass


def version_tuple(version_text: str) -> tuple[int, ...]:
    text = str(version_text or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = [int(item) for item in re.findall(r"\d+", text)]
    if not parts:
        return (0,)
    return tuple(parts)


def is_newer_version(latest: str, current: str) -> bool:
    latest_tuple = version_tuple(latest)
    current_tuple = version_tuple(current)
    max_len = max(len(latest_tuple), len(current_tuple))
    latest_norm = latest_tuple + (0,) * (max_len - len(latest_tuple))
    current_norm = current_tuple + (0,) * (max_len - len(current_tuple))
    return latest_norm > current_norm


class DonutChart(Gtk.Box):
    def __init__(self, center_text: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.segments: list[tuple[float, str, str]] = []
        self.progress = 1.0
        self.center_text = center_text
        self.sub_text = ""
        self.target_fraction = 0.0

        self.value_label = Gtk.Label(label=center_text or "0%")
        self.value_label.add_css_class("kpi-value")
        self.value_label.set_xalign(0)

        self.sub_label = Gtk.Label(label="")
        self.sub_label.add_css_class("subtitle")
        self.sub_label.set_xalign(0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_hexpand(True)
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_show_text(False)

        self.legend_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self.append(self.value_label)
        self.append(self.sub_label)
        self.append(self.progress_bar)
        self.append(self.legend_box)

    def set_segments(self, segments: list[tuple[float, str, str]], center_text: str = "", sub_text: str = "") -> None:
        self.segments = segments
        if center_text:
            self.center_text = center_text
        self.sub_text = sub_text
        self.target_fraction = self._extract_fraction(self.center_text, segments)
        self._render_legend()
        self._update_display()

    def set_progress(self, progress: float) -> None:
        self.progress = max(0.0, min(1.0, progress))
        self._update_display()

    def _extract_fraction(self, center_text: str, segments: list[tuple[float, str, str]]) -> float:
        text = center_text.strip()
        if text.endswith("%"):
            raw = text[:-1].strip()
            try:
                return max(0.0, min(float(raw) / 100.0, 1.0))
            except ValueError:
                pass

        total = sum(max(0.0, value) for value, _, _ in segments)
        if total <= 0:
            return 0.0
        return max(0.0, min(segments[0][0] / total, 1.0))

    def _render_legend(self) -> None:
        child = self.legend_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.legend_box.remove(child)
            child = nxt

        top_items = sorted(self.segments, key=lambda x: x[0], reverse=True)[:3]
        for value, color, label in top_items:
            item = Gtk.Label()
            item.set_xalign(0)
            item.set_use_markup(True)
            safe_label = html.escape(label)
            item.set_markup(f"<span foreground='{color}'>●</span> {safe_label}")
            item.add_css_class("subtitle")
            self.legend_box.append(item)

    def _update_display(self) -> None:
        self.value_label.set_text(self.center_text or "0%")
        self.sub_label.set_text(self.sub_text)
        self.progress_bar.set_fraction(max(0.0, min(self.target_fraction * self.progress, 1.0)))


MainWindowBase = Gtk.ApplicationWindow if IS_WINDOWS else Adw.ApplicationWindow


class FinanceAppWindow(MainWindowBase):
    def __init__(self, app: Adw.Application, launched_from_autostart: bool = False) -> None:
        super().__init__(application=app)
        self.set_title("JARVIS Buchhaltungssystem")
        self.set_icon_name(APP_ICON_NAME)
        self.set_default_size(1280, 820)
        self.set_resizable(True)
        self.set_decorated(True)
        self.is_closing = False
        self.connect("close-request", self.on_close_request)

        self.data = self.load_data()

        self.nav_buttons: dict[str, Gtk.Button] = {}
        self.account_ids: list[str] = []
        self.account_names: list[str] = []
        self.selected_account_focus_id: str | None = None
        self.recurring_popup: Gtk.Window | None = None
        self.installment_popup: Gtk.Window | None = None
        self.income_edit_popup: Gtk.Window | None = None
        self.recurring_edit_popup: Gtk.Window | None = None
        self.analysis_open_filter_id: str = "ALL"
        self.analysis_category_filter_id: str = "ALL"
        self._last_accounts_scroller_height = 0
        self.launched_from_autostart = launched_from_autostart
        self.reminder_popup: Gtk.Window | None = None
        self.reminder_popup_open_btn: Gtk.Button | None = None
        self.reminder_popup_text: Gtk.Label | None = None
        self.last_reminder_popup_at = 0.0
        self.last_reminder_signature = ""
        self.last_reminder_day = date.today().isoformat()
        self.update_check_in_progress = False
        self.last_update_check_at = 0.0
        self.last_announced_update_tag = ""
        self.update_popup: Gtk.Window | None = None
        self.update_popup_title: Gtk.Label | None = None
        self.update_popup_details: Gtk.Label | None = None
        self.update_popup_install_btn: Gtk.Button | None = None
        self.update_popup_asset_name = ""
        self.update_popup_asset_url = ""
        self.update_download_in_progress = False
        self.update_install_in_progress = False

        self._setup_css()
        self._build_ui()
        append_runtime_log(
            "ui-built "
            f"accounts={len(self.data.get('accounts', []))} "
            f"stack_child={self.stack.get_visible_child_name() if hasattr(self, 'stack') else '-'}"
        )
        self.ensure_autostart_configuration()
        self.apply_monthly_recurring_if_needed()
        self.refresh_all()
        self.start_reminder_monitoring()
        self.start_update_monitoring()
        GLib.idle_add(self.check_overdue_notifications, True)

        GLib.idle_add(self.run_initial_animations)

    def on_close_request(self, *_args) -> bool:
        self.is_closing = True
        app = self.get_application()
        if app is not None:
            app.quit()
        return False

    # -----------------------------
    # Data layer
    # -----------------------------
    def load_data(self) -> dict:
        self._ensure_data_layout()
        self._initialize_db()

        db_data = self._load_data_from_db()
        if db_data is not None and self._db_payload_has_content(db_data):
            return self._normalize_data(db_data)

        legacy_data: dict | None = None
        # First-time migration path from legacy JSON beside app.py.
        legacy_source = LEGACY_DATA_PATH if LEGACY_DATA_PATH.exists() else DATA_PATH
        if legacy_source.exists():
            try:
                legacy_data = json.loads(legacy_source.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                legacy_data = None

        normalized = self._normalize_data(legacy_data or deepcopy(DEFAULT_DATA))
        self._save_data_to_db(normalized)
        return normalized

    def save_data(self) -> None:
        self._save_data_to_db(self.data)

    def _ensure_data_layout(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self._migrate_legacy_db_if_needed()
        self._migrate_legacy_json_if_needed()

    def _migrate_legacy_db_if_needed(self) -> None:
        if DB_PATH.exists():
            return
        if not LEGACY_DB_PATH.exists():
            return
        if LEGACY_DB_PATH.resolve() == DB_PATH.resolve():
            return
        try:
            DB_PATH.write_bytes(LEGACY_DB_PATH.read_bytes())
        except OSError:
            pass

    def _migrate_legacy_json_if_needed(self) -> None:
        if DATA_PATH.exists():
            return
        if not LEGACY_DATA_PATH.exists():
            return
        if LEGACY_DATA_PATH.resolve() == DATA_PATH.resolve():
            return
        try:
            DATA_PATH.write_bytes(LEGACY_DATA_PATH.read_bytes())
        except OSError:
            pass

    def _connect_db(self) -> sqlite3.Connection:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DB_PATH)
        connection.execute("PRAGMA foreign_keys = OFF")
        return connection

    def _initialize_db(self) -> None:
        conn = self._connect_db()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recurring_payments (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    day INTEGER NOT NULL,
                    frequency TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    final_amount REAL,
                    checked_months TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expenses (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    date TEXT NOT NULL,
                    source TEXT,
                    recurring_plan_id TEXT,
                    recurring_month TEXT
                );
                CREATE TABLE IF NOT EXISTS incomes (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    date TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date);
                CREATE INDEX IF NOT EXISTS idx_expenses_account ON expenses(account_id);
                CREATE INDEX IF NOT EXISTS idx_incomes_date ON incomes(date);
                CREATE INDEX IF NOT EXISTS idx_incomes_account ON incomes(account_id);
                CREATE INDEX IF NOT EXISTS idx_recurring_account ON recurring_payments(account_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _db_payload_has_content(self, payload: dict) -> bool:
        return any(
            [
                bool(payload.get("accounts")),
                bool(payload.get("recurring_payments")),
                bool(payload.get("expenses")),
                bool(payload.get("incomes")),
                bool(payload.get("settings")),
                bool(payload.get("meta")),
            ]
        )

    def _load_data_from_db(self) -> dict | None:
        conn = self._connect_db()
        try:
            row_count = 0
            for table in ("settings", "meta", "accounts", "recurring_payments", "expenses", "incomes"):
                row_count += int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            if row_count == 0:
                return None

            data = deepcopy(DEFAULT_DATA)

            settings_rows = conn.execute("SELECT key, value FROM settings").fetchall()
            for key, value in settings_rows:
                if key == "income_sources":
                    try:
                        data["settings"][key] = json.loads(value)
                    except json.JSONDecodeError:
                        data["settings"][key] = list(DEFAULT_INCOME_SOURCES)
                elif key == "monthly_budget":
                    try:
                        data["settings"][key] = float(value)
                    except ValueError:
                        data["settings"][key] = 0.0
                else:
                    data["settings"][key] = value

            meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
            for key, value in meta_rows:
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    parsed = []
                data["meta"][key] = parsed

            accounts_rows = conn.execute("SELECT id, name FROM accounts ORDER BY name").fetchall()
            data["accounts"] = [{"id": rid, "name": name} for rid, name in accounts_rows]

            recurring_rows = conn.execute(
                """
                SELECT id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months
                FROM recurring_payments
                ORDER BY description
                """
            ).fetchall()
            recurring_items: list[dict] = []
            for row in recurring_rows:
                checked_raw = row[10] if row[10] is not None else "[]"
                try:
                    checked = json.loads(checked_raw)
                except json.JSONDecodeError:
                    checked = []
                recurring_items.append(
                    {
                        "id": row[0],
                        "kind": row[1],
                        "account_id": row[2],
                        "description": row[3],
                        "amount": float(row[4]),
                        "day": int(row[5]),
                        "frequency": row[6],
                        "start_date": row[7],
                        "end_date": row[8],
                        "final_amount": row[9],
                        "checked_months": checked if isinstance(checked, list) else [],
                    }
                )
            data["recurring_payments"] = recurring_items

            expense_rows = conn.execute(
                """
                SELECT id, account_id, description, amount, date, source, recurring_plan_id, recurring_month
                FROM expenses
                ORDER BY date
                """
            ).fetchall()
            data["expenses"] = [
                {
                    "id": row[0],
                    "account_id": row[1],
                    "description": row[2],
                    "amount": float(row[3]),
                    "date": row[4],
                    "source": row[5],
                    "recurring_plan_id": row[6],
                    "recurring_month": row[7],
                }
                for row in expense_rows
            ]

            income_rows = conn.execute(
                "SELECT id, type, account_id, description, amount, date FROM incomes ORDER BY date"
            ).fetchall()
            data["incomes"] = [
                {
                    "id": row[0],
                    "type": row[1],
                    "account_id": row[2],
                    "description": row[3],
                    "amount": float(row[4]),
                    "date": row[5],
                }
                for row in income_rows
            ]

            return data
        except sqlite3.Error:
            return None
        finally:
            conn.close()

    def _save_data_to_db(self, payload: dict) -> None:
        data = self._normalize_data(payload)
        conn = self._connect_db()
        try:
            self._initialize_db()
            conn.execute("BEGIN")

            conn.execute("DELETE FROM settings")
            conn.execute("DELETE FROM meta")
            conn.execute("DELETE FROM accounts")
            conn.execute("DELETE FROM recurring_payments")
            conn.execute("DELETE FROM expenses")
            conn.execute("DELETE FROM incomes")

            for key, value in data["settings"].items():
                if key == "income_sources":
                    stored_value = json.dumps(value, ensure_ascii=False)
                else:
                    stored_value = str(value)
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (key, stored_value))

            for key, value in data["meta"].items():
                conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))

            for account in data["accounts"]:
                account_id = str(account.get("id") or uuid.uuid4())
                conn.execute(
                    "INSERT INTO accounts(id, name) VALUES (?, ?)",
                    (account_id, str(account.get("name", ""))),
                )

            for recurring in data["recurring_payments"]:
                recurring_id = str(recurring.get("id") or uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO recurring_payments(
                        id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        recurring_id,
                        recurring.get("kind", "standard"),
                        str(recurring.get("account_id", "")),
                        str(recurring.get("description", "")),
                        float(recurring.get("amount", 0.0)),
                        int(recurring.get("day", 1)),
                        recurring.get("frequency", "monthly"),
                        recurring.get("start_date"),
                        recurring.get("end_date"),
                        recurring.get("final_amount"),
                        json.dumps(recurring.get("checked_months", []), ensure_ascii=False),
                    ),
                )

            for expense in data["expenses"]:
                expense_id = str(expense.get("id") or uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO expenses(id, account_id, description, amount, date, source, recurring_plan_id, recurring_month)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        expense_id,
                        str(expense.get("account_id", "")),
                        str(expense.get("description", "")),
                        float(expense.get("amount", 0.0)),
                        expense.get("date", ""),
                        expense.get("source"),
                        expense.get("recurring_plan_id"),
                        expense.get("recurring_month"),
                    ),
                )

            for income in data["incomes"]:
                income_id = str(income.get("id") or uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO incomes(id, type, account_id, description, amount, date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        income_id,
                        str(income.get("type", "")),
                        str(income.get("account_id", "")),
                        str(income.get("description", "")),
                        float(income.get("amount", 0.0)),
                        income.get("date", ""),
                    ),
                )

            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _normalize_data(self, loaded: dict) -> dict:
        if not isinstance(loaded, dict):
            loaded = {}
        data = deepcopy(DEFAULT_DATA)
        data["settings"].update(loaded.get("settings", {}))
        data["accounts"] = loaded.get("accounts", [])
        data["recurring_payments"] = loaded.get("recurring_payments", [])
        data["expenses"] = loaded.get("expenses", [])
        data["incomes"] = loaded.get("incomes", [])
        if isinstance(loaded.get("meta"), dict):
            data["meta"].update(loaded["meta"])
        if "recurring_applied_months" not in data["meta"]:
            data["meta"]["recurring_applied_months"] = []
        closed = data["meta"].get("closed_months")
        if not isinstance(closed, list):
            data["meta"]["closed_months"] = []
        else:
            cleaned_closed: list[str] = []
            for item in closed:
                try:
                    month = parse_month_text(str(item))
                except ValueError:
                    continue
                if month not in cleaned_closed:
                    cleaned_closed.append(month)
            data["meta"]["closed_months"] = cleaned_closed

        sources = data["settings"].get("income_sources")
        if not isinstance(sources, list):
            data["settings"]["income_sources"] = list(DEFAULT_INCOME_SOURCES)
        else:
            cleaned: list[str] = []
            for source in sources:
                text = str(source).strip()
                if text and text.lower() not in [s.lower() for s in cleaned]:
                    cleaned.append(text)
            if not cleaned:
                cleaned = list(DEFAULT_INCOME_SOURCES)
            if "spesen" not in [s.lower() for s in cleaned]:
                cleaned.append("Spesen")
            data["settings"]["income_sources"] = cleaned

        visible_month_raw = str(data["settings"].get("visible_month", "")).strip()
        if visible_month_raw:
            try:
                data["settings"]["visible_month"] = parse_month_text(visible_month_raw)
            except ValueError:
                data["settings"]["visible_month"] = month_key(date.today())
        else:
            data["settings"]["visible_month"] = month_key(date.today())

        data["settings"]["autostart_enabled"] = parse_bool(data["settings"].get("autostart_enabled"), False)
        data["settings"]["autostart_open_window"] = parse_bool(data["settings"].get("autostart_open_window"), False)
        interval_raw = data["settings"].get("reminder_interval_minutes", 15)
        try:
            interval_value = int(interval_raw)
        except (TypeError, ValueError):
            interval_value = 15
        data["settings"]["reminder_interval_minutes"] = max(1, min(interval_value, 240))
        data["settings"]["auto_update_check"] = parse_bool(data["settings"].get("auto_update_check"), True)
        update_raw = data["settings"].get("update_check_interval_hours", 6)
        try:
            update_hours = int(update_raw)
        except (TypeError, ValueError):
            update_hours = 6
        data["settings"]["update_check_interval_hours"] = max(1, min(update_hours, 168))

        for recurring in data["recurring_payments"]:
            if not isinstance(recurring.get("checked_months"), list):
                recurring["checked_months"] = []
            if recurring.get("kind") not in ("standard", "installment"):
                recurring["kind"] = "standard"
            if recurring.get("frequency") not in ("monthly", "quarterly", "yearly"):
                recurring["frequency"] = "monthly"
            if recurring["kind"] == "standard" and not recurring.get("start_date"):
                recurring["start_date"] = iso_today()
            if recurring["kind"] == "installment":
                if not recurring.get("start_date"):
                    recurring["start_date"] = iso_today()
                if not recurring.get("end_date"):
                    recurring["end_date"] = recurring["start_date"]
                if recurring.get("final_amount") in ("", None):
                    recurring["final_amount"] = None
        return data

    def account_name(self, account_id: str | None) -> str:
        for account in self.data["accounts"]:
            if account["id"] == account_id:
                return account["name"]
        return "-"

    def get_income_sources(self) -> list[str]:
        sources = self.data["settings"].get("income_sources")
        if not isinstance(sources, list):
            self.data["settings"]["income_sources"] = list(DEFAULT_INCOME_SOURCES)
            return list(DEFAULT_INCOME_SOURCES)

        cleaned: list[str] = []
        for source in sources:
            text = str(source).strip()
            if text and text.lower() not in [s.lower() for s in cleaned]:
                cleaned.append(text)

        if not cleaned:
            cleaned = list(DEFAULT_INCOME_SOURCES)
        if cleaned != sources:
            self.data["settings"]["income_sources"] = cleaned
        return cleaned

    def current_display_month(self) -> str:
        raw = str(self.data["settings"].get("visible_month", "")).strip()
        if not raw:
            current = month_key(date.today())
            self.data["settings"]["visible_month"] = current
            return current
        try:
            parsed = parse_month_text(raw)
        except ValueError:
            parsed = month_key(date.today())
        if parsed != raw:
            self.data["settings"]["visible_month"] = parsed
        return parsed

    def month_is_closed(self, month: str) -> bool:
        closed = self.data.get("meta", {}).get("closed_months", [])
        return isinstance(closed, list) and month in closed

    def autostart_enabled(self) -> bool:
        return parse_bool(self.data["settings"].get("autostart_enabled"), False)

    def should_open_window_on_autostart(self) -> bool:
        return parse_bool(self.data["settings"].get("autostart_open_window"), False)

    def reminder_interval_minutes(self) -> int:
        raw = self.data["settings"].get("reminder_interval_minutes", 15)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 15
        return max(1, min(value, 240))

    def auto_update_check_enabled(self) -> bool:
        return parse_bool(self.data["settings"].get("auto_update_check"), True)

    def update_check_interval_hours(self) -> int:
        raw = self.data["settings"].get("update_check_interval_hours", 6)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 6
        return max(1, min(value, 168))

    # -----------------------------
    # UI base
    # -----------------------------
    def _setup_css(self) -> None:
        if IS_WINDOWS:
            # Windows-safe fallback style: no advanced effects, high contrast, predictable rendering.
            css = f"""
            window {{
              background: #1b1b1f;
              color: #f2f2f6;
            }}

            .app-root {{
              padding: 14px;
            }}

            .glass-sidebar {{
              background-color: #23232a;
              border: 1px solid #3a3a45;
              border-radius: 14px;
              padding: 12px;
            }}

            .main-surface {{
              background-color: #1f1f26;
              border: 1px solid #343440;
              border-radius: 14px;
              padding: 12px;
            }}

            .nav-button, .account-focus-button {{
              border-radius: 10px;
              padding: 8px 10px;
            }}

            .nav-button.active, .account-focus-button.active {{
              background: #5e43b7;
              color: #ffffff;
            }}

            .bento-card {{
              background-color: #292934;
              border: 1px solid #3c3c48;
              border-radius: 14px;
              padding: 12px;
            }}

            entry, combobox, dropdown, spinbutton {{
              min-height: 34px;
              background: #2f2f3b;
              color: #f7f7ff;
              border: 1px solid #505064;
              border-radius: 10px;
            }}

            button.solid {{
              min-height: 36px;
              border-radius: 10px;
              background: #7a56ea;
              color: #ffffff;
              font-weight: 700;
            }}

            .danger {{
              background: #71303a;
              color: #ffd8df;
            }}

            .subtitle, .muted {{
              color: #c6c6d8;
            }}
            """
        else:
            css = f"""
        * {{
          font-family: Inter, \"Geist Sans\", \"Cantarell\", sans-serif;
        }}

        window {{
          background: linear-gradient(145deg, #121212 0%, #17171b 48%, #101015 100%);
          color: #f4f5f7;
        }}

        .app-root {{
          padding: 20px;
          border-radius: 24px;
        }}

        .glass-sidebar {{
          background-color: rgba(22, 22, 28, 0.62);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 24px;
          box-shadow: 0 20px 40px rgba(0, 0, 0, 0.38);
          padding: 16px;
        }}

        .main-surface {{
          background-color: rgba(19, 19, 22, 0.9);
          border: 1px solid rgba(255, 255, 255, 0.06);
          border-radius: 24px;
          padding: 18px;
        }}

        .nav-button {{
          border-radius: 16px;
          padding: 10px 12px;
          background: transparent;
          color: #cfcfe8;
          border: 1px solid rgba(255,255,255,0.04);
          transition: all 180ms ease;
        }}

        .nav-button.active {{
          background: rgba(138, 92, 255, 0.24);
          border-color: rgba(138, 92, 255, 0.64);
          color: #ffffff;
          box-shadow: 0 1px 5px rgba(138, 92, 255, 0.07);
        }}

        .account-focus-button {{
          border-radius: 12px;
          padding: 8px 12px;
          background: rgba(255,255,255,0.04);
          color: #d8d8ea;
          border: 1px solid rgba(255,255,255,0.08);
        }}

        .account-focus-button.active {{
          background: rgba(138, 92, 255, 0.24);
          border-color: rgba(138, 92, 255, 0.62);
          color: #ffffff;
        }}

        .expense-inline-row > box {{
          min-width: 180px;
        }}

        .title-xl {{
          font-size: 26px;
          font-weight: 700;
          letter-spacing: 0.2px;
        }}

        .subtitle {{
          color: #b8b8cc;
          font-size: 13px;
        }}

        .bento-card {{
          background-color: rgba(30, 30, 38, 0.88);
          border: 1px solid rgba(255,255,255,0.06);
          border-radius: 24px;
          padding: 16px;
          box-shadow: 0 14px 28px rgba(0,0,0,0.28);
        }}

        .kpi-value {{
          font-size: 22px;
          font-weight: 700;
        }}

        .kpi-positive {{
          color: {MINT};
        }}

        .kpi-negative {{
          color: #ff7070;
        }}

        entry, combobox, dropdown, spinbutton {{
          border-radius: 14px;
          min-height: 36px;
          padding: 4px 10px;
          background: rgba(255,255,255,0.06);
          border: 1px solid rgba(255,255,255,0.1);
          color: #f5f6fc;
        }}

        button.solid {{
          border-radius: 14px;
          min-height: 38px;
          padding: 0 14px;
          color: #120f1a;
          background: linear-gradient(120deg, {VIOLET}, #A678FF);
          box-shadow: 0 1px 5px rgba(138, 92, 255, 0.09);
          font-weight: 700;
        }}

        .danger {{
          background: rgba(255, 95, 110, 0.26);
          color: #ffdbe2;
          border: 1px solid rgba(255, 118, 131, 0.52);
        }}

        .danger:hover {{
          background: rgba(255, 95, 110, 0.34);
          color: #ffeaf0;
        }}

        .expense-card {{
          border-radius: 20px;
          padding: 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          transition: all 180ms ease;
        }}

        .expense-card.hovered {{
          transform: scale(1.02);
          background: rgba(138,92,255,0.18);
          border-color: rgba(138,92,255,0.45);
          box-shadow: 0 0 0 1px rgba(61,232,165,0.32), 0 18px 34px rgba(138,92,255,0.33);
        }}

        .recurring-compact {{
          padding: 6px 10px;
          border-radius: 12px;
        }}

        .recurring-compact checkbutton {{
          margin-top: 0;
        }}

        .recurring-row {{
          min-height: 36px;
        }}

        .flow-scroll {{
          background: transparent;
        }}

        .accounts-scroll,
        .accounts-scroll > viewport {{
          background: transparent;
          border-radius: 16px;
        }}

        .account-list {{
          background: transparent;
        }}

        .account-list row {{
          background: transparent;
          padding: 2px 0;
        }}

        .account-list row:selected {{
          background: transparent;
        }}

        .account-row {{
          border-radius: 16px;
          padding: 10px;
          background: rgba(255, 255, 255, 0.05);
          border: 1px solid rgba(255, 255, 255, 0.09);
        }}

        .settings-account-icon {{
          color: #ececff;
          opacity: 1;
        }}

        .settings-account-name {{
          color: #f4f5ff;
          font-weight: 600;
        }}

        popover.menu-popover contents {{
          background: rgba(24, 24, 31, 0.98);
          border: 1px solid rgba(255, 255, 255, 0.14);
          border-radius: 14px;
          box-shadow: 0 12px 28px rgba(0, 0, 0, 0.44);
        }}

        popover.menu-popover button {{
          color: #f3f4ff;
          background: rgba(255, 255, 255, 0.08);
          border: 1px solid rgba(255, 255, 255, 0.12);
          border-radius: 10px;
        }}

        popover.menu-popover button:hover {{
          background: rgba(138, 92, 255, 0.24);
          border-color: rgba(138, 92, 255, 0.58);
        }}

        .muted {{
          color: #a2a2b3;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _build_ui(self) -> None:
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        root.add_css_class("app-root")

        if IS_WINDOWS:
            header = Gtk.HeaderBar()
            header.set_show_title_buttons(True)
            header.set_decoration_layout("minimize,maximize,close")
            title_label = Gtk.Label(label="JARVIS Buchhaltungssystem")
            title_label.add_css_class("title-sm")
            header.set_title_widget(title_label)
            self.set_titlebar(header)
            self.set_child(root)
        else:
            toolbar_view = Adw.ToolbarView()
            header = Adw.HeaderBar()
            header.set_show_start_title_buttons(True)
            header.set_show_end_title_buttons(True)
            toolbar_view.add_top_bar(header)
            toolbar_view.set_content(root)
            self.set_content(toolbar_view)

        sidebar = self._build_sidebar()
        root.append(sidebar)

        main_surface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_surface.add_css_class("main-surface")
        main_surface.set_hexpand(True)
        main_surface.set_vexpand(True)
        root.append(main_surface)

        transition = Gtk.StackTransitionType.NONE if IS_WINDOWS else Gtk.StackTransitionType.CROSSFADE
        self.stack = Gtk.Stack(transition_type=transition)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.stack.set_hhomogeneous(False)
        self.stack.set_vhomogeneous(False)
        self.stack.connect("notify::visible-child-name", self._on_page_switched)
        self.page_scroller = Gtk.ScrolledWindow()
        self.page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.page_scroller.set_kinetic_scrolling(True)
        self.page_scroller.set_overlay_scrolling(not IS_WINDOWS)
        self.page_scroller.set_propagate_natural_height(False)
        self.page_scroller.set_propagate_natural_width(False)
        self.page_scroller.set_vexpand(True)
        self.page_scroller.set_hexpand(True)
        self.page_scroller.set_child(self.stack)
        main_surface.append(self.page_scroller)

        self.start_page = self._build_start_page()
        self.accounts_page = self._build_accounts_page()
        self.analysis_page = self._build_analysis_page()
        self.settings_page = self._build_settings_page()

        self.stack.add_named(self.start_page, "start")
        self.stack.add_named(self.accounts_page, "accounts")
        self.stack.add_named(self.analysis_page, "analysis")
        self.stack.add_named(self.settings_page, "settings")

        self.stack.set_visible_child(self.start_page)
        self.switch_page("start")
        self.add_tick_callback(self._sync_accounts_layout_tick)

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.add_css_class("glass-sidebar")
        sidebar.set_hexpand(False)
        sidebar.set_halign(Gtk.Align.START)
        sidebar.set_size_request(260, -1)

        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label="Finanz Cockpit")
        title.add_css_class("title-xl")
        title.set_xalign(0)
        sub = Gtk.Label(label="Privatbuchhaltung")
        sub.add_css_class("subtitle")
        sub.set_xalign(0)
        top.append(title)
        top.append(sub)
        sidebar.append(top)

        sidebar.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        nav_items = [
            ("start", "Start", ["go-home-symbolic", "user-home-symbolic", "applications-system-symbolic"]),
            ("accounts", "Konten", ["wallet-symbolic", "folder-symbolic", "applications-office-symbolic"]),
            (
                "analysis",
                "Analyse",
                ["view-statistics-symbolic", "utilities-system-monitor-symbolic", "x-office-spreadsheet-symbolic"],
            ),
            ("settings", "Einstellungen", ["emblem-system-symbolic", "preferences-system-symbolic"]),
        ]

        for page_name, label, icon_candidates in nav_items:
            button = self._nav_button(label, icon_candidates, page_name)
            self.nav_buttons[page_name] = button
            sidebar.append(button)

        sidebar.append(Gtk.Box(vexpand=True))

        legend = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        legend_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        legend_card.add_css_class("bento-card")
        legend_label = Gtk.Label(label="Live-Hinweis")
        legend_label.set_xalign(0)
        legend_label.add_css_class("subtitle")
        legend_card.append(legend_label)
        legend_value = Gtk.Label(label="Mint = positiver Cashflow")
        legend_value.set_xalign(0)
        legend_value.add_css_class("kpi-positive")
        legend_card.append(legend_value)
        legend.append(legend_card)
        sidebar.append(legend)

        return sidebar

    def _resolve_icon_name(self, candidates: list[str]) -> str:
        display = Gdk.Display.get_default()
        if display is None:
            return candidates[0]
        theme = Gtk.IconTheme.get_for_display(display)
        for name in candidates:
            if theme.has_icon(name):
                return name
        return candidates[0]

    def _nav_button(self, label: str, icon_candidates: list[str], page_name: str) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("nav-button")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        icon = Gtk.Image.new_from_icon_name(self._resolve_icon_name(icon_candidates))
        icon.set_pixel_size(18)
        text = Gtk.Label(label=label)
        text.set_xalign(0)
        text.set_hexpand(True)
        box.append(icon)
        box.append(text)
        button.set_child(box)
        button.connect("clicked", lambda _b: self.switch_page(page_name))
        return button

    def switch_page(self, page_name: str) -> None:
        self.stack.set_visible_child_name(page_name)
        for name, button in self.nav_buttons.items():
            if name == page_name:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    # -----------------------------
    # Page builders
    # -----------------------------
    def _build_start_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        income_form = self._card_with_header("Einnahmen erfassen", "Lohn, Nebentätigkeit und Spesen")
        income_form.root.set_size_request(420, -1)
        income_form.root.set_valign(Gtk.Align.START)
        form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        self.income_type_items = []
        self.income_type_model = Gtk.StringList.new(self.income_type_items)
        self.income_type = Gtk.DropDown.new(self.income_type_model, None)

        self.income_account_model = Gtk.StringList.new([])
        self.income_account = Gtk.DropDown.new(self.income_account_model, None)

        self.income_desc = Gtk.Entry(placeholder_text="Beschreibung")
        self.income_amount = Gtk.Entry(placeholder_text="Betrag")
        self.income_date = Gtk.Entry(placeholder_text="DD-MM-JJJJ")
        self.income_date.set_text(iso_today())

        for label, widget in [
            ("Typ", self.income_type),
            ("Konto", self.income_account),
            ("Beschreibung", self.income_desc),
            ("Betrag", self.income_amount),
            ("Datum", self.income_date),
        ]:
            form_box.append(self._labeled(label, widget))

        income_save = Gtk.Button(label="Einnahme speichern")
        income_save.add_css_class("solid")
        income_save.connect("clicked", self.on_add_income)
        form_box.append(income_save)
        income_form.content.append(form_box)

        cashflow_card = self._card_with_header("Cashflow", "Live-Monatsstatus")
        cashflow_card.root.set_valign(Gtk.Align.START)
        self.start_cashflow_value = Gtk.Label(label="-")
        self.start_cashflow_value.add_css_class("kpi-value")
        self.start_cashflow_value.set_xalign(0)
        cashflow_card.content.append(self.start_cashflow_value)
        open_head = Gtk.Label(label="Offen je Konto (Daueraufträge)")
        open_head.set_xalign(0)
        open_head.add_css_class("subtitle")
        cashflow_card.content.append(open_head)
        self.start_open_accounts_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cashflow_card.content.append(self.start_open_accounts_box)

        recent_card = self._card_with_header("Letzte Einnahmen", "Karten statt Tabellen")
        recent_card.root.set_valign(Gtk.Align.START)
        self.income_recent_flow = self._flow_container(min_per_line=1, max_per_line=2)
        recent_card.content.append(self._scroller_for(self.income_recent_flow, min_h=180))

        next_payments_card = self._card_with_header("Nächste Zahlungen je Konto", "Daueraufträge im Fokus")
        next_payments_card.root.set_valign(Gtk.Align.START)
        self.start_next_payments_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.start_next_payments_grid.set_hexpand(True)
        next_payments_card.content.append(self._scroller_for(self.start_next_payments_grid, min_h=190))

        grid.attach(income_form.root, 0, 0, 1, 2)
        grid.attach(cashflow_card.root, 1, 0, 1, 1)
        grid.attach(recent_card.root, 1, 1, 1, 1)
        grid.attach(next_payments_card.root, 0, 2, 2, 1)

        self.start_animated_widgets = [income_form.root, cashflow_card.root, recent_card.root, next_payments_card.root]
        return grid

    def _build_accounts_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_top(10)
        page.set_margin_bottom(10)
        page.set_margin_start(10)
        page.set_margin_end(10)
        page.set_vexpand(True)
        page.set_hexpand(True)
        page.set_valign(Gtk.Align.FILL)

        focus_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        focus_bar.set_vexpand(False)
        self.accounts_focus_bar = focus_bar
        self.account_focus_flow = Gtk.FlowBox()
        self.account_focus_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.account_focus_flow.set_row_spacing(8)
        self.account_focus_flow.set_column_spacing(8)
        self.account_focus_flow.set_min_children_per_line(1)
        self.account_focus_flow.set_max_children_per_line(8)
        self.account_focus_flow.set_hexpand(True)
        focus_bar.append(self.account_focus_flow)

        add_recurring_popup_btn = Gtk.Button(label="Dauerzahlung hinzufügen")
        add_recurring_popup_btn.add_css_class("solid")
        add_recurring_popup_btn.connect("clicked", self.open_recurring_popup)
        focus_bar.append(add_recurring_popup_btn)

        add_installment_btn = Gtk.Button(label="Abzahlung")
        add_installment_btn.connect("clicked", self.open_installment_popup)
        focus_bar.append(add_installment_btn)

        recurring_list_card = self._card_with_header("Aktive Dauerzahlungen", "Kompakt mit Monats-Häkchen")
        self.accounts_recurring_card = recurring_list_card.root
        recurring_list_card.root.set_vexpand(True)
        recurring_list_card.root.set_hexpand(True)
        recurring_list_card.root.set_valign(Gtk.Align.FILL)
        recurring_list_card.content.set_vexpand(True)
        recurring_list_card.content.set_valign(Gtk.Align.FILL)
        self.recurring_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.recurring_list_box.set_hexpand(True)
        self.recurring_list_box.set_valign(Gtk.Align.START)
        recurring_scroller = self._scroller_for(self.recurring_list_box, min_h=0)
        self.recurring_scroller = recurring_scroller
        recurring_scroller.set_vexpand(True)
        recurring_scroller.set_hexpand(True)
        recurring_scroller.set_valign(Gtk.Align.FILL)
        recurring_scroller.set_propagate_natural_height(False)
        recurring_scroller.set_propagate_natural_width(True)
        recurring_scroller.set_min_content_height(0)
        recurring_scroller.set_max_content_height(self._accounts_scroller_target_height())
        recurring_list_card.content.append(recurring_scroller)

        page.append(focus_bar)
        page.append(recurring_list_card.root)

        self.accounts_animated_widgets = [recurring_list_card.root]
        return page

    def _build_analysis_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        expense_form_card = self._card_with_header("Ausgabe erfassen", "Jetzt unter Analyse")
        expense_form_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        expense_form_box.add_css_class("expense-inline-row")
        self.expense_account_model = Gtk.StringList.new([])
        self.expense_account = Gtk.DropDown.new(self.expense_account_model, None)
        self.expense_desc = Gtk.Entry(placeholder_text="Kategorie / Beschreibung")
        self.expense_amount = Gtk.Entry(placeholder_text="Betrag")
        self.expense_date = Gtk.Entry(placeholder_text="DD-MM-JJJJ")
        self.expense_date.set_text(iso_today())
        self.expense_desc.set_hexpand(True)
        expense_form_box.append(self._labeled("Konto", self.expense_account))
        expense_form_box.append(self._labeled("Kategorie", self.expense_desc))
        expense_form_box.append(self._labeled("Betrag", self.expense_amount))
        expense_form_box.append(self._labeled("Datum", self.expense_date))
        add_expense = Gtk.Button(label="Ausgabe speichern")
        add_expense.add_css_class("solid")
        add_expense.connect("clicked", self.on_add_expense)
        add_expense.set_valign(Gtk.Align.END)
        expense_form_box.append(add_expense)
        expense_form_card.content.append(expense_form_box)

        headline_card = self._card_with_header("Analyse", "Ausgaben, Budget, Cashflow")
        self.analysis_month = Gtk.Label(label="")
        self.analysis_month.set_xalign(0)
        self.analysis_month.add_css_class("subtitle")
        headline_card.content.append(self.analysis_month)

        self.kpi_income_row, self.kpi_income_value = self._kpi_row("Einnahmen")
        self.kpi_expense_row, self.kpi_expense_value = self._kpi_row("Ausgaben")
        self.kpi_remaining_row, self.kpi_remaining_value = self._kpi_row("Übrig")
        self.kpi_budget_left_row, self.kpi_budget_left_value = self._kpi_row("Budget frei")
        for row in [
            self.kpi_income_row,
            self.kpi_expense_row,
            self.kpi_remaining_row,
            self.kpi_budget_left_row,
        ]:
            headline_card.content.append(row)

        budget_chart_card = self._card_with_header("Budget-Quote", "Float-in Chart")
        self.budget_chart = DonutChart("0%")
        budget_chart_card.content.append(self.budget_chart)

        account_chart_card = self._card_with_header("Konten-Verteilung", "Interaktiver Donut")
        self.account_split_chart = DonutChart("0%")
        account_chart_card.content.append(self.account_split_chart)

        open_card = self._card_with_header("Noch offen diesen Monat", "Nicht erledigte Daueraufträge")
        self.analysis_open_filter_flow = Gtk.FlowBox()
        self.analysis_open_filter_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.analysis_open_filter_flow.set_row_spacing(6)
        self.analysis_open_filter_flow.set_column_spacing(6)
        self.analysis_open_filter_flow.set_min_children_per_line(1)
        self.analysis_open_filter_flow.set_max_children_per_line(6)
        open_card.content.append(self.analysis_open_filter_flow)
        self.analysis_open_value = Gtk.Label(label="-")
        self.analysis_open_value.add_css_class("kpi-value")
        self.analysis_open_value.set_xalign(0)
        open_card.content.append(self.analysis_open_value)

        category_summary_card = self._card_with_header("Top-Kategorien", "Sortierbar nach Konto oder Alle")
        self.analysis_category_filter_flow = Gtk.FlowBox()
        self.analysis_category_filter_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.analysis_category_filter_flow.set_row_spacing(6)
        self.analysis_category_filter_flow.set_column_spacing(6)
        self.analysis_category_filter_flow.set_min_children_per_line(1)
        self.analysis_category_filter_flow.set_max_children_per_line(6)
        category_summary_card.content.append(self.analysis_category_filter_flow)
        self.analysis_categories_flow = self._flow_container(min_per_line=1, max_per_line=3)
        category_summary_card.content.append(self._scroller_for(self.analysis_categories_flow, min_h=180))

        grid.attach(expense_form_card.root, 0, 0, 2, 1)
        grid.attach(headline_card.root, 0, 1, 1, 2)
        grid.attach(budget_chart_card.root, 1, 1, 1, 1)
        grid.attach(account_chart_card.root, 1, 2, 1, 1)
        grid.attach(open_card.root, 0, 3, 2, 1)
        grid.attach(category_summary_card.root, 0, 4, 2, 1)

        self.analysis_animated_widgets = [
            expense_form_card.root,
            budget_chart_card.root,
            account_chart_card.root,
            open_card.root,
            self.budget_chart,
            self.account_split_chart,
        ]
        return grid

    def _build_settings_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=16, row_spacing=16)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        grid.set_column_homogeneous(True)

        settings_card = self._card_with_header("Grundeinstellungen", "Basis für deine Finanzplanung")
        settings_card.root.set_hexpand(True)
        settings_card.root.set_vexpand(True)
        self.currency_entry = Gtk.Entry()
        self.budget_entry = Gtk.Entry()
        settings_card.content.append(self._labeled("Währung", self.currency_entry))
        settings_card.content.append(self._labeled("Monatsbudget", self.budget_entry))

        self.autostart_enabled_check = Gtk.CheckButton.new_with_label("Autostart aktivieren")
        self.autostart_open_window_check = Gtk.CheckButton.new_with_label("Beim Systemstart App-Fenster öffnen")
        settings_card.content.append(self.autostart_enabled_check)
        settings_card.content.append(self.autostart_open_window_check)

        reminder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reminder_label = Gtk.Label(label="Erinnerung alle (Minuten)")
        reminder_label.set_xalign(0)
        reminder_label.set_hexpand(True)
        reminder_label.add_css_class("muted")
        adjustment = Gtk.Adjustment.new(15, 1, 240, 1, 5, 0)
        self.reminder_interval_spin = Gtk.SpinButton.new(adjustment, 1, 0)
        reminder_box.append(reminder_label)
        reminder_box.append(self.reminder_interval_spin)
        settings_card.content.append(reminder_box)

        self.auto_update_check_check = Gtk.CheckButton.new_with_label("Periodisch auf Updates prüfen")
        settings_card.content.append(self.auto_update_check_check)

        update_interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        update_interval_label = Gtk.Label(label="Update-Prüfung alle (Stunden)")
        update_interval_label.set_xalign(0)
        update_interval_label.set_hexpand(True)
        update_interval_label.add_css_class("muted")
        update_adjustment = Gtk.Adjustment.new(6, 1, 168, 1, 4, 0)
        self.update_check_interval_spin = Gtk.SpinButton.new(update_adjustment, 1, 0)
        update_interval_box.append(update_interval_label)
        update_interval_box.append(self.update_check_interval_spin)
        settings_card.content.append(update_interval_box)

        self.manual_update_check_btn = Gtk.Button(label="Jetzt auf Updates prüfen")
        self.manual_update_check_btn.add_css_class("solid")
        self.manual_update_check_btn.connect("clicked", self.on_manual_update_check)
        settings_card.content.append(self.manual_update_check_btn)

        self.current_version_label = Gtk.Label(label=f"Aktuelle Version: {APP_VERSION}")
        self.current_version_label.set_xalign(0)
        self.current_version_label.add_css_class("subtitle")
        settings_card.content.append(self.current_version_label)

        settings_card.content.append(Gtk.Box(vexpand=True))

        save_settings = Gtk.Button(label="Einstellungen speichern")
        save_settings.add_css_class("solid")
        save_settings.connect("clicked", self.on_save_settings)
        settings_card.content.append(save_settings)

        month_card = self._card_with_header("Monat steuern", "Anzeigen, schließen und wieder öffnen")
        self.visible_month_entry = Gtk.Entry(placeholder_text="MM-JJJJ")
        month_card.content.append(self._labeled("Anzeigemonat", self.visible_month_entry))
        month_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        month_set_btn = Gtk.Button(label="Monat übernehmen")
        month_set_btn.add_css_class("solid")
        month_set_btn.connect("clicked", self.on_set_visible_month)
        close_btn = Gtk.Button(label="Monat schließen")
        close_btn.connect("clicked", self.on_close_visible_month)
        month_actions.append(month_set_btn)
        month_actions.append(close_btn)
        month_card.content.append(month_actions)
        self.month_state_label = Gtk.Label(label="")
        self.month_state_label.set_xalign(0)
        self.month_state_label.add_css_class("subtitle")
        month_card.content.append(self.month_state_label)

        closed_months_head = Gtk.Label(label="Geschlossene Monate")
        closed_months_head.set_xalign(0)
        closed_months_head.add_css_class("subtitle")
        month_card.content.append(closed_months_head)
        self.closed_months_listbox = Gtk.ListBox()
        self.closed_months_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.closed_months_listbox.add_css_class("account-list")
        closed_months_scroller = self._scroller_for(self.closed_months_listbox, min_h=160)
        closed_months_scroller.add_css_class("accounts-scroll")
        month_card.content.append(closed_months_scroller)

        accounts_card = self._card_with_header("Konten verwalten", "Mehrere Konten, klare Übersicht")
        accounts_card.root.set_hexpand(True)
        accounts_card.root.set_vexpand(True)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.new_account_entry = Gtk.Entry(placeholder_text="Neues Konto")
        row.append(self.new_account_entry)
        add_btn = Gtk.Button(label="Anlegen")
        add_btn.add_css_class("solid")
        add_btn.connect("clicked", self.on_add_account)
        row.append(add_btn)
        accounts_card.content.append(row)

        self.accounts_listbox = Gtk.ListBox()
        self.accounts_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.accounts_listbox.add_css_class("account-list")
        accounts_scroller = self._scroller_for(self.accounts_listbox, min_h=220)
        accounts_scroller.set_hexpand(True)
        accounts_scroller.set_vexpand(True)
        accounts_scroller.add_css_class("accounts-scroll")
        accounts_card.content.append(accounts_scroller)

        income_sources_card = self._card_with_header("Einnahmequellen", "Für Startseite und Erfassung")
        income_sources_card.root.set_hexpand(True)
        income_sources_card.root.set_vexpand(True)
        add_source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.new_income_source_entry = Gtk.Entry(placeholder_text="Neue Einnahmequelle")
        add_source_row.append(self.new_income_source_entry)
        add_source_btn = Gtk.Button(label="Hinzufügen")
        add_source_btn.add_css_class("solid")
        add_source_btn.connect("clicked", self.on_add_income_source)
        add_source_row.append(add_source_btn)
        income_sources_card.content.append(add_source_row)

        self.income_sources_listbox = Gtk.ListBox()
        self.income_sources_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.income_sources_listbox.add_css_class("account-list")
        income_sources_scroller = self._scroller_for(self.income_sources_listbox, min_h=220)
        income_sources_scroller.set_hexpand(True)
        income_sources_scroller.set_vexpand(True)
        income_sources_scroller.add_css_class("accounts-scroll")
        income_sources_card.content.append(income_sources_scroller)

        grid.attach(settings_card.root, 0, 0, 1, 1)
        grid.attach(accounts_card.root, 1, 0, 2, 1)
        grid.attach(month_card.root, 0, 1, 1, 1)
        grid.attach(income_sources_card.root, 1, 1, 2, 1)
        return grid

    # -----------------------------
    # UI helpers
    # -----------------------------
    class CardBundle:
        def __init__(self, root: Gtk.Box, content: Gtk.Box) -> None:
            self.root = root
            self.content = content

    def _card_with_header(self, title: str, subtitle: str) -> "FinanceAppWindow.CardBundle":
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("bento-card")

        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        h1 = Gtk.Label(label=title)
        h1.set_xalign(0)
        h1.add_css_class("title-3")
        h2 = Gtk.Label(label=subtitle)
        h2.set_xalign(0)
        h2.add_css_class("subtitle")
        head.append(h1)
        head.append(h2)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.append(head)
        card.append(content)
        return FinanceAppWindow.CardBundle(card, content)

    def _labeled(self, label: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0)
        lbl.add_css_class("muted")
        box.append(lbl)
        box.append(widget)
        return box

    def _flow_container(self, min_per_line: int = 1, max_per_line: int = 3) -> Gtk.FlowBox:
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_min_children_per_line(min_per_line)
        flow.set_max_children_per_line(max_per_line)
        flow.set_column_spacing(10)
        flow.set_row_spacing(10)
        return flow

    def _scroller_for(self, child: Gtk.Widget, min_h: int = 160) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow()
        sw.add_css_class("flow-scroll")
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(min_h)
        sw.set_child(child)
        return sw

    def _kpi_row(self, title: str) -> tuple[Gtk.Widget, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        name = Gtk.Label(label=title)
        name.set_xalign(0)
        name.set_hexpand(True)
        name.add_css_class("muted")
        value = Gtk.Label(label="-")
        value.add_css_class("kpi-value")
        row.append(name)
        row.append(value)
        return row, value

    def _clear_container(self, widget: Gtk.Widget) -> None:
        child = widget.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            widget.remove(child)
            child = nxt

    # -----------------------------
    # Events
    # -----------------------------
    def on_add_income(self, _button: Gtk.Button) -> None:
        account_idx = int(self.income_account.get_selected())
        if account_idx < 0 or account_idx >= len(self.account_ids):
            self.toast("Bitte zuerst ein Konto anlegen.")
            return

        description = self.income_desc.get_text().strip()
        amount_raw = self.income_amount.get_text().strip()
        date_raw = self.income_date.get_text().strip()
        income_type_idx = int(self.income_type.get_selected())
        income_type = self.income_type_items[income_type_idx] if 0 <= income_type_idx < len(self.income_type_items) else "Lohn"

        if not description:
            self.toast("Beschreibung fehlt.")
            return

        try:
            amount = parse_float(amount_raw)
            if amount <= 0:
                raise ValueError
            parsed_date = parse_input_date(date_raw)
        except ValueError:
            self.toast("Bitte gültige Werte für Betrag und Datum eingeben.")
            return
        target_month = month_key(parsed_date)
        if self.month_is_closed(target_month):
            self.toast(f"Monat {format_month_label(target_month)} ist geschlossen.")
            return

        self.data["incomes"].append(
            {
                "id": str(uuid.uuid4()),
                "type": income_type,
                "account_id": self.account_ids[account_idx],
                "description": description,
                "amount": amount,
                "date": f"{parsed_date.day:02d}-{parsed_date.month:02d}-{parsed_date.year}",
            }
        )

        self.income_desc.set_text("")
        self.income_amount.set_text("")
        display_month = self.current_display_month()
        year_text, month_text = display_month.split("-")
        self.income_date.set_text(f"01-{month_text}-{year_text}")
        self.save_data()
        self.refresh_all()
        self.toast("Einnahme gespeichert.")

    def on_add_expense(self, _button: Gtk.Button) -> None:
        account_idx = int(self.expense_account.get_selected())
        if account_idx < 0 or account_idx >= len(self.account_ids):
            self.toast("Bitte ein Konto auswählen.")
            return
        aid = self.account_ids[account_idx]

        description = self.expense_desc.get_text().strip()
        amount_raw = self.expense_amount.get_text().strip()
        date_raw = self.expense_date.get_text().strip()

        if not description:
            self.toast("Kategorie fehlt.")
            return

        try:
            amount = parse_float(amount_raw)
            if amount <= 0:
                raise ValueError
            parsed_date = parse_input_date(date_raw)
        except ValueError:
            self.toast("Bitte gültige Werte eingeben.")
            return
        target_month = month_key(parsed_date)
        if self.month_is_closed(target_month):
            self.toast(f"Monat {format_month_label(target_month)} ist geschlossen.")
            return

        self.data["expenses"].append(
            {
                "id": str(uuid.uuid4()),
                "account_id": aid,
                "description": description,
                "amount": amount,
                "date": f"{parsed_date.day:02d}-{parsed_date.month:02d}-{parsed_date.year}",
                "source": "manual",
            }
        )
        self.expense_desc.set_text("")
        self.expense_amount.set_text("")
        display_month = self.current_display_month()
        year_text, month_text = display_month.split("-")
        self.expense_date.set_text(f"01-{month_text}-{year_text}")
        self.save_data()
        self.refresh_all()
        self.toast("Ausgabe gespeichert.")

    def add_recurring_payment_record(self, account_id: str, desc: str, amount: float, day: int, frequency: str) -> None:
        display_month = self.current_display_month()
        year_text, month_text = display_month.split("-")
        self.data["recurring_payments"].append(
            {
                "id": str(uuid.uuid4()),
                "kind": "standard",
                "account_id": account_id,
                "description": desc,
                "amount": amount,
                "day": day,
                "frequency": frequency,
                "start_date": f"01-{month_text}-{year_text}",
                "checked_months": [],
            }
        )
        self.apply_monthly_recurring_if_needed(force_current_month=True)
        self.save_data()
        self.refresh_all()
        self.toast("Dauerzahlung gespeichert.")

    def add_installment_record(
        self,
        account_id: str,
        desc: str,
        amount: float,
        day: int,
        start_date: date,
        end_date: date,
        final_amount: float | None,
    ) -> None:
        self.data["recurring_payments"].append(
            {
                "id": str(uuid.uuid4()),
                "kind": "installment",
                "account_id": account_id,
                "description": desc,
                "amount": amount,
                "day": day,
                "frequency": "monthly",
                "start_date": f"{start_date.day:02d}-{start_date.month:02d}-{start_date.year}",
                "end_date": f"{end_date.day:02d}-{end_date.month:02d}-{end_date.year}",
                "final_amount": final_amount,
                "checked_months": [],
            }
        )
        self.apply_monthly_recurring_if_needed(force_current_month=True)
        self.save_data()
        self.refresh_all()
        self.toast("Abzahlung gespeichert.")

    def open_recurring_popup(self, _button: Gtk.Button) -> None:
        aid = self.current_account_id()
        if not aid:
            self.toast("Bitte ein Konto auswählen.")
            return

        if self.recurring_popup is not None:
            self.recurring_popup.present()
            return

        popup = Gtk.Window()
        popup.set_title("Dauerzahlung hinzufügen")
        popup.set_transient_for(self)
        popup.set_modal(True)
        popup.set_default_size(500, 330)
        popup.set_resizable(False)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        desc_entry = Gtk.Entry(placeholder_text="Beschreibung")
        amount_entry = Gtk.Entry(placeholder_text="Betrag")
        day_entry = Gtk.Entry(placeholder_text="Tag im Monat (1-28)")
        day_entry.set_text("1")
        freq_labels = [label for label, _key in RECURRING_FREQUENCY_OPTIONS]
        freq_keys = [key for _label, key in RECURRING_FREQUENCY_OPTIONS]
        freq_model = Gtk.StringList.new(freq_labels)
        freq_dd = Gtk.DropDown.new(freq_model, None)
        freq_dd.set_selected(0)

        content.append(self._labeled("Beschreibung", desc_entry))
        content.append(self._labeled("Betrag", amount_entry))
        content.append(self._labeled("Tag", day_entry))
        content.append(self._labeled("Intervall", freq_dd))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Speichern")
        save_btn.add_css_class("solid")
        save_btn.set_hexpand(True)

        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.set_hexpand(True)
        cancel_btn.connect("clicked", lambda *_: popup.close())

        save_btn.connect(
            "clicked",
            self.on_save_recurring_popup,
            popup,
            desc_entry,
            amount_entry,
            day_entry,
            freq_keys,
            freq_dd,
        )

        actions.append(cancel_btn)
        actions.append(save_btn)
        content.append(actions)

        popup.set_child(content)
        popup.connect("close-request", self.on_recurring_popup_close)
        self.recurring_popup = popup
        popup.present()

    def on_recurring_popup_close(self, window: Gtk.Window, *_args) -> bool:
        if self.recurring_popup is window:
            self.recurring_popup = None
        return False

    def on_save_recurring_popup(
        self,
        _button: Gtk.Button,
        popup: Gtk.Window,
        desc_entry: Gtk.Entry,
        amount_entry: Gtk.Entry,
        day_entry: Gtk.Entry,
        freq_keys: list[str],
        freq_dd: Gtk.DropDown,
    ) -> None:
        aid = self.current_account_id()
        if not aid:
            self.toast("Bitte ein Konto auswählen.")
            return

        desc = desc_entry.get_text().strip()
        amount_raw = amount_entry.get_text().strip()
        day_raw = day_entry.get_text().strip()

        if not desc:
            self.toast("Beschreibung fehlt.")
            return

        try:
            amount = parse_float(amount_raw)
            day = int(day_raw)
            if amount <= 0 or not (1 <= day <= 28):
                raise ValueError
        except ValueError:
            self.toast("Betrag oder Tag ungültig.")
            return
        freq_idx = int(freq_dd.get_selected())
        if freq_idx < 0 or freq_idx >= len(freq_keys):
            self.toast("Intervall ungültig.")
            return
        frequency = freq_keys[freq_idx]

        self.add_recurring_payment_record(aid, desc, amount, day, frequency)
        popup.close()

    def open_installment_popup(self, _button: Gtk.Button) -> None:
        aid = self.current_account_id()
        if not aid:
            self.toast("Bitte ein Konto auswählen.")
            return

        if self.installment_popup is not None:
            self.installment_popup.present()
            return

        popup = Gtk.Window()
        popup.set_title("Abzahlung hinzufügen")
        popup.set_transient_for(self)
        popup.set_modal(True)
        popup.set_default_size(540, 420)
        popup.set_resizable(False)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        display_month = self.current_display_month()
        year_text, month_text = display_month.split("-")
        start_default = f"01-{month_text}-{year_text}"

        desc_entry = Gtk.Entry(placeholder_text="Beschreibung")
        amount_entry = Gtk.Entry(placeholder_text="Regelbetrag")
        day_entry = Gtk.Entry(placeholder_text="Abbuchungstag (1-28)")
        day_entry.set_text("1")
        start_entry = Gtk.Entry(placeholder_text="Startdatum DD-MM-JJJJ")
        start_entry.set_text(start_default)
        end_entry = Gtk.Entry(placeholder_text="Enddatum DD-MM-JJJJ")
        end_entry.set_text(start_default)
        final_amount_entry = Gtk.Entry(placeholder_text="Abschlagssumme letzte Zahlung (optional)")

        content.append(self._labeled("Beschreibung", desc_entry))
        content.append(self._labeled("Betrag", amount_entry))
        content.append(self._labeled("Abbuchungstag", day_entry))
        content.append(self._labeled("Startdatum", start_entry))
        content.append(self._labeled("Enddatum", end_entry))
        content.append(self._labeled("Abschlagssumme (optional)", final_amount_entry))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Speichern")
        save_btn.add_css_class("solid")
        save_btn.set_hexpand(True)
        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.set_hexpand(True)
        cancel_btn.connect("clicked", lambda *_: popup.close())

        save_btn.connect(
            "clicked",
            self.on_save_installment_popup,
            popup,
            desc_entry,
            amount_entry,
            day_entry,
            start_entry,
            end_entry,
            final_amount_entry,
        )
        actions.append(cancel_btn)
        actions.append(save_btn)
        content.append(actions)

        popup.set_child(content)
        popup.connect("close-request", self.on_installment_popup_close)
        self.installment_popup = popup
        popup.present()

    def on_installment_popup_close(self, window: Gtk.Window, *_args) -> bool:
        if self.installment_popup is window:
            self.installment_popup = None
        return False

    def on_save_installment_popup(
        self,
        _button: Gtk.Button,
        popup: Gtk.Window,
        desc_entry: Gtk.Entry,
        amount_entry: Gtk.Entry,
        day_entry: Gtk.Entry,
        start_entry: Gtk.Entry,
        end_entry: Gtk.Entry,
        final_amount_entry: Gtk.Entry,
    ) -> None:
        aid = self.current_account_id()
        if not aid:
            self.toast("Bitte ein Konto auswählen.")
            return

        desc = desc_entry.get_text().strip()
        amount_raw = amount_entry.get_text().strip()
        day_raw = day_entry.get_text().strip()
        start_raw = start_entry.get_text().strip()
        end_raw = end_entry.get_text().strip()
        final_raw = final_amount_entry.get_text().strip()

        if not desc:
            self.toast("Beschreibung fehlt.")
            return

        try:
            amount = parse_float(amount_raw)
            day = int(day_raw)
            start_date = parse_input_date(start_raw)
            end_date = parse_input_date(end_raw)
            if amount <= 0 or not (1 <= day <= 28):
                raise ValueError
            if end_date < start_date:
                self.toast("Enddatum muss nach dem Startdatum liegen.")
                return
            final_amount: float | None = None
            if final_raw:
                final_amount = parse_float(final_raw)
                if final_amount <= 0:
                    raise ValueError
        except ValueError:
            self.toast("Bitte gültige Werte für Abzahlung eingeben.")
            return

        self.add_installment_record(aid, desc, amount, day, start_date, end_date, final_amount)
        popup.close()

    def on_save_settings(self, _button: Gtk.Button) -> None:
        currency = self.currency_entry.get_text().strip().upper() or "EUR"
        try:
            budget = parse_float(self.budget_entry.get_text().strip())
            if budget < 0:
                raise ValueError
        except ValueError:
            self.toast("Monatsbudget ist ungültig.")
            return

        self.data["settings"]["currency"] = currency
        self.data["settings"]["monthly_budget"] = budget
        self.data["settings"]["autostart_enabled"] = self.autostart_enabled_check.get_active()
        self.data["settings"]["autostart_open_window"] = self.autostart_open_window_check.get_active()
        self.data["settings"]["reminder_interval_minutes"] = int(self.reminder_interval_spin.get_value_as_int())
        self.data["settings"]["auto_update_check"] = self.auto_update_check_check.get_active()
        self.data["settings"]["update_check_interval_hours"] = int(self.update_check_interval_spin.get_value_as_int())
        self.save_data()
        self.ensure_autostart_configuration()
        self.refresh_all()
        self.toast("Einstellungen gespeichert.")

    def on_manual_update_check(self, _button: Gtk.Button) -> None:
        self.request_update_check(manual=True)

    def on_set_visible_month(self, _button: Gtk.Button) -> None:
        try:
            month = parse_month_text(self.visible_month_entry.get_text())
        except ValueError:
            self.toast("Monat bitte als MM-JJJJ eingeben.")
            return
        self.data["settings"]["visible_month"] = month
        year_text, month_text = month.split("-")
        default_date = f"01-{month_text}-{year_text}"
        self.income_date.set_text(default_date)
        self.expense_date.set_text(default_date)
        self.save_data()
        self.refresh_all()
        self.toast(f"Anzeigemonat gesetzt: {format_month_label(month)}")

    def on_close_visible_month(self, _button: Gtk.Button) -> None:
        month = self.current_display_month()
        closed = self.data["meta"].setdefault("closed_months", [])
        if month in closed:
            self.toast("Monat ist bereits geschlossen.")
            return
        closed.append(month)
        closed.sort()
        self.save_data()
        self.refresh_all()
        self.toast(f"Monat geschlossen: {format_month_label(month)}")

    def on_reopen_month(self, _button: Gtk.Button, month: str) -> None:
        closed = self.data["meta"].setdefault("closed_months", [])
        if month in closed:
            closed.remove(month)
            self.save_data()
            self.refresh_all()
            self.toast(f"Monat geöffnet: {format_month_label(month)}")

    def on_add_account(self, _button: Gtk.Button) -> None:
        name = self.new_account_entry.get_text().strip()
        if not name:
            self.toast("Kontoname fehlt.")
            return
        if any(item["name"].lower() == name.lower() for item in self.data["accounts"]):
            self.toast("Dieses Konto existiert bereits.")
            return

        self.data["accounts"].append({"id": str(uuid.uuid4()), "name": name})
        self.new_account_entry.set_text("")
        self.save_data()
        self.refresh_all()
        self.toast("Konto angelegt.")

    def on_add_income_source(self, _button: Gtk.Button) -> None:
        source_name = self.new_income_source_entry.get_text().strip()
        if not source_name:
            self.toast("Name der Einnahmequelle fehlt.")
            return

        sources = self.get_income_sources()
        if source_name.lower() in [item.lower() for item in sources]:
            self.toast("Einnahmequelle existiert bereits.")
            return

        sources.append(source_name)
        self.data["settings"]["income_sources"] = sources
        self.new_income_source_entry.set_text("")
        self.save_data()
        self.refresh_all()
        self.toast("Einnahmequelle hinzugefügt.")

    def on_rename_income_source(self, _button: Gtk.Button, old_name: str, name_entry: Gtk.Entry) -> None:
        new_name = name_entry.get_text().strip()
        if not new_name:
            self.toast("Neuer Name fehlt.")
            return

        sources = self.get_income_sources()
        if old_name.lower() != new_name.lower() and new_name.lower() in [item.lower() for item in sources]:
            self.toast("Einnahmequelle existiert bereits.")
            return

        changed = False
        for idx, source in enumerate(sources):
            if source.lower() == old_name.lower():
                sources[idx] = new_name
                changed = True
                break

        if not changed:
            self.toast("Einnahmequelle nicht gefunden.")
            return

        for income in self.data["incomes"]:
            income_type = str(income.get("type", "")).strip()
            if income_type.lower() == old_name.lower():
                income["type"] = new_name

        self.data["settings"]["income_sources"] = sources
        self.save_data()
        self.refresh_all()
        self.toast("Einnahmequelle aktualisiert.")

    def on_delete_income_source(self, _button: Gtk.Button, source_name: str) -> None:
        sources = self.get_income_sources()
        remaining = [source for source in sources if source.lower() != source_name.lower()]

        if len(remaining) == len(sources):
            self.toast("Einnahmequelle nicht gefunden.")
            return
        if not remaining:
            self.toast("Mindestens eine Einnahmequelle muss bleiben.")
            return

        self.data["settings"]["income_sources"] = remaining
        self.save_data()
        self.refresh_all()
        self.toast("Einnahmequelle gelöscht.")

    def on_delete_income(self, _button: Gtk.Button, income_id: str) -> None:
        income = next((item for item in self.data["incomes"] if item.get("id") == income_id), None)
        if income is None:
            self.toast("Einnahme nicht gefunden.")
            return
        income_month = month_key_from_date_text(str(income.get("date", "")))
        if income_month and self.month_is_closed(income_month):
            self.toast(f"Monat {format_month_label(income_month)} ist geschlossen.")
            return
        self.data["incomes"] = [item for item in self.data["incomes"] if item.get("id") != income_id]
        self.save_data()
        self.refresh_all()
        self.toast("Einnahme gelöscht.")

    def open_income_edit_popup(self, _button: Gtk.Button, income_id: str) -> None:
        income = next((item for item in self.data["incomes"] if item.get("id") == income_id), None)
        if income is None:
            self.toast("Einnahme nicht gefunden.")
            return
        if self.income_edit_popup is not None:
            self.income_edit_popup.close()

        popup = Gtk.Window()
        popup.set_title("Einnahme bearbeiten")
        popup.set_transient_for(self)
        popup.set_modal(True)
        popup.set_default_size(520, 320)
        popup.set_resizable(False)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        source_items = self.get_income_sources()
        source_model = Gtk.StringList.new(source_items)
        source_dd = Gtk.DropDown.new(source_model, None)
        source_value = str(income.get("type", "")).strip()
        if source_value and source_value not in source_items:
            source_items.append(source_value)
            source_model = Gtk.StringList.new(source_items)
            source_dd.set_model(source_model)
        if source_items:
            selected = 0
            for idx, source in enumerate(source_items):
                if source.lower() == source_value.lower():
                    selected = idx
                    break
            source_dd.set_selected(selected)

        account_model = Gtk.StringList.new(self.account_names)
        account_dd = Gtk.DropDown.new(account_model, None)
        selected_account = str(income.get("account_id", ""))
        if self.account_ids:
            selected_idx = 0
            for idx, aid in enumerate(self.account_ids):
                if aid == selected_account:
                    selected_idx = idx
                    break
            account_dd.set_selected(selected_idx)

        desc_entry = Gtk.Entry()
        desc_entry.set_text(str(income.get("description", "")))
        amount_entry = Gtk.Entry()
        amount_entry.set_text(str(income.get("amount", 0.0)))
        date_entry = Gtk.Entry()
        date_entry.set_text(str(income.get("date", "")))

        content.append(self._labeled("Quelle", source_dd))
        content.append(self._labeled("Konto", account_dd))
        content.append(self._labeled("Beschreibung", desc_entry))
        content.append(self._labeled("Betrag", amount_entry))
        content.append(self._labeled("Datum", date_entry))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Speichern")
        save_btn.add_css_class("solid")
        save_btn.set_hexpand(True)
        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.set_hexpand(True)
        cancel_btn.connect("clicked", lambda *_: popup.close())
        save_btn.connect(
            "clicked",
            self.on_save_income_edit_popup,
            popup,
            income_id,
            source_items,
            source_dd,
            account_dd,
            desc_entry,
            amount_entry,
            date_entry,
        )
        actions.append(cancel_btn)
        actions.append(save_btn)
        content.append(actions)

        popup.set_child(content)
        popup.connect("close-request", self.on_income_edit_popup_close)
        self.income_edit_popup = popup
        popup.present()

    def on_income_edit_popup_close(self, window: Gtk.Window, *_args) -> bool:
        if self.income_edit_popup is window:
            self.income_edit_popup = None
        return False

    def on_save_income_edit_popup(
        self,
        _button: Gtk.Button,
        popup: Gtk.Window,
        income_id: str,
        source_items: list[str],
        source_dd: Gtk.DropDown,
        account_dd: Gtk.DropDown,
        desc_entry: Gtk.Entry,
        amount_entry: Gtk.Entry,
        date_entry: Gtk.Entry,
    ) -> None:
        income = next((item for item in self.data["incomes"] if item.get("id") == income_id), None)
        if income is None:
            self.toast("Einnahme nicht gefunden.")
            return

        source_idx = int(source_dd.get_selected())
        if source_idx < 0 or source_idx >= len(source_items):
            self.toast("Bitte eine Quelle auswählen.")
            return
        account_idx = int(account_dd.get_selected())
        if account_idx < 0 or account_idx >= len(self.account_ids):
            self.toast("Bitte ein Konto auswählen.")
            return

        description = desc_entry.get_text().strip()
        if not description:
            self.toast("Beschreibung fehlt.")
            return

        try:
            amount = parse_float(amount_entry.get_text().strip())
            if amount <= 0:
                raise ValueError
            parsed_date = parse_input_date(date_entry.get_text().strip())
        except ValueError:
            self.toast("Bitte gültige Werte eingeben.")
            return
        target_month = month_key(parsed_date)
        if self.month_is_closed(target_month):
            self.toast(f"Monat {format_month_label(target_month)} ist geschlossen.")
            return

        income["type"] = source_items[source_idx]
        income["account_id"] = self.account_ids[account_idx]
        income["description"] = description
        income["amount"] = amount
        income["date"] = f"{parsed_date.day:02d}-{parsed_date.month:02d}-{parsed_date.year}"
        self.save_data()
        self.refresh_all()
        popup.close()
        self.toast("Einnahme aktualisiert.")

    def open_recurring_edit_popup(self, _button: Gtk.Button, recurring_id: str) -> None:
        recurring = next((item for item in self.data["recurring_payments"] if item.get("id") == recurring_id), None)
        if recurring is None:
            self.toast("Dauerzahlung nicht gefunden.")
            return
        if self.recurring_edit_popup is not None:
            self.recurring_edit_popup.close()

        popup = Gtk.Window()
        popup.set_title("Dauerzahlung bearbeiten")
        popup.set_transient_for(self)
        popup.set_modal(True)
        popup.set_default_size(460, 280)
        popup.set_resizable(False)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(14)
        content.set_margin_end(14)

        desc_entry = Gtk.Entry()
        desc_entry.set_text(str(recurring.get("description", "")))
        amount_entry = Gtk.Entry()
        amount_entry.set_text(str(recurring.get("amount", 0.0)))
        day_entry = Gtk.Entry()
        day_entry.set_text(str(recurring.get("day", 1)))

        content.append(self._labeled("Beschreibung", desc_entry))
        content.append(self._labeled("Betrag", amount_entry))
        content.append(self._labeled("Tag", day_entry))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="Speichern")
        save_btn.add_css_class("solid")
        save_btn.set_hexpand(True)
        cancel_btn = Gtk.Button(label="Abbrechen")
        cancel_btn.set_hexpand(True)
        cancel_btn.connect("clicked", lambda *_: popup.close())
        save_btn.connect("clicked", self.on_save_recurring_edit_popup, popup, recurring_id, desc_entry, amount_entry, day_entry)
        actions.append(cancel_btn)
        actions.append(save_btn)
        content.append(actions)

        popup.set_child(content)
        popup.connect("close-request", self.on_recurring_edit_popup_close)
        self.recurring_edit_popup = popup
        popup.present()

    def on_recurring_edit_popup_close(self, window: Gtk.Window, *_args) -> bool:
        if self.recurring_edit_popup is window:
            self.recurring_edit_popup = None
        return False

    def on_save_recurring_edit_popup(
        self,
        _button: Gtk.Button,
        popup: Gtk.Window,
        recurring_id: str,
        desc_entry: Gtk.Entry,
        amount_entry: Gtk.Entry,
        day_entry: Gtk.Entry,
    ) -> None:
        recurring = next((item for item in self.data["recurring_payments"] if item.get("id") == recurring_id), None)
        if recurring is None:
            self.toast("Dauerzahlung nicht gefunden.")
            return
        desc = desc_entry.get_text().strip()
        if not desc:
            self.toast("Beschreibung fehlt.")
            return
        try:
            amount = parse_float(amount_entry.get_text().strip())
            day = int(day_entry.get_text().strip())
            if amount <= 0 or not (1 <= day <= 28):
                raise ValueError
        except ValueError:
            self.toast("Betrag oder Tag ungültig.")
            return

        recurring["description"] = desc
        recurring["amount"] = amount
        recurring["day"] = day
        self.save_data()
        self.refresh_all()
        popup.close()
        self.toast("Dauerzahlung aktualisiert.")

    def on_delete_account(self, account_id: str) -> None:
        self.data["accounts"] = [a for a in self.data["accounts"] if a["id"] != account_id]
        self.data["expenses"] = [e for e in self.data["expenses"] if e["account_id"] != account_id]
        self.data["recurring_payments"] = [r for r in self.data["recurring_payments"] if r["account_id"] != account_id]
        self.data["incomes"] = [i for i in self.data["incomes"] if i.get("account_id") != account_id]
        self.save_data()
        self.refresh_all()
        self.toast("Konto gelöscht.")

    def on_delete_recurring(self, recurring_id: str) -> None:
        self.data["recurring_payments"] = [r for r in self.data["recurring_payments"] if r["id"] != recurring_id]
        self.save_data()
        self.refresh_all()
        self.toast("Dauerzahlung gelöscht.")

    # -----------------------------
    # Refresh / rendering
    # -----------------------------
    def refresh_all(self) -> None:
        self.apply_monthly_recurring_if_needed()
        self.refresh_accounts_index()
        self.refresh_settings_page()
        self.refresh_start_page()
        self.refresh_accounts_page()
        self.refresh_analysis_page()
        GLib.idle_add(self._run_scroll_policy_once)

    def _run_scroll_policy_once(self) -> bool:
        self.update_page_scroll_policy()
        return False

    def refresh_accounts_index(self) -> None:
        self.account_ids = [a["id"] for a in self.data["accounts"]]
        self.account_names = [a["name"] for a in self.data["accounts"]]
        self.income_type_items = self.get_income_sources()

        income_active = int(self.income_account.get_selected())
        income_type_active = int(self.income_type.get_selected())
        expense_account_active = int(self.expense_account.get_selected())

        self.income_account_model = Gtk.StringList.new(self.account_names)
        self.income_account.set_model(self.income_account_model)
        self.expense_account_model = Gtk.StringList.new(self.account_names)
        self.expense_account.set_model(self.expense_account_model)
        self.income_type_model = Gtk.StringList.new(self.income_type_items)
        self.income_type.set_model(self.income_type_model)

        if self.account_names:
            income_idx = max(0, min(income_active, len(self.account_names) - 1))
            self.income_account.set_selected(income_idx)
            expense_idx = max(0, min(expense_account_active, len(self.account_names) - 1))
            self.expense_account.set_selected(expense_idx)
        if self.income_type_items:
            type_idx = max(0, min(income_type_active, len(self.income_type_items) - 1))
            self.income_type.set_selected(type_idx)

        if self.selected_account_focus_id not in self.account_ids:
            self.selected_account_focus_id = self.account_ids[0] if self.account_ids else None

        if self.analysis_open_filter_id != "ALL" and self.analysis_open_filter_id not in self.account_ids:
            self.analysis_open_filter_id = "ALL"
        if self.analysis_category_filter_id != "ALL" and self.analysis_category_filter_id not in self.account_ids:
            self.analysis_category_filter_id = "ALL"

        self.refresh_account_focus_buttons()
        self.refresh_analysis_open_filter_buttons()
        self.refresh_analysis_category_filter_buttons()

    def refresh_account_focus_buttons(self) -> None:
        self._clear_container(self.account_focus_flow)

        if not self.account_ids:
            return

        for account in self.data["accounts"]:
            account_id = account["id"]
            btn = Gtk.Button(label=account["name"])
            btn.add_css_class("account-focus-button")
            if account_id == self.selected_account_focus_id:
                btn.add_css_class("active")
            btn.connect("clicked", self.on_select_account_focus, account_id)
            self.account_focus_flow.insert(btn, -1)

    def on_select_account_focus(self, _button: Gtk.Button, account_id: str) -> None:
        self.selected_account_focus_id = account_id
        self.refresh_account_focus_buttons()
        self.refresh_accounts_page()

    def refresh_analysis_open_filter_buttons(self) -> None:
        self._clear_container(self.analysis_open_filter_flow)

        def make_button(label: str, key: str) -> Gtk.Button:
            btn = Gtk.Button(label=label)
            btn.add_css_class("account-focus-button")
            if self.analysis_open_filter_id == key:
                btn.add_css_class("active")
            btn.connect("clicked", self.on_select_analysis_open_filter, key)
            return btn

        self.analysis_open_filter_flow.insert(make_button("Alle", "ALL"), -1)
        for account in self.data["accounts"]:
            self.analysis_open_filter_flow.insert(make_button(account["name"], account["id"]), -1)

    def on_select_analysis_open_filter(self, _button: Gtk.Button, filter_id: str) -> None:
        self.analysis_open_filter_id = filter_id
        self.refresh_analysis_open_filter_buttons()
        self.refresh_analysis_page()

    def refresh_analysis_category_filter_buttons(self) -> None:
        self._clear_container(self.analysis_category_filter_flow)

        def make_button(label: str, key: str) -> Gtk.Button:
            btn = Gtk.Button(label=label)
            btn.add_css_class("account-focus-button")
            if self.analysis_category_filter_id == key:
                btn.add_css_class("active")
            btn.connect("clicked", self.on_select_analysis_category_filter, key)
            return btn

        self.analysis_category_filter_flow.insert(make_button("Alle Konten", "ALL"), -1)
        for account in self.data["accounts"]:
            self.analysis_category_filter_flow.insert(make_button(account["name"], account["id"]), -1)

    def on_select_analysis_category_filter(self, _button: Gtk.Button, filter_id: str) -> None:
        self.analysis_category_filter_id = filter_id
        self.refresh_analysis_category_filter_buttons()
        self.refresh_analysis_page()

    def refresh_settings_page(self) -> None:
        self.currency_entry.set_text(self.data["settings"].get("currency", "EUR"))
        self.budget_entry.set_text(str(self.data["settings"].get("monthly_budget", 0.0)))
        self.autostart_enabled_check.set_active(self.autostart_enabled())
        self.autostart_open_window_check.set_active(self.should_open_window_on_autostart())
        self.reminder_interval_spin.set_value(float(self.reminder_interval_minutes()))
        self.auto_update_check_check.set_active(self.auto_update_check_enabled())
        self.update_check_interval_spin.set_value(float(self.update_check_interval_hours()))
        visible_month = self.current_display_month()
        self.visible_month_entry.set_text(format_month_label(visible_month))
        self.month_state_label.remove_css_class("kpi-positive")
        self.month_state_label.remove_css_class("kpi-negative")
        if self.month_is_closed(visible_month):
            self.month_state_label.set_text("Status: geschlossen (keine Bearbeitung möglich)")
            self.month_state_label.add_css_class("kpi-negative")
        else:
            self.month_state_label.set_text("Status: offen")
            self.month_state_label.add_css_class("kpi-positive")

        self._clear_container(self.closed_months_listbox)
        closed_months = self.data.get("meta", {}).get("closed_months", [])
        if isinstance(closed_months, list):
            for month in sorted(closed_months, reverse=True):
                month_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                month_row.add_css_class("account-row")
                name = Gtk.Label(label=format_month_label(month))
                name.set_xalign(0)
                name.set_hexpand(True)
                month_row.append(name)
                reopen_btn = Gtk.Button(label="Öffnen")
                reopen_btn.add_css_class("solid")
                reopen_btn.connect("clicked", self.on_reopen_month, month)
                month_row.append(reopen_btn)
                row = Gtk.ListBoxRow()
                row.set_child(month_row)
                self.closed_months_listbox.append(row)

        self._clear_container(self.accounts_listbox)
        account_icon_name = self._resolve_icon_name(
            ["wallet-symbolic", "folder-symbolic", "applications-office-symbolic", "user-home-symbolic"]
        )
        for account in self.data["accounts"]:
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row_box.add_css_class("account-row")

            icon = Gtk.Image.new_from_icon_name(account_icon_name)
            icon.set_pixel_size(18)
            icon.add_css_class("settings-account-icon")
            row_box.append(icon)

            name = Gtk.Label(label=account["name"])
            name.set_xalign(0)
            name.set_hexpand(True)
            name.add_css_class("settings-account-name")
            row_box.append(name)

            delete_btn = Gtk.Button(label="Löschen")
            delete_btn.add_css_class("danger")
            delete_btn.connect("clicked", lambda _b, aid=account["id"]: self.on_delete_account(aid))
            row_box.append(delete_btn)

            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            self.accounts_listbox.append(row)

        self._clear_container(self.income_sources_listbox)
        for source in self.get_income_sources():
            source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            source_row.add_css_class("account-row")

            icon = Gtk.Image.new_from_icon_name("money-symbolic")
            icon.set_pixel_size(18)
            source_row.append(icon)

            source_entry = Gtk.Entry()
            source_entry.set_text(source)
            source_entry.set_hexpand(True)
            source_row.append(source_entry)

            save_btn = Gtk.Button(label="Speichern")
            save_btn.add_css_class("solid")
            save_btn.connect("clicked", self.on_rename_income_source, source, source_entry)
            source_row.append(save_btn)

            delete_btn = Gtk.Button(label="Löschen")
            delete_btn.add_css_class("danger")
            delete_btn.connect("clicked", self.on_delete_income_source, source)
            source_row.append(delete_btn)

            row = Gtk.ListBoxRow()
            row.set_child(source_row)
            self.income_sources_listbox.append(row)

    def refresh_start_page(self) -> None:
        currency = self.data["settings"].get("currency", "EUR")
        this_month = self.current_display_month()
        year_text, month_text = this_month.split("-")
        reference_date = date(int(year_text), int(month_text), 1)

        month_incomes = [
            item
            for item in self.data["incomes"]
            if month_key_from_date_text(item.get("date", "")) == this_month
        ]
        month_expenses = [
            item
            for item in self.data["expenses"]
            if month_key_from_date_text(item.get("date", "")) == this_month
        ]

        total_income = sum(float(item.get("amount", 0.0)) for item in month_incomes)
        total_expense = sum(float(item.get("amount", 0.0)) for item in month_expenses)
        balance = total_income - total_expense

        self.start_cashflow_value.set_text(format_money(balance, currency))
        self.start_cashflow_value.remove_css_class("kpi-positive")
        self.start_cashflow_value.remove_css_class("kpi-negative")
        self.start_cashflow_value.add_css_class("kpi-positive" if balance >= 0 else "kpi-negative")

        self._clear_container(self.start_open_accounts_box)
        open_by_account: dict[str, float] = {account["id"]: 0.0 for account in self.data["accounts"]}
        for recurring in self.data["recurring_payments"]:
            if not self.is_recurring_due_in_month(recurring, this_month):
                continue
            months = recurring.get("checked_months", [])
            if isinstance(months, list) and this_month in months:
                continue
            aid = recurring.get("account_id")
            if aid in open_by_account:
                open_by_account[aid] += self.recurring_amount_for_month(recurring, this_month)

        for account in self.data["accounts"]:
            amount = open_by_account.get(account["id"], 0.0)
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            name = Gtk.Label(label=account["name"])
            name.set_xalign(0)
            name.set_hexpand(True)
            value = Gtk.Label(label=format_money(amount, currency))
            value.set_xalign(1)
            value.add_css_class("kpi-negative" if amount > 0 else "kpi-positive")
            row.append(name)
            row.append(value)
            self.start_open_accounts_box.append(row)

        self._clear_container(self.income_recent_flow)
        recent = sorted(
            month_incomes,
            key=lambda x: parse_date_safe(x.get("date", "")),
            reverse=True,
        )[:8]
        for item in recent:
            card = self._mini_info_card(
                title=item.get("description", "-"),
                subtitle=f"{item.get('date', '')} - {item.get('type', '')}",
                amount=format_money(float(item.get("amount", 0.0)), currency),
                icon_name="money-symbolic",
            )
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            edit_btn = Gtk.Button(label="Bearbeiten")
            edit_btn.connect("clicked", self.open_income_edit_popup, item.get("id", ""))
            delete_btn = Gtk.Button(label="Löschen")
            delete_btn.add_css_class("danger")
            delete_btn.connect("clicked", self.on_delete_income, item.get("id", ""))
            actions.append(edit_btn)
            actions.append(delete_btn)
            card.append(actions)
            self.income_recent_flow.insert(card, -1)

        self._clear_container(self.start_next_payments_grid)
        if not self.data["accounts"]:
            empty = Gtk.Label(label="Lege ein Konto an, um nächste Zahlungen zu sehen.")
            empty.set_xalign(0)
            empty.add_css_class("subtitle")
            self.start_next_payments_grid.attach(empty, 0, 0, 1, 1)
            return

        recurring_all = self.data["recurring_payments"]
        for col, account in enumerate(self.data["accounts"]):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            column.add_css_class("expense-card")
            column.set_hexpand(True)

            title = Gtk.Label(label=account["name"])
            title.set_xalign(0)
            title.set_hexpand(True)
            column.append(title)

            recurring_for_account = [r for r in recurring_all if r.get("account_id") == account["id"]]
            if not recurring_for_account:
                hint = Gtk.Label(label="Keine Dauerzahlungen")
                hint.set_xalign(0)
                hint.add_css_class("subtitle")
                column.append(hint)
                self.start_next_payments_grid.attach(column, col, 0, 1, 1)
                continue

            next_items: list[tuple[date, bool, dict]] = []
            for recurring in recurring_for_account:
                if not self.has_future_due_from_month(recurring, this_month):
                    continue
                due_date, checked_current = self.next_due_info_for_recurring(recurring, reference_date)
                next_items.append((due_date, checked_current, recurring))

            next_items.sort(key=lambda item: item[0])
            for due_date, checked_current, recurring in next_items:
                due_text = f"{due_date.day:02d}-{due_date.month:02d}-{due_date.year}"
                if (not checked_current) and due_date < reference_date:
                    subtitle = f"Überfällig seit {due_text}"
                elif checked_current:
                    subtitle = f"Nächste Rate am {due_text}"
                else:
                    subtitle = f"Fällig am {due_text}"

                card = self._mini_info_card(
                    title=recurring.get("description", "-"),
                    subtitle=subtitle,
                    amount=format_money(float(recurring.get("amount", 0.0)), currency),
                    icon_name="view-refresh-symbolic",
                )
                column.append(card)

            self.start_next_payments_grid.attach(column, col, 0, 1, 1)

    def refresh_accounts_page(self) -> None:
        currency = self.data["settings"].get("currency", "EUR")
        account_id = self.current_account_id()
        current_month = self.current_display_month()
        self._clear_container(self.recurring_list_box)

        if not account_id:
            return

        recurring_items = [r for r in self.data["recurring_payments"] if r.get("account_id") == account_id]
        recurring_items.sort(key=lambda item: (self._safe_recurring_day(item), str(item.get("description", "")).lower()))

        if not recurring_items:
            empty = Gtk.Label(label="Keine Dauerzahlungen im ausgewählten Konto.")
            empty.set_xalign(0)
            empty.add_css_class("subtitle")
            self.recurring_list_box.append(empty)
            return

        month_closed = self.month_is_closed(current_month)
        for recurring in recurring_items:
            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            card.add_css_class("expense-card")
            card.add_css_class("recurring-compact")
            card.add_css_class("recurring-row")
            card.set_valign(Gtk.Align.START)

            left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            left.set_hexpand(True)

            due_this_month = self.is_recurring_due_in_month(recurring, current_month)
            is_done = self.is_recurring_checked_for_month(recurring, current_month)
            if due_this_month:
                check_label = "Erledigt" if is_done else "Offen"
            else:
                check_label = "Nicht fällig"
            check = Gtk.CheckButton.new_with_label(check_label)
            check.set_tooltip_text(f"Status für {format_month_label(current_month)}")
            check.set_active(is_done)
            check.set_sensitive((not month_closed) and due_this_month)
            check.connect("toggled", self.on_toggle_recurring_done, recurring["id"], current_month)
            left.append(check)

            sep = Gtk.Label(label="|")
            sep.add_css_class("subtitle")
            left.append(sep)

            recurring_day = self._safe_recurring_day(recurring)
            title_text = f"{str(recurring.get('description', '-'))} | Abbuchung am {recurring_day:02d}."
            title = Gtk.Label(label=title_text)
            title.set_xalign(0)
            title.set_hexpand(True)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_tooltip_text(title_text)
            left.append(title)
            card.append(left)

            month_amount = self.recurring_amount_for_month(recurring, current_month)
            if not due_this_month:
                month_amount = float(recurring.get("amount", 0.0))
            amount = Gtk.Label(label=format_money(month_amount, currency))
            amount.add_css_class("subtitle")
            card.append(amount)

            menu_btn = Gtk.MenuButton()
            menu_btn.set_icon_name("open-menu-symbolic")
            popover = Gtk.Popover()
            popover.add_css_class("menu-popover")
            pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pop_box.set_margin_top(8)
            pop_box.set_margin_bottom(8)
            pop_box.set_margin_start(8)
            pop_box.set_margin_end(8)
            edit_btn = Gtk.Button(label="Bearbeiten")
            edit_btn.connect("clicked", self.open_recurring_edit_popup, recurring["id"])
            delete_btn = Gtk.Button(label="Löschen")
            delete_btn.add_css_class("danger")
            delete_btn.connect("clicked", lambda _b, rid=recurring["id"]: self.on_delete_recurring(rid))
            pop_box.append(edit_btn)
            pop_box.append(delete_btn)
            popover.set_child(pop_box)
            menu_btn.set_popover(popover)
            card.append(menu_btn)

            self.recurring_list_box.append(card)

    def refresh_analysis_page(self) -> None:
        currency = self.data["settings"].get("currency", "EUR")
        this_month = self.current_display_month()

        month_expenses = [e for e in self.data["expenses"] if month_key_from_date_text(e.get("date", "")) == this_month]
        month_incomes = [i for i in self.data["incomes"] if month_key_from_date_text(i.get("date", "")) == this_month]

        total_expenses = sum(float(e.get("amount", 0.0)) for e in month_expenses)
        total_incomes = sum(float(i.get("amount", 0.0)) for i in month_incomes)
        remaining = total_incomes - total_expenses

        monthly_budget = float(self.data["settings"].get("monthly_budget", 0.0))
        budget_remaining = monthly_budget - total_expenses

        month_suffix = " (geschlossen)" if self.month_is_closed(this_month) else ""
        self.analysis_month.set_text(f"Monat: {format_month_label(this_month)}{month_suffix}")
        self.kpi_income_value.set_text(format_money(total_incomes, currency))
        self.kpi_expense_value.set_text(format_money(total_expenses, currency))
        self.kpi_remaining_value.set_text(format_money(remaining, currency))
        self.kpi_budget_left_value.set_text(format_money(budget_remaining, currency))

        for label, value in [
            (self.kpi_remaining_value, remaining),
            (self.kpi_budget_left_value, budget_remaining),
        ]:
            label.remove_css_class("kpi-positive")
            label.remove_css_class("kpi-negative")
            label.add_css_class("kpi-positive" if value >= 0 else "kpi-negative")

        budget_reference = monthly_budget if monthly_budget > 0 else max(total_incomes, 1.0)
        budget_ratio = min(1.0, max(0.0, total_expenses / budget_reference))
        self.budget_chart.set_segments(
            [(total_expenses, VIOLET, "Ausgaben"), (max(0.0, budget_reference - total_expenses), MINT, "Rest")],
            center_text=f"{int(budget_ratio * 100)}%",
            sub_text="Budget genutzt",
        )

        by_account = {}
        for account in self.data["accounts"]:
            aid = account["id"]
            by_account[account["name"]] = sum(float(e.get("amount", 0.0)) for e in month_expenses if e.get("account_id") == aid)

        account_segments = []
        for idx, (name, amount) in enumerate(by_account.items()):
            if amount <= 0:
                continue
            account_segments.append((amount, CATEGORY_COLORS[idx % len(CATEGORY_COLORS)], name))

        self.account_split_chart.set_segments(account_segments, center_text="100%", sub_text="Ausgaben verteilt")

        open_recurring_amount = 0.0
        for recurring in self.data["recurring_payments"]:
            if self.analysis_open_filter_id != "ALL" and recurring.get("account_id") != self.analysis_open_filter_id:
                continue
            if not self.is_recurring_due_in_month(recurring, this_month):
                continue
            if not self.is_recurring_checked_for_month(recurring, this_month):
                open_recurring_amount += self.recurring_amount_for_month(recurring, this_month)
        self.analysis_open_value.set_text(format_money(open_recurring_amount, currency))
        self.analysis_open_value.remove_css_class("kpi-positive")
        self.analysis_open_value.remove_css_class("kpi-negative")
        if open_recurring_amount > 0:
            self.analysis_open_value.add_css_class("kpi-negative")
        else:
            self.analysis_open_value.add_css_class("kpi-positive")

        self._clear_container(self.analysis_categories_flow)
        by_category: dict[str, float] = {}
        for expense in month_expenses:
            if self.analysis_category_filter_id != "ALL" and expense.get("account_id") != self.analysis_category_filter_id:
                continue
            key = expense.get("description", "Sonstiges")
            by_category[key] = by_category.get(key, 0.0) + float(expense.get("amount", 0.0))

        category_subtitle = "Alle Konten" if self.analysis_category_filter_id == "ALL" else self.account_name(self.analysis_category_filter_id)
        for idx, (name, amount) in enumerate(sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:9]):
            card = self._category_card(
                name,
                format_money(amount, currency),
                f"Monatskategorie - {category_subtitle}",
                CATEGORY_COLORS[idx % len(CATEGORY_COLORS)],
            )
            self.analysis_categories_flow.insert(card, -1)

    # -----------------------------
    # Card components
    # -----------------------------
    def _mini_info_card(self, title: str, subtitle: str, amount: str, icon_name: str) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("expense-card")

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(16)
        top.append(icon)

        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        top.append(title_label)
        card.append(top)

        subtitle_label = Gtk.Label(label=subtitle)
        subtitle_label.set_xalign(0)
        subtitle_label.add_css_class("subtitle")
        card.append(subtitle_label)

        amount_label = Gtk.Label(label=amount)
        amount_label.set_xalign(0)
        amount_label.add_css_class("kpi-value")
        card.append(amount_label)

        return card

    def _category_card(self, title: str, amount_text: str, subtitle: str, accent: str) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("expense-card")

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: card.add_css_class("hovered"))
        motion.connect("leave", lambda *_: card.remove_css_class("hovered"))
        card.add_controller(motion)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        dot = Gtk.Label()
        dot.set_use_markup(True)
        dot.set_markup(f"<span foreground='{accent}'>●</span>")
        head.append(dot)

        title_label = Gtk.Label(label=title)
        title_label.set_xalign(0)
        title_label.set_hexpand(True)
        head.append(title_label)
        card.append(head)

        amount_label = Gtk.Label(label=amount_text)
        amount_label.set_xalign(0)
        amount_label.add_css_class("kpi-value")
        card.append(amount_label)

        sub_label = Gtk.Label(label=subtitle)
        sub_label.set_xalign(0)
        sub_label.add_css_class("subtitle")
        card.append(sub_label)

        return card

    # -----------------------------
    # Animation
    # -----------------------------
    def run_initial_animations(self) -> bool:
        self.animate_page_widgets("start")
        return False

    def _on_page_switched(self, _stack: Gtk.Stack, _pspec) -> None:
        name = self.stack.get_visible_child_name()
        self.animate_page_widgets(name)
        self.update_page_scroll_policy()
        GLib.idle_add(self._run_scroll_policy_once)

    def animate_page_widgets(self, page_name: str) -> None:
        if self.is_closing:
            return
        if IS_WINDOWS:
            return
        widgets: list[Gtk.Widget] = []
        if page_name == "start":
            widgets = self.start_animated_widgets
        elif page_name == "accounts":
            widgets = self.accounts_animated_widgets
        elif page_name == "analysis":
            widgets = self.analysis_animated_widgets

        if page_name == "start":
            for widget in widgets:
                self.animate_float_in(widget, delay_ms=0)
        else:
            for idx, widget in enumerate(widgets):
                self.animate_float_in(widget, delay_ms=idx * 90)

        charts: list[DonutChart] = []
        for attr in ("budget_chart", "account_split_chart"):
            chart = getattr(self, attr, None)
            if isinstance(chart, DonutChart):
                charts.append(chart)
        for idx, chart in enumerate(charts):
            GLib.timeout_add(idx * 60, self._start_chart_anim, chart)

    def _start_chart_anim(self, chart: DonutChart) -> bool:
        if self.is_closing:
            return False
        chart.set_progress(0.0)
        self.animate_chart_progress(chart)
        return False

    def animate_chart_progress(self, chart: DonutChart) -> None:
        state = {"x": 0.0, "v": 0.0}

        def tick() -> bool:
            if self.is_closing:
                return False
            target = 1.0
            stiffness = 0.14
            damping = 0.74
            force = (target - state["x"]) * stiffness
            state["v"] = (state["v"] + force) * damping
            state["x"] += state["v"]
            chart.set_progress(state["x"])

            if abs(target - state["x"]) < 0.004 and abs(state["v"]) < 0.004:
                chart.set_progress(1.0)
                return False
            return True

        GLib.timeout_add(16, tick)

    def animate_float_in(self, widget: Gtk.Widget, delay_ms: int = 0) -> None:
        # Windows: avoid hidden UI when timer-based reveal is delayed or skipped.
        if IS_WINDOWS:
            widget.set_opacity(1.0)
            return

        widget.set_opacity(0.0)
        base_margin = widget.get_margin_top()
        widget.set_margin_top(base_margin + 24)
        state = {"x": 24.0, "v": 0.0}

        def start_anim() -> bool:
            if self.is_closing:
                return False
            def tick() -> bool:
                if self.is_closing:
                    return False
                target = 0.0
                stiffness = 0.16
                damping = 0.75
                force = (target - state["x"]) * stiffness
                state["v"] = (state["v"] + force) * damping
                state["x"] += state["v"]

                progress = max(0.0, min(1.0, 1.0 - (state["x"] / 24.0)))
                widget.set_opacity(progress)
                widget.set_margin_top(base_margin + max(0, int(state["x"])))

                if abs(state["x"]) < 0.2 and abs(state["v"]) < 0.2:
                    widget.set_opacity(1.0)
                    widget.set_margin_top(base_margin)
                    return False
                return True

            GLib.timeout_add(16, tick)
            return False

        GLib.timeout_add(delay_ms, start_anim)

    def update_page_scroll_policy(self) -> None:
        if hasattr(self, "page_scroller"):
            page_name = self.stack.get_visible_child_name() if hasattr(self, "stack") else None
            if page_name == "accounts":
                self.page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
                vadj = self.page_scroller.get_vadjustment()
                vadj.set_value(vadj.get_lower())
                self._sync_accounts_scroller_height()
            else:
                if hasattr(self, "recurring_scroller"):
                    self.recurring_scroller.set_min_content_height(0)
                    self.recurring_scroller.set_max_content_height(self._accounts_scroller_target_height())
                self.page_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

    def _sync_accounts_layout_tick(self, _widget: Gtk.Widget, _frame_clock: Gdk.FrameClock) -> bool:
        if self.is_closing:
            return False
        if hasattr(self, "stack") and self.stack.get_visible_child_name() == "accounts":
            self._sync_accounts_scroller_height()
        return True

    def _sync_accounts_scroller_height(self) -> None:
        if not hasattr(self, "recurring_scroller"):
            return
        target_h = self._accounts_scroller_target_height()
        if target_h == self._last_accounts_scroller_height:
            return
        self._last_accounts_scroller_height = target_h
        self.recurring_scroller.set_min_content_height(0)
        self.recurring_scroller.set_max_content_height(target_h)
        self.recurring_scroller.queue_resize()

    def _accounts_scroller_target_height(self) -> int:
        available_h = self.page_scroller.get_height() if hasattr(self, "page_scroller") else 0
        if available_h <= 0:
            available_h = self.get_height()
        if available_h <= 0:
            _default_w, default_h = self.get_default_size()
            available_h = default_h

        page_margin = 0
        if hasattr(self, "accounts_page"):
            page_margin = self.accounts_page.get_margin_top() + self.accounts_page.get_margin_bottom()

        focus_h = self.accounts_focus_bar.get_height() if hasattr(self, "accounts_focus_bar") else 0
        if focus_h <= 0:
            focus_h = 46

        header_h = 0
        if hasattr(self, "accounts_recurring_card"):
            card_header = self.accounts_recurring_card.get_first_child()
            if card_header is not None:
                header_h = card_header.get_height()
        if header_h <= 0:
            header_h = 48

        page_spacing = 16
        card_spacing = 10
        card_padding = 32
        target_h = available_h - page_margin - focus_h - page_spacing - header_h - card_spacing - card_padding
        return max(80, int(target_h))

    # -----------------------------
    # Reminder / Autostart
    # -----------------------------
    def hide_for_background_mode(self) -> bool:
        self.set_visible(False)
        return False

    def start_reminder_monitoring(self) -> None:
        GLib.timeout_add_seconds(60, self._reminder_tick)

    def _reminder_tick(self) -> bool:
        if self.is_closing:
            return False
        self.check_overdue_notifications()
        return True

    def check_overdue_notifications(self, force: bool = False) -> bool:
        overdue_items = self.collect_overdue_items()
        if not overdue_items:
            self.last_reminder_signature = ""
            return False

        signature = "|".join(sorted(item["key"] for item in overdue_items))
        now = time.time()
        today_key = date.today().isoformat()
        day_changed = today_key != self.last_reminder_day
        is_new = signature != self.last_reminder_signature
        cooldown = self.reminder_interval_minutes() * 60
        should_show = force or is_new or day_changed or (now - self.last_reminder_popup_at >= cooldown)

        if should_show:
            self.present_reminder_popup(overdue_items)
            self.last_reminder_popup_at = now
            self.last_reminder_signature = signature
            self.last_reminder_day = today_key
        return False

    def collect_overdue_items(self) -> list[dict]:
        today = date.today()
        current_month = month_key(today)
        items: list[dict] = []
        currency = self.data["settings"].get("currency", "EUR")

        for recurring in self.data["recurring_payments"]:
            for due_month in self.iter_due_months_until_today(recurring, current_month):
                if self.month_is_closed(due_month):
                    continue
                if self.is_recurring_checked_for_month(recurring, due_month):
                    continue
                year_text, month_text = due_month.split("-")
                due_date = self._date_with_clamped_day(int(year_text), int(month_text), self._safe_recurring_day(recurring))
                if due_date >= today:
                    continue
                account_id = str(recurring.get("account_id", ""))
                amount = self.recurring_amount_for_month(recurring, due_month)
                items.append(
                    {
                        "key": f"{recurring.get('id','')}:{due_month}",
                        "account": self.account_name(account_id),
                        "description": str(recurring.get("description", "-")),
                        "month": due_month,
                        "due_date": due_date,
                        "amount": format_money(float(amount), currency),
                    }
                )

        items.sort(key=lambda item: (item["due_date"], item["account"], item["description"]))
        return items

    def iter_due_months_until_today(self, recurring: dict, current_month: str) -> list[str]:
        start_month = self.recurring_start_month(recurring)
        if start_month > current_month:
            return []

        kind = str(recurring.get("kind", "standard"))
        if kind == "installment":
            end_month = self.recurring_end_month(recurring) or current_month
            if end_month > current_month:
                end_month = current_month
            months: list[str] = []
            probe = start_month
            for _idx in range(240):
                if probe > end_month:
                    break
                if self.is_recurring_due_in_month(recurring, probe):
                    months.append(probe)
                probe = self._month_shift(probe, 1)
            return months

        step = self._frequency_step(str(recurring.get("frequency", "monthly")))
        distance = self._month_distance(start_month, current_month)
        if distance < 0:
            return []
        months = []
        for offset in range(0, distance + 1, step):
            month_value = self._month_shift(start_month, offset)
            if self.is_recurring_due_in_month(recurring, month_value):
                months.append(month_value)
        return months

    def present_reminder_popup(self, overdue_items: list[dict]) -> None:
        if not overdue_items:
            return
        if self.reminder_popup is None:
            popup = Gtk.Window()
            popup.set_title("Überfällige Zahlungen")
            popup.set_transient_for(None)
            popup.set_modal(False)
            popup.set_default_size(560, 320)
            popup.set_resizable(True)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            content.set_margin_top(14)
            content.set_margin_bottom(14)
            content.set_margin_start(14)
            content.set_margin_end(14)

            title = Gtk.Label(label="Offene Zahlungen sind überfällig")
            title.set_xalign(0)
            title.add_css_class("title-3")
            content.append(title)

            subtitle = Gtk.Label(
                label="Diese Einträge liegen in der Vergangenheit und sind noch nicht als erledigt markiert."
            )
            subtitle.set_wrap(True)
            subtitle.set_xalign(0)
            subtitle.add_css_class("subtitle")
            content.append(subtitle)

            message = Gtk.Label(label="")
            message.set_xalign(0)
            message.set_wrap(True)
            message.set_selectable(True)
            message.add_css_class("subtitle")
            content.append(message)
            self.reminder_popup_text = message

            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            open_btn = Gtk.Button(label="Programm öffnen")
            open_btn.add_css_class("solid")
            open_btn.connect("clicked", self.on_open_program_from_reminder)
            self.reminder_popup_open_btn = open_btn
            actions.append(open_btn)
            later_btn = Gtk.Button(label="Später erinnern")
            later_btn.connect("clicked", lambda *_args: popup.close())
            actions.append(later_btn)
            content.append(actions)

            popup.set_child(content)
            popup.connect("close-request", self.on_reminder_popup_close)
            self.reminder_popup = popup

        lines: list[str] = []
        show_count = min(len(overdue_items), 8)
        for item in overdue_items[:show_count]:
            due_date = item["due_date"]
            date_text = f"{due_date.day:02d}-{due_date.month:02d}-{due_date.year}"
            lines.append(f"{item['account']} | {item['description']} | {item['amount']} | fällig {date_text}")
        remaining = len(overdue_items) - show_count
        if remaining > 0:
            lines.append(f"+ {remaining} weitere überfällige Zahlung(en)")
        if self.reminder_popup_text is not None:
            self.reminder_popup_text.set_text("\n".join(lines))

        self.reminder_popup.present()

    def on_reminder_popup_close(self, popup: Gtk.Window, *_args) -> bool:
        if self.reminder_popup is popup:
            self.reminder_popup = None
            self.reminder_popup_text = None
            self.reminder_popup_open_btn = None
        return False

    def on_open_program_from_reminder(self, _button: Gtk.Button) -> None:
        self.set_visible(True)
        self.present()
        self.switch_page("accounts")
        if self.reminder_popup is not None:
            self.reminder_popup.close()

    def ensure_autostart_configuration(self) -> None:
        enabled = self.autostart_enabled()
        if os.name == "nt":
            self.configure_windows_autostart(enabled)
        else:
            self.configure_linux_autostart(enabled)

    def autostart_command_parts(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable).resolve()), "--autostart"]
        return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve()), "--autostart"]

    def configure_linux_autostart(self, enabled: bool) -> None:
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / "jarvis-buchhaltung.desktop"
        if not enabled:
            if desktop_file.exists():
                try:
                    desktop_file.unlink()
                except OSError:
                    pass
            return

        try:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            command_parts = self.autostart_command_parts()
            exec_line = " ".join(f"\"{part}\"" for part in command_parts)
            desktop_content = "\n".join(
                [
                    "[Desktop Entry]",
                    "Type=Application",
                    "Name=Jarvis Buchhaltung",
                    "Comment=Startet Erinnerungen für überfällige Zahlungen",
                    f"Exec={exec_line}",
                    "Terminal=false",
                    "X-GNOME-Autostart-enabled=true",
                ]
            )
            desktop_file.write_text(desktop_content + "\n", encoding="utf-8")
        except OSError:
            pass

    def configure_windows_autostart(self, enabled: bool) -> None:
        appdata = os.environ.get("APPDATA", "").strip()
        if not appdata:
            return
        startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_file = startup_dir / "jarvis_buchhaltung_autostart.bat"

        if not enabled:
            if startup_file.exists():
                try:
                    startup_file.unlink()
                except OSError:
                    pass
            return

        try:
            startup_dir.mkdir(parents=True, exist_ok=True)
            command_parts = self.autostart_command_parts()
            if (not getattr(sys, "frozen", False)) and len(command_parts) >= 2:
                python_exec = Path(command_parts[0])
                pythonw_exec = python_exec.with_name("pythonw.exe")
                if pythonw_exec.exists():
                    command_parts[0] = str(pythonw_exec)
            command_line = " ".join(f"\"{part}\"" for part in command_parts)
            content = f"@echo off\r\nstart \"\" {command_line}\r\n"
            startup_file.write_text(content, encoding="utf-8")
        except OSError:
            pass

    def start_update_monitoring(self) -> None:
        GLib.timeout_add_seconds(300, self._update_check_tick)
        GLib.timeout_add_seconds(30, self._kickoff_update_check_once)

    def _kickoff_update_check_once(self) -> bool:
        if self.auto_update_check_enabled():
            self.request_update_check(manual=False)
        return False

    def _update_check_tick(self) -> bool:
        if self.is_closing:
            return False
        if not self.auto_update_check_enabled():
            return True

        interval_seconds = self.update_check_interval_hours() * 3600
        if (time.time() - self.last_update_check_at) >= interval_seconds:
            self.request_update_check(manual=False)
        return True

    def request_update_check(self, manual: bool = False) -> None:
        if self.update_check_in_progress:
            if manual:
                self.toast("Update-Prüfung läuft bereits.")
            return
        self.update_check_in_progress = True
        if manual and hasattr(self, "manual_update_check_btn"):
            self.manual_update_check_btn.set_sensitive(False)
        worker = threading.Thread(target=self._run_update_check_thread, args=(manual,), daemon=True)
        worker.start()

    def _run_update_check_thread(self, manual: bool) -> None:
        result = {
            "manual": manual,
            "ok": False,
            "error": "",
            "tag": "",
            "name": "",
            "published_at": "",
            "assets": [],
        }
        try:
            request = urllib.request.Request(
                GITHUB_LATEST_RELEASE_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "jarvis-buchhaltung-update-checker",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))

            result["ok"] = True
            result["tag"] = str(payload.get("tag_name", "")).strip()
            result["name"] = str(payload.get("name", "")).strip()
            result["published_at"] = str(payload.get("published_at", "")).strip()
            assets = payload.get("assets", [])
            if isinstance(assets, list):
                cleaned_assets: list[dict] = []
                for asset in assets:
                    if not isinstance(asset, dict):
                        continue
                    cleaned_assets.append(
                        {
                            "name": str(asset.get("name", "")).strip(),
                            "url": str(asset.get("browser_download_url", "")).strip(),
                            "size": int(asset.get("size", 0) or 0),
                        }
                    )
                result["assets"] = cleaned_assets
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            result["error"] = str(exc)
        GLib.idle_add(self._handle_update_check_result, result)

    def _handle_update_check_result(self, result: dict) -> bool:
        self.update_check_in_progress = False
        if hasattr(self, "manual_update_check_btn"):
            self.manual_update_check_btn.set_sensitive(True)
        self.last_update_check_at = time.time()

        manual = bool(result.get("manual"))
        if not result.get("ok"):
            if manual:
                self.toast("Update-Prüfung fehlgeschlagen.")
            return False

        latest_tag = str(result.get("tag", "")).strip()
        if not latest_tag:
            if manual:
                self.toast("Kein Release-Tag gefunden.")
            return False

        if not is_newer_version(latest_tag, APP_VERSION):
            if manual:
                self.toast(f"Du nutzt bereits die aktuelle Version ({APP_VERSION}).")
            return False

        if (not manual) and latest_tag == self.last_announced_update_tag:
            return False

        asset = self.choose_update_asset_for_current_platform(result.get("assets", []))
        if asset is None:
            if manual:
                self.toast("Kein passendes Update-Paket für dieses System gefunden.")
            return False

        self.last_announced_update_tag = latest_tag
        self.present_update_popup(
            latest_tag=latest_tag,
            release_name=str(result.get("name", "")).strip(),
            published_at=str(result.get("published_at", "")).strip(),
            asset_name=str(asset.get("name", "")).strip(),
            asset_url=str(asset.get("url", "")).strip(),
            asset_size=int(asset.get("size", 0) or 0),
        )
        return False

    def choose_update_asset_for_current_platform(self, assets: list[dict]) -> dict | None:
        valid_assets: list[dict] = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            url = str(asset.get("url", "")).strip()
            if not name or not url:
                continue
            valid_assets.append(asset)
        if not valid_assets:
            return None

        platform_key = "windows" if os.name == "nt" else "linux"
        if platform_key == "windows":
            for asset in valid_assets:
                name = str(asset.get("name", "")).lower()
                if name.endswith(".exe"):
                    return asset
            for asset in valid_assets:
                name = str(asset.get("name", "")).lower()
                if name.endswith(".msi"):
                    return asset
            return None

        for asset in valid_assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".appimage"):
                return asset
        for asset in valid_assets:
            name = str(asset.get("name", "")).lower()
            if name.endswith(".deb"):
                return asset
        return None

    def present_update_popup(
        self,
        latest_tag: str,
        release_name: str,
        published_at: str,
        asset_name: str,
        asset_url: str,
        asset_size: int,
    ) -> None:
        self.update_popup_asset_name = asset_name
        self.update_popup_asset_url = asset_url
        if self.update_popup is None:
            popup = Gtk.Window()
            popup.set_title("Update verfügbar")
            popup.set_transient_for(None)
            popup.set_modal(False)
            popup.set_default_size(520, 280)
            popup.set_resizable(True)

            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            content.set_margin_top(14)
            content.set_margin_bottom(14)
            content.set_margin_start(14)
            content.set_margin_end(14)

            title = Gtk.Label(label="")
            title.set_xalign(0)
            title.add_css_class("title-3")
            title.set_wrap(True)
            content.append(title)
            self.update_popup_title = title

            details = Gtk.Label(label="")
            details.set_xalign(0)
            details.set_wrap(True)
            details.set_selectable(True)
            details.add_css_class("subtitle")
            content.append(details)
            self.update_popup_details = details

            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            install_btn = Gtk.Button(label="Update installieren")
            install_btn.add_css_class("solid")
            install_btn.connect("clicked", self.on_install_update_clicked)
            actions.append(install_btn)
            self.update_popup_install_btn = install_btn
            later_btn = Gtk.Button(label="Später")
            later_btn.connect("clicked", lambda *_args: popup.close())
            actions.append(later_btn)
            content.append(actions)

            popup.set_child(content)
            popup.connect("close-request", self.on_update_popup_close)
            self.update_popup = popup

        title_text = f"Neues Update verfügbar: {latest_tag}"
        if self.update_popup_title is not None:
            self.update_popup_title.set_text(title_text)
        human_name = release_name or latest_tag
        published_text = published_at[:10] if published_at else "-"
        size_text = f"{asset_size / (1024 * 1024):.1f} MB" if asset_size > 0 else "-"
        details_text = (
            f"Aktuelle App-Version: {APP_VERSION}\n"
            f"Verfügbare Version: {latest_tag}\n"
            f"Release: {human_name}\n"
            f"Veröffentlicht: {published_text}\n"
            f"Paket: {asset_name}\n"
            f"Größe: {size_text}"
        )
        if self.update_popup_details is not None:
            self.update_popup_details.set_text(details_text)
        if self.update_popup_install_btn is not None:
            self.update_popup_install_btn.set_sensitive(
                (not self.update_download_in_progress) and (not self.update_install_in_progress)
            )

        self.update_popup.present()
        self.toast(f"Update verfügbar: {latest_tag}")

    def on_update_popup_close(self, popup: Gtk.Window, *_args) -> bool:
        if self.update_popup is popup:
            self.update_popup = None
            self.update_popup_title = None
            self.update_popup_details = None
            self.update_popup_install_btn = None
        return False

    def on_install_update_clicked(self, _button: Gtk.Button) -> None:
        if self.update_download_in_progress:
            self.toast("Update-Download läuft bereits.")
            return
        if self.update_install_in_progress:
            self.toast("Update-Installation läuft bereits.")
            return
        if not self.update_popup_asset_url:
            self.toast("Kein Update-Paket ausgewählt.")
            return
        self.update_download_in_progress = True
        if self.update_popup_install_btn is not None:
            self.update_popup_install_btn.set_sensitive(False)
        self.toast("Update wird heruntergeladen...")
        worker = threading.Thread(target=self._download_update_thread, daemon=True)
        worker.start()

    def _download_update_thread(self) -> None:
        result = {"ok": False, "path": "", "error": ""}
        try:
            target_dir = DATA_DIR / "updates"
            target_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(self.update_popup_asset_name).name or "update.bin"
            target_path = target_dir / safe_name

            request = urllib.request.Request(
                self.update_popup_asset_url,
                headers={"User-Agent": "jarvis-buchhaltung-updater"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                with open(target_path, "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
            result["ok"] = True
            result["path"] = str(target_path)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            result["error"] = str(exc)
        GLib.idle_add(self._handle_update_download_result, result)

    def _handle_update_download_result(self, result: dict) -> bool:
        self.update_download_in_progress = False
        if self.update_popup_install_btn is not None:
            self.update_popup_install_btn.set_sensitive(True)
        if not result.get("ok"):
            error_text = str(result.get("error", "")).strip()
            if error_text:
                self.toast(f"Update-Download fehlgeschlagen: {error_text}")
            else:
                self.toast("Update-Download fehlgeschlagen.")
            return False

        update_path = str(result.get("path", "")).strip()
        if not update_path:
            self.toast("Update-Datei fehlt.")
            return False

        update_file = Path(update_path)
        if os.name != "nt" and update_file.name.lower().endswith(".deb"):
            self._start_linux_deb_install(update_file)
            return False

        launched = self.launch_update_installer(update_file)
        if not launched:
            self.toast("Update konnte nicht gestartet werden.")
            return False

        self.toast("Update gestartet. App wird beendet.")
        self.is_closing = True
        app = self.get_application()
        if app is not None:
            app.quit()
        return False

    def _start_linux_deb_install(self, update_path: Path) -> None:
        if self.update_install_in_progress:
            return
        self.update_install_in_progress = True
        if self.update_popup_install_btn is not None:
            self.update_popup_install_btn.set_sensitive(False)
        self.toast("Update wird installiert. Bitte Admin-Freigabe bestätigen.")
        worker = threading.Thread(target=self._install_linux_deb_thread, args=(str(update_path),), daemon=True)
        worker.start()

    def _install_linux_deb_thread(self, update_path: str) -> None:
        result = {"ok": False, "error": "", "opened": False}
        path = Path(update_path)
        try:
            install_commands: list[list[str]] = []
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                if shutil.which("apt"):
                    install_commands.append(["apt", "install", "-y", str(path)])
                if shutil.which("apt-get"):
                    install_commands.append(["apt-get", "install", "-y", str(path)])
                install_commands.append(["dpkg", "-i", str(path)])
            elif shutil.which("pkexec"):
                if shutil.which("apt"):
                    install_commands.append(["pkexec", "apt", "install", "-y", str(path)])
                if shutil.which("apt-get"):
                    install_commands.append(["pkexec", "apt-get", "install", "-y", str(path)])
                install_commands.append(["pkexec", "dpkg", "-i", str(path)])

            error_messages: list[str] = []
            for cmd in install_commands:
                proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if proc.returncode == 0:
                    result["ok"] = True
                    break
                err = (proc.stderr or proc.stdout or "").strip()
                if not err:
                    err = f"{' '.join(cmd)} Fehlercode {proc.returncode}"
                error_messages.append(err[-240:])

            if not result["ok"]:
                # Fallback: open in Linux app center/package manager.
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", str(path)])
                    result["opened"] = True
                elif shutil.which("gio"):
                    subprocess.Popen(["gio", "open", str(path)])
                    result["opened"] = True
                else:
                    if error_messages:
                        result["error"] = " | ".join(error_messages)[-500:]
                    else:
                        result["error"] = "Weder Install-Kommando noch App-Center-Öffnung verfügbar."
        except OSError as exc:
            result["error"] = str(exc)

        GLib.idle_add(self._handle_linux_deb_install_result, result)

    def _handle_linux_deb_install_result(self, result: dict) -> bool:
        self.update_install_in_progress = False
        if self.update_popup_install_btn is not None:
            self.update_popup_install_btn.set_sensitive(True)

        if result.get("opened"):
            self.toast("Update-Paket geöffnet. Bitte Installation abschließen.")
            return False

        if not result.get("ok"):
            error_text = str(result.get("error", "")).strip()
            if error_text:
                self.toast(f"Update-Installation fehlgeschlagen: {error_text}")
            else:
                self.toast("Update-Installation fehlgeschlagen.")
            return False

        self.toast("Update installiert. App wird beendet.")
        self.restart_after_successful_update()
        self.is_closing = True
        app = self.get_application()
        if app is not None:
            app.quit()
        return False

    def restart_after_successful_update(self) -> None:
        try:
            if os.name == "nt":
                exe_path = Path(sys.executable)
                if exe_path.name.lower().endswith(".exe") and exe_path.stem.lower() != "python":
                    subprocess.Popen([str(exe_path)], close_fds=True)
                else:
                    subprocess.Popen([sys.executable, str(PROJECT_DIR / "app.py")], close_fds=True)
                return

            if shutil.which("jarvis-buchhaltung"):
                subprocess.Popen(["jarvis-buchhaltung"], start_new_session=True)
            else:
                subprocess.Popen([sys.executable, str(PROJECT_DIR / "app.py")], start_new_session=True)
        except OSError:
            self.toast("Neustart nach Update konnte nicht automatisch gestartet werden.")

    def launch_update_installer(self, update_path: Path) -> bool:
        name = update_path.name.lower()
        if os.name == "nt":
            try:
                os.startfile(str(update_path))  # type: ignore[attr-defined]
                return True
            except OSError:
                return False

        if name.endswith(".deb"):
            try:
                if shutil.which("pkexec"):
                    subprocess.Popen(["pkexec", "dpkg", "-i", str(update_path)])
                    return True
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", str(update_path)])
                    return True
            except OSError:
                return False
            return False

        if name.endswith(".appimage"):
            try:
                mode = update_path.stat().st_mode
                update_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                subprocess.Popen([str(update_path)])
                return True
            except OSError:
                return False

        try:
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", str(update_path)])
                return True
        except GLib.Error:
            return False
        except OSError:
            return False
        return False

    # -----------------------------
    # Domain logic
    # -----------------------------
    def _month_forward(self, year: int, month: int) -> tuple[int, int]:
        if month == 12:
            return year + 1, 1
        return year, month + 1

    def _month_shift(self, month: str, delta: int) -> str:
        year, month_num = [int(part) for part in month.split("-")]
        idx = (year * 12) + (month_num - 1) + delta
        target_year = idx // 12
        target_month = (idx % 12) + 1
        return f"{target_year}-{target_month:02d}"

    def _month_distance(self, start_month: str, target_month: str) -> int:
        sy, sm = [int(part) for part in start_month.split("-")]
        ty, tm = [int(part) for part in target_month.split("-")]
        return (ty * 12 + tm) - (sy * 12 + sm)

    def _frequency_step(self, frequency: str) -> int:
        if frequency == "quarterly":
            return 3
        if frequency == "yearly":
            return 12
        return 1

    def _date_with_clamped_day(self, year: int, month: int, day: int) -> date:
        day = max(1, min(31, day))
        while day > 28:
            try:
                return date(year, month, day)
            except ValueError:
                day -= 1
        return date(year, month, day)

    def _safe_recurring_day(self, recurring: dict) -> int:
        try:
            return max(1, min(28, int(recurring.get("day", 1))))
        except (TypeError, ValueError):
            return 1

    def recurring_start_month(self, recurring: dict) -> str:
        start_raw = str(recurring.get("start_date", "")).strip()
        if start_raw:
            return month_key_from_date_text(start_raw) or self.current_display_month()
        return self.current_display_month()

    def recurring_end_month(self, recurring: dict) -> str | None:
        end_raw = str(recurring.get("end_date", "")).strip()
        if not end_raw:
            return None
        return month_key_from_date_text(end_raw)

    def is_recurring_due_in_month(self, recurring: dict, target_month: str) -> bool:
        start_month = self.recurring_start_month(recurring)
        if self._month_distance(start_month, target_month) < 0:
            return False

        kind = str(recurring.get("kind", "standard"))
        if kind == "installment":
            end_month = self.recurring_end_month(recurring)
            if end_month and self._month_distance(target_month, end_month) < 0:
                return False
            step = 1
        else:
            step = self._frequency_step(str(recurring.get("frequency", "monthly")))

        distance = self._month_distance(start_month, target_month)
        return distance % step == 0

    def recurring_amount_for_month(self, recurring: dict, target_month: str) -> float:
        base_amount = float(recurring.get("amount", 0.0))
        if str(recurring.get("kind", "standard")) != "installment":
            return base_amount

        end_month = self.recurring_end_month(recurring)
        final_raw = recurring.get("final_amount")
        if final_raw in (None, ""):
            return base_amount
        try:
            final_amount = float(final_raw)
        except (TypeError, ValueError):
            return base_amount
        if final_amount <= 0:
            return base_amount
        if end_month and target_month == end_month:
            return final_amount
        return base_amount

    def has_future_due_from_month(self, recurring: dict, from_month: str) -> bool:
        probe = from_month
        for _ in range(240):
            if self.is_recurring_due_in_month(recurring, probe):
                return True
            probe = self._month_shift(probe, 1)
        return False

    def next_due_info_for_recurring(self, recurring: dict, reference_date: date) -> tuple[date, bool]:
        current_month = month_key(reference_date)
        checked_current = self.is_recurring_checked_for_month(recurring, current_month)

        candidate_month = current_month
        found_due = self.is_recurring_due_in_month(recurring, candidate_month) and not checked_current
        if checked_current or not self.is_recurring_due_in_month(recurring, current_month):
            found_due = False
            for _ in range(240):
                candidate_month = self._month_shift(candidate_month, 1)
                if self.is_recurring_due_in_month(recurring, candidate_month):
                    found_due = True
                    break
        if not found_due:
            # Fallback: no future due month (e.g., abzahlung already completed)
            year_text, month_text = current_month.split("-")
            due_date = self._date_with_clamped_day(int(year_text), int(month_text), self._safe_recurring_day(recurring))
            return due_date, True

        year_text, month_text = candidate_month.split("-")
        due_date = self._date_with_clamped_day(int(year_text), int(month_text), self._safe_recurring_day(recurring))
        return due_date, checked_current

    def is_recurring_checked_for_month(self, recurring: dict, month: str) -> bool:
        months = recurring.get("checked_months", [])
        return isinstance(months, list) and month in months

    def on_toggle_recurring_done(self, button: Gtk.CheckButton, recurring_id: str, month: str) -> None:
        recurring = next((r for r in self.data["recurring_payments"] if r.get("id") == recurring_id), None)
        if not recurring:
            return
        if not self.is_recurring_due_in_month(recurring, month):
            button.set_active(False)
            button.set_label("Nicht fällig")
            return
        if self.month_is_closed(month):
            button.set_active(self.is_recurring_checked_for_month(recurring, month))
            button.set_label("Erledigt" if button.get_active() else "Offen")
            self.toast(f"Monat {format_month_label(month)} ist geschlossen.")
            return

        months = recurring.get("checked_months")
        if not isinstance(months, list):
            months = []
            recurring["checked_months"] = months

        active = bool(button.get_active())
        if active and month not in months:
            months.append(month)
        if (not active) and month in months:
            months.remove(month)

        self.save_data()
        self.refresh_start_page()
        self.refresh_accounts_page()
        self.refresh_analysis_page()
        button.set_label("Erledigt" if button.get_active() else "Offen")

    def current_account_id(self) -> str | None:
        if self.selected_account_focus_id in self.account_ids:
            return self.selected_account_focus_id
        if self.account_ids:
            return self.account_ids[0]
        return None

    def apply_monthly_recurring_if_needed(self, force_current_month: bool = False) -> None:
        target_months = {month_key(date.today()), self.current_display_month()}
        changed = False

        for target_month in target_months:
            year_text, month_text = target_month.split("-")
            for payment in self.data["recurring_payments"]:
                if not self.is_recurring_due_in_month(payment, target_month):
                    continue

                amount = self.recurring_amount_for_month(payment, target_month)
                recurring_date = f"{self._safe_recurring_day(payment):02d}-{month_text}-{year_text}"
                plan_id = str(payment.get("id", ""))

                duplicate = any(
                    (
                        e.get("recurring_plan_id") == plan_id and e.get("recurring_month") == target_month
                    )
                    or (
                        e.get("source") in ("recurring", "installment")
                        and e.get("account_id") == payment.get("account_id")
                        and e.get("description") == payment.get("description")
                        and float(e.get("amount", 0.0)) == float(amount)
                        and e.get("date") == recurring_date
                    )
                    for e in self.data["expenses"]
                )
                if duplicate:
                    continue

                source_kind = "installment" if str(payment.get("kind", "standard")) == "installment" else "recurring"
                self.data["expenses"].append(
                    {
                        "id": str(uuid.uuid4()),
                        "account_id": payment.get("account_id"),
                        "description": payment.get("description"),
                        "amount": float(amount),
                        "date": recurring_date,
                        "source": source_kind,
                        "recurring_plan_id": plan_id,
                        "recurring_month": target_month,
                    }
                )
                changed = True

        applied = self.data["meta"].setdefault("recurring_applied_months", [])
        if isinstance(applied, list):
            for month in target_months:
                if month not in applied:
                    applied.append(month)
            applied.sort()
            if len(applied) > 36:
                del applied[:-36]

        if changed or force_current_month:
            self.save_data()

    def toast(self, message: str) -> None:
        # Lightweight non-blocking fallback in terminal output.
        print(message)


class FinanceApp(Adw.Application):
    def __init__(self, launched_from_autostart: bool = False, start_visible: bool = False) -> None:
        super().__init__(
            application_id="com.jarvis.buchhaltung",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.launched_from_autostart = launched_from_autostart
        self.autostart_launch_handled = False
        self.pending_show_request = bool(start_visible)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ICON_NAME)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit_action)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _on_quit_action(self, *_args) -> None:
        self.quit()

    def do_activate(self) -> None:
        window = self.props.active_window
        if not window:
            window = FinanceAppWindow(self, launched_from_autostart=self.launched_from_autostart)

        if self.launched_from_autostart and not self.autostart_launch_handled:
            self.autostart_launch_handled = True
            if (not self.pending_show_request) and (not window.should_open_window_on_autostart()):
                window.set_visible(False)
                window.check_overdue_notifications(force=True)
                return

        window.set_visible(True)
        window.present()
        self.pending_show_request = False

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        force_show = "--show" in args
        autostart_request = "--autostart" in args
        service_request = "--gapplication-service" in args

        window = self.props.active_window
        if window is None:
            # Race-safe: if the first remote activation is a normal/manual launch, force visible UI.
            self.pending_show_request = force_show or (not autostart_request and not service_request)
            self.activate()
            window = self.props.active_window
            if window is not None and self.pending_show_request:
                window.set_visible(True)
                window.present()
        else:
            if force_show:
                window.set_visible(True)
                window.present()
            elif autostart_request and (not window.should_open_window_on_autostart()):
                window.set_visible(False)
                window.check_overdue_notifications(force=True)
            else:
                window.set_visible(True)
                window.present()
        self.pending_show_request = False
        return 0


def main() -> None:
    args = sys.argv[1:]
    launched_from_autostart = "--autostart" in args
    start_visible = "--show" in args

    # Filter app-private launch flags before handing args to GApplication.
    filtered_args = [arg for arg in args if arg not in ("--autostart", "--show")]
    argv = [sys.argv[0]] + filtered_args

    append_runtime_log(
        f"start platform={sys.platform} frozen={getattr(sys, 'frozen', False)} "
        f"autostart={launched_from_autostart} show={start_visible} args={filtered_args}"
    )

    app = FinanceApp(launched_from_autostart=launched_from_autostart, start_visible=start_visible)
    app.run(argv)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        append_runtime_log(f"fatal: {exc}\n{traceback.format_exc()}")
        raise
