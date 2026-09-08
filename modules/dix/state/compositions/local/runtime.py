from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel

from dix.core.composition import CompositionRuntimeContext


class StateModelsApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Own one model-bound value within one composition instance."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        models: StateModelsApi,
    ) -> None:
        self.context = context
        self.config = config
        model_spec = _load_model_spec(context.config_base_dir, config.get("model"))
        resolved = models.require("resolve")(model_spec)
        if not isinstance(resolved, type) or not issubclass(resolved, BaseModel):
            raise TypeError("state model resolver must return a Pydantic model type")
        self._model_type = resolved
        initial = config.get("initial", {})
        if not isinstance(initial, Mapping):
            raise TypeError("state initial value must be a mapping")
        self._value = self._model_type.model_validate(deepcopy(dict(initial)))

    def get(self) -> dict[str, object]:
        """Return a detached dump of the complete local state value."""
        return cast(dict[str, object], deepcopy(self._value.model_dump(mode="python")))

    def set(self, values: Mapping[str, object]) -> bool:
        """Validate and replace the complete local state value if it changed."""
        if not isinstance(values, Mapping):
            raise TypeError("state value must be a mapping")
        candidate = self._model_type.model_validate(deepcopy(dict(values)))
        if candidate == self._value:
            return False
        self._value = candidate
        return True


def _load_model_spec(config_base_dir: Path, configured_path: object) -> dict[str, object]:
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise ValueError("state model path must be a non-empty string")
    relative_path = Path(configured_path)
    if relative_path.is_absolute():
        raise ValueError("state model path must be relative to config base directory")
    root = config_base_dir.expanduser().resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"state model path escapes config base directory: {configured_path}")
    if not path.is_file():
        raise ValueError(f"state model path is not a file: {configured_path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)
