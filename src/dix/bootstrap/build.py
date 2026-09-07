from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .renderer import render_launcher
from .spec import load_launcher_spec


class LauncherBuildError(RuntimeError):
    """Raised when a rendered launcher cannot be published atomically."""


def build_launcher(
    spec_path: Path,
    output_path: Path,
    *,
    replace: bool = False,
) -> Path:
    """Build one launcher and atomically publish it at an explicit path."""
    definition = load_launcher_spec(spec_path)
    source = render_launcher(definition)
    output = _normalize_output(output_path)
    if os.path.lexists(output) and not replace:
        raise LauncherBuildError(f"launcher output already exists: {output}")

    temporary: Path | None = None
    try:
        descriptor, raw_temporary = tempfile.mkstemp(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary = Path(raw_temporary)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, output)
            temporary = None
        else:
            try:
                os.link(temporary, output)
            except FileExistsError as exc:
                raise LauncherBuildError(
                    f"launcher output already exists: {output}"
                ) from exc
        return output
    except LauncherBuildError:
        raise
    except OSError as exc:
        raise LauncherBuildError(f"cannot build launcher {output}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _normalize_output(path: Path) -> Path:
    expanded = path.expanduser()
    parent = expanded.parent.resolve(strict=True)
    if not parent.is_dir():
        raise LauncherBuildError(f"launcher output parent is not a directory: {parent}")
    output = parent / expanded.name
    if output.exists() and output.is_dir():
        raise LauncherBuildError(f"launcher output is a directory: {output}")
    return output
