"""Install missing application dependencies and start Avenor on either platform."""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def interpreter(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def ensure_environment(directory: Path, extra: str | None, repair: bool) -> Path:
    if not directory.resolve().is_relative_to(ROOT):
        raise RuntimeError("Environment paths must remain inside the application directory.")
    executable = interpreter(directory)
    valid = (
        executable.is_file()
        and subprocess.run(
            [str(executable), "-c", "import sys; sys.exit(sys.version_info < (3, 12))"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    if directory.exists() and not valid:
        if not (directory / "pyvenv.cfg").is_file():
            raise RuntimeError(f"{directory.name} exists but is not a virtual environment.")
        backup = ROOT / ".runtime" / "backups" / f"{directory.name}-{time.time_ns()}"
        if not directory.resolve().is_relative_to(ROOT) or not backup.resolve().is_relative_to(
            ROOT
        ):
            raise RuntimeError("Environment paths must remain inside the application directory.")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(directory), str(backup))
        print(f"Preserved incompatible environment in {backup.relative_to(ROOT)}.", flush=True)
    if not valid:
        run(sys.executable, "-m", "venv", str(directory))
    fingerprint = hashlib.sha256(
        (ROOT / "pyproject.toml").read_bytes()
        + str(ROOT).encode()
        + sys.platform.encode()
        + (extra or "core").encode()
    ).hexdigest()
    stamp = directory / ".avenor-setup"
    probe = (
        "import cognition, fastapi, uvicorn, dotenv; from cognition.config import load_environment"
    )
    if extra:
        probe += "; import google.adk, google.antigravity"
    ready = (
        subprocess.run(
            [str(executable), "-c", probe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    )
    if ready:
        ready = (
            subprocess.run(
                [str(executable), "-m", "pip", "check"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    unchanged = stamp.is_file() and stamp.read_text(encoding="utf-8") == fingerprint
    if repair or not ready or not unchanged:
        print("Installing application dependencies...", flush=True)
        run(str(executable), "-m", "pip", "install", "-e", f".[{extra}]" if extra else ".")
        stamp.write_text(fingerprint, encoding="utf-8")
    else:
        print("Application dependencies are ready.", flush=True)
    return executable


def preserve_settings() -> None:
    path = ROOT / ".env"
    try:
        with path.open("x", encoding="utf-8") as settings:
            settings.write((ROOT / ".env.example").read_text(encoding="utf-8"))
        if os.name != "nt":
            path.chmod(0o600)
        print("Created .env. Add your Gemini key there to enable live investigations.", flush=True)
    except FileExistsError:
        pass


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=1) as response:
            status = json.load(response)
        return status.get("application") == "avenor" and status.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def start(executable: Path, port: int, no_browser: bool) -> None:
    url = f"http://127.0.0.1:{port}"
    if healthy(url):
        print(f"Avenor is already running at {url}", flush=True)
        if not no_browser:
            webbrowser.open(url + "/studio")
        return
    with socket.socket() as connection:
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is occupied by another application. Use another port.")
    process = subprocess.Popen(
        [str(executable), "-m", "cognition.cli", "serve", "--port", str(port)], cwd=ROOT
    )
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"Backend exited during startup (exit {process.returncode}).")
            if healthy(url):
                print(f"\nAvenor is ready: {url}/studio\nPress Ctrl+C to stop.\n", flush=True)
                if not no_browser:
                    webbrowser.open(url + "/studio")
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Backend did not become ready within 30 seconds.")
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", help="Ignored; kept for launcher compatibility.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--setup-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    os.chdir(ROOT)
    preserve_settings()
    core = ensure_environment(ROOT / ".venv", "adk,antigravity", args.repair)
    if args.setup_only:
        print("Setup complete.", flush=True)
    else:
        start(core, args.port, args.no_browser)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAvenor stopped.")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"\nAvenor could not start: {error}", file=sys.stderr)
        raise SystemExit(1) from None
