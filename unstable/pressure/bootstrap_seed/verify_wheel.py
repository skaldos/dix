from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> int:
    wheel = Path(sys.argv[1]).resolve(strict=True)
    with zipfile.ZipFile(wheel) as archive:
        names = tuple(archive.namelist())
    required = {
        "dix/bootstrap/__init__.py",
        "dix/bootstrap/__main__.py",
        "dix/bootstrap/build.py",
        "dix/bootstrap/models.py",
        "dix/bootstrap/renderer.py",
        "dix/bootstrap/spec.py",
    }
    missing = sorted(required - set(names))
    unstable = sorted(name for name in names if name.startswith("unstable/"))
    if missing:
        raise SystemExit(f"wheel misses bootstrap files: {', '.join(missing)}")
    if unstable:
        raise SystemExit(f"wheel contains unstable files: {', '.join(unstable)}")
    print(f"verified {wheel.name}: {len(names)} files, bootstrap included, unstable excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
