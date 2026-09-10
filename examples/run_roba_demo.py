from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from dix.bootstrap import build_launcher


REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_roba.toml"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dix-roba-demo-") as directory:
        launcher = build_launcher(SPEC, Path(directory) / "dix_roba.py")
        completed = subprocess.run([sys.executable, str(launcher), *sys.argv[1:]], check=False)
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
