"""Load local settings without replacing variables provided by the process host."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def load_environment(path: Path | None = None) -> None:
    load_dotenv(path or Path.cwd() / ".env", override=False)


def environment_python(directory: Path, *, windows: bool | None = None) -> Path:
    """Resolve a virtual environment's interpreter for the target platform."""
    windows = sys.platform == "win32" if windows is None else windows
    return directory / ("Scripts/python.exe" if windows else "bin/python")


def worker_interpreter(name: str, root: Path | None = None) -> str | None:
    """Return the interpreter set in COGNITION_<NAME>_PYTHON; otherwise run in-process.

    The project uses one virtual environment, so nothing is discovered automatically.
    """
    root = root or Path.cwd()
    configured = os.getenv(f"COGNITION_{name.upper()}_PYTHON", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            path = environment_python(path)
        return os.path.abspath(path)
    return None


def kill_after_seconds() -> float:
    """Kill switch: seconds after a run starts before all agents and harnesses stop. 0 is off."""
    try:
        return max(0.0, float(os.getenv("COGNITION_KILL_AFTER_SECONDS", "0")))
    except ValueError:
        return 0.0


def tool_cap() -> int:
    """Main-harness tool-call cap per incident. High by default; it is not a run budget."""
    try:
        return max(1, int(os.getenv("COGNITION_TOOL_CAP", "200")))
    except ValueError:
        return 200
