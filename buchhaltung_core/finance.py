from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

APP_NAME = "JarvisBuchhaltung"
PROJECT_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE_PATH = PROJECT_DIR / "version.json"
LEGACY_DATA_PATH = PROJECT_DIR / "data.json"
LEGACY_DB_PATH = PROJECT_DIR / "buchhaltung.db"
APP_ICON_NAME = "jarvis-buchhaltung"
GITHUB_REPO_URL = "https://github.com/JARVIS-ai-code/buchhaltung"
GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/JARVIS-ai-code/buchhaltung/releases/latest"

DEFAULT_INCOME_SOURCES = ["Lohn", "Nebentätigkeit", "Spesen"]
RECURRING_FREQUENCY_OPTIONS = [
    ("Monatlich", "monthly"),
    ("Quartalszahlung", "quarterly"),
    ("Jährlich", "yearly"),
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

DEFAULT_DATA = {
    "settings": {
        "currency": "EUR",
        "income_sources": list(DEFAULT_INCOME_SOURCES),
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


class FinanceError(ValueError):
    pass


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
    candidates: list[Path] = []

    env_version_file = os.environ.get("JARVIS_VERSION_FILE", "").strip()
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
    return f"{month_num:02d}-{year}"


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
    if freq == "yearly":
        return 12
    return 1


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

    kind = str(recurring.get("kind", "standard"))
    if kind == "installment":
        end = recurring_end_month(recurring)
        if end and month_distance(target_month, end) < 0:
            return False
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
        self.ensure_data_layout()
        self.initialize_db()
        if self.db_is_empty():
            self.import_legacy_json_if_available()
        self.ensure_defaults()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_data_layout(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists() and LEGACY_DB_PATH.exists() and LEGACY_DB_PATH.resolve() != self.db_path.resolve():
            try:
                self.db_path.write_bytes(LEGACY_DB_PATH.read_bytes())
            except OSError:
                pass

    def initialize_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def db_is_empty(self) -> bool:
        with self.connect() as conn:
            for table in ("settings", "meta", "accounts", "recurring_payments", "expenses", "incomes"):
                if int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) > 0:
                    return False
        return True

    def import_legacy_json_if_available(self) -> None:
        source = LEGACY_DATA_PATH if LEGACY_DATA_PATH.exists() else DATA_PATH
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
                        data["settings"][key] = list(DEFAULT_INCOME_SOURCES)
                elif key in ("autostart_enabled", "autostart_open_window", "auto_update_check"):
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

            data["accounts"] = [dict(row) for row in conn.execute("SELECT id, name FROM accounts ORDER BY name COLLATE NOCASE")]
            data["recurring_payments"] = [self.recurring_from_row(row) for row in conn.execute(
                """
                SELECT id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months
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
                conn.execute("INSERT INTO accounts(id, name) VALUES (?, ?)", (account["id"], account["name"]))
            for rec in data["recurring_payments"]:
                conn.execute(
                    """
                    INSERT INTO recurring_payments(
                        id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(rec.get("checked_months", []), ensure_ascii=False),
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
        for key, default in (("autostart_enabled", False), ("autostart_open_window", False), ("auto_update_check", True)):
            data["settings"][key] = parse_bool(data["settings"].get(key), default)
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

    def recurring_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            checked = json.loads(row["checked_months"] or "[]")
        except json.JSONDecodeError:
            checked = []
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
            "checked_months": checked if isinstance(checked, list) else [],
        }

    def clean_income_sources(self, sources: Any) -> list[str]:
        cleaned: list[str] = []
        items = sources if isinstance(sources, list) else DEFAULT_INCOME_SOURCES
        for source in items:
            text = str(source).strip()
            if text and text.lower() not in [item.lower() for item in cleaned]:
                cleaned.append(text)
        if not cleaned:
            cleaned = list(DEFAULT_INCOME_SOURCES)
        if "spesen" not in [item.lower() for item in cleaned]:
            cleaned.append("Spesen")
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

    def clean_accounts(self, accounts: Any) -> list[dict[str, str]]:
        cleaned: list[dict[str, str]] = []
        seen: set[str] = set()
        for account in accounts if isinstance(accounts, list) else []:
            if not isinstance(account, dict):
                continue
            name = str(account.get("name", "")).strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            cleaned.append({"id": str(account.get("id") or uuid.uuid4()), "name": name})
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
            frequency = str(item.get("frequency", "monthly"))
            if frequency not in ("monthly", "quarterly", "yearly"):
                frequency = "monthly"
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
                    "end_date": end_date if kind == "installment" else "",
                    "final_amount": final_amount if kind == "installment" else None,
                    "checked_months": self.clean_month_list(item.get("checked_months")),
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
                base["type"] = str(item.get("type", "")).strip() or DEFAULT_INCOME_SOURCES[0]
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

    def add_account(self, name: str) -> None:
        data = self.load_payload()
        text = str(name).strip()
        if not text:
            raise FinanceError("Kontoname fehlt.")
        if text.lower() in [account["name"].lower() for account in data["accounts"]]:
            raise FinanceError("Dieses Konto existiert bereits.")
        data["accounts"].append({"id": str(uuid.uuid4()), "name": text})
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
        income_type = str(payload.get("type", "")).strip() or DEFAULT_INCOME_SOURCES[0]
        if not description:
            raise FinanceError("Beschreibung fehlt.")
        try:
            amount = parse_float(payload.get("amount", ""))
            parsed_date = parse_input_date(str(payload.get("date", "")))
        except (FinanceError, ValueError):
            raise FinanceError("Bitte gültige Werte für Betrag und Datum eingeben.") from None
        if amount <= 0:
            raise FinanceError("Der Betrag muss größer als 0 sein.")
        if account_id not in [item["id"] for item in self.load_payload()["accounts"]]:
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
        if account_id not in [item["id"] for item in self.load_payload()["accounts"]]:
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
        checked_months = rec.get("checked_months", [])
        rec.update(self.validate_recurring_payload(payload, data))
        rec["checked_months"] = checked_months
        self.apply_recurring_for_visible_and_current(data, force=True)
        self.save_payload(data)

    def delete_recurring(self, recurring_id: str) -> None:
        data = self.load_payload()
        data["recurring_payments"] = [item for item in data["recurring_payments"] if item["id"] != recurring_id]
        self.save_payload(data)

    def validate_recurring_payload(self, payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        account_id = str(payload.get("account_id", "")).strip()
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
        frequency = str(payload.get("frequency", "monthly"))
        if frequency not in ("monthly", "quarterly", "yearly"):
            frequency = "monthly"
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
            "checked_months": self.clean_month_list(payload.get("checked_months")),
        }

    def set_recurring_checked(self, recurring_id: str, month: str, checked: bool) -> None:
        data = self.load_payload()
        month = parse_month_text(month)
        self.require_open_month(month, data)
        rec = next((item for item in data["recurring_payments"] if item["id"] == recurring_id), None)
        if rec is None:
            raise FinanceError("Dauerzahlung nicht gefunden.")
        if not is_recurring_due_in_month(rec, month, self.visible_month(data)):
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
        for key in ("autostart_enabled", "autostart_open_window", "auto_update_check"):
            if key in payload:
                data["settings"][key] = parse_bool(payload.get(key), False)
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
        if not remaining:
            raise FinanceError("Mindestens eine Einnahmequelle muss bleiben.")
        data["settings"]["income_sources"] = remaining
        self.save_payload(data)

    def apply_recurring_for_visible_and_current(self, data: dict[str, Any], force: bool = False) -> None:
        target_months = {month_key(date.today()), self.visible_month(data)}
        changed = False
        for target_month in target_months:
            if self.month_is_closed(target_month, data):
                continue
            year_text, month_text = target_month.split("-")
            for rec in data["recurring_payments"]:
                if not is_recurring_due_in_month(rec, target_month, self.visible_month(data)):
                    continue
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
                if duplicate:
                    continue
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
        applied = self.clean_month_list(data["meta"].get("recurring_applied_months"))
        for month in target_months:
            if month not in applied:
                applied.append(month)
        data["meta"]["recurring_applied_months"] = sorted(applied)[-36:]
        if changed or force:
            self.save_payload(data)

    def open_amounts_per_account(self, month: str, data: dict[str, Any]) -> dict[str, float]:
        account_ids = [account["id"] for account in data["accounts"]]
        open_amounts = {account_id: 0.0 for account_id in account_ids}
        if self.month_is_closed(month, data):
            return open_amounts
        for rec in data["recurring_payments"]:
            if not is_recurring_due_in_month(rec, month, self.visible_month(data)):
                continue
            checked = month in rec.get("checked_months", [])
            if checked:
                continue
            account_id = str(rec.get("account_id", ""))
            open_amounts[account_id] = open_amounts.get(account_id, 0.0) + recurring_amount_for_month(rec, month)
        return open_amounts

    def next_due_rows(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        today = date.today()
        names = self.account_name_map(data)
        for rec in data["recurring_payments"]:
            probe_month = month_key(today)
            for _ in range(60):
                if is_recurring_due_in_month(rec, probe_month, self.visible_month(data)):
                    checked = probe_month in rec.get("checked_months", [])
                    y, m = [int(part) for part in probe_month.split("-")]
                    due = clamped_date(y, m, safe_recurring_day(rec))
                    if due >= today or not checked:
                        rows.append(
                            {
                                "account": names.get(rec["account_id"], "-"),
                                "account_id": rec["account_id"],
                                "description": rec["description"],
                                "due": date_to_text(due),
                                "due_month": probe_month,
                                "amount": recurring_amount_for_month(rec, probe_month),
                            }
                        )
                        break
                probe_month = month_shift(probe_month, 1)
        rows.sort(key=lambda item: (item["account"], item["due"], item["description"]))
        return rows

    def collect_overdue_items(self, data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        payload = data or self.data()
        today = date.today()
        current_month = month_key(today)
        names = self.account_name_map(payload)
        currency = str(payload["settings"].get("currency", "EUR"))
        items: list[dict[str, Any]] = []
        for rec in payload["recurring_payments"]:
            for due_month in self.iter_due_months_until_today(rec, current_month, payload):
                if self.month_is_closed(due_month, payload):
                    continue
                if due_month in rec.get("checked_months", []):
                    continue
                year_text, month_text = due_month.split("-")
                due_date = clamped_date(int(year_text), int(month_text), safe_recurring_day(rec))
                if due_date >= today:
                    continue
                amount = recurring_amount_for_month(rec, due_month)
                items.append(
                    {
                        "key": f"{rec.get('id','')}:{due_month}",
                        "account": names.get(rec["account_id"], "-"),
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
        if str(recurring.get("kind", "standard")) == "installment":
            end = recurring_end_month(recurring) or current_month
            if end > current_month:
                end = current_month
            months: list[str] = []
            probe = start
            for _ in range(240):
                if probe > end:
                    break
                if is_recurring_due_in_month(recurring, probe, self.visible_month(data)):
                    months.append(probe)
                probe = month_shift(probe, 1)
            return months
        step = frequency_step(str(recurring.get("frequency", "monthly")))
        distance = month_distance(start, current_month)
        return [month_shift(start, offset) for offset in range(0, distance + 1, step)]

    def build_state(self, analysis_filter_account: str | None = None, selected_account_id: str | None = None) -> dict[str, Any]:
        data = self.data()
        month = self.visible_month(data)
        currency = str(data["settings"]["currency"])
        names = self.account_name_map(data)
        incomes = self.list_month_incomes(month, data)
        expenses = self.list_month_expenses(month, data)
        income_sum = sum(float(item.get("amount", 0.0)) for item in incomes)
        expense_sum = sum(float(item.get("amount", 0.0)) for item in expenses)
        open_amounts = self.open_amounts_per_account(month, data)
        selected = selected_account_id if selected_account_id in names else (data["accounts"][0]["id"] if data["accounts"] else None)
        filtered_expenses = expenses
        if analysis_filter_account:
            filtered_expenses = [item for item in expenses if item.get("account_id") == analysis_filter_account]
        categories: dict[str, float] = {}
        for expense in filtered_expenses:
            category = str(expense.get("description", "-")).strip() or "-"
            categories[category] = categories.get(category, 0.0) + float(expense.get("amount", 0.0))

        return {
            "version": APP_VERSION,
            "db_path": str(self.db_path),
            "settings": data["settings"],
            "meta": data["meta"],
            "accounts": data["accounts"],
            "account_names": names,
            "selected_account_id": selected,
            "analysis_filter_account": analysis_filter_account,
            "visible_month": month,
            "visible_month_label": format_month_label(month),
            "is_month_closed": self.month_is_closed(month, data),
            "income_sources": data["settings"]["income_sources"],
            "recurring": data["recurring_payments"],
            "selected_recurring": [item for item in data["recurring_payments"] if item.get("account_id") == selected],
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
        if getattr(sys, "frozen", False):
            return [str(Path(sys.executable).resolve()), "--autostart"]
        return [str(Path(sys.executable).resolve()), str(PROJECT_DIR / "app.py"), "--autostart"]

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
            desktop_file.write_text(
                "\n".join(
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
                + "\n",
                encoding="utf-8",
            )
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
            if not getattr(sys, "frozen", False) and len(command_parts) >= 2:
                python_exec = Path(command_parts[0])
                pythonw_exec = python_exec.with_name("pythonw.exe")
                if pythonw_exec.exists():
                    command_parts[0] = str(pythonw_exec)
            command_line = " ".join(f"\"{part}\"" for part in command_parts)
            startup_file.write_text(f"@echo off\r\nstart \"\" {command_line}\r\n", encoding="utf-8")
        except OSError:
            pass

    def check_update(self) -> dict[str, Any]:
        try:
            request = urllib.request.Request(
                GITHUB_LATEST_RELEASE_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "jarvis-buchhaltung-update-checker"},
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
            for name in (f"jarvis-buchhaltung-{version}-setup.exe", f"jarvis-buchhaltung-{version}-portable.exe"):
                lower_name = name.lower()
                if lower_name in known_names:
                    continue
                url = f"https://raw.githubusercontent.com/JARVIS-ai-code/buchhaltung/{tag}/{name}"
                if self.url_is_reachable(url):
                    candidates.append({"name": name, "url": url, "size": 0})
        else:
            name = f"jarvis-buchhaltung_{version}_amd64.deb"
            lower_name = name.lower()
            if lower_name not in known_names:
                url = f"https://raw.githubusercontent.com/JARVIS-ai-code/buchhaltung/{tag}/dist/deb/{name}"
                if self.url_is_reachable(url):
                    candidates.append({"name": name, "url": url, "size": 0})

        return candidates

    def url_is_reachable(self, url: str) -> bool:
        try:
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "jarvis-buchhaltung-update-checker"})
            with urllib.request.urlopen(request, timeout=6):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code not in (405, 501):
                return False
        except (urllib.error.URLError, TimeoutError):
            return False

        try:
            request = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0", "User-Agent": "jarvis-buchhaltung-update-checker"})
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

    def download_and_launch_update(self, asset: dict[str, Any]) -> dict[str, Any]:
        url = str(asset.get("url", "")).strip()
        name = Path(str(asset.get("name", "")).strip()).name or "update.bin"
        if not url:
            raise FinanceError("Kein Update-Paket ausgewählt.")
        target_dir = DATA_DIR / "updates"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / name
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "jarvis-buchhaltung-updater"}, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                with open(target_path, "wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            raise FinanceError(f"Update-Download fehlgeschlagen: {exc}") from None
        launched = self.launch_update_installer(target_path)
        if not launched:
            raise FinanceError("Update-Installation konnte nicht gestartet werden. Bitte Paket manuell installieren.")
        return {"path": str(target_path), "launched": launched}

    def launch_update_installer(self, update_path: Path) -> bool:
        name = update_path.name.lower()
        if os.name == "nt":
            try:
                os.startfile(str(update_path))  # type: ignore[attr-defined]
                return True
            except OSError:
                return False
        if name.endswith(".deb"):
            apt_cmd = shutil.which("apt") or shutil.which("apt-get")
            if shutil.which("pkexec") and apt_cmd:
                try:
                    result = subprocess.run(
                        ["pkexec", apt_cmd, "install", "-y", str(update_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        return True
                    stderr = (result.stderr or "").strip()
                    if stderr:
                        raise FinanceError(f"Update-Installation fehlgeschlagen: {stderr}")
                    raise FinanceError(f"Update-Installation fehlgeschlagen (Code {result.returncode}).")
                except OSError as exc:
                    raise FinanceError(f"Update-Installation konnte nicht gestartet werden: {exc}") from None
            if shutil.which("pkexec"):
                try:
                    result = subprocess.run(
                        ["pkexec", "dpkg", "-i", str(update_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        return True
                    stderr = (result.stderr or "").strip()
                    if stderr:
                        raise FinanceError(f"Update-Installation fehlgeschlagen: {stderr}")
                    raise FinanceError(f"Update-Installation fehlgeschlagen (Code {result.returncode}).")
                except OSError as exc:
                    raise FinanceError(f"Update-Installation konnte nicht gestartet werden: {exc}") from None
            return False
        if name.endswith(".appimage"):
            try:
                update_path.chmod(update_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                subprocess.Popen([str(update_path)])
                return True
            except OSError:
                return False
        try:
            if shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", str(update_path)])
                return True
        except OSError:
            return False
        return False
