"""Portable setup, SDK checks and local startup. Requires Python 3.12 or newer."""

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def interpreter(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def environment(directory: Path) -> Path:
    executable = interpreter(directory)
    if not directory.exists():
        venv.EnvBuilder(with_pip=True).create(directory)
    if not executable.is_file():
        raise RuntimeError(
            f"{directory.name} has no compatible interpreter. "
            "Recreate this environment on the current machine; do not copy virtual environments."
        )
    return executable


def run(executable: Path, *args: str) -> None:
    subprocess.run([str(executable), *args], cwd=ROOT, check=True)


def main() -> None:
    # Bootstrap runs before the package's Python requirement can be enforced.
    if sys.version_info < (3, 12):  # noqa: UP036
        raise SystemExit("Python 3.12 or newer is required.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "serve", "check"])
    parser.add_argument("--harness", choices=["antigravity", "adk", "deepagents"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    os.chdir(ROOT)
    core = interpreter(ROOT / ".venv")
    if args.command == "setup":
        core = environment(ROOT / ".venv")
        extras = "dev,mcp,adk,antigravity" + (",deepagents" if args.harness == "deepagents" else "")
        run(core, "-m", "pip", "install", "-e", f".[{extras}]")
        settings = ROOT / ".env"
        if not settings.exists():
            shutil.copyfile(ROOT / ".env.example", settings)
        print("Setup complete. Edit .env, then run scripts/manage.py serve.")
    elif not core.is_file():
        raise SystemExit("Run scripts/manage.py setup first.")
    elif args.command == "serve":
        run(core, "-m", "cognition.cli", "serve", "--port", str(args.port))
    elif not args.harness:
        parser.error("check requires --harness")
    else:
        run(core, "scripts/check_sdk.py", args.harness)


if __name__ == "__main__":
    main()
