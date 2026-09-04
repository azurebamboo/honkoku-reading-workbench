#!/usr/bin/env python3
"""
Skill Launcher for Standalone OCR & Reading Desk.

Provides automated bootstrapping, health checks, single-port production execution (Option A),
and dual-process development server execution (Option B).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"
IS_WINDOWS = platform.system() == "Windows"
NPM_CMD = "npm.cmd" if IS_WINDOWS else "npm"


def get_venv_python() -> Path:
    if IS_WINDOWS:
        return BACKEND_DIR / ".venv" / "Scripts" / "python.exe"
    return BACKEND_DIR / ".venv" / "bin" / "python"


def get_venv_uvicorn() -> Path:
    if IS_WINDOWS:
        return BACKEND_DIR / ".venv" / "Scripts" / "uvicorn.exe"
    return BACKEND_DIR / ".venv" / "bin" / "uvicorn"


def check_prerequisites() -> dict[str, bool | str]:
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = sys.version_info >= (3, 10)

    node_ok = False
    node_version = "Missing"
    npm_ok = False

    node_bin = shutil.which("node")
    if node_bin:
        try:
            res = subprocess.run([node_bin, "--version"], capture_output=True, text=True, check=True)
            node_version = res.stdout.strip()
            # node version starts with 'v', e.g., 'v18.15.0'
            major = int(node_version.lstrip("v").split(".")[0])
            node_ok = major >= 18
        except Exception:
            pass

    npm_bin = shutil.which(NPM_CMD) or shutil.which("npm")
    if npm_bin:
        npm_ok = True

    return {
        "python_ok": python_ok,
        "python_version": python_version,
        "node_ok": node_ok,
        "node_version": node_version,
        "npm_ok": npm_ok,
    }


def cmd_bootstrap(args: argparse.Namespace) -> None:
    print("=== Standalone OCR Desk Skill Bootstrapper ===")
    prereqs = check_prerequisites()
    print(f"[*] Python Version: {prereqs['python_version']} (OK: {prereqs['python_ok']})")
    print(f"[*] Node.js Version: {prereqs['node_version']} (OK: {prereqs['node_ok']})")

    if not prereqs["python_ok"]:
        print("[!] Error: Python 3.10 or higher is required.")
        sys.exit(1)

    if not prereqs["node_ok"] or not prereqs["npm_ok"]:
        print("[!] Error: Node.js 18+ and npm are required to build the frontend.")
        print("[!] Please install Node.js from https://nodejs.org/")
        if IS_WINDOWS:
            print("    Windows (winget): winget install OpenJS.NodeJS")
        elif platform.system() == "Darwin":
            print("    macOS (Homebrew): brew install node")
        else:
            print("    Linux (Ubuntu/Debian): sudo apt install nodejs npm")
        sys.exit(1)

    venv_dir = BACKEND_DIR / ".venv"
    if not venv_dir.exists():
        print(f"[*] Creating Python virtual environment at {venv_dir}...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    else:
        print(f"[*] Python virtual environment exists at {venv_dir}.")

    venv_python = get_venv_python()
    req_file = BACKEND_DIR / "requirements.txt"
    print("[*] Installing/upgrading backend Python dependencies...")
    subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(venv_python), "-m", "pip", "install", "-r", str(req_file)], check=True)

    print("[*] Installing frontend npm dependencies...")
    subprocess.run([NPM_CMD, "install"], cwd=FRONTEND_DIR, check=True)

    print("[*] Building frontend single-file bundle...")
    subprocess.run([NPM_CMD, "run", "build"], cwd=FRONTEND_DIR, check=True)

    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if dist_index.exists():
        print(f"[✓] Frontend built successfully at {dist_index}")
    else:
        print("[!] Warning: dist/index.html was not found after build.")

    print("\n[✓] Skill bootstrap completed successfully!")


def check_health(host: str = "127.0.0.1", port: int = 8000) -> bool:
    url = f"http://{host}:{port}/api/v1/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SkillLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("ok") is True
    except Exception:
        pass
    return False


def cmd_status(args: argparse.Namespace) -> None:
    host = args.host
    port = args.port
    is_healthy = check_health(host, port)
    status_info = {
        "running": is_healthy,
        "host": host,
        "port": port,
        "health_url": f"http://{host}:{port}/api/v1/health",
        "web_url": f"http://{host}:{port}/" if is_healthy else None,
    }
    print(json.dumps(status_info, indent=2))
    sys.exit(0 if is_healthy else 1)


def cmd_start(args: argparse.Namespace) -> None:
    host = args.host
    port = args.port
    is_dev = args.dev

    print(f"=== Starting Standalone OCR Desk (Mode: {'Dev' if is_dev else 'Single-Port Production'}) ===")

    if check_health(host, port):
        web_url = f"http://{host}:{port}/"
        print(f"[*] Application is already running on {web_url}")
        print(f"[*] Opening browser...")
        webbrowser.open(web_url)
        return

    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if not is_dev and not dist_index.exists():
        print("[*] Frontend single-file bundle not found. Running auto-bootstrap...")
        cmd_bootstrap(args)

    uvicorn_bin = get_venv_uvicorn()
    if not uvicorn_bin.exists():
        uvicorn_bin_path = shutil.which("uvicorn")
        if not uvicorn_bin_path:
            print("[!] Virtualenv uvicorn not found. Running auto-bootstrap...")
            cmd_bootstrap(args)
            uvicorn_bin = get_venv_uvicorn()
        else:
            uvicorn_bin = Path(uvicorn_bin_path)

    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR)

    backend_cmd = [
        str(uvicorn_bin),
        "backend.app.main:app",
        "--host", host,
        "--port", str(port),
        "--log-level", "warning"
    ]
    if is_dev:
        backend_cmd.append("--reload")

    print(f"[*] Launching FastAPI backend on http://{host}:{port} ...")
    backend_proc = subprocess.Popen(backend_cmd, cwd=ROOT_DIR, env=env, **kwargs)

    frontend_proc = None
    if is_dev:
        print("[*] Launching Vite dev server on http://127.0.0.1:5173 ...")
        frontend_cmd = [NPM_CMD, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"]
        frontend_proc = subprocess.Popen(frontend_cmd, cwd=FRONTEND_DIR, **kwargs)

    print("[*] Waiting for backend initialization...")
    start_time = time.time()
    healthy = False
    while time.time() - start_time < 15:
        if check_health(host, port):
            healthy = True
            break
        time.sleep(0.5)

    if not healthy:
        print("[!] Backend server failed to start within timeout.")
        if backend_proc.poll() is None:
            backend_proc.terminate()
        if frontend_proc and frontend_proc.poll() is None:
            frontend_proc.terminate()
        sys.exit(1)

    target_url = "http://127.0.0.1:5173/" if is_dev else f"http://{host}:{port}/"
    print(f"[✓] Backend healthy! Opening web app: {target_url}")
    webbrowser.open(target_url)

    if args.no_wait:
        print(f"[✓] Skill launcher finished (running in background).")
        return

    print("\nOCR Reading Desk is active. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print("[!] Backend process exited.")
                break
            if frontend_proc and frontend_proc.poll() is not None:
                print("[!] Frontend dev server process exited.")
                break
    except KeyboardInterrupt:
        print("\nShutting down OCR Reading Desk...")
    finally:
        def terminate_proc(p: subprocess.Popen | None, name: str) -> None:
            if p and p.poll() is None:
                if IS_WINDOWS:
                    os.kill(p.pid, signal.CTRL_BREAK_EVENT)
                else:
                    p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
                print(f"[*] {name} stopped.")

        terminate_proc(backend_proc, "Backend")
        terminate_proc(frontend_proc, "Frontend")


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone OCR & Reading Desk Skill Launcher")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    subparsers.add_parser("bootstrap", help="Setup python venv, install pip/npm packages, and build frontend")
    
    start_parser = subparsers.add_parser("start", help="Start the OCR Reading Desk app and open browser")
    start_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    start_parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")
    start_parser.add_argument("--dev", action="store_true", help="Launch Vite dev server alongside uvicorn (Option B)")
    start_parser.add_argument("--no-wait", action="store_true", help="Launch in background and exit immediately")

    status_parser = subparsers.add_parser("status", help="Check server health status")
    status_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    status_parser.add_argument("--port", type=int, default=8000, help="Port number (default: 8000)")

    args = parser.parse_args()

    if args.command == "bootstrap":
        cmd_bootstrap(args)
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        # Default behavior if run with no args: start app
        args.host = "127.0.0.1"
        args.port = 8000
        args.dev = False
        args.no_wait = False
        cmd_start(args)


if __name__ == "__main__":
    main()
