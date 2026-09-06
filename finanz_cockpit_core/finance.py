from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

APP_NAME = "FinanzCockpit"
LEGACY_APP_NAME = "JarvisBuchhaltung"
PROJECT_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE_PATH = PROJECT_DIR / "version.json"
LEGACY_DATA_PATH = PROJECT_DIR / "data.json"
LEGACY_DB_PATH = PROJECT_DIR / "buchhaltung.db"
APP_ICON_NAME = "finanz-cockpit"
GITHUB_REPO_URL = "https://github.com/JARVIS-ai-code/finanz-cockpit"
GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/JARVIS-ai-code/finanz-cockpit/releases/latest"

RECURRING_FREQUENCY_OPTIONS = [
    ("Monatlich", "monthly"),
    ("Quartalszahlung", "quarterly"),
    ("Halbjährlich", "semiannual"),
    ("Jährlich", "yearly"),
]
MONTH_NAMES = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

SCHEMA_SQL = """
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
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#C9A227'
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
    manual_transfer TEXT NOT NULL DEFAULT '{}',
    checked_months TEXT NOT NULL,
    skipped_months TEXT NOT NULL DEFAULT '[]',
    deferred_months TEXT NOT NULL DEFAULT '{}'
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

THEME_IDS = {"autumn", "monochrome", "deep-ocean", "mint-forest", "ice-cyan"}
LEGACY_THEME_IDS = {"cyberpunk-light": "ice-cyan"}

DEFAULT_DATA = {
    "settings": {
        "currency": "EUR",
        "theme": "autumn",
        "income_sources": [],
        "visible_month": "",
        "autostart_enabled": False,
        "autostart_start_hidden": False,
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

DEFAULT_ACCOUNT_COLORS = [
    "#4A3C1A",
    "#8B6914",
    "#C9A227",
    "#D4B896",
    "#F5E6C8",
    "#6B581B",
    "#A9892A",
    "#BDA16E",
]


class FinanceError(ValueError):
    pass


def app_data_dir(app_name: str = APP_NAME) -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA", "").strip() or os.environ.get("LOCALAPPDATA", "").strip()
        if base:
            return Path(base) / app_name
        return Path.home() / "AppData" / "Roaming" / app_name
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / app_name
    return Path.home() / ".local" / "share" / app_name


DATA_DIR = app_data_dir()
LEGACY_INSTALLED_DATA_DIR = app_data_dir(LEGACY_APP_NAME)
DATA_PATH = DATA_DIR / "data.json"
DB_PATH = DATA_DIR / "finanz-cockpit.db"
LEGACY_INSTALLED_DB_PATH = LEGACY_INSTALLED_DATA_DIR / "buchhaltung.db"
LEGACY_INSTALLED_DATA_PATH = LEGACY_INSTALLED_DATA_DIR / "data.json"


def load_app_version() -> str:
    candidates: list[Path] = []

    env_version_file = os.environ.get("FINANZ_COCKPIT_VERSION_FILE", "").strip()
    if env_version_file:
        candidates.append(Path(env_version_file))

    candidates.append(VERSION_FILE_PATH)

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates.extend(
            [
                exe_path.parent / "version.json",
                exe_path.parent.parent / "version.json",
            ]
        )
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(str(meipass)) / "version.json")

    checked: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in checked:
            continue
        checked.add(key)
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            value = str(payload.get("version", "")).strip()
            if value:
                return value
        except (OSError, json.JSONDecodeError):
            continue

    # Conservative fallback if no version source is available at runtime.
    return "0.1.0"


APP_VERSION = load_app_version()


def month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def parse_bool(value: Any, default: bool = False) -> bool:
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


def parse_float(text: Any) -> float:
    return float(str(text).strip().replace(",", "."))


def clean_color(value: Any, fallback: str = "#C9A227") -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in text[1:]):
        return text.lower()
    return fallback


def format_money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")


def date_to_text(d: date) -> str:
    return f"{d.day:02d}-{d.month:02d}-{d.year}"


def parse_input_date(text: str) -> date:
    raw = str(text).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise FinanceError("Ungültiges Datum")


def parse_month_text(value: str) -> str:
    text = str(value).strip()
    for fmt in ("%m-%Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return f"{parsed.year}-{parsed.month:02d}"
        except ValueError:
            pass
    raise FinanceError("Ungültiger Monat")


def format_month_label(month: str) -> str:
    try:
        year_text, month_text = str(month).split("-")
        month_num = int(month_text)
        year = int(year_text)
        if not (1 <= month_num <= 12):
            raise ValueError
    except (ValueError, TypeError):
        return str(month)
    return f"{MONTH_NAMES[month_num - 1]} {year} ({month_num:02d}-{year})"


def month_shift(month: str, delta: int) -> str:
    year, month_num = [int(part) for part in month.split("-")]
    idx = (year * 12) + (month_num - 1) + delta
    return f"{idx // 12}-{(idx % 12) + 1:02d}"


def month_distance(start_month: str, target_month: str) -> int:
    sy, sm = [int(part) for part in start_month.split("-")]
    ty, tm = [int(part) for part in target_month.split("-")]
    return (ty * 12 + tm) - (sy * 12 + sm)


def month_from_date_text(value: str) -> str | None:
    try:
        return month_key(parse_input_date(value))
    except FinanceError:
        return None


def clamped_date(year: int, month: int, day: int) -> date:
    d = max(1, min(31, int(day)))
    while d > 28:
        try:
            return date(year, month, d)
        except ValueError:
            d -= 1
    return date(year, month, d)


def frequency_step(freq: str) -> int:
    if freq == "quarterly":
        return 3
    if freq == "semiannual":
        return 6
    if freq == "yearly":
        return 12
    return 1


def normalize_recurring_frequency(value: Any, fallback: str = "monthly") -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "monthly": "monthly",
        "monatlich": "monthly",
        "quarterly": "quarterly",
        "quarter": "quarterly",
        "quartal": "quarterly",
        "quartalszahlung": "quarterly",
        "semiannual": "semiannual",
        "semi-annual": "semiannual",
        "semi_annually": "semiannual",
        "half-yearly": "semiannual",
        "halfyearly": "semiannual",
        "half_yearly": "semiannual",
        "halbjaehrlich": "semiannual",
        "halbjährlich": "semiannual",
        "yearly": "yearly",
        "annual": "yearly",
        "jaehrlich": "yearly",
        "jährlich": "yearly",
    }
    return mapping.get(text, fallback)


def iso_today() -> str:
    return date_to_text(date.today())


def safe_recurring_day(recurring: dict[str, Any]) -> int:
    try:
        return max(1, min(28, int(recurring.get("day", 1))))
    except (ValueError, TypeError):
        return 1


def recurring_start_month(recurring: dict[str, Any], fallback_month: str) -> str:
    raw = str(recurring.get("start_date", "")).strip()
    if raw:
        return month_from_date_text(raw) or fallback_month
    return fallback_month


def recurring_end_month(recurring: dict[str, Any]) -> str | None:
    raw = str(recurring.get("end_date", "")).strip()
    if not raw:
        return None
    return month_from_date_text(raw)


def is_recurring_due_in_month(recurring: dict[str, Any], target_month: str, fallback_month: str | None = None) -> bool:
    start = recurring_start_month(recurring, fallback_month or target_month)
    if month_distance(start, target_month) < 0:
        return False
    if target_month in recurring.get("skipped_months", []):
        return False
    if target_month in recurring.get("deferred_months", {}):
        return False
    end = recurring_end_month(recurring)
    if end and month_distance(target_month, end) < 0:
        return False

    kind = str(recurring.get("kind", "standard"))
    if kind == "installment":
        step = 1
    else:
        step = frequency_step(str(recurring.get("frequency", "monthly")))

    return month_distance(start, target_month) % step == 0


def recurring_amount_for_month(recurring: dict[str, Any], target_month: str) -> float:
    base_amount = float(recurring.get("amount", 0.0))
    if str(recurring.get("kind", "standard")) != "installment":
        return base_amount

    final_raw = recurring.get("final_amount")
    if final_raw in (None, ""):
        return base_amount
    try:
        final_amount = float(final_raw)
    except (TypeError, ValueError):
        return base_amount
    if final_amount <= 0:
        return base_amount
    if recurring_end_month(recurring) == target_month:
        return final_amount
    return base_amount


def version_tuple(version_text: str) -> tuple[int, ...]:
    cleaned = str(version_text).strip().lstrip("vV")
    parts: list[int] = []
    for token in cleaned.replace("-", ".").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    return version_tuple(latest) > version_tuple(current)


class FinanceService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._update_jobs: dict[str, dict[str, Any]] = {}
        self._update_jobs_lock = threading.Lock()
        self._latest_update_job_id: str = ""
        self.ensure_data_layout()
        self.initialize_db()
        if self.db_is_empty():
            self.import_legacy_json_if_available()
        self.ensure_defaults()
        self.ensure_autostart_configuration()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_data_layout(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            return

        for source in (LEGACY_INSTALLED_DB_PATH, LEGACY_DB_PATH):
            if not source.exists() or source.resolve() == self.db_path.resolve():
                continue
            try:
                self.db_path.write_bytes(source.read_bytes())
                return
            except OSError:
                pass

    def initialize_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            account_columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
            if "color" not in account_columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN color TEXT NOT NULL DEFAULT '#C9A227'")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(recurring_payments)")}
            if "skipped_months" not in columns:
                conn.execute("ALTER TABLE recurring_payments ADD COLUMN skipped_months TEXT NOT NULL DEFAULT '[]'")
            if "deferred_months" not in columns:
                conn.execute("ALTER TABLE recurring_payments ADD COLUMN deferred_months TEXT NOT NULL DEFAULT '{}'")
            if "manual_transfer" not in columns:
                conn.execute("ALTER TABLE recurring_payments ADD COLUMN manual_transfer TEXT NOT NULL DEFAULT '{}'")

    def db_is_empty(self) -> bool:
        with self.connect() as conn:
            for table in ("settings", "meta", "accounts", "recurring_payments", "expenses", "incomes"):
                if int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > 0:
                    return False
        return True

    def import_legacy_json_if_available(self) -> None:
        source = next(
            (
                candidate
                for candidate in (LEGACY_INSTALLED_DATA_PATH, LEGACY_DATA_PATH, DATA_PATH)
                if candidate.exists()
            ),
            DATA_PATH,
        )
        if not source.exists():
            return
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.save_payload(self.normalize_data(payload))

    def ensure_defaults(self) -> None:
        data = self.normalize_data(self.load_payload())
        self.save_payload(data)

    def load_payload(self) -> dict[str, Any]:
        data = deepcopy(DEFAULT_DATA)
        with self.connect() as conn:
            for row in conn.execute("SELECT key, value FROM settings"):
                key = str(row["key"])
                value = row["value"]
                if key == "income_sources":
                    try:
                        data["settings"][key] = json.loads(value)
                    except json.JSONDecodeError:
                        data["settings"][key] = []
                elif key in ("autostart_enabled", "autostart_start_hidden", "auto_update_check"):
                    data["settings"][key] = parse_bool(value, bool(DEFAULT_DATA["settings"].get(key)))
                elif key in ("reminder_interval_minutes", "update_check_interval_hours"):
                    try:
                        data["settings"][key] = int(value)
                    except (TypeError, ValueError):
                        data["settings"][key] = DEFAULT_DATA["settings"][key]
                else:
                    data["settings"][key] = value

            for row in conn.execute("SELECT key, value FROM meta"):
                try:
                    data["meta"][row["key"]] = json.loads(row["value"])
                except json.JSONDecodeError:
                    data["meta"][row["key"]] = []

            data["accounts"] = [dict(row) for row in conn.execute("SELECT id, name, color FROM accounts ORDER BY name COLLATE NOCASE")]
            data["recurring_payments"] = [self.recurring_from_row(row) for row in conn.execute(
                """
                SELECT id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, manual_transfer, checked_months, skipped_months, deferred_months
                FROM recurring_payments
                ORDER BY day, description COLLATE NOCASE
                """
            )]
            data["expenses"] = [dict(row) for row in conn.execute(
                """
                SELECT id, account_id, description, amount, date, source, recurring_plan_id, recurring_month
                FROM expenses
                ORDER BY date DESC, description COLLATE NOCASE
                """
            )]
            data["incomes"] = [dict(row) for row in conn.execute(
                "SELECT id, type, account_id, description, amount, date FROM incomes ORDER BY date DESC"
            )]
        return self.normalize_data(data)

    def save_payload(self, payload: dict[str, Any]) -> None:
        data = self.normalize_data(payload)
        with self.connect() as conn:
            conn.execute("BEGIN")
            for table in ("settings", "meta", "accounts", "recurring_payments", "expenses", "incomes"):
                conn.execute(f"DELETE FROM {table}")

            for key, value in data["settings"].items():
                if key == "income_sources":
                    stored = json.dumps(value, ensure_ascii=False)
                else:
                    stored = str(value)
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (key, stored))
            for key, value in data["meta"].items():
                conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, json.dumps(value, ensure_ascii=False)))
            for account in data["accounts"]:
                conn.execute(
                    "INSERT INTO accounts(id, name, color) VALUES (?, ?, ?)",
                    (account["id"], account["name"], account["color"]),
                )
            for rec in data["recurring_payments"]:
                conn.execute(
                    """
                    INSERT INTO recurring_payments(
                        id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, manual_transfer, checked_months, skipped_months, deferred_months
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec["id"],
                        rec["kind"],
                        rec["account_id"],
                        rec["description"],
                        rec["amount"],
                        rec["day"],
                        rec["frequency"],
                        rec.get("start_date") or "",
                        rec.get("end_date") or "",
                        rec.get("final_amount"),
                        json.dumps(rec.get("manual_transfer", {}), ensure_ascii=False),
                        json.dumps(rec.get("checked_months", []), ensure_ascii=False),
                        json.dumps(rec.get("skipped_months", []), ensure_ascii=False),
                        json.dumps(rec.get("deferred_months", {}), ensure_ascii=False),
                    ),
                )
            for expense in data["expenses"]:
                conn.execute(
                    """
                    INSERT INTO expenses(id, account_id, description, amount, date, source, recurring_plan_id, recurring_month)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        expense["id"],
                        expense["account_id"],
                        expense["description"],
                        expense["amount"],
                        expense["date"],
                        expense.get("source"),
                        expense.get("recurring_plan_id"),
                        expense.get("recurring_month"),
                    ),
                )
            for income in data["incomes"]:
                conn.execute(
                    "INSERT INTO incomes(id, type, account_id, description, amount, date) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        income["id"],
                        income["type"],
                        income["account_id"],
                        income["description"],
                        income["amount"],
                        income["date"],
                    ),
                )

    def normalize_data(self, loaded: dict[str, Any]) -> dict[str, Any]:
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

        # Keep only supported setting keys; silently drop legacy keys from older app versions.
        data["settings"] = {key: data["settings"].get(key) for key in DEFAULT_DATA["settings"].keys()}
        data["settings"]["currency"] = str(data["settings"].get("currency", "EUR")).strip().upper() or "EUR"
        data["settings"]["theme"] = self.normalize_theme_id(data["settings"].get("theme"))
        for key, default in (("autostart_enabled", False), ("autostart_start_hidden", False), ("auto_update_check", True)):
            data["settings"][key] = parse_bool(data["settings"].get(key), default)
        if not data["settings"]["autostart_enabled"]:
            data["settings"]["autostart_start_hidden"] = False
        data["settings"]["reminder_interval_minutes"] = self.clamp_int(data["settings"].get("reminder_interval_minutes", 15), 1, 240, 15)
        data["settings"]["update_check_interval_hours"] = self.clamp_int(data["settings"].get("update_check_interval_hours", 6), 1, 168, 6)
        try:
            data["settings"]["visible_month"] = parse_month_text(str(data["settings"].get("visible_month", "")))
        except FinanceError:
            data["settings"]["visible_month"] = month_key(date.today())
        data["settings"]["income_sources"] = self.clean_income_sources(data["settings"].get("income_sources"))

        data["meta"]["closed_months"] = self.clean_month_list(data["meta"].get("closed_months"))
        applied = data["meta"].get("recurring_applied_months")
        data["meta"]["recurring_applied_months"] = self.clean_month_list(applied)[-36:]

        data["accounts"] = self.clean_accounts(data["accounts"])
        valid_accounts = {account["id"] for account in data["accounts"]}
        data["recurring_payments"] = self.clean_recurring(data["recurring_payments"], valid_accounts)
        data["expenses"] = self.clean_transactions(data["expenses"], valid_accounts, "expense")
        data["incomes"] = self.clean_transactions(data["incomes"], valid_accounts, "income")
        return data

    def normalize_theme_id(self, value: Any) -> str:
        theme = str(value or "autumn").strip().lower()
        theme = LEGACY_THEME_IDS.get(theme, theme)
        return theme if theme in THEME_IDS else "autumn"

    def recurring_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            checked = json.loads(row["checked_months"] or "[]")
        except json.JSONDecodeError:
            checked = []
        try:
            skipped = json.loads(row["skipped_months"] or "[]")
        except (IndexError, json.JSONDecodeError):
            skipped = []
        try:
            deferred = json.loads(row["deferred_months"] or "{}")
        except (IndexError, json.JSONDecodeError):
            deferred = {}
        try:
            manual_transfer = json.loads(row["manual_transfer"] or "{}")
        except (IndexError, json.JSONDecodeError):
            manual_transfer = {}
        return {
            "id": row["id"],
            "kind": row["kind"],
            "account_id": row["account_id"],
            "description": row["description"],
            "amount": float(row["amount"]),
            "day": int(row["day"]),
            "frequency": row["frequency"],
            "start_date": row["start_date"] or "",
            "end_date": row["end_date"] or "",
            "final_amount": row["final_amount"],
            "manual_transfer": self.clean_manual_transfer(manual_transfer),
            "checked_months": checked if isinstance(checked, list) else [],
            "skipped_months": skipped if isinstance(skipped, list) else [],
            "deferred_months": deferred if isinstance(deferred, dict) else {},
        }

    def clean_income_sources(self, sources: Any) -> list[str]:
        cleaned: list[str] = []
        items = sources if isinstance(sources, list) else []
        for source in items:
            text = str(source).strip()
            if text and text.lower() not in [item.lower() for item in cleaned]:
                cleaned.append(text)
        return cleaned

    def clean_month_list(self, months: Any) -> list[str]:
        cleaned: list[str] = []
        for item in months if isinstance(months, list) else []:
            try:
                month = parse_month_text(str(item))
            except FinanceError:
                continue
            if month not in cleaned:
                cleaned.append(month)
        cleaned.sort()
        return cleaned

    def clean_deferred_months(self, deferred: Any) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        if not isinstance(deferred, dict):
            return cleaned
        for source_raw, target_raw in deferred.items():
            try:
                source = parse_month_text(str(source_raw))
                target = parse_month_text(str(target_raw))
            except FinanceError:
                continue
            if target == month_shift(source, 1):
                cleaned[source] = target
        return dict(sorted(cleaned.items()))

    def clean_manual_transfer(self, value: Any) -> dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        transfer_type = str(raw.get("type") or "private").strip().lower()
        if transfer_type not in ("private", "company"):
            transfer_type = "private"
        return {
            "enabled": parse_bool(raw.get("enabled"), False),
            "type": transfer_type,
            "first_name": str(raw.get("first_name") or "").strip(),
            "last_name": str(raw.get("last_name") or "").strip(),
            "company_name": str(raw.get("company_name") or "").strip(),
            "iban": str(raw.get("iban") or "").strip().upper().replace(" ", ""),
            "bic": str(raw.get("bic") or "").strip().upper().replace(" ", ""),
            "purpose": str(raw.get("purpose") or "").strip(),
        }

    def clean_accounts(self, accounts: Any) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for index, account in enumerate(accounts if isinstance(accounts, list) else []):
            if not isinstance(account, dict):
                continue
            name = str(account.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            fallback_color = DEFAULT_ACCOUNT_COLORS[index % len(DEFAULT_ACCOUNT_COLORS)]
            cleaned.append({
                "id": str(account.get("id") or uuid.uuid4()),
                "name": name,
                "color": clean_color(account.get("color"), fallback_color),
            })
        cleaned.sort(key=lambda item: item["name"].lower())
        return cleaned

    def clean_recurring(self, items: Any, valid_accounts: set[str]) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("account_id", ""))
            if account_id not in valid_accounts:
                continue
            description = str(item.get("description", "")).strip()
            if not description:
                continue
            try:
                amount = parse_float(item.get("amount", 0.0))
                day = self.clamp_int(item.get("day", 1), 1, 28, 1)
            except ValueError:
                continue
            kind = str(item.get("kind", "standard"))
            if kind not in ("standard", "installment"):
                kind = "standard"
            frequency = normalize_recurring_frequency(item.get("frequency", "monthly"))
            start_date = str(item.get("start_date") or iso_today())
            end_date = str(item.get("end_date") or "")
            final_amount = item.get("final_amount")
            if final_amount not in (None, ""):
                try:
                    final_amount = parse_float(final_amount)
                except ValueError:
                    final_amount = None
            cleaned.append(
                {
                    "id": str(item.get("id") or uuid.uuid4()),
                    "kind": kind,
                    "account_id": account_id,
                    "description": description,
                    "amount": max(0.0, amount),
                    "day": day,
                    "frequency": "monthly" if kind == "installment" else frequency,
                    "start_date": start_date,
                    "end_date": end_date,
                    "final_amount": final_amount if kind == "installment" else None,
                    "manual_transfer": self.clean_manual_transfer(item.get("manual_transfer")),
                    "checked_months": self.clean_month_list(item.get("checked_months")),
                    "skipped_months": self.clean_month_list(item.get("skipped_months")),
                    "deferred_months": self.clean_deferred_months(item.get("deferred_months")),
                }
            )
        return cleaned

    def clean_transactions(self, items: Any, valid_accounts: set[str], kind: str) -> list[dict[str, Any]]:
        cleaned: list[dict[str, Any]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            account_id = str(item.get("account_id", ""))
            if account_id not in valid_accounts:
                continue
            try:
                parsed = parse_input_date(str(item.get("date", "")))
                amount = parse_float(item.get("amount", 0.0))
            except (FinanceError, ValueError):
                continue
            base = {
                "id": str(item.get("id") or uuid.uuid4()),
                "account_id": account_id,
                "description": str(item.get("description", "")).strip() or ("Ausgabe" if kind == "expense" else "Einnahme"),
                "amount": max(0.0, amount),
                "date": date_to_text(parsed),
            }
            if kind == "income":
                base["type"] = str(item.get("type", "")).strip() or "Ohne Quelle"
            else:
                base["source"] = item.get("source")
                base["recurring_plan_id"] = item.get("recurring_plan_id")
                base["recurring_month"] = item.get("recurring_month")
            cleaned.append(base)
        return cleaned

    def clamp_int(self, value: Any, low: int, high: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(low, min(parsed, high))

    def data(self) -> dict[str, Any]:
        payload = self.load_payload()
        self.apply_recurring_for_visible_and_current(payload)
        return self.load_payload()

    def settings(self) -> dict[str, Any]:
        return self.data()["settings"]

    def account_name_map(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        data = payload or self.data()
        return {account["id"]: account["name"] for account in data["accounts"]}

    def account_color_map(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        data = payload or self.data()
        return {account["id"]: clean_color(account.get("color")) for account in data["accounts"]}

    def visible_month(self, payload: dict[str, Any] | None = None) -> str:
        data = payload or self.data()
        return str(data["settings"]["visible_month"])

    def month_is_closed(self, month: str, payload: dict[str, Any] | None = None) -> bool:
        data = payload or self.data()
        return month in data["meta"].get("closed_months", [])

    def require_open_month(self, month: str, payload: dict[str, Any]) -> None:
        if self.month_is_closed(month, payload):
            raise FinanceError(f"Monat {format_month_label(month)} ist geschlossen.")

    def list_month_incomes(self, month: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = payload or self.data()
        return [item for item in data["incomes"] if month_from_date_text(str(item.get("date", ""))) == month]

    def list_month_expenses(self, month: str, payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = payload or self.data()
        return [item for item in data["expenses"] if month_from_date_text(str(item.get("date", ""))) == month]

    def add_account(self, name: str, color: str = "") -> None:
        data = self.load_payload()
        text = str(name).strip()
        if not text:
            raise FinanceError("Kontoname fehlt.")
        if text.lower() in [account["name"].lower() for account in data["accounts"]]:
            raise FinanceError("Dieses Konto existiert bereits.")
        fallback_color = DEFAULT_ACCOUNT_COLORS[len(data["accounts"]) % len(DEFAULT_ACCOUNT_COLORS)]
        data["accounts"].append({"id": str(uuid.uuid4()), "name": text, "color": clean_color(color, fallback_color)})
        self.save_payload(data)

    def update_account(self, account_id: str, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        account = next((item for item in data["accounts"] if item["id"] == account_id), None)
        if account is None:
            raise FinanceError("Konto nicht gefunden.")
        if "color" in payload:
            account["color"] = clean_color(payload.get("color"), account.get("color", "#C9A227"))
        self.save_payload(data)

    def delete_account(self, account_id: str) -> None:
        data = self.load_payload()
        data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
        data["expenses"] = [e for e in data["expenses"] if e["account_id"] != account_id]
        data["recurring_payments"] = [r for r in data["recurring_payments"] if r["account_id"] != account_id]
        data["incomes"] = [i for i in data["incomes"] if i["account_id"] != account_id]
        self.save_payload(data)

    def add_income(self, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        entry = self.validate_income_payload(payload)
        self.require_open_month(month_from_date_text(entry["date"]) or "", data)
        data["incomes"].append({"id": str(uuid.uuid4()), **entry})
        self.save_payload(data)

    def update_income(self, income_id: str, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        entry = self.validate_income_payload(payload)
        old = next((item for item in data["incomes"] if item["id"] == income_id), None)
        if old is None:
            raise FinanceError("Einnahme nicht gefunden.")
        for month in {month_from_date_text(old["date"]), month_from_date_text(entry["date"])}:
            if month:
                self.require_open_month(month, data)
        old.update(entry)
        self.save_payload(data)

    def delete_income(self, income_id: str) -> None:
        data = self.load_payload()
        income = next((item for item in data["incomes"] if item["id"] == income_id), None)
        if income is None:
            raise FinanceError("Einnahme nicht gefunden.")
        month = month_from_date_text(income["date"])
        if month:
            self.require_open_month(month, data)
        data["incomes"] = [item for item in data["incomes"] if item["id"] != income_id]
        self.save_payload(data)

    def add_expense(self, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        entry = self.validate_expense_payload(payload)
        self.require_open_month(month_from_date_text(entry["date"]) or "", data)
        data["expenses"].append({"id": str(uuid.uuid4()), **entry})
        self.save_payload(data)

    def update_expense(self, expense_id: str, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        entry = self.validate_expense_payload(payload)
        old = next((item for item in data["expenses"] if item["id"] == expense_id), None)
        if old is None:
            raise FinanceError("Ausgabe nicht gefunden.")
        for month in {month_from_date_text(old["date"]), month_from_date_text(entry["date"])}:
            if month:
                self.require_open_month(month, data)
        old.update(entry)
        self.save_payload(data)

    def delete_expense(self, expense_id: str) -> None:
        data = self.load_payload()
        expense = next((item for item in data["expenses"] if item["id"] == expense_id), None)
        if expense is None:
            raise FinanceError("Ausgabe nicht gefunden.")
        month = month_from_date_text(expense["date"])
        if month:
            self.require_open_month(month, data)
        data["expenses"] = [item for item in data["expenses"] if item["id"] != expense_id]
        self.save_payload(data)

    def validate_income_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id", "")).strip()
        description = str(payload.get("description", "")).strip()
        income_type = str(payload.get("type", "")).strip()
        data = self.load_payload()
        income_sources = self.clean_income_sources(data["settings"].get("income_sources"))
        if not income_sources:
            raise FinanceError("Bitte zuerst eine Einnahmequelle anlegen.")
        if income_type.lower() not in [source.lower() for source in income_sources]:
            raise FinanceError("Bitte eine gültige Einnahmequelle auswählen.")
        if not description:
            raise FinanceError("Beschreibung fehlt.")
        try:
            amount = parse_float(payload.get("amount", ""))
            parsed_date = parse_input_date(str(payload.get("date", "")))
        except (FinanceError, ValueError):
            raise FinanceError("Bitte gültige Werte für Betrag und Datum eingeben.") from None
        if amount <= 0:
            raise FinanceError("Der Betrag muss größer als 0 sein.")
        if not data["accounts"]:
            raise FinanceError("Bitte zuerst ein Konto anlegen.")
        if account_id not in [item["id"] for item in data["accounts"]]:
            raise FinanceError("Bitte ein Konto auswählen.")
        return {
            "type": income_type,
            "account_id": account_id,
            "description": description,
            "amount": amount,
            "date": date_to_text(parsed_date),
        }

    def validate_expense_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id", "")).strip()
        description = str(payload.get("description", "")).strip()
        if not description:
            raise FinanceError("Kategorie fehlt.")
        try:
            amount = parse_float(payload.get("amount", ""))
            parsed_date = parse_input_date(str(payload.get("date", "")))
        except (FinanceError, ValueError):
            raise FinanceError("Bitte gültige Werte für Betrag und Datum eingeben.") from None
        if amount <= 0:
            raise FinanceError("Der Betrag muss größer als 0 sein.")
        data = self.load_payload()
        if not data["accounts"]:
            raise FinanceError("Bitte zuerst ein Konto anlegen.")
        if account_id not in [item["id"] for item in data["accounts"]]:
            raise FinanceError("Bitte ein Konto auswählen.")
        return {
            "account_id": account_id,
            "description": description,
            "amount": amount,
            "date": date_to_text(parsed_date),
            "source": payload.get("source") or "manual",
            "recurring_plan_id": payload.get("recurring_plan_id"),
            "recurring_month": payload.get("recurring_month"),
        }

    def add_recurring(self, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        data["recurring_payments"].append({"id": str(uuid.uuid4()), **self.validate_recurring_payload(payload, data)})
        self.apply_recurring_for_visible_and_current(data, force=True)
        self.save_payload(data)

    def update_recurring(self, recurring_id: str, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            raise FinanceError("Dauerzahlung nicht gefunden.")
        scope = str(payload.get("effective_scope") or "current")
        if scope not in ("current", "next"):
            scope = "current"
        effective_month = self.visible_month(data) if scope == "current" else month_shift(self.visible_month(data), 1)
        entry = self.validate_recurring_payload(payload, data)
        if recurring_start_month(rec, self.visible_month(data)) >= effective_month:
            checked_months = rec.get("checked_months", [])
            skipped_months = rec.get("skipped_months", [])
            deferred_months = rec.get("deferred_months", {})
            rec.update(entry)
            rec["checked_months"] = checked_months
            rec["skipped_months"] = skipped_months
            rec["deferred_months"] = deferred_months
            self.update_recurring_expenses_from_month(data, rec, effective_month)
        else:
            rec["end_date"] = self.month_end_date_text(month_shift(effective_month, -1))
            new_id = str(uuid.uuid4())
            new_rec = {
                "id": new_id,
                **entry,
                "start_date": self.month_start_date_text(effective_month),
                "checked_months": [],
                "skipped_months": [],
                "deferred_months": {},
            }
            data["recurring_payments"].append(new_rec)
            if scope == "current":
                self.move_month_expense_to_recurring(data, rec, new_rec, effective_month)
            self.remove_recurring_expenses_from_month(data, rec["id"], effective_month, include_future=True)
        self.apply_recurring_for_visible_and_current(data, force=True)
        self.save_payload(data)

    def delete_recurring(self, recurring_id: str, scope: str = "current") -> None:
        data = self.load_payload()
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            return
        if scope not in ("current", "next"):
            scope = "current"
        effective_month = self.visible_month(data) if scope == "current" else month_shift(self.visible_month(data), 1)
        rec["end_date"] = self.month_end_date_text(month_shift(effective_month, -1))
        self.remove_recurring_expenses_from_month(data, recurring_id, effective_month, include_future=True)
        self.save_payload(data)

    def skip_recurring_month(self, recurring_id: str, month: str) -> None:
        data = self.load_payload()
        month = parse_month_text(month)
        self.require_open_month(month, data)
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            raise FinanceError("Dauerzahlung nicht gefunden.")
        deferred = self.clean_deferred_months(rec.get("deferred_months"))
        if not is_recurring_due_in_month({**rec, "skipped_months": [], "deferred_months": {}}, month, self.visible_month(data)) and month not in deferred:
            raise FinanceError("Diese Zahlung ist im Monat nicht fällig.")
        skipped = self.clean_month_list(rec.get("skipped_months"))
        checked = self.clean_month_list(rec.get("checked_months"))
        if month not in skipped:
            skipped.append(month)
        if month in checked:
            checked.remove(month)
        if month in deferred:
            del deferred[month]
        rec["skipped_months"] = sorted(skipped)
        rec["checked_months"] = sorted(checked)
        rec["deferred_months"] = deferred
        self.remove_recurring_expenses_from_month(data, recurring_id, month, include_future=False)
        self.save_payload(data)

    def postpone_recurring_month(self, recurring_id: str, month: str) -> None:
        data = self.load_payload()
        month = parse_month_text(month)
        target_month = month_shift(month, 1)
        self.require_open_month(month, data)
        self.require_open_month(target_month, data)
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            raise FinanceError("Dauerzahlung nicht gefunden.")
        if month in self.clean_month_list(rec.get("checked_months")):
            raise FinanceError("Erledigte Zahlungen können nicht verschoben werden.")
        if not is_recurring_due_in_month({**rec, "skipped_months": [], "deferred_months": {}}, month, self.visible_month(data)):
            raise FinanceError("Diese Zahlung ist im Monat nicht fällig.")
        skipped = self.clean_month_list(rec.get("skipped_months"))
        if month in skipped:
            skipped.remove(month)
        deferred = self.clean_deferred_months(rec.get("deferred_months"))
        deferred[month] = target_month
        rec["skipped_months"] = skipped
        rec["deferred_months"] = dict(sorted(deferred.items()))
        self.ensure_deferred_expense(data, rec, month, target_month)
        self.save_payload(data)

    def month_start_date_text(self, month: str) -> str:
        year_text, month_text = month.split("-")
        return f"01-{month_text}-{year_text}"

    def month_end_date_text(self, month: str) -> str:
        year, month_num = [int(part) for part in month.split("-")]
        return date_to_text(clamped_date(year, month_num, 28))

    def remove_recurring_expenses_from_month(
        self,
        data: dict[str, Any],
        recurring_id: str,
        month: str,
        include_future: bool,
    ) -> None:
        data["expenses"] = [
            expense
            for expense in data["expenses"]
            if not (
                expense.get("recurring_plan_id") == recurring_id
                and (
                    str(expense.get("recurring_month")) >= month
                    if include_future
                    else expense.get("recurring_month") == month
                )
            )
        ]

    def ensure_deferred_expense(
        self,
        data: dict[str, Any],
        rec: dict[str, Any],
        source_month: str,
        target_month: str,
    ) -> bool:
        year_text, month_text = target_month.split("-")
        plan_id = str(rec.get("id", ""))
        amount = recurring_amount_for_month(rec, source_month)
        entry = {
            "account_id": rec["account_id"],
            "description": rec["description"],
            "amount": float(amount),
            "date": f"01-{month_text}-{year_text}",
            "source": "deferred",
            "recurring_plan_id": plan_id,
            "recurring_month": source_month,
        }
        existing = next(
            (
                expense
                for expense in data["expenses"]
                if expense.get("recurring_plan_id") == plan_id and expense.get("recurring_month") == source_month
            ),
            None,
        )
        if existing:
            changed = any(existing.get(key) != value for key, value in entry.items())
            existing.update(entry)
            return changed
        data["expenses"].append({"id": str(uuid.uuid4()), **entry})
        return True

    def move_month_expense_to_recurring(
        self,
        data: dict[str, Any],
        old_rec: dict[str, Any],
        new_rec: dict[str, Any],
        month: str,
    ) -> None:
        for expense in data["expenses"]:
            if expense.get("recurring_plan_id") != old_rec.get("id") or expense.get("recurring_month") != month:
                continue
            year_text, month_text = month.split("-")
            expense.update(
                {
                    "account_id": new_rec["account_id"],
                    "description": new_rec["description"],
                    "amount": recurring_amount_for_month(new_rec, month),
                    "date": f"{safe_recurring_day(new_rec):02d}-{month_text}-{year_text}",
                    "source": "installment" if new_rec.get("kind") == "installment" else "recurring",
                    "recurring_plan_id": new_rec["id"],
                    "recurring_month": month,
                }
            )
            break

    def update_recurring_expenses_from_month(self, data: dict[str, Any], rec: dict[str, Any], month: str) -> None:
        for expense in list(data["expenses"]):
            if expense.get("recurring_plan_id") != rec.get("id") or str(expense.get("recurring_month")) < month:
                continue
            if not self.generated_expense_is_expected(data, expense):
                data["expenses"].remove(expense)
                continue
            expense_month = str(expense.get("recurring_month"))
            if expense.get("source") == "deferred":
                expense.update(
                    {
                        "account_id": rec["account_id"],
                        "description": rec["description"],
                        "amount": recurring_amount_for_month(rec, expense_month),
                        "source": "deferred",
                    }
                )
                continue
            year_text, month_text = expense_month.split("-")
            expense.update(
                {
                    "account_id": rec["account_id"],
                    "description": rec["description"],
                    "amount": recurring_amount_for_month(rec, expense_month),
                    "date": f"{safe_recurring_day(rec):02d}-{month_text}-{year_text}",
                    "source": "installment" if rec.get("kind") == "installment" else "recurring",
                }
            )

    def validate_recurring_payload(self, payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id", "")).strip()
        if not data["accounts"]:
            raise FinanceError("Bitte zuerst ein Konto anlegen.")
        if account_id not in [item["id"] for item in data["accounts"]]:
            raise FinanceError("Bitte ein Konto auswählen.")
        description = str(payload.get("description", "")).strip()
        if not description:
            raise FinanceError("Beschreibung fehlt.")
        try:
            amount = parse_float(payload.get("amount", ""))
            day = int(payload.get("day", 1))
        except (TypeError, ValueError):
            raise FinanceError("Betrag oder Tag ungültig.") from None
        if amount <= 0 or not (1 <= day <= 28):
            raise FinanceError("Betrag oder Tag ungültig.")

        kind = str(payload.get("kind", "standard"))
        if kind not in ("standard", "installment"):
            kind = "standard"
        frequency = normalize_recurring_frequency(payload.get("frequency", "monthly"))
        start_date = date_to_text(parse_input_date(str(payload.get("start_date") or iso_today())))
        end_date = ""
        final_amount = None
        if kind == "installment":
            end = parse_input_date(str(payload.get("end_date") or start_date))
            start = parse_input_date(start_date)
            if end < start:
                raise FinanceError("Enddatum muss nach dem Startdatum liegen.")
            end_date = date_to_text(end)
            final_raw = payload.get("final_amount")
            if final_raw not in (None, ""):
                try:
                    final_amount = parse_float(final_raw)
                except ValueError:
                    raise FinanceError("Abschlagssumme ist ungültig.") from None
                if final_amount <= 0:
                    raise FinanceError("Abschlagssumme ist ungültig.")

        manual_transfer = self.validate_manual_transfer_payload(payload)
        return {
            "kind": kind,
            "account_id": account_id,
            "description": description,
            "amount": amount,
            "day": day,
            "frequency": "monthly" if kind == "installment" else frequency,
            "start_date": start_date,
            "end_date": end_date,
            "final_amount": final_amount,
            "manual_transfer": manual_transfer,
            "checked_months": self.clean_month_list(payload.get("checked_months")),
        }

    def validate_manual_transfer_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = parse_bool(payload.get("manual_transfer_enabled"), False)
        transfer_type = str(payload.get("manual_transfer_type") or "private").strip().lower()
        if transfer_type not in ("private", "company"):
            transfer_type = "private"
        details = {
            "enabled": enabled,
            "type": transfer_type,
            "first_name": str(payload.get("manual_transfer_first_name") or "").strip(),
            "last_name": str(payload.get("manual_transfer_last_name") or "").strip(),
            "company_name": str(payload.get("manual_transfer_company_name") or "").strip(),
            "iban": str(payload.get("manual_transfer_iban") or "").strip().upper().replace(" ", ""),
            "bic": str(payload.get("manual_transfer_bic") or "").strip().upper().replace(" ", ""),
            "purpose": str(payload.get("manual_transfer_purpose") or "").strip(),
        }
        if not enabled:
            return {**details, "enabled": False}
        if transfer_type == "private" and (not details["first_name"] or not details["last_name"]):
            raise FinanceError("Bitte Name und Nachname des Empfängers eintragen.")
        if transfer_type == "company" and not details["company_name"]:
            raise FinanceError("Bitte den Namen des Unternehmens eintragen.")
        if not details["iban"]:
            raise FinanceError("Bitte die IBAN eintragen.")
        if not details["purpose"]:
            raise FinanceError("Bitte den Verwendungszweck eintragen.")
        return details

    def set_recurring_checked(self, recurring_id: str, month: str, checked: bool) -> None:
        data = self.load_payload()
        month = parse_month_text(month)
        self.require_open_month(month, data)
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            raise FinanceError("Dauerzahlung nicht gefunden.")
        is_due = is_recurring_due_in_month({**rec, "deferred_months": {}}, month, self.visible_month(data))
        is_deferred = month in self.clean_deferred_months(rec.get("deferred_months"))
        if not is_due and not is_deferred:
            raise FinanceError("Diese Zahlung ist im Monat nicht fällig.")
        months = self.clean_month_list(rec.get("checked_months"))
        if checked and month not in months:
            months.append(month)
        if not checked and month in months:
            months.remove(month)
        rec["checked_months"] = sorted(months)
        self.save_payload(data)

    def save_settings(self, payload: dict[str, Any]) -> None:
        data = self.load_payload()
        if "currency" in payload:
            data["settings"]["currency"] = str(payload.get("currency") or "EUR").strip().upper()
        if "theme" in payload:
            data["settings"]["theme"] = self.normalize_theme_id(payload.get("theme"))
        for key in ("autostart_enabled", "autostart_start_hidden", "auto_update_check"):
            if key in payload:
                data["settings"][key] = parse_bool(payload.get(key), False)
        if not data["settings"]["autostart_enabled"]:
            data["settings"]["autostart_start_hidden"] = False
        if "reminder_interval_minutes" in payload:
            data["settings"]["reminder_interval_minutes"] = self.clamp_int(payload.get("reminder_interval_minutes"), 1, 240, 15)
        if "update_check_interval_hours" in payload:
            data["settings"]["update_check_interval_hours"] = self.clamp_int(payload.get("update_check_interval_hours"), 1, 168, 6)
        self.save_payload(data)
        self.ensure_autostart_configuration()

    def set_visible_month(self, value: str) -> None:
        data = self.load_payload()
        data["settings"]["visible_month"] = parse_month_text(value)
        self.apply_recurring_for_visible_and_current(data, force=True)
        self.save_payload(data)

    def close_visible_month(self) -> None:
        data = self.load_payload()
        month = self.visible_month(data)
        closed = self.clean_month_list(data["meta"].get("closed_months"))
        if month not in closed:
            closed.append(month)
        data["meta"]["closed_months"] = sorted(closed)
        self.save_payload(data)

    def reopen_month(self, month: str) -> None:
        data = self.load_payload()
        parsed = parse_month_text(month)
        data["meta"]["closed_months"] = [item for item in self.clean_month_list(data["meta"].get("closed_months")) if item != parsed]
        self.save_payload(data)

    def delete_closed_month(self, month: str) -> None:
        data = self.load_payload()
        parsed = parse_month_text(month)
        closed = self.clean_month_list(data["meta"].get("closed_months"))
        if parsed not in closed:
            raise FinanceError("Geschlossener Monat nicht gefunden.")
        data["meta"]["closed_months"] = [item for item in closed if item != parsed]
        self.save_payload(data)

    def available_months(self, data: dict[str, Any]) -> list[str]:
        months = {month_key(date.today()), self.visible_month(data)}
        months.update(self.clean_month_list(data["meta"].get("closed_months")))
        months.update(self.clean_month_list(data["meta"].get("recurring_applied_months")))
        for item in [*data["incomes"], *data["expenses"]]:
            month = month_from_date_text(str(item.get("date", "")))
            if month:
                months.add(month)
        return sorted(months)

    def add_income_source(self, name: str) -> None:
        data = self.load_payload()
        text = str(name).strip()
        if not text:
            raise FinanceError("Name der Einnahmequelle fehlt.")
        sources = self.clean_income_sources(data["settings"].get("income_sources"))
        if text.lower() in [item.lower() for item in sources]:
            raise FinanceError("Einnahmequelle existiert bereits.")
        sources.append(text)
        data["settings"]["income_sources"] = sources
        self.save_payload(data)

    def rename_income_source(self, old_name: str, new_name: str) -> None:
        data = self.load_payload()
        old_text = str(old_name).strip()
        new_text = str(new_name).strip()
        if not new_text:
            raise FinanceError("Neuer Name fehlt.")
        sources = self.clean_income_sources(data["settings"].get("income_sources"))
        if old_text.lower() != new_text.lower() and new_text.lower() in [item.lower() for item in sources]:
            raise FinanceError("Einnahmequelle existiert bereits.")
        changed = False
        for idx, source in enumerate(sources):
            if source.lower() == old_text.lower():
                sources[idx] = new_text
                changed = True
                break
        if not changed:
            raise FinanceError("Einnahmequelle nicht gefunden.")
        for income in data["incomes"]:
            if str(income.get("type", "")).strip().lower() == old_text.lower():
                income["type"] = new_text
        data["settings"]["income_sources"] = sources
        self.save_payload(data)

    def delete_income_source(self, name: str) -> None:
        data = self.load_payload()
        text = str(name).strip()
        sources = self.clean_income_sources(data["settings"].get("income_sources"))
        remaining = [source for source in sources if source.lower() != text.lower()]
        if len(remaining) == len(sources):
            raise FinanceError("Einnahmequelle nicht gefunden.")
        data["settings"]["income_sources"] = remaining
        self.save_payload(data)

    def apply_recurring_for_visible_and_current(self, data: dict[str, Any], force: bool = False) -> None:
        target_months = {month_key(date.today()), self.visible_month(data)}
        changed = False
        for target_month in target_months:
            if self.month_is_closed(target_month, data):
                continue
            changed = self.remove_stale_generated_expenses_for_month(data, target_month) or changed
            year_text, month_text = target_month.split("-")
            for rec in data["recurring_payments"]:
                if is_recurring_due_in_month(rec, target_month, self.visible_month(data)):
                    amount = recurring_amount_for_month(rec, target_month)
                    recurring_date = f"{safe_recurring_day(rec):02d}-{month_text}-{year_text}"
                    plan_id = str(rec.get("id", ""))
                    duplicate = any(
                        (expense.get("recurring_plan_id") == plan_id and expense.get("recurring_month") == target_month)
                        or (
                            expense.get("source") in ("recurring", "installment")
                            and expense.get("account_id") == rec.get("account_id")
                            and expense.get("description") == rec.get("description")
                            and float(expense.get("amount", 0.0)) == float(amount)
                            and expense.get("date") == recurring_date
                        )
                        for expense in data["expenses"]
                    )
                    if not duplicate:
                        data["expenses"].append(
                            {
                                "id": str(uuid.uuid4()),
                                "account_id": rec["account_id"],
                                "description": rec["description"],
                                "amount": float(amount),
                                "date": recurring_date,
                                "source": "installment" if rec.get("kind") == "installment" else "recurring",
                                "recurring_plan_id": plan_id,
                                "recurring_month": target_month,
                            }
                        )
                        changed = True
                for source_month, deferred_target in self.clean_deferred_months(rec.get("deferred_months")).items():
                    if deferred_target == target_month and source_month not in rec.get("checked_months", []):
                        changed = self.ensure_deferred_expense(data, rec, source_month, target_month) or changed
        applied = self.clean_month_list(data["meta"].get("recurring_applied_months"))
        for month in target_months:
            if month not in applied:
                applied.append(month)
        data["meta"]["recurring_applied_months"] = sorted(applied)[-36:]
        if changed or force:
            self.save_payload(data)

    def generated_expense_is_expected(self, data: dict[str, Any], expense: dict[str, Any]) -> bool:
        if expense.get("source") not in ("recurring", "installment", "deferred"):
            return True
        plan_id = str(expense.get("recurring_plan_id") or "")
        source_month = str(expense.get("recurring_month") or "")
        if not plan_id or not source_month:
            return True
        rec = next((item for item in data["recurring_payments"] if item["id"] == plan_id), None)
        if rec is None:
            return True
        expense_month = month_from_date_text(str(expense.get("date", "")))
        if not expense_month:
            return True
        deferred_target = self.clean_deferred_months(rec.get("deferred_months")).get(source_month)
        if expense.get("source") == "deferred":
            return deferred_target == expense_month
        if deferred_target:
            return False
        return is_recurring_due_in_month(rec, source_month, self.visible_month(data)) and expense_month == source_month

    def remove_stale_generated_expenses_for_month(self, data: dict[str, Any], month: str) -> bool:
        before = len(data["expenses"])
        data["expenses"] = [
            expense for expense in data["expenses"]
            if month_from_date_text(str(expense.get("date", ""))) != month or self.generated_expense_is_expected(data, expense)
        ]
        return len(data["expenses"]) != before

    def open_amounts_per_account(self, month: str, data: dict[str, Any]) -> dict[str, float]:
        account_ids = [account["id"] for account in data["accounts"]]
        open_amounts = {account_id: 0.0 for account_id in account_ids}
        if self.month_is_closed(month, data):
            return open_amounts
        expenses_by_plan_month = {
            (str(expense.get("recurring_plan_id")), str(expense.get("recurring_month"))): expense
            for expense in data["expenses"]
            if expense.get("recurring_plan_id") and expense.get("recurring_month")
        }
        for rec in data["recurring_payments"]:
            if not is_recurring_due_in_month(rec, month, self.visible_month(data)):
                for source_month, deferred_target in self.clean_deferred_months(rec.get("deferred_months")).items():
                    if deferred_target == month and source_month not in rec.get("checked_months", []):
                        account_id = str(rec.get("account_id", ""))
                        expense = expenses_by_plan_month.get((str(rec.get("id", "")), source_month))
                        amount = float(expense.get("amount", 0.0)) if expense else recurring_amount_for_month(rec, source_month)
                        open_amounts[account_id] = open_amounts.get(account_id, 0.0) + amount
                continue
            if month not in rec.get("checked_months", []):
                account_id = str(rec.get("account_id", ""))
                expense = expenses_by_plan_month.get((str(rec.get("id", "")), month))
                amount = float(expense.get("amount", 0.0)) if expense else recurring_amount_for_month(rec, month)
                open_amounts[account_id] = open_amounts.get(account_id, 0.0) + amount
            for source_month, deferred_target in self.clean_deferred_months(rec.get("deferred_months")).items():
                if deferred_target == month and source_month not in rec.get("checked_months", []):
                    account_id = str(rec.get("account_id", ""))
                    expense = expenses_by_plan_month.get((str(rec.get("id", "")), source_month))
                    amount = float(expense.get("amount", 0.0)) if expense else recurring_amount_for_month(rec, source_month)
                    open_amounts[account_id] = open_amounts.get(account_id, 0.0) + amount
        return open_amounts

    def next_due_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        today = date.today()
        current_month = month_key(today)
        names = self.account_name_map(data)
        if self.month_is_closed(current_month, data):
            return rows
        expenses_by_plan = {
            (str(expense.get("recurring_plan_id")), str(expense.get("recurring_month"))): expense
            for expense in data["expenses"]
            if expense.get("recurring_plan_id") and expense.get("recurring_month")
        }
        for rec in data["recurring_payments"]:
            if not is_recurring_due_in_month(rec, current_month, self.visible_month(data)):
                for source_month, target_month in self.clean_deferred_months(rec.get("deferred_months")).items():
                    if target_month != current_month or source_month in rec.get("checked_months", []):
                        continue
                    year, month = [int(part) for part in target_month.split("-")]
                    due = date(year, month, 1)
                    if due < today:
                        continue
                    rows.append(
                        {
                            "account": names.get(rec["account_id"], "-"),
                            "account_id": rec["account_id"],
                            "description": f"{rec['description']} (verschoben)",
                            "due": date_to_text(due),
                            "due_month": source_month,
                            "amount": float(
                                expenses_by_plan.get((str(rec.get("id", "")), source_month), {}).get(
                                    "amount",
                                    recurring_amount_for_month(rec, source_month),
                                )
                            ),
                        }
                    )
                continue
            if current_month not in rec.get("checked_months", []):
                year, month = [int(part) for part in current_month.split("-")]
                due = clamped_date(year, month, safe_recurring_day(rec))
                if due >= today:
                    rows.append(
                        {
                            "account": names.get(rec["account_id"], "-"),
                            "account_id": rec["account_id"],
                            "description": rec["description"],
                            "due": date_to_text(due),
                            "due_month": current_month,
                            "amount": float(
                                expenses_by_plan.get((str(rec.get("id", "")), current_month), {}).get(
                                    "amount",
                                    recurring_amount_for_month(rec, current_month),
                                )
                            ),
                        }
                    )
            for source_month, target_month in self.clean_deferred_months(rec.get("deferred_months")).items():
                if target_month != current_month or source_month in rec.get("checked_months", []):
                    continue
                year, month = [int(part) for part in target_month.split("-")]
                due = date(year, month, 1)
                if due < today:
                    continue
                rows.append(
                    {
                        "account": names.get(rec["account_id"], "-"),
                        "account_id": rec["account_id"],
                        "description": f"{rec['description']} (verschoben)",
                        "due": date_to_text(due),
                        "due_month": source_month,
                        "amount": float(
                            expenses_by_plan.get((str(rec.get("id", "")), source_month), {}).get(
                                "amount",
                                recurring_amount_for_month(rec, source_month),
                            )
                        ),
                    }
                )
        rows.sort(key=lambda item: (item["account"], item["due"], item["description"]))
        return rows

    def collect_overdue_items(self, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = data or self.data()
        today = date.today()
        current_month = month_key(today)
        names = self.account_name_map(payload)
        currency = str(payload["settings"].get("currency", "EUR"))
        expenses_by_plan_month = {
            (str(expense.get("recurring_plan_id")), str(expense.get("recurring_month"))): expense
            for expense in payload["expenses"]
            if expense.get("recurring_plan_id") and expense.get("recurring_month")
        }
        items: list[dict[str, Any]] = []
        for rec in payload["recurring_payments"]:
            for source_month, target_month in self.clean_deferred_months(rec.get("deferred_months")).items():
                if source_month in rec.get("checked_months", []):
                    continue
                if self.month_is_closed(source_month, payload) or self.month_is_closed(target_month, payload):
                    continue
                year_text, month_text = target_month.split("-")
                due_date = date(int(year_text), int(month_text), 1)
                if due_date >= today:
                    continue
                amount = float(
                    expenses_by_plan_month.get((str(rec.get("id", "")), source_month), {}).get(
                        "amount",
                        recurring_amount_for_month(rec, source_month),
                    )
                )
                items.append(
                    {
                        "key": f"{rec.get('id','')}:{source_month}",
                        "recurring_id": str(rec.get("id", "")),
                        "account": names.get(rec["account_id"], "-"),
                        "account_id": rec["account_id"],
                        "description": f"{rec['description']} (verschoben)",
                        "month": source_month,
                        "month_label": format_month_label(source_month),
                        "due_date": date_to_text(due_date),
                        "amount": amount,
                        "amount_label": format_money(amount, currency),
                    }
                )
            for due_month in self.iter_due_months_until_today(rec, current_month, payload):
                if self.month_is_closed(due_month, payload):
                    continue
                if due_month in rec.get("checked_months", []):
                    continue
                year_text, month_text = due_month.split("-")
                due_date = clamped_date(int(year_text), int(month_text), safe_recurring_day(rec))
                if due_date >= today:
                    continue
                amount = float(
                    expenses_by_plan_month.get((str(rec.get("id", "")), due_month), {}).get(
                        "amount",
                        recurring_amount_for_month(rec, due_month),
                    )
                )
                items.append(
                    {
                        "key": f"{rec.get('id','')}:{due_month}",
                        "recurring_id": str(rec.get("id", "")),
                        "account": names.get(rec["account_id"], "-"),
                        "account_id": rec["account_id"],
                        "description": rec["description"],
                        "month": due_month,
                        "month_label": format_month_label(due_month),
                        "due_date": date_to_text(due_date),
                        "amount": amount,
                        "amount_label": format_money(amount, currency),
                    }
                )
        items.sort(key=lambda item: (item["due_date"], item["account"], item["description"]))
        return items

    def iter_due_months_until_today(self, recurring: dict[str, Any], current_month: str, data: dict[str, Any]) -> list[str]:
        start = recurring_start_month(recurring, self.visible_month(data))
        if start > current_month:
            return []
        months: list[str] = []
        probe = start
        for _ in range(240):
            if probe > current_month:
                break
            if is_recurring_due_in_month(recurring, probe, self.visible_month(data)):
                months.append(probe)
            probe = month_shift(probe, 1)
        return months

    def build_state(self, analysis_filter_account: str | None = None, selected_account_id: str | None = None) -> dict[str, Any]:
        data = self.data()
        month = self.visible_month(data)
        currency = str(data["settings"]["currency"])
        names = self.account_name_map(data)
        colors = self.account_color_map(data)
        incomes = self.list_month_incomes(month, data)
        expenses = self.list_month_expenses(month, data)
        income_sum = sum(float(item.get("amount", 0.0)) for item in incomes)
        expense_sum = sum(float(item.get("amount", 0.0)) for item in expenses)
        open_amounts = self.open_amounts_per_account(month, data)
        selected = selected_account_id if selected_account_id == "all" or selected_account_id in names else "all"
        filtered_expenses = expenses
        if analysis_filter_account:
            filtered_expenses = [item for item in expenses if item.get("account_id") == analysis_filter_account]
        categories: dict[str, float] = {}
        for expense in filtered_expenses:
            category = str(expense.get("description", "-")).strip() or "-"
            categories[category] = categories.get(category, 0.0) + float(expense.get("amount", 0.0))
        expenses_by_plan_month = {
            (str(expense.get("recurring_plan_id")), str(expense.get("recurring_month"))): expense
            for expense in expenses
            if expense.get("recurring_plan_id") and expense.get("recurring_month")
        }
        selected_recurring: list[dict[str, Any]] = []
        for item in data["recurring_payments"]:
            if selected != "all" and item.get("account_id") != selected:
                continue
            plan_id = str(item.get("id", ""))
            if is_recurring_due_in_month(item, month, self.visible_month(data)):
                expense = expenses_by_plan_month.get((plan_id, month), {})
                current_amount = float(expense.get("amount", recurring_amount_for_month(item, month)))
                selected_recurring.append(
                    {
                        **item,
                        "status_month": month,
                        "is_deferred": False,
                        "current_expense_id": str(expense.get("id", "")),
                        "current_amount": current_amount,
                        "current_amount_label": format_money(current_amount, currency),
                    }
                )
            for source_month, target_month in self.clean_deferred_months(item.get("deferred_months")).items():
                if target_month != month:
                    continue
                expense = expenses_by_plan_month.get((plan_id, source_month), {})
                current_amount = float(expense.get("amount", recurring_amount_for_month(item, source_month)))
                selected_recurring.append(
                    {
                        **item,
                        "status_month": source_month,
                        "is_deferred": True,
                        "deferred_target_month": target_month,
                        "current_expense_id": str(expense.get("id", "")),
                        "current_amount": current_amount,
                        "current_amount_label": format_money(current_amount, currency),
                    }
                )

        return {
            "version": APP_VERSION,
            "db_path": str(self.db_path),
            "settings": data["settings"],
            "meta": data["meta"],
            "accounts": data["accounts"],
            "account_names": names,
            "account_colors": colors,
            "selected_account_id": selected,
            "analysis_filter_account": analysis_filter_account,
            "visible_month": month,
            "visible_month_label": format_month_label(month),
            "is_month_closed": self.month_is_closed(month, data),
            "income_sources": data["settings"]["income_sources"],
            "recurring": data["recurring_payments"],
            "selected_recurring": selected_recurring,
            "incomes": incomes,
            "expenses": expenses,
            "summary": {
                "income": income_sum,
                "expense": expense_sum,
                "remaining": income_sum - expense_sum,
                "open_total": sum(open_amounts.values()),
                "cashflow_label": format_money(income_sum - expense_sum, currency),
                "income_label": format_money(income_sum, currency),
                "expense_label": format_money(expense_sum, currency),
                "remaining_label": format_money(income_sum - expense_sum, currency),
                "open_total_label": format_money(sum(open_amounts.values()), currency),
            },
            "open_amounts": [
                {
                    "account_id": account_id,
                    "account": names.get(account_id, "-"),
                    "amount": amount,
                    "amount_label": format_money(amount, currency),
                }
                for account_id, amount in sorted(open_amounts.items(), key=lambda item: names.get(item[0], ""))
            ],
            "recent_incomes": [
                {**item, "account": names.get(item["account_id"], "-"), "amount_label": format_money(float(item["amount"]), currency)}
                for item in incomes[:10]
            ],
            "next_due": [
                {**item, "amount_label": format_money(float(item["amount"]), currency)}
                for item in self.next_due_rows(data)
            ],
            "categories": [
                {"name": name, "amount": amount, "amount_label": format_money(amount, currency)}
                for name, amount in sorted(categories.items(), key=lambda item: item[1], reverse=True)
            ],
            "closed_months": [
                {"month": month_value, "label": format_month_label(month_value)}
                for month_value in data["meta"].get("closed_months", [])
            ],
            "available_months": [
                {"month": month_value, "label": format_month_label(month_value)}
                for month_value in self.available_months(data)
            ],
            "overdue": self.collect_overdue_items(data),
            "frequency_options": [{"label": label, "value": value} for label, value in RECURRING_FREQUENCY_OPTIONS],
        }

    def ensure_autostart_configuration(self) -> None:
        enabled = parse_bool(self.settings().get("autostart_enabled"), False)
        if os.name == "nt":
            self.configure_windows_autostart(enabled)
        else:
            self.configure_linux_autostart(enabled)

    def autostart_command_parts(self) -> list[str]:
        app_executable = os.environ.get("FINANZ_COCKPIT_APP_EXECUTABLE", "").strip()
        if app_executable:
            return [app_executable, "--autostart"]
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable).resolve()), "--autostart"]
        return [str(Path(sys.executable).resolve()), str(PROJECT_DIR / "app.py"), "--autostart"]

    def configure_linux_autostart(self, enabled: bool) -> None:
        autostart_dir = Path.home() / ".config" / "autostart"
        desktop_file = autostart_dir / "finanz-cockpit.desktop"
        legacy_desktop_file = autostart_dir / "jarvis-buchhaltung.desktop"
        if not enabled:
            for file_path in (desktop_file, legacy_desktop_file):
                if not file_path.exists():
                    continue
                try:
                    file_path.unlink()
                except OSError:
                    pass
            return
        try:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            # The predecessor used its own desktop file. Remove it so the app is not
            # started twice after an update from older releases.
            if legacy_desktop_file.exists():
                try:
                    legacy_desktop_file.unlink()
                except OSError:
                    pass
            command_parts = self.autostart_command_parts()
            exec_line = " ".join(f"\"{part}\"" for part in command_parts)
            desktop_file.write_text(
                "\n".join(
                    [
                        "[Desktop Entry]",
                        "Type=Application",
                        "Name=Finanz Cockpit",
                        "Comment=Startet Erinnerungen für überfällige Zahlungen",
                        f"Exec={exec_line}",
                        "Terminal=false",
                        "X-GNOME-Autostart-enabled=true",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    def configure_windows_autostart(self, enabled: bool) -> None:
        value_name = "Finanz Cockpit"
        legacy_value_names = ("FinanzCockpit",)

        try:
            import winreg
        except ImportError:
            return

        appdata = os.environ.get("APPDATA", "").strip()
        startup_file = None
        legacy_startup_files: list[Path] = []
        if appdata:
            startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup_file = startup_dir / "finanz_cockpit_autostart.bat"
            legacy_startup_files = [
                startup_file,
                startup_dir / "jarvis_buchhaltung_autostart.bat",
            ]

        run_key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

        def remove_startup_files() -> None:
            for file_path in legacy_startup_files:
                if file_path.exists():
                    try:
                        file_path.unlink()
                    except OSError:
                        pass

        def remove_registry_values(key: Any) -> None:
            for name in (value_name, *legacy_value_names):
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass

        if not enabled:
            remove_startup_files()
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key_path, 0, winreg.KEY_SET_VALUE) as key:
                    remove_registry_values(key)
            except OSError:
                pass
            return
        try:
            command_parts = self.autostart_command_parts()
            if not getattr(sys, "frozen", False) and len(command_parts) >= 2:
                python_exec = Path(command_parts[0])
                pythonw_exec = python_exec.with_name("pythonw.exe")
                if pythonw_exec.exists():
                    command_parts[0] = str(pythonw_exec)
            command_line = subprocess.list2cmdline(command_parts)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key_path) as key:
                remove_registry_values(key)
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command_line)
            remove_startup_files()
        except OSError:
            if startup_file is None:
                return
            try:
                startup_file.parent.mkdir(parents=True, exist_ok=True)
                command_line = " ".join(f"\"{part}\"" for part in self.autostart_command_parts())
                startup_file.write_text(f"@echo off\r\nstart \"\" {command_line}\r\n", encoding="utf-8")
            except OSError:
                pass
        except Exception:
            pass

    def check_update(self) -> dict[str, Any]:
        try:
            request = urllib.request.Request(
                GITHUB_LATEST_RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "finanz-cockpit-update-checker"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise FinanceError(f"Update-Prüfung fehlgeschlagen: {exc}") from None

        assets = []
        for asset in payload.get("assets", []) if isinstance(payload.get("assets"), list) else []:
            if not isinstance(asset, dict):
                continue
            assets.append(
                {
                    "name": str(asset.get("name", "")).strip(),
                    "url": str(asset.get("browser_download_url", "")).strip(),
                    "size": int(asset.get("size", 0) or 0),
                }
            )
        latest_tag = str(payload.get("tag_name", "")).strip()
        assets.extend(self.fallback_release_assets(latest_tag, assets))
        selected = self.choose_update_asset(assets)
        return {
            "current": APP_VERSION,
            "latest": latest_tag,
            "name": str(payload.get("name", "")).strip(),
            "published_at": str(payload.get("published_at", "")).strip(),
            "is_newer": bool(latest_tag and is_newer_version(latest_tag, APP_VERSION)),
            "assets": assets,
            "asset": selected,
        }

    def fallback_release_assets(self, latest_tag: str, existing_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tag = str(latest_tag).strip()
        if not tag:
            return []

        known_names = {str(item.get("name", "")).strip().lower() for item in existing_assets}
        version = tag.lstrip("vV")
        candidates: list[dict[str, Any]] = []

        if os.name == "nt":
            for name in (f"finanz-cockpit-{version}-setup.exe", f"finanz-cockpit-{version}-portable.exe"):
                lower_name = name.lower()
                if lower_name in known_names:
                    continue
                url = f"https://raw.githubusercontent.com/JARVIS-ai-code/finanz-cockpit/{tag}/{name}"
                if self.url_is_reachable(url):
                    candidates.append({"name": name, "url": url, "size": 0})
        else:
            name = f"finanz-cockpit_{version}_amd64.deb"
            lower_name = name.lower()
            if lower_name not in known_names:
                url = f"https://raw.githubusercontent.com/JARVIS-ai-code/finanz-cockpit/{tag}/dist/deb/{name}"
                if self.url_is_reachable(url):
                    candidates.append({"name": name, "url": url, "size": 0})

        return candidates

    def url_is_reachable(self, url: str) -> bool:
        try:
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "finanz-cockpit-update-checker"})
            with urllib.request.urlopen(request, timeout=6):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 501):
                return False
        except (urllib.error.URLError, TimeoutError):
            return False

        try:
            request = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0", "User-Agent": "finanz-cockpit-update-checker"})
            with urllib.request.urlopen(request, timeout=6):
                return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            return False

    def current_arch_tokens(self) -> tuple[str, ...]:
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            return ("x64", "amd64", "x86_64", "win64")
        if machine in ("aarch64", "arm64"):
            return ("arm64", "aarch64")
        return (machine,)

    def choose_update_asset(self, assets: list[dict[str, Any]]) -> dict[str, Any] | None:
        valid = [asset for asset in assets if asset.get("name") and asset.get("url")]
        if os.name == "nt":
            arch_tokens = self.current_arch_tokens()
            choices: list[tuple[int, dict[str, Any]]] = []
            for asset in valid:
                name = str(asset["name"]).lower()
                if not (name.endswith(".exe") or name.endswith(".msi")):
                    continue
                if "backend" in name:
                    continue
                score = 10
                if name.endswith(".msi"):
                    score += 20
                if "setup" in name or "installer" in name:
                    score += 30
                if "portable" in name:
                    score -= 10
                if any(token in name for token in arch_tokens):
                    score += 25
                elif any(token in name for token in ("arm64", "aarch64", "x64", "amd64", "x86_64", "win64")):
                    score -= 40
                choices.append((score, asset))
            if choices:
                choices.sort(key=lambda item: item[0], reverse=True)
                return choices[0][1]
            return None
        for suffix in (".deb", ".appimage"):
            for asset in valid:
                if str(asset["name"]).lower().endswith(suffix):
                    return asset
        return None

    def _cleanup_update_jobs_locked(self) -> None:
        finished = [item for item in self._update_jobs.values() if item.get("status") in ("completed", "failed")]
        if len(finished) <= 20:
            return
        finished.sort(key=lambda item: str(item.get("finished_at", "")))
        remove_count = len(finished) - 20
        for item in finished[:remove_count]:
            task_id = str(item.get("id", ""))
            if task_id:
                self._update_jobs.pop(task_id, None)

    def _create_update_task(self, asset: dict[str, Any]) -> dict[str, Any]:
        task_id = uuid.uuid4().hex
        task = {
            "id": task_id,
            "asset_name": str(asset.get("name", "")).strip(),
            "status": "running",
            "phase": "queued",
            "message": "Update wird vorbereitet.",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "progress_percent": 0.0,
            "speed_bps": 0.0,
            "path": "",
            "launched": False,
            "restart_required": False,
            "quit_required": False,
            "error": "",
            "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "finished_at": "",
        }
        with self._update_jobs_lock:
            self._cleanup_update_jobs_locked()
            self._update_jobs[task_id] = task
            self._latest_update_job_id = task_id
        return deepcopy(task)

    def _update_task(self, task_id: str, **changes: Any) -> None:
        with self._update_jobs_lock:
            task = self._update_jobs.get(task_id)
            if not task:
                return
            task.update(changes)

    def get_update_task(self, task_id: str = "") -> dict[str, Any]:
        with self._update_jobs_lock:
            resolved = task_id.strip() or self._latest_update_job_id
            if not resolved or resolved not in self._update_jobs:
                raise FinanceError("Kein laufendes Update gefunden.")
            return deepcopy(self._update_jobs[resolved])

    def start_update_install(self, asset: dict[str, Any]) -> dict[str, Any]:
        url = str(asset.get("url", "")).strip()
        if not url:
            raise FinanceError("Kein Update-Paket ausgewählt.")
        task = self._create_update_task(asset)
        worker = threading.Thread(
            target=self._run_update_task,
            args=(task["id"], asset),
            daemon=True,
            name=f"update-task-{task['id'][:8]}",
        )
        worker.start()
        return task

    def _run_update_task(self, task_id: str, asset: dict[str, Any]) -> None:
        started = time.monotonic()
        last_downloaded = 0
        try:
            self._update_task(task_id, phase="download", message="Update wird heruntergeladen.")

            def on_progress(downloaded: int, total: int) -> None:
                nonlocal last_downloaded
                last_downloaded = downloaded
                elapsed = max(0.001, time.monotonic() - started)
                speed = downloaded / elapsed
                percent = (downloaded * 100.0 / total) if total > 0 else 0.0
                self._update_task(
                    task_id,
                    downloaded_bytes=int(downloaded),
                    total_bytes=int(total),
                    progress_percent=float(min(100.0, max(0.0, percent))) if total > 0 else 0.0,
                    speed_bps=float(speed),
                )

            target_path = self.download_update_file(asset, on_progress)
            self._update_task(task_id, phase="install", message="Installer wird gestartet.", path=str(target_path))
            launch_result = self.launch_update_installer(target_path)
            if not launch_result["launched"]:
                raise FinanceError(launch_result["error"] or "Update-Installation konnte nicht gestartet werden. Bitte Paket manuell installieren.")

            final_total = int(self.get_update_task(task_id).get("total_bytes", 0))
            final_percent = 100.0 if final_total > 0 else 0.0
            restart_required = bool(launch_result["restart_required"])
            quit_required = bool(launch_result["quit_required"])
            self._update_task(
                task_id,
                status="completed",
                phase="completed",
                message=(
                    "Update installiert. Programm wird neu gestartet."
                    if restart_required
                    else "Installer wird gestartet. Programm wird geschlossen."
                    if quit_required
                    else "Installer wurde geöffnet. Bitte Installation abschließen."
                ),
                launched=True,
                restart_required=restart_required,
                quit_required=quit_required,
                downloaded_bytes=last_downloaded,
                progress_percent=final_percent,
            )
        except FinanceError as exc:
            self._update_task(task_id, status="failed", phase="failed", message="Update fehlgeschlagen.", error=str(exc))
        except Exception as exc:
            self._update_task(task_id, status="failed", phase="failed", message="Update fehlgeschlagen.", error=str(exc))
        finally:
            self._update_task(task_id, finished_at=datetime.utcnow().isoformat(timespec="seconds") + "Z")

    def download_update_file(
        self,
        asset: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> Path:
        url = str(asset.get("url", "")).strip()
        name = Path(str(asset.get("name", "")).strip()).name or "update.bin"
        if not url:
            raise FinanceError("Kein Update-Paket ausgewählt.")
        target_dir = DATA_DIR / "updates"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / name
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "finanz-cockpit-updater"}, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                total_raw = response.headers.get("Content-Length", "0").strip()
                try:
                    total = max(0, int(total_raw))
                except ValueError:
                    total = 0
                downloaded = 0
                if progress_callback:
                    progress_callback(downloaded, total)
                with open(target_path, "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
                if progress_callback:
                    progress_callback(downloaded, total)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise FinanceError(f"Update-Download fehlgeschlagen: {exc}") from None
        return target_path

    def download_and_launch_update(self, asset: dict[str, Any]) -> dict[str, Any]:
        target_path = self.download_update_file(asset)
        launch_result = self.launch_update_installer(target_path)
        if not launch_result["launched"]:
            raise FinanceError(launch_result["error"] or "Update-Installation konnte nicht gestartet werden. Bitte Paket manuell installieren.")
        return {"path": str(target_path), **launch_result}

    def launch_update_installer(self, update_path: Path) -> dict[str, Any]:
        def launch_result(launched: bool, *, restart_required: bool = False, quit_required: bool = False, error: str = "") -> dict[str, Any]:
            return {
                "launched": launched,
                "restart_required": restart_required,
                "quit_required": quit_required,
                "error": error,
            }

        name = update_path.name.lower()
        if os.name == "nt":
            try:
                # Let Electron release its locked executable before NSIS starts.
                command = f'timeout /t 2 /nobreak >nul & start "" "{update_path}"'
                flags = (
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
                subprocess.Popen(["cmd.exe", "/d", "/s", "/c", command], creationflags=flags)
                return launch_result(True, quit_required=True)
            except OSError as exc:
                return launch_result(False, error=f"Windows-Installer konnte nicht gestartet werden: {exc}")
        if name.endswith(".deb"):
            apt_cmd = shutil.which("apt") or shutil.which("apt-get")
            errors: list[str] = []
            if shutil.which("pkexec") and apt_cmd:
                try:
                    process_result = subprocess.run(
                        ["pkexec", apt_cmd, "install", "-y", str(update_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if process_result.returncode == 0:
                        return {"launched": True, "restart_required": True, "quit_required": False, "error": ""}
                    errors.append((process_result.stderr or process_result.stdout or "apt-Installation fehlgeschlagen.").strip())
                except OSError as exc:
                    errors.append(str(exc))
            if shutil.which("pkexec"):
                try:
                    process_result = subprocess.run(
                        ["pkexec", "dpkg", "-i", str(update_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if process_result.returncode == 0:
                        return {"launched": True, "restart_required": True, "quit_required": False, "error": ""}
                    errors.append((process_result.stderr or process_result.stdout or "dpkg-Installation fehlgeschlagen.").strip())
                except OSError as exc:
                    errors.append(str(exc))
            if shutil.which("xdg-open"):
                try:
                    subprocess.Popen(["xdg-open", str(update_path)])
                    # A software center still needs user confirmation, so the current app must stay open.
                    return launch_result(True)
                except OSError as exc:
                    errors.append(str(exc))
            detail = " ".join(item for item in errors if item)
            return launch_result(False, error=f"Linux-Paketinstallation konnte nicht gestartet werden. {detail}".strip())
        if name.endswith(".appimage"):
            try:
                update_path.chmod(update_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                subprocess.Popen([str(update_path)])
                return launch_result(True)
            except OSError as exc:
                return launch_result(False, error=f"AppImage konnte nicht gestartet werden: {exc}")
        try:
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", str(update_path)])
                return launch_result(True)
        except OSError as exc:
            return launch_result(False, error=f"Installer konnte nicht geöffnet werden: {exc}")
        return launch_result(False, error="Kein Programm zum Öffnen des Update-Pakets gefunden.")

    def open_db_folder(self) -> bool:
        folder = self.db_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            try:
                os.startfile(str(folder))  # type: ignore[attr-defined]
                return True
            except OSError as exc:
                raise FinanceError(f"DB-Ordner konnte nicht geöffnet werden: {exc}") from None

        opener_commands = [
            ["xdg-open", str(folder)],
            ["gio", "open", str(folder)],
            ["kioclient5", "exec", str(folder)],
            ["kioclient", "exec", str(folder)],
        ]
        for command in opener_commands:
            if not shutil.which(command[0]):
                continue
            try:
                subprocess.Popen(command)
                return True
            except OSError:
                continue
        raise FinanceError("DB-Ordner konnte nicht geöffnet werden (kein System-Öffner gefunden).")
