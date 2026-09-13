from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import i3ipc

from dix.core.composition import CompositionRuntimeContext


class SwayIpcError(RuntimeError):
    """Raised when the small Sway IPC boundary cannot be satisfied."""


class Runtime:
    """Expose detached focus and live-container primitives through i3/Sway IPC."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config

    def focused_con_id(self) -> int:
        """Connect through i3ipc and return the focused container's integer ID."""
        try:
            connection = i3ipc.Connection()
            tree = connection.get_tree()
            focused = tree.find_focused()
        except Exception as exc:
            raise SwayIpcError(f"cannot read focused Sway container: {exc}") from exc
        if focused is None:
            raise SwayIpcError("Sway tree has no focused container")
        con_id = getattr(focused, "id", None)
        if type(con_id) is not int:
            raise SwayIpcError("focused Sway container has no integer con_id")
        return con_id

    def focus_direction(self, direction: str) -> None:
        """Move focus exactly once through one native Sway direction."""
        if direction not in {"left", "right", "up", "down"}:
            raise SwayIpcError(f"unsupported Sway focus direction: {direction!r}")
        self._command(f"focus {direction}")

    def focus_con_id(self, con_id: int) -> None:
        """Focus exactly one container selected by its integer Sway ID."""
        if type(con_id) is not int:
            raise SwayIpcError("Sway con_id must be an integer")
        self._command(f"[con_id={con_id}] focus")

    def live_con_ids(self) -> list[int]:
        """Return ordered detached IDs from one current Sway tree read."""
        try:
            connection = i3ipc.Connection()
            tree = connection.get_tree()
            leaves = tree.leaves()
        except Exception as exc:
            raise SwayIpcError(f"cannot read live Sway containers: {exc}") from exc

        result: list[int] = []
        seen: set[int] = set()
        try:
            iterator = iter(leaves)
        except TypeError as exc:
            raise SwayIpcError("Sway tree leaves must be iterable") from exc
        for leaf in iterator:
            con_id = getattr(leaf, "id", None)
            if type(con_id) is not int:
                raise SwayIpcError("Sway tree leaf has no integer con_id")
            if con_id in seen:
                raise SwayIpcError(f"Sway tree contains duplicate con_id: {con_id}")
            seen.add(con_id)
            result.append(con_id)
        return result

    def _command(self, command: str) -> None:
        try:
            connection = i3ipc.Connection()
            replies = connection.command(command)
        except Exception as exc:
            raise SwayIpcError(f"cannot execute Sway command {command!r}: {exc}") from exc
        if not isinstance(replies, list) or not replies:
            raise SwayIpcError(f"Sway command returned no replies: {command!r}")
        for reply in replies:
            if getattr(reply, "success", None) is not True:
                detail = getattr(reply, "error", None)
                suffix = f": {detail}" if isinstance(detail, str) and detail else ""
                raise SwayIpcError(f"Sway command failed: {command!r}{suffix}")
