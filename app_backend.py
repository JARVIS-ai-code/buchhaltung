#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from buchhaltung_core import APP_VERSION, FinanceService
from buchhaltung_core.finance import FinanceError

PROJECT_DIR = Path(__file__).resolve().parent


def resolve_web_dir() -> Path:
    env_override = os.environ.get("JARVIS_WEB_DIR", "").strip()
    if env_override:
        override = Path(env_override)
        if (override / "index.html").exists():
            return override

    candidates: list[Path] = [PROJECT_DIR / "web"]

    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        candidates.extend(
            [
                exe_path.parent / "web",
                exe_path.parent.parent / "web",
            ]
        )
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(str(meipass)) / "web")

    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate

    return PROJECT_DIR / "web"


WEB_DIR = resolve_web_dir()


def json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def schedule_process_exit(code: int = 77, delay_seconds: float = 0.25) -> None:
    def worker() -> None:
        time.sleep(max(0.0, float(delay_seconds)))
        os._exit(int(code))

    threading.Thread(target=worker, daemon=True, name="app-exit-scheduler").start()


class ApiHandler(BaseHTTPRequestHandler):
    service: FinanceService
    server_version = "JarvisBuchhaltungBackend/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(fmt, *args)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_common_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api("GET", parsed.path, self.query(parsed))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("POST", parsed.path, self.query(parsed), self.read_json())

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("PUT", parsed.path, self.query(parsed), self.read_json())

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        self.handle_api("DELETE", parsed.path, self.query(parsed), self.read_json())

    def query(self, parsed: Any) -> dict[str, str]:
        raw = parse_qs(parsed.query)
        return {key: values[-1] for key, values in raw.items() if values}

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise FinanceError("Ungültige JSON-Daten.")
        if not isinstance(payload, dict):
            raise FinanceError("JSON-Daten müssen ein Objekt sein.")
        return payload

    def handle_api(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> None:
        payload = payload or {}
        try:
            result = self.route_api(method, path, query, payload)
            self.send_json({"ok": True, **result})
        except FinanceError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self.send_json({"ok": False, "error": f"Interner Fehler: {exc}"}, status=500)

    def route_api(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        service = self.service
        parts = [part for part in path.strip("/").split("/") if part]

        if method == "GET" and path == "/api/health":
            return {"version": APP_VERSION}
        if method == "GET" and path == "/api/state":
            return {
                "state": service.build_state(
                    analysis_filter_account=query.get("analysis_filter_account") or None,
                    selected_account_id=query.get("selected_account_id") or None,
                )
            }
        if method == "GET" and path == "/api/overdue":
            return {"overdue": service.collect_overdue_items()}

        if method == "POST" and path == "/api/accounts":
            service.add_account(str(payload.get("name", "")))
            return self.state_after(payload)
        if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "accounts"]:
            service.delete_account(parts[2])
            return self.state_after(payload)

        if method == "POST" and path == "/api/incomes":
            service.add_income(payload)
            return self.state_after(payload)
        if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "incomes"]:
            service.update_income(parts[2], payload)
            return self.state_after(payload)
        if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "incomes"]:
            service.delete_income(parts[2])
            return self.state_after(payload)

        if method == "POST" and path == "/api/expenses":
            service.add_expense(payload)
            return self.state_after(payload)
        if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "expenses"]:
            service.update_expense(parts[2], payload)
            return self.state_after(payload)
        if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "expenses"]:
            service.delete_expense(parts[2])
            return self.state_after(payload)

        if method == "POST" and path == "/api/recurring":
            service.add_recurring(payload)
            return self.state_after(payload)
        if method == "PUT" and len(parts) == 3 and parts[:2] == ["api", "recurring"]:
            service.update_recurring(parts[2], payload)
            return self.state_after(payload)
        if method == "DELETE" and len(parts) == 3 and parts[:2] == ["api", "recurring"]:
            service.delete_recurring(parts[2])
            return self.state_after(payload)
        if method == "POST" and len(parts) == 4 and parts[:2] == ["api", "recurring"] and parts[3] == "checked":
            service.set_recurring_checked(parts[2], str(payload.get("month", "")), bool(payload.get("checked")))
            return self.state_after(payload)

        if method == "POST" and path == "/api/settings":
            service.save_settings(payload)
            return self.state_after(payload)
        if method == "POST" and path == "/api/settings/visible-month":
            service.set_visible_month(str(payload.get("month", "")))
            return self.state_after(payload)
        if method == "POST" and path == "/api/settings/close-month":
            service.close_visible_month()
            return self.state_after(payload)
        if method == "POST" and path == "/api/settings/reopen-month":
            service.reopen_month(str(payload.get("month", "")))
            return self.state_after(payload)

        if method == "POST" and path == "/api/income-sources":
            service.add_income_source(str(payload.get("name", "")))
            return self.state_after(payload)
        if method == "PUT" and path == "/api/income-sources":
            service.rename_income_source(str(payload.get("old_name", "")), str(payload.get("new_name", "")))
            return self.state_after(payload)
        if method == "DELETE" and path == "/api/income-sources":
            service.delete_income_source(str(payload.get("name", "")))
            return self.state_after(payload)

        if method == "POST" and path == "/api/update/check":
            return {"update": service.check_update()}
        if method == "POST" and path == "/api/update/install":
            asset = payload.get("asset")
            if not isinstance(asset, dict):
                raise FinanceError("Kein Update-Paket ausgewählt.")
            return {"update": {"task": service.start_update_install(asset)}}
        if method == "GET" and path == "/api/update/progress":
            task_id = str(query.get("task_id", "")).strip()
            return {"update": {"task": service.get_update_task(task_id)}}
        if method == "POST" and path == "/api/app/restart":
            schedule_process_exit(code=77)
            return {"restart": True}

        raise FinanceError("Unbekannter API-Endpunkt.")

    def state_after(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": self.service.build_state(
                analysis_filter_account=payload.get("analysis_filter_account") or None,
                selected_account_id=payload.get("selected_account_id") or None,
            )
        }

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_common_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_common_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def serve_static(self, path: str) -> None:
        if path in ("", "/"):
            target = WEB_DIR / "index.html"
        else:
            candidate = (WEB_DIR / path.lstrip("/")).resolve()
            if not str(candidate).startswith(str(WEB_DIR.resolve())):
                self.send_error(403)
                return
            target = candidate
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(target.suffix.lower(), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_common_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host: str, port: int, quiet: bool) -> ThreadingHTTPServer:
    handler = ApiHandler
    handler.service = FinanceService()
    server = ThreadingHTTPServer((host, port), handler)
    server.quiet = quiet  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis Buchhaltung backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    server = make_server(args.host, args.port, args.quiet)
    actual_host, actual_port = server.server_address
    print(json.dumps({"ready": True, "host": actual_host, "port": actual_port}), flush=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
