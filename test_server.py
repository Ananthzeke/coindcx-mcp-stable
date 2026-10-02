#!/usr/bin/env python3
"""Run the offline regression suite; no live exchange or credentials are needed."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    raise SystemExit(
        subprocess.call([sys.executable, "-m", "pytest", "-q"], cwd=Path(__file__).resolve().parent)
    )
