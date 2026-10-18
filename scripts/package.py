"""Create a portable source archive, excluding credentials, databases and caches."""

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=root / "dist" / "Fabrix_Source.zip")
output = parser.parse_args().output.resolve()
output.parent.mkdir(parents=True, exist_ok=True)
excluded = {
    ".git",
    ".runtime",
    ".aws",
    ".ssh",
    ".codex",
    ".agents",
    ".playwright-cli",
    ".codex-remote-attachments",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "data",
    "dist",
    "output",
}
manifest = {}


def source_files():
    for directory, children, filenames in os.walk(root):
        children[:] = sorted(
            name for name in children if name not in excluded and not name.startswith(".venv")
        )
        for filename in sorted(filenames):
            yield Path(directory) / filename


with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(source_files()):
        relative = path.relative_to(root)
        if (
            path == output
            or not path.is_file()
            or any(p in excluded or p.startswith(".venv") for p in relative.parts)
        ):
            continue
        if (
            path.name.startswith(".env") and path.name != ".env.example"
        ) or path.name == "SOURCE_MANIFEST.json":
            continue
        if path.suffix in {".pyc", ".db", ".zip", ".pem", ".key"}:
            continue
        if path.name == "core" or path.name.startswith("core."):
            continue
        data = path.read_bytes()
        name = "industrial-cognition/" + relative.as_posix()
        if relative.as_posix() == "start.sh":
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = 0o100755 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
        else:
            archive.writestr(name, data)
        manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    archive.writestr("industrial-cognition/SOURCE_MANIFEST.json", json.dumps(manifest, indent=2))
print(str(output))
