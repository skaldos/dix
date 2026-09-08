from __future__ import annotations

from collections.abc import Mapping

import typer

from dix.core.composition import CompositionRuntimeContext


class Runtime:
    """First-party Typer adapter runtime."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config
        self.typer_version = typer.__version__
