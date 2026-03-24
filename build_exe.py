#!/usr/bin/env python3
"""Build a standalone Windows executable for the local AEO Score UI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    for path in (BASE_DIR / "build", BASE_DIR / "dist"):
        if path.exists():
            shutil.rmtree(path)

    spec_file = BASE_DIR / "AEOScore.spec"
    if spec_file.exists():
        spec_file.unlink()

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "AEOScore",
        "--add-data",
        "web;web",
        "--hidden-import",
        "requests",
        "app.py",
    ]
    return subprocess.call(command, cwd=BASE_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
