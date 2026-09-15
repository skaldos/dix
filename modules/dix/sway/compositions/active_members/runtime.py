from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import tempfile

from dix.core.composition import CompositionRuntimeContext


class Runtime:
    """Read and atomically publish the canonical active-member artifact."""

    def __init__(self, *, context: CompositionRuntimeContext, config: Mapping[str, object]) -> None:
        self.context = context
        self.config = config
        configured = config.get("path")
        if configured is None:
            configured = os.environ.get("DIX_SWAY_ACTIVE_MEMBERS_FILE")
        if not isinstance(configured, str) or not configured:
            raise ValueError("active Sway members path must be set through path or DIX_SWAY_ACTIVE_MEMBERS_FILE")
        self.path = Path(configured)

    def get(self) -> list[int]:
        if not self.path.exists():
            return []
        try:
            payload = self.path.read_bytes()
        except OSError as exc:
            raise ValueError(f"cannot read active Sway members: {exc}") from exc
        if payload == b"\n":
            return []
        if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
            raise ValueError("active Sway members must contain exactly one newline-terminated line")
        body = payload[:-1]
        try:
            tokens = body.decode("ascii").split(" ")
        except UnicodeDecodeError as exc:
            raise ValueError("active Sway members must be ASCII") from exc
        if not tokens or any(not _canonical_id(token) for token in tokens):
            raise ValueError("active Sway members contain non-canonical con_ids")
        result = [int(token) for token in tokens]
        if len(set(result)) != len(result):
            raise ValueError("active Sway members contain duplicate con_ids")
        return result

    def set(self, members: list[int]) -> None:
        checked = _members(members)
        payload = (" ".join(str(member) for member in checked) + "\n").encode("ascii")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent, prefix=f".{self.path.name}.", delete=False) as handle:
                temporary = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)


def _canonical_id(value: str) -> bool:
    return bool(value) and value[0] in "123456789" and value.isascii() and value.isdigit()


def _members(value: object) -> list[int]:
    if not isinstance(value, list):
        raise TypeError("active Sway members must be a list")
    if any(type(member) is not int or member <= 0 for member in value):
        raise TypeError("active Sway members must contain positive integer con_ids")
    if len(set(value)) != len(value):
        raise ValueError("active Sway members must not contain duplicate con_ids")
    return list(value)
