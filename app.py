#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_electron(binary: Path, project_dir: Path, args: list[str]) -> int:
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    command = [str(binary), str(project_dir), *args]
    code = subprocess.call(command, cwd=project_dir, env=env)
    if code != 0 and os.name != "nt" and "--no-sandbox" not in args:
        fallback_command = [str(binary), str(project_dir), "--no-sandbox", *args]
        return subprocess.call(fallback_command, cwd=project_dir, env=env)
    return code


def main() -> None:
    args = sys.argv[1:]
    project_dir = Path(__file__).resolve().parent

    if "--backend" in args:
        from app_backend import main as backend_main

        sys.argv = [sys.argv[0]] + [arg for arg in args if arg != "--backend"]
        backend_main()
        return

    electron_bin = project_dir / "node_modules" / ".bin" / ("electron.cmd" if os.name == "nt" else "electron")
    electron_dist_bin = project_dir / "node_modules" / "electron" / "dist" / ("electron.exe" if os.name == "nt" else "electron")
    if electron_dist_bin.exists():
        raise SystemExit(run_electron(electron_dist_bin, project_dir, args))
    if electron_bin.exists():
        raise SystemExit(run_electron(electron_bin, project_dir, args))

    npm = shutil.which("npm")
    if npm and (project_dir / "package.json").exists() and (project_dir / "node_modules").exists():
        env = os.environ.copy()
        env.pop("ELECTRON_RUN_AS_NODE", None)
        raise SystemExit(subprocess.call([npm, "start", "--", *args], cwd=project_dir, env=env))

    print("Electron ist noch nicht installiert.", file=sys.stderr)
    print("Bitte einmal ausführen: npm install", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
