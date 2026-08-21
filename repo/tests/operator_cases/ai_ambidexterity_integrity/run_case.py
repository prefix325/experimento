#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[3]
raise SystemExit(
    subprocess.call(
        [
            sys.executable,
            str(root / "tools/validate_manuscript_integrity.py"),
            "--output",
            str(root / "build/manuscript-integrity"),
        ],
        cwd=root,
    )
)
