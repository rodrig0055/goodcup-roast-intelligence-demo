"""One-command launcher for the local GoodCup demo."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if command not in {"demo", "app"}:
        raise SystemExit("Usage: goodcup [demo|app]")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", "")])
    app = ROOT / "src" / "goodcup" / "dashboard" / "app.py"
    raise SystemExit(subprocess.call(
        [sys.executable, "-m", "streamlit", "run", str(app), "--server.headless=true"],
        cwd=ROOT, env=env,
    ))


if __name__ == "__main__":
    main()
