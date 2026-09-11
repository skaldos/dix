from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import i3ipc

from dix.core.composition import CompositionRuntimeContext


class SwayIpcError(RuntimeError):
    """Raised when the focused Sway container cannot be read."""


class Runtime:
    """Expose only the focused container ID from one i3/Sway IPC query."""

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
