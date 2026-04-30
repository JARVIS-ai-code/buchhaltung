#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "JarvisBuchhaltung"
PROJECT_DIR = Path(__file__).resolve().parent
VERSION_FILE_PATH = PROJECT_DIR / "version.json"
DEFAULT_INCOME_SOURCES = ["Lohn", "Nebentätigkeit", "Spesen"]


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
"""


DEFAULT_SETTINGS = {
    "currency": "EUR",
    "monthly_budget": "0.0",
    "income_sources": json.dumps(DEFAULT_INCOME_SOURCES, ensure_ascii=False),
    "visible_month": "",
    "autostart_enabled": "false",
    "autostart_open_window": "false",
}


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


def parse_float(text: str) -> float:
    return float(text.strip().replace(",", "."))


def format_money(value: float, currency: str) -> str:
    return f"{value:,.2f} {currency}".replace(",", "X").replace(".", ",").replace("X", ".")


def date_to_text(d: date) -> str:
    return f"{d.day:02d}-{d.month:02d}-{d.year}"


def parse_input_date(text: str) -> date:
    raw = text.strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError("Ungültiges Datum")


def parse_month_text(value: str) -> str:
    text = value.strip()
    for fmt in ("%m-%Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return f"{parsed.year}-{parsed.month:02d}"
        except ValueError:
            pass
    raise ValueError("Ungültiger Monat")


def format_month_label(month: str) -> str:
    try:
        y, m = month.split("-")
        return f"{int(m):02d}-{int(y)}"
    except (ValueError, TypeError):
        return month


def month_shift(month: str, delta: int) -> str:
    y, m = [int(part) for part in month.split("-")]
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12}-{(idx % 12) + 1:02d}"


def month_distance(start_month: str, target_month: str) -> int:
    sy, sm = [int(part) for part in start_month.split("-")]
    ty, tm = [int(part) for part in target_month.split("-")]
    return (ty * 12 + tm) - (sy * 12 + sm)


def month_from_date_text(value: str) -> str | None:
    try:
        return month_key(parse_input_date(value))
    except ValueError:
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


class DataStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._ensure_defaults()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _ensure_defaults(self) -> None:
        with self._connect() as conn:
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, value),
                )
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)", ("closed_months", "[]"))

    def setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is None:
                return default
            return str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def settings(self) -> dict[str, Any]:
        currency = self.setting("currency", "EUR")
        budget = self.setting("monthly_budget", "0.0")
        visible_month = self.setting("visible_month", "")
        if not visible_month:
            visible_month = month_key(date.today())
            self.set_setting("visible_month", visible_month)
        autostart = parse_bool(self.setting("autostart_enabled", "false"), False)
        open_window = parse_bool(self.setting("autostart_open_window", "false"), False)

        raw_sources = self.setting("income_sources", json.dumps(DEFAULT_INCOME_SOURCES, ensure_ascii=False))
        try:
            sources = json.loads(raw_sources)
        except json.JSONDecodeError:
            sources = list(DEFAULT_INCOME_SOURCES)
        cleaned: list[str] = []
        for item in sources if isinstance(sources, list) else []:
            text = str(item).strip()
            if text and text.lower() not in [c.lower() for c in cleaned]:
                cleaned.append(text)
        if not cleaned:
            cleaned = list(DEFAULT_INCOME_SOURCES)
        if "spesen" not in [c.lower() for c in cleaned]:
            cleaned.append("Spesen")

        return {
            "currency": currency,
            "monthly_budget": float(budget.replace(",", ".")) if str(budget).strip() else 0.0,
            "visible_month": visible_month,
            "autostart_enabled": autostart,
            "autostart_open_window": open_window,
            "income_sources": cleaned,
        }

    def set_income_sources(self, sources: list[str]) -> None:
        cleaned: list[str] = []
        for source in sources:
            text = str(source).strip()
            if text and text.lower() not in [c.lower() for c in cleaned]:
                cleaned.append(text)
        if not cleaned:
            cleaned = list(DEFAULT_INCOME_SOURCES)
        self.set_setting("income_sources", json.dumps(cleaned, ensure_ascii=False))

    def list_accounts(self) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name FROM accounts ORDER BY name COLLATE NOCASE").fetchall()
            return [{"id": r["id"], "name": r["name"]} for r in rows]

    def add_account(self, name: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO accounts(id, name) VALUES (?, ?)", (str(uuid.uuid4()), name.strip()))

    def delete_account(self, account_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM recurring_payments WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM expenses WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM incomes WHERE account_id = ?", (account_id,))

    def list_closed_months(self) -> list[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'closed_months'").fetchone()
            raw = row["value"] if row else "[]"
        try:
            months = json.loads(raw)
        except json.JSONDecodeError:
            months = []
        cleaned: list[str] = []
        for item in months if isinstance(months, list) else []:
            try:
                m = parse_month_text(str(item))
            except ValueError:
                continue
            if m not in cleaned:
                cleaned.append(m)
        cleaned.sort()
        return cleaned

    def set_closed_months(self, months: list[str]) -> None:
        cleaned = sorted(set(months))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('closed_months', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(cleaned, ensure_ascii=False),),
            )

    def close_month(self, month: str) -> None:
        months = self.list_closed_months()
        if month not in months:
            months.append(month)
            self.set_closed_months(months)

    def reopen_month(self, month: str) -> None:
        months = [m for m in self.list_closed_months() if m != month]
        self.set_closed_months(months)

    def list_recurring(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months "
            "FROM recurring_payments"
        )
        params: tuple[Any, ...] = ()
        if account_id:
            sql += " WHERE account_id = ?"
            params = (account_id,)
        sql += " ORDER BY day, description COLLATE NOCASE"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                checked = json.loads(row["checked_months"] or "[]")
            except json.JSONDecodeError:
                checked = []
            items.append(
                {
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
            )
        return items

    def add_recurring(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recurring_payments(
                    id, kind, account_id, description, amount, day, frequency, start_date, end_date, final_amount, checked_months
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    payload.get("kind", "standard"),
                    payload["account_id"],
                    payload["description"],
                    float(payload["amount"]),
                    int(payload["day"]),
                    payload.get("frequency", "monthly"),
                    payload.get("start_date", ""),
                    payload.get("end_date", ""),
                    payload.get("final_amount"),
                    json.dumps(payload.get("checked_months", []), ensure_ascii=False),
                ),
            )

    def update_recurring(self, recurring_id: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE recurring_payments
                SET account_id=?, description=?, amount=?, day=?, frequency=?, start_date=?, end_date=?, final_amount=?
                WHERE id=?
                """,
                (
                    payload["account_id"],
                    payload["description"],
                    float(payload["amount"]),
                    int(payload["day"]),
                    payload.get("frequency", "monthly"),
                    payload.get("start_date", ""),
                    payload.get("end_date", ""),
                    payload.get("final_amount"),
                    recurring_id,
                ),
            )

    def delete_recurring(self, recurring_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM recurring_payments WHERE id=?", (recurring_id,))

    def set_recurring_checked(self, recurring_id: str, month: str, checked: bool) -> None:
        items = self.list_recurring()
        recurring = next((r for r in items if r["id"] == recurring_id), None)
        if recurring is None:
            return
        months = list(recurring.get("checked_months", []))
        if checked and month not in months:
            months.append(month)
        if (not checked) and month in months:
            months.remove(month)
        months = sorted(set(months))
        with self._connect() as conn:
            conn.execute("UPDATE recurring_payments SET checked_months=? WHERE id=?", (json.dumps(months), recurring_id))

    def add_income(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO incomes(id, type, account_id, description, amount, date) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    payload["type"],
                    payload["account_id"],
                    payload["description"],
                    float(payload["amount"]),
                    payload["date"],
                ),
            )

    def add_expense(self, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO expenses(id, account_id, description, amount, date, source, recurring_plan_id, recurring_month)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    payload["account_id"],
                    payload["description"],
                    float(payload["amount"]),
                    payload["date"],
                    payload.get("source"),
                    payload.get("recurring_plan_id"),
                    payload.get("recurring_month"),
                ),
            )

    def month_incomes(self, month: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM incomes ORDER BY date DESC").fetchall()
        out = []
        for row in rows:
            try:
                if month_key(parse_input_date(str(row["date"]))) != month:
                    continue
            except ValueError:
                continue
            out.append(dict(row))
        return out

    def month_expenses(self, month: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM expenses ORDER BY date DESC").fetchall()
        out = []
        for row in rows:
            try:
                if month_key(parse_input_date(str(row["date"]))) != month:
                    continue
            except ValueError:
                continue
            out.append(dict(row))
        return out

    def apply_recurring_for_month(self, month: str) -> None:
        rec_list = self.list_recurring()
        y, m = month.split("-")
        for recurring in rec_list:
            if not is_recurring_due_in_month(recurring, month):
                continue
            amount = recurring_amount_for_month(recurring, month)
            recurring_date = f"{safe_recurring_day(recurring):02d}-{m}-{y}"
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM expenses WHERE recurring_plan_id=? AND recurring_month=?",
                    (recurring["id"], month),
                ).fetchone()
                if row is not None:
                    continue
                conn.execute(
                    """
                    INSERT INTO expenses(id, account_id, description, amount, date, source, recurring_plan_id, recurring_month)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        recurring["account_id"],
                        recurring["description"],
                        float(amount),
                        recurring_date,
                        "installment" if recurring.get("kind") == "installment" else "recurring",
                        recurring["id"],
                        month,
                    ),
                )


@dataclass
class RecurringInput:
    account_id: str
    description: str
    amount: float
    day: int
    frequency: str
    start_date: str
    end_date: str
    final_amount: float | None
    kind: str


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


def is_recurring_due_in_month(recurring: dict[str, Any], target_month: str) -> bool:
    start = recurring_start_month(recurring, target_month)
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

    dist = month_distance(start, target_month)
    return dist % step == 0


def recurring_amount_for_month(recurring: dict[str, Any], target_month: str) -> float:
    base_amount = float(recurring.get("amount", 0.0))
    if str(recurring.get("kind", "standard")) != "installment":
        return base_amount

    end = recurring_end_month(recurring)
    final_raw = recurring.get("final_amount")
    if final_raw in (None, ""):
        return base_amount
    try:
        final_amount = float(final_raw)
    except (TypeError, ValueError):
        return base_amount
    if final_amount <= 0:
        return base_amount
    if end and target_month == end:
        return final_amount
    return base_amount


class RecurringDialog(QDialog):
    def __init__(self, accounts: list[dict[str, str]], title: str, kind: str = "standard", recurring: dict[str, Any] | None = None):
        super().__init__()
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(460, 320)
        self._accounts = accounts
        self.kind = kind

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.account_combo = QComboBox()
        for acc in accounts:
            self.account_combo.addItem(acc["name"], acc["id"])

        self.description_edit = QLineEdit()
        self.amount_edit = QLineEdit()
        self.day_spin = QSpinBox()
        self.day_spin.setRange(1, 28)

        self.frequency_combo = QComboBox()
        self.frequency_combo.addItem("Monatlich", "monthly")
        self.frequency_combo.addItem("Quartalszahlung", "quarterly")
        self.frequency_combo.addItem("Jährlich", "yearly")

        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("dd-MM-yyyy")
        self.start_date.setDate(QDate.currentDate())

        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("dd-MM-yyyy")
        self.end_date.setDate(QDate.currentDate())

        self.final_amount_edit = QLineEdit()
        self.final_amount_edit.setPlaceholderText("Optional")

        form.addRow("Konto", self.account_combo)
        form.addRow("Beschreibung", self.description_edit)
        form.addRow("Betrag", self.amount_edit)
        form.addRow("Abbuchungstag", self.day_spin)

        if kind == "standard":
            form.addRow("Intervall", self.frequency_combo)
            form.addRow("Startdatum", self.start_date)
        else:
            form.addRow("Startdatum", self.start_date)
            form.addRow("Enddatum", self.end_date)
            form.addRow("Abschlagssumme (letzter Monat)", self.final_amount_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if recurring is not None:
            self._load_existing(recurring)

    def _load_existing(self, recurring: dict[str, Any]) -> None:
        idx = self.account_combo.findData(recurring.get("account_id"))
        if idx >= 0:
            self.account_combo.setCurrentIndex(idx)
        self.description_edit.setText(str(recurring.get("description", "")))
        self.amount_edit.setText(str(recurring.get("amount", "")))
        self.day_spin.setValue(int(recurring.get("day", 1)))
        fidx = self.frequency_combo.findData(recurring.get("frequency", "monthly"))
        if fidx >= 0:
            self.frequency_combo.setCurrentIndex(fidx)
        if recurring.get("start_date"):
            try:
                d = parse_input_date(str(recurring["start_date"]))
                self.start_date.setDate(QDate(d.year, d.month, d.day))
            except ValueError:
                pass
        if recurring.get("end_date"):
            try:
                d = parse_input_date(str(recurring["end_date"]))
                self.end_date.setDate(QDate(d.year, d.month, d.day))
            except ValueError:
                pass
        if recurring.get("final_amount") not in (None, ""):
            self.final_amount_edit.setText(str(recurring.get("final_amount")))

    def _validate_accept(self) -> None:
        if not self.description_edit.text().strip():
            QMessageBox.warning(self, "Fehler", "Beschreibung fehlt.")
            return
        try:
            _ = parse_float(self.amount_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Betrag ist ungültig.")
            return
        self.accept()

    def payload(self) -> RecurringInput:
        final_amount: float | None = None
        if self.final_amount_edit.text().strip():
            final_amount = parse_float(self.final_amount_edit.text())

        end_text = ""
        if self.kind == "installment":
            end = self.end_date.date()
            end_text = f"{end.day():02d}-{end.month():02d}-{end.year()}"

        start = self.start_date.date()
        start_text = f"{start.day():02d}-{start.month():02d}-{start.year()}"

        return RecurringInput(
            account_id=str(self.account_combo.currentData()),
            description=self.description_edit.text().strip(),
            amount=parse_float(self.amount_edit.text()),
            day=int(self.day_spin.value()),
            frequency=str(self.frequency_combo.currentData() or "monthly"),
            start_date=start_text,
            end_date=end_text,
            final_amount=final_amount,
            kind=self.kind,
        )


class FinanceWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JARVIS Buchhaltungssystem")
        self.resize(1360, 900)

        self.store = DataStore(DB_PATH)
        self.settings = self.store.settings()
        self.visible_month = str(self.settings["visible_month"])
        self.selected_account_id: str | None = None
        self.analysis_filter_account: str | None = None

        self._apply_due_recurring()
        self._build_ui()
        self._apply_style()
        self.refresh_all()
        self._show_overdue_if_needed()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(250)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14, 14, 14, 14)
        side_layout.setSpacing(8)

        title = QLabel("Finanz Cockpit")
        title.setObjectName("sideTitle")
        subtitle = QLabel("Privatbuchhaltung")
        subtitle.setObjectName("sideSub")
        side_layout.addWidget(title)
        side_layout.addWidget(subtitle)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}

        for key, label in [
            ("start", "Start"),
            ("accounts", "Konten"),
            ("analysis", "Analyse"),
            ("settings", "Einstellungen"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("nav", True)
            btn.clicked.connect(lambda _=False, k=key: self.switch_page(k))
            self.nav_group.addButton(btn)
            self.nav_buttons[key] = btn
            side_layout.addWidget(btn)

        side_layout.addStretch(1)
        hint = QLabel("Live-Hinweis\nMint = positiver Cashflow")
        hint.setObjectName("sideHint")
        side_layout.addWidget(hint)

        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self.page_start = self._build_start_page()
        self.page_accounts = self._build_accounts_page()
        self.page_analysis = self._build_analysis_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_start)
        self.stack.addWidget(self.page_accounts)
        self.stack.addWidget(self.page_analysis)
        self.stack.addWidget(self.page_settings)

        self.page_index = {"start": 0, "accounts": 1, "analysis": 2, "settings": 3}
        self.switch_page("start")

    def _build_start_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        income_box = QGroupBox("Einnahmen erfassen")
        income_layout = QFormLayout(income_box)

        self.income_source_combo = QComboBox()
        self.income_account_combo = QComboBox()
        self.income_desc_edit = QLineEdit()
        self.income_amount_edit = QLineEdit()
        self.income_date_edit = QDateEdit()
        self.income_date_edit.setCalendarPopup(True)
        self.income_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.income_date_edit.setDate(QDate.currentDate())

        income_layout.addRow("Typ", self.income_source_combo)
        income_layout.addRow("Konto", self.income_account_combo)
        income_layout.addRow("Beschreibung", self.income_desc_edit)
        income_layout.addRow("Betrag", self.income_amount_edit)
        income_layout.addRow("Datum", self.income_date_edit)

        income_btn = QPushButton("Einnahme speichern")
        income_btn.clicked.connect(self.on_add_income)
        income_layout.addRow(income_btn)

        cash_box = QGroupBox("Cashflow")
        cash_layout = QVBoxLayout(cash_box)
        self.cashflow_value = QLabel("0,00 EUR")
        self.cashflow_value.setObjectName("kpi")
        self.cashflow_open_list = QListWidget()
        cash_layout.addWidget(self.cashflow_value)
        cash_layout.addWidget(QLabel("Offen je Konto"))
        cash_layout.addWidget(self.cashflow_open_list)

        recent_box = QGroupBox("Letzte Einnahmen")
        recent_layout = QVBoxLayout(recent_box)
        self.recent_income_table = QTableWidget(0, 4)
        self.recent_income_table.setHorizontalHeaderLabels(["Datum", "Typ", "Konto", "Betrag"])
        self.recent_income_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.recent_income_table.verticalHeader().setVisible(False)
        self.recent_income_table.setEditTriggers(QTableWidget.NoEditTriggers)
        recent_layout.addWidget(self.recent_income_table)

        next_box = QGroupBox("Nächste Zahlungen je Konto")
        next_layout = QVBoxLayout(next_box)
        self.next_payment_table = QTableWidget(0, 4)
        self.next_payment_table.setHorizontalHeaderLabels(["Konto", "Beschreibung", "Fällig", "Betrag"])
        self.next_payment_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.next_payment_table.verticalHeader().setVisible(False)
        self.next_payment_table.setEditTriggers(QTableWidget.NoEditTriggers)
        next_layout.addWidget(self.next_payment_table)

        grid.addWidget(income_box, 0, 0, 2, 1)
        grid.addWidget(cash_box, 0, 1)
        grid.addWidget(recent_box, 1, 1)
        grid.addWidget(next_box, 2, 0, 1, 2)

        return page

    def _build_accounts_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_row = QHBoxLayout()

        self.account_focus_scroll = QScrollArea()
        self.account_focus_scroll.setWidgetResizable(True)
        self.account_focus_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.account_focus_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.account_focus_scroll.setFrameShape(QFrame.NoFrame)

        self.account_focus_widget = QWidget()
        self.account_focus_layout = QHBoxLayout(self.account_focus_widget)
        self.account_focus_layout.setContentsMargins(0, 0, 0, 0)
        self.account_focus_layout.setSpacing(8)
        self.account_focus_layout.addStretch(1)
        self.account_focus_scroll.setWidget(self.account_focus_widget)

        top_row.addWidget(self.account_focus_scroll, 1)

        add_rec_btn = QPushButton("Dauerzahlung hinzufügen")
        add_rec_btn.clicked.connect(self.on_add_recurring)
        top_row.addWidget(add_rec_btn)

        add_inst_btn = QPushButton("Abzahlung")
        add_inst_btn.clicked.connect(self.on_add_installment)
        top_row.addWidget(add_inst_btn)

        layout.addLayout(top_row)

        card = QGroupBox("Aktive Dauerzahlungen")
        card_layout = QVBoxLayout(card)
        self.recurring_table = QTableWidget(0, 6)
        self.recurring_table.setHorizontalHeaderLabels(["Status", "Beschreibung", "Betrag", "Rhythmus", "Tag", "Aktion"])
        self.recurring_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.recurring_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recurring_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recurring_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.recurring_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.recurring_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.recurring_table.verticalHeader().setVisible(False)
        self.recurring_table.setEditTriggers(QTableWidget.NoEditTriggers)
        card_layout.addWidget(self.recurring_table)
        layout.addWidget(card, 1)

        return page

    def _build_analysis_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        form_box = QGroupBox("Ausgabe erfassen")
        form_layout = QHBoxLayout(form_box)
        self.expense_account_combo = QComboBox()
        self.expense_cat_edit = QLineEdit()
        self.expense_amount_edit = QLineEdit()
        self.expense_date_edit = QDateEdit()
        self.expense_date_edit.setCalendarPopup(True)
        self.expense_date_edit.setDisplayFormat("dd-MM-yyyy")
        self.expense_date_edit.setDate(QDate.currentDate())

        form_layout.addWidget(self._labeled_widget("Konto", self.expense_account_combo))
        form_layout.addWidget(self._labeled_widget("Kategorie", self.expense_cat_edit))
        form_layout.addWidget(self._labeled_widget("Betrag", self.expense_amount_edit))
        form_layout.addWidget(self._labeled_widget("Datum", self.expense_date_edit))

        save_exp_btn = QPushButton("Ausgabe speichern")
        save_exp_btn.clicked.connect(self.on_add_expense)
        form_layout.addWidget(save_exp_btn)
        layout.addWidget(form_box)

        kpi_box = QGroupBox("Analyse")
        kpi_layout = QGridLayout(kpi_box)
        self.analysis_month_label = QLabel("-")
        self.kpi_income = QLabel("0")
        self.kpi_expense = QLabel("0")
        self.kpi_remaining = QLabel("0")
        self.kpi_budget = QLabel("0")
        self.analysis_open_value = QLabel("0")
        for w in [self.kpi_income, self.kpi_expense, self.kpi_remaining, self.kpi_budget, self.analysis_open_value]:
            w.setObjectName("kpi")

        kpi_layout.addWidget(QLabel("Monat"), 0, 0)
        kpi_layout.addWidget(self.analysis_month_label, 0, 1)
        kpi_layout.addWidget(QLabel("Einnahmen"), 1, 0)
        kpi_layout.addWidget(self.kpi_income, 1, 1)
        kpi_layout.addWidget(QLabel("Ausgaben"), 2, 0)
        kpi_layout.addWidget(self.kpi_expense, 2, 1)
        kpi_layout.addWidget(QLabel("Übrig"), 3, 0)
        kpi_layout.addWidget(self.kpi_remaining, 3, 1)
        kpi_layout.addWidget(QLabel("Budget frei"), 4, 0)
        kpi_layout.addWidget(self.kpi_budget, 4, 1)
        kpi_layout.addWidget(QLabel("Noch offen"), 5, 0)
        kpi_layout.addWidget(self.analysis_open_value, 5, 1)

        layout.addWidget(kpi_box)

        filter_box = QGroupBox("Filter")
        filter_layout = QHBoxLayout(filter_box)
        self.analysis_filter_scroll = QScrollArea()
        self.analysis_filter_scroll.setWidgetResizable(True)
        self.analysis_filter_scroll.setFrameShape(QFrame.NoFrame)
        self.analysis_filter_widget = QWidget()
        self.analysis_filter_layout = QHBoxLayout(self.analysis_filter_widget)
        self.analysis_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.analysis_filter_layout.setSpacing(6)
        self.analysis_filter_layout.addStretch(1)
        self.analysis_filter_scroll.setWidget(self.analysis_filter_widget)
        filter_layout.addWidget(self.analysis_filter_scroll)
        layout.addWidget(filter_box)

        cat_box = QGroupBox("Kategorien")
        cat_layout = QVBoxLayout(cat_box)
        self.category_table = QTableWidget(0, 2)
        self.category_table.setHorizontalHeaderLabels(["Kategorie", "Betrag"])
        self.category_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.category_table.verticalHeader().setVisible(False)
        self.category_table.setEditTriggers(QTableWidget.NoEditTriggers)
        cat_layout.addWidget(self.category_table)
        layout.addWidget(cat_box, 1)

        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        basic_box = QGroupBox("Grundeinstellungen")
        basic_layout = QFormLayout(basic_box)
        self.currency_edit = QLineEdit()
        self.budget_edit = QLineEdit()
        self.visible_month_edit = QLineEdit()
        self.visible_month_edit.setPlaceholderText("MM-JJJJ")

        basic_layout.addRow("Währung", self.currency_edit)
        basic_layout.addRow("Monatsbudget", self.budget_edit)
        basic_layout.addRow("Anzeigemonat", self.visible_month_edit)

        month_btn_row = QHBoxLayout()
        apply_month_btn = QPushButton("Monat übernehmen")
        apply_month_btn.clicked.connect(self.on_apply_visible_month)
        close_month_btn = QPushButton("Monat schließen")
        close_month_btn.clicked.connect(self.on_close_visible_month)
        month_btn_row.addWidget(apply_month_btn)
        month_btn_row.addWidget(close_month_btn)
        basic_layout.addRow(month_btn_row)

        self.closed_months_list = QListWidget()
        basic_layout.addRow(QLabel("Geschlossene Monate"), self.closed_months_list)

        reopen_btn = QPushButton("Gewählten Monat wieder öffnen")
        reopen_btn.clicked.connect(self.on_reopen_month)
        basic_layout.addRow(reopen_btn)

        save_settings_btn = QPushButton("Einstellungen speichern")
        save_settings_btn.clicked.connect(self.on_save_settings)
        basic_layout.addRow(save_settings_btn)

        basic_layout.addRow(QLabel(f"Aktuelle Version: {APP_VERSION}"))

        account_box = QGroupBox("Konten verwalten")
        acc_layout = QVBoxLayout(account_box)
        add_acc_row = QHBoxLayout()
        self.new_account_edit = QLineEdit()
        self.new_account_edit.setPlaceholderText("Neues Konto")
        add_acc_btn = QPushButton("Anlegen")
        add_acc_btn.clicked.connect(self.on_add_account)
        add_acc_row.addWidget(self.new_account_edit)
        add_acc_row.addWidget(add_acc_btn)
        acc_layout.addLayout(add_acc_row)

        self.account_settings_table = QTableWidget(0, 2)
        self.account_settings_table.setHorizontalHeaderLabels(["Konto", "Löschen"])
        self.account_settings_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.account_settings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.account_settings_table.verticalHeader().setVisible(False)
        self.account_settings_table.setEditTriggers(QTableWidget.NoEditTriggers)
        acc_layout.addWidget(self.account_settings_table)

        source_box = QGroupBox("Einnahmequellen")
        source_layout = QVBoxLayout(source_box)
        source_add_row = QHBoxLayout()
        self.new_source_edit = QLineEdit()
        self.new_source_edit.setPlaceholderText("Neue Einnahmequelle")
        add_source_btn = QPushButton("Hinzufügen")
        add_source_btn.clicked.connect(self.on_add_income_source)
        source_add_row.addWidget(self.new_source_edit)
        source_add_row.addWidget(add_source_btn)
        source_layout.addLayout(source_add_row)

        self.source_table = QTableWidget(0, 3)
        self.source_table.setHorizontalHeaderLabels(["Name", "Speichern", "Löschen"])
        self.source_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.source_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.source_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.source_table.verticalHeader().setVisible(False)
        self.source_table.setEditTriggers(QTableWidget.NoEditTriggers)
        source_layout.addWidget(self.source_table)

        grid.addWidget(basic_box, 0, 0)
        grid.addWidget(account_box, 0, 1)
        grid.addWidget(source_box, 1, 0, 1, 2)
        return page

    def _labeled_widget(self, label: str, widget: QWidget) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)
        return holder

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget { background: #17171c; color: #f4f4f8; font-family: Segoe UI, Inter, sans-serif; font-size: 13px; }
            QMainWindow { background: #111116; }
            QFrame#sidebar { background: #1f2028; border: 1px solid #333540; border-radius: 18px; }
            QLabel#sideTitle { font-size: 34px; font-weight: 800; }
            QLabel#sideSub { color: #c0c0d0; margin-bottom: 8px; }
            QLabel#sideHint { color: #9af5cf; background: #2a2d35; border-radius: 12px; padding: 10px; }
            QPushButton[nav="true"] { text-align: left; padding: 10px 12px; border-radius: 10px; background: #262834; border: 1px solid #383b49; }
            QPushButton[nav="true"]:checked { background: #5f45b8; border: 1px solid #8d70f0; }
            QGroupBox { border: 1px solid #353847; border-radius: 16px; margin-top: 10px; padding: 8px; font-weight: 700; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #d9d9f4; }
            QPushButton { background: #7451e8; border: 1px solid #977eff; border-radius: 10px; padding: 8px 12px; color: white; }
            QPushButton:hover { background: #8264eb; }
            QLineEdit, QComboBox, QDateEdit, QSpinBox, QListWidget, QTableWidget { background: #232633; border: 1px solid #44485a; border-radius: 8px; padding: 6px; }
            QHeaderView::section { background: #2d3040; color: #f0f0fb; border: none; padding: 6px; }
            QLabel#kpi { font-size: 20px; font-weight: 800; color: #6cf0bc; }
            """
        )

    def switch_page(self, name: str) -> None:
        idx = self.page_index[name]
        self.stack.setCurrentIndex(idx)
        self.nav_buttons[name].setChecked(True)
        if name == "accounts":
            self.refresh_accounts_page()
        elif name == "analysis":
            self.refresh_analysis_page()
        elif name == "settings":
            self.refresh_settings_page()
        elif name == "start":
            self.refresh_start_page()

    def _apply_due_recurring(self) -> None:
        target_months = {month_key(date.today()), self.visible_month}
        for m in target_months:
            self.store.apply_recurring_for_month(m)

    def refresh_all(self) -> None:
        self.settings = self.store.settings()
        self.visible_month = str(self.settings["visible_month"])
        self._apply_due_recurring()
        self.refresh_start_page()
        self.refresh_accounts_page()
        self.refresh_analysis_page()
        self.refresh_settings_page()

    def _accounts_lookup(self) -> dict[str, str]:
        return {a["id"]: a["name"] for a in self.store.list_accounts()}

    def _open_amounts_per_account(self) -> dict[str, float]:
        closed = set(self.store.list_closed_months())
        open_amounts: dict[str, float] = {}
        accounts = self._accounts_lookup()
        rec_items = self.store.list_recurring()
        month = self.visible_month

        if month in closed:
            return {acc_id: 0.0 for acc_id in accounts}

        for rec in rec_items:
            if not is_recurring_due_in_month(rec, month):
                continue
            checked = isinstance(rec.get("checked_months"), list) and month in rec.get("checked_months", [])
            if checked:
                continue
            acc_id = str(rec.get("account_id", ""))
            open_amounts[acc_id] = open_amounts.get(acc_id, 0.0) + recurring_amount_for_month(rec, month)

        for acc_id in accounts:
            open_amounts.setdefault(acc_id, 0.0)
        return open_amounts

    def _month_totals(self) -> tuple[float, float]:
        incomes = self.store.month_incomes(self.visible_month)
        expenses = self.store.month_expenses(self.visible_month)
        income_sum = sum(float(i.get("amount", 0.0)) for i in incomes)
        expense_sum = sum(float(e.get("amount", 0.0)) for e in expenses)
        return income_sum, expense_sum

    def _next_due_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        today = date.today()
        account_names = self._accounts_lookup()
        for rec in self.store.list_recurring():
            probe_month = month_key(today)
            for _ in range(60):
                if is_recurring_due_in_month(rec, probe_month):
                    checked = probe_month in rec.get("checked_months", [])
                    y, m = [int(p) for p in probe_month.split("-")]
                    due = clamped_date(y, m, safe_recurring_day(rec))
                    if due >= today or (not checked):
                        rows.append(
                            {
                                "account": account_names.get(rec["account_id"], "-"),
                                "description": rec["description"],
                                "due": due,
                                "amount": recurring_amount_for_month(rec, probe_month),
                            }
                        )
                        break
                probe_month = month_shift(probe_month, 1)
        rows.sort(key=lambda x: (x["account"], x["due"], x["description"]))
        return rows

    def refresh_start_page(self) -> None:
        accounts = self.store.list_accounts()
        self.income_source_combo.clear()
        for src in self.settings["income_sources"]:
            self.income_source_combo.addItem(src)

        self.income_account_combo.clear()
        for acc in accounts:
            self.income_account_combo.addItem(acc["name"], acc["id"])

        currency = str(self.settings["currency"])
        income_sum, expense_sum = self._month_totals()
        cashflow = income_sum - expense_sum
        self.cashflow_value.setText(format_money(cashflow, currency))
        self.cashflow_value.setStyleSheet("color: #6cf0bc;" if cashflow >= 0 else "color: #ff7f9a;")

        self.cashflow_open_list.clear()
        open_amounts = self._open_amounts_per_account()
        names = self._accounts_lookup()
        for acc_id, amount in sorted(open_amounts.items(), key=lambda x: names.get(x[0], "")):
            self.cashflow_open_list.addItem(f"{names.get(acc_id, '-')}  |  {format_money(amount, currency)}")

        recent = self.store.month_incomes(self.visible_month)[:10]
        self.recent_income_table.setRowCount(len(recent))
        for row, item in enumerate(recent):
            self.recent_income_table.setItem(row, 0, QTableWidgetItem(str(item.get("date", ""))))
            self.recent_income_table.setItem(row, 1, QTableWidgetItem(str(item.get("type", ""))))
            self.recent_income_table.setItem(row, 2, QTableWidgetItem(names.get(str(item.get("account_id", "")), "-")))
            self.recent_income_table.setItem(row, 3, QTableWidgetItem(format_money(float(item.get("amount", 0.0)), currency)))

        due_rows = self._next_due_rows()
        self.next_payment_table.setRowCount(len(due_rows))
        for row, item in enumerate(due_rows):
            self.next_payment_table.setItem(row, 0, QTableWidgetItem(item["account"]))
            self.next_payment_table.setItem(row, 1, QTableWidgetItem(item["description"]))
            self.next_payment_table.setItem(row, 2, QTableWidgetItem(date_to_text(item["due"])))
            self.next_payment_table.setItem(row, 3, QTableWidgetItem(format_money(float(item["amount"]), currency)))

    def refresh_accounts_page(self) -> None:
        accounts = self.store.list_accounts()
        if self.selected_account_id not in [a["id"] for a in accounts]:
            self.selected_account_id = accounts[0]["id"] if accounts else None

        self._clear_layout(self.account_focus_layout)
        self.account_focus_layout.addStretch(1)
        for acc in accounts:
            btn = QPushButton(acc["name"])
            btn.setCheckable(True)
            btn.setChecked(acc["id"] == self.selected_account_id)
            btn.clicked.connect(lambda _=False, aid=acc["id"]: self._set_account_focus(aid))
            self.account_focus_layout.insertWidget(max(0, self.account_focus_layout.count() - 1), btn)

        recurring = self.store.list_recurring(self.selected_account_id)
        currency = str(self.settings["currency"])
        month = self.visible_month

        self.recurring_table.setRowCount(len(recurring))
        for row, rec in enumerate(recurring):
            checked = month in rec.get("checked_months", [])
            status_wrap = QWidget()
            status_l = QHBoxLayout(status_wrap)
            status_l.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox("Erledigt" if checked else "Offen")
            check.setChecked(checked)
            check.stateChanged.connect(
                lambda state, rid=rec["id"]: self.on_toggle_recurring_done(rid, state == Qt.Checked)
            )
            status_l.addWidget(check)
            self.recurring_table.setCellWidget(row, 0, status_wrap)

            desc = f"{rec['description']} | monatlich am {safe_recurring_day(rec):02d}."
            self.recurring_table.setItem(row, 1, QTableWidgetItem(desc))
            amount_text = format_money(recurring_amount_for_month(rec, month), currency)
            self.recurring_table.setItem(row, 2, QTableWidgetItem(amount_text))
            freq_label = {"monthly": "Monatlich", "quarterly": "Quartal", "yearly": "Jährlich"}.get(
                rec.get("frequency", "monthly"),
                "Monatlich",
            )
            self.recurring_table.setItem(row, 3, QTableWidgetItem(freq_label))
            self.recurring_table.setItem(row, 4, QTableWidgetItem(f"{safe_recurring_day(rec):02d}"))

            menu_btn = QPushButton("⋮")
            menu_btn.setFixedWidth(34)
            menu = QMenu(menu_btn)
            edit_action = QAction("Bearbeiten", menu)
            del_action = QAction("Löschen", menu)
            edit_action.triggered.connect(lambda _=False, r=rec: self.on_edit_recurring(r))
            del_action.triggered.connect(lambda _=False, rid=rec["id"]: self.on_delete_recurring(rid))
            menu.addAction(edit_action)
            menu.addAction(del_action)
            menu_btn.setMenu(menu)
            self.recurring_table.setCellWidget(row, 5, menu_btn)

    def refresh_analysis_page(self) -> None:
        accounts = self.store.list_accounts()
        names = self._accounts_lookup()
        currency = str(self.settings["currency"])

        self.expense_account_combo.clear()
        for acc in accounts:
            self.expense_account_combo.addItem(acc["name"], acc["id"])

        self.analysis_month_label.setText(format_month_label(self.visible_month))
        income_sum, expense_sum = self._month_totals()
        remaining = income_sum - expense_sum
        budget = float(self.settings["monthly_budget"])
        budget_left = budget - expense_sum

        self.kpi_income.setText(format_money(income_sum, currency))
        self.kpi_expense.setText(format_money(expense_sum, currency))
        self.kpi_remaining.setText(format_money(remaining, currency))
        self.kpi_budget.setText(format_money(budget_left, currency))

        self._clear_layout(self.analysis_filter_layout)
        all_btn = QPushButton("Alle")
        all_btn.setCheckable(True)
        all_btn.setChecked(self.analysis_filter_account is None)
        all_btn.clicked.connect(lambda: self._set_analysis_filter(None))
        self.analysis_filter_layout.addWidget(all_btn)
        for acc in accounts:
            btn = QPushButton(acc["name"])
            btn.setCheckable(True)
            btn.setChecked(self.analysis_filter_account == acc["id"])
            btn.clicked.connect(lambda _=False, aid=acc["id"]: self._set_analysis_filter(aid))
            self.analysis_filter_layout.addWidget(btn)
        self.analysis_filter_layout.addStretch(1)

        open_amounts = self._open_amounts_per_account()
        if self.analysis_filter_account:
            open_value = open_amounts.get(self.analysis_filter_account, 0.0)
        else:
            open_value = sum(open_amounts.values())
        self.analysis_open_value.setText(format_money(open_value, currency))

        expenses = self.store.month_expenses(self.visible_month)
        if self.analysis_filter_account:
            expenses = [e for e in expenses if str(e.get("account_id")) == self.analysis_filter_account]

        by_cat: dict[str, float] = {}
        for e in expenses:
            cat = str(e.get("description", "-")).strip() or "-"
            by_cat[cat] = by_cat.get(cat, 0.0) + float(e.get("amount", 0.0))

        rows = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        self.category_table.setRowCount(len(rows))
        for r, (cat, amount) in enumerate(rows):
            self.category_table.setItem(r, 0, QTableWidgetItem(cat))
            self.category_table.setItem(r, 1, QTableWidgetItem(format_money(amount, currency)))

    def refresh_settings_page(self) -> None:
        self.currency_edit.setText(str(self.settings["currency"]))
        self.budget_edit.setText(str(self.settings["monthly_budget"]))
        self.visible_month_edit.setText(format_month_label(self.visible_month))

        closed = self.store.list_closed_months()
        self.closed_months_list.clear()
        for month in closed:
            self.closed_months_list.addItem(format_month_label(month))

        accounts = self.store.list_accounts()
        self.account_settings_table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            self.account_settings_table.setItem(row, 0, QTableWidgetItem(acc["name"]))
            del_btn = QPushButton("Löschen")
            del_btn.clicked.connect(lambda _=False, aid=acc["id"]: self.on_delete_account(aid))
            self.account_settings_table.setCellWidget(row, 1, del_btn)

        sources = list(self.settings["income_sources"])
        self.source_table.setRowCount(len(sources))
        for row, src in enumerate(sources):
            edit = QLineEdit(src)
            self.source_table.setCellWidget(row, 0, edit)
            save_btn = QPushButton("Speichern")
            save_btn.clicked.connect(lambda _=False, r=row: self.on_save_income_source_row(r))
            del_btn = QPushButton("Löschen")
            del_btn.clicked.connect(lambda _=False, r=row: self.on_delete_income_source_row(r))
            self.source_table.setCellWidget(row, 1, save_btn)
            self.source_table.setCellWidget(row, 2, del_btn)

    def _set_account_focus(self, account_id: str) -> None:
        self.selected_account_id = account_id
        self.refresh_accounts_page()

    def _set_analysis_filter(self, account_id: str | None) -> None:
        self.analysis_filter_account = account_id
        self.refresh_analysis_page()

    def _clear_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def on_add_income(self) -> None:
        if self.income_account_combo.currentData() is None:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst ein Konto anlegen.")
            return
        try:
            amount = parse_float(self.income_amount_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Ungültiger Betrag.")
            return

        qd = self.income_date_edit.date()
        date_text = f"{qd.day():02d}-{qd.month():02d}-{qd.year()}"
        self.store.add_income(
            {
                "type": self.income_source_combo.currentText().strip(),
                "account_id": str(self.income_account_combo.currentData()),
                "description": self.income_desc_edit.text().strip() or "Einnahme",
                "amount": amount,
                "date": date_text,
            }
        )
        self.income_desc_edit.clear()
        self.income_amount_edit.clear()
        self.refresh_all()

    def on_add_expense(self) -> None:
        if self.expense_account_combo.currentData() is None:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst ein Konto anlegen.")
            return
        try:
            amount = parse_float(self.expense_amount_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Ungültiger Betrag.")
            return
        category = self.expense_cat_edit.text().strip()
        if not category:
            QMessageBox.warning(self, "Fehler", "Kategorie/Beschreibung fehlt.")
            return

        qd = self.expense_date_edit.date()
        date_text = f"{qd.day():02d}-{qd.month():02d}-{qd.year()}"
        self.store.add_expense(
            {
                "account_id": str(self.expense_account_combo.currentData()),
                "description": category,
                "amount": amount,
                "date": date_text,
                "source": "manual",
                "recurring_plan_id": None,
                "recurring_month": None,
            }
        )
        self.expense_cat_edit.clear()
        self.expense_amount_edit.clear()
        self.refresh_all()

    def on_add_recurring(self) -> None:
        accounts = self.store.list_accounts()
        if not accounts:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst ein Konto anlegen.")
            return
        dlg = RecurringDialog(accounts, "Dauerzahlung hinzufügen", kind="standard")
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.payload()
        self.store.add_recurring(
            {
                "kind": "standard",
                "account_id": payload.account_id,
                "description": payload.description,
                "amount": payload.amount,
                "day": payload.day,
                "frequency": payload.frequency,
                "start_date": payload.start_date,
                "end_date": "",
                "final_amount": None,
                "checked_months": [],
            }
        )
        self.refresh_all()

    def on_add_installment(self) -> None:
        accounts = self.store.list_accounts()
        if not accounts:
            QMessageBox.warning(self, "Hinweis", "Bitte zuerst ein Konto anlegen.")
            return
        dlg = RecurringDialog(accounts, "Abzahlung hinzufügen", kind="installment")
        if dlg.exec() != QDialog.Accepted:
            return

        payload = dlg.payload()
        self.store.add_recurring(
            {
                "kind": "installment",
                "account_id": payload.account_id,
                "description": payload.description,
                "amount": payload.amount,
                "day": payload.day,
                "frequency": "monthly",
                "start_date": payload.start_date,
                "end_date": payload.end_date,
                "final_amount": payload.final_amount,
                "checked_months": [],
            }
        )
        self.refresh_all()

    def on_edit_recurring(self, recurring: dict[str, Any]) -> None:
        accounts = self.store.list_accounts()
        dlg = RecurringDialog(
            accounts,
            "Dauerzahlung bearbeiten" if recurring.get("kind") != "installment" else "Abzahlung bearbeiten",
            kind=str(recurring.get("kind", "standard")),
            recurring=recurring,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        payload = dlg.payload()
        self.store.update_recurring(
            recurring_id=str(recurring["id"]),
            payload={
                "account_id": payload.account_id,
                "description": payload.description,
                "amount": payload.amount,
                "day": payload.day,
                "frequency": payload.frequency if recurring.get("kind") != "installment" else "monthly",
                "start_date": payload.start_date,
                "end_date": payload.end_date if recurring.get("kind") == "installment" else "",
                "final_amount": payload.final_amount if recurring.get("kind") == "installment" else None,
            },
        )
        self.refresh_all()

    def on_delete_recurring(self, recurring_id: str) -> None:
        if QMessageBox.question(self, "Löschen", "Diesen Eintrag wirklich löschen?") != QMessageBox.Yes:
            return
        self.store.delete_recurring(recurring_id)
        self.refresh_all()

    def on_toggle_recurring_done(self, recurring_id: str, checked: bool) -> None:
        if self.visible_month in self.store.list_closed_months():
            QMessageBox.information(self, "Gesperrt", f"Monat {format_month_label(self.visible_month)} ist geschlossen.")
            self.refresh_accounts_page()
            return
        self.store.set_recurring_checked(recurring_id, self.visible_month, checked)
        self.refresh_all()

    def on_save_settings(self) -> None:
        currency = self.currency_edit.text().strip() or "EUR"
        budget_text = self.budget_edit.text().strip() or "0.0"
        try:
            _ = parse_float(budget_text)
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Monatsbudget ist ungültig.")
            return

        self.store.set_setting("currency", currency)
        self.store.set_setting("monthly_budget", budget_text.replace(",", "."))
        self.settings = self.store.settings()
        self.refresh_all()

    def on_apply_visible_month(self) -> None:
        text = self.visible_month_edit.text().strip()
        try:
            month = parse_month_text(text)
        except ValueError:
            QMessageBox.warning(self, "Fehler", "Monat ungültig. Format: MM-JJJJ")
            return
        self.store.set_setting("visible_month", month)
        self.visible_month = month
        self.refresh_all()

    def on_close_visible_month(self) -> None:
        self.store.close_month(self.visible_month)
        self.refresh_all()

    def on_reopen_month(self) -> None:
        item = self.closed_months_list.currentItem()
        if item is None:
            return
        text = item.text().strip()
        try:
            month = parse_month_text(text)
        except ValueError:
            return
        self.store.reopen_month(month)
        self.refresh_all()

    def on_add_account(self) -> None:
        name = self.new_account_edit.text().strip()
        if not name:
            return
        if name.lower() in [a["name"].lower() for a in self.store.list_accounts()]:
            QMessageBox.warning(self, "Hinweis", "Konto existiert bereits.")
            return
        self.store.add_account(name)
        self.new_account_edit.clear()
        self.refresh_all()

    def on_delete_account(self, account_id: str) -> None:
        if QMessageBox.question(self, "Löschen", "Konto inklusive Einträge löschen?") != QMessageBox.Yes:
            return
        self.store.delete_account(account_id)
        self.refresh_all()

    def on_add_income_source(self) -> None:
        text = self.new_source_edit.text().strip()
        if not text:
            return
        sources = list(self.settings["income_sources"])
        if text.lower() in [s.lower() for s in sources]:
            QMessageBox.warning(self, "Hinweis", "Quelle existiert bereits.")
            return
        sources.append(text)
        self.store.set_income_sources(sources)
        self.new_source_edit.clear()
        self.refresh_all()

    def on_save_income_source_row(self, row: int) -> None:
        edit = self.source_table.cellWidget(row, 0)
        if not isinstance(edit, QLineEdit):
            return
        new_text = edit.text().strip()
        if not new_text:
            QMessageBox.warning(self, "Fehler", "Name darf nicht leer sein.")
            return
        sources = list(self.settings["income_sources"])
        if row < 0 or row >= len(sources):
            return
        sources[row] = new_text
        self.store.set_income_sources(sources)
        self.refresh_all()

    def on_delete_income_source_row(self, row: int) -> None:
        sources = list(self.settings["income_sources"])
        if row < 0 or row >= len(sources):
            return
        del sources[row]
        self.store.set_income_sources(sources)
        self.refresh_all()

    def _show_overdue_if_needed(self) -> None:
        closed = set(self.store.list_closed_months())
        today = date.today()
        overdue_lines: list[str] = []
        accounts = self._accounts_lookup()
        for rec in self.store.list_recurring():
            current = month_key(today)
            for _ in range(24):
                if is_recurring_due_in_month(rec, current):
                    if current in closed:
                        current = month_shift(current, -1)
                        continue
                    if current not in rec.get("checked_months", []):
                        y, m = [int(p) for p in current.split("-")]
                        due = clamped_date(y, m, safe_recurring_day(rec))
                        if due < today:
                            overdue_lines.append(
                                f"{accounts.get(rec['account_id'], '-')} | {rec['description']} | fällig {date_to_text(due)}"
                            )
                current = month_shift(current, -1)

        if overdue_lines:
            preview = "\n".join(overdue_lines[:8])
            if len(overdue_lines) > 8:
                preview += f"\n+ {len(overdue_lines) - 8} weitere"
            QMessageBox.information(self, "Überfällige Zahlungen", preview)



def main() -> None:
    app = QApplication(sys.argv)
    win = FinanceWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
