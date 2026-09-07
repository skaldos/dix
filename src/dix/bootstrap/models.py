from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LauncherModule:
    """One explicitly ordered source module embedded in a launcher."""

    id: str
    source: Path


@dataclass(frozen=True)
class LauncherDefinition:
    """Normalized build-time definition for one generated launcher."""

    name: str
    adapter: str
    application: str
    function: str
    modules: tuple[LauncherModule, ...]
    spec_path: Path
