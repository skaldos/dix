from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel
from roba import RobaClient

from dix.core.composition import CompositionRuntimeContext


class ModelsApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class ControlApi(Protocol):
    def require(self, function_id: str) -> Callable[..., object]: ...


class Runtime:
    """Bind one DIX model to the state of an existing ROBA context."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        models: ModelsApi,
        control: ControlApi,
    ) -> None:
        self.context = context
        self.config = config
        context_id = _required_string(config.get("context_id"), "context_id")
        model_spec = _load_model_spec(context.config_base_dir, config.get("model"))
        resolved = models.require("resolve")(model_spec)
        if not isinstance(resolved, type) or not issubclass(resolved, BaseModel):
            raise TypeError("state model resolver must return a Pydantic model type")
        self._model_type = resolved
        self._context_id = context_id
        self._control = control

    def get(self) -> dict[str, object]:
        """Read, validate, and detach the modeled ROBA Context state."""
        state = self._remote_context().state()
        if not isinstance(state, Mapping):
            raise TypeError("ROBA context state must be a mapping")
        value = self._model_type.model_validate(deepcopy(dict(state)))
        return cast(dict[str, object], deepcopy(value.model_dump(mode="python")))

    def set(self, values: Mapping[str, object]) -> bool:
        """Validate a complete value, then write changed model fields sequentially."""
        if not isinstance(values, Mapping):
            raise TypeError("ROBA context state value must be a mapping")
        remote = self._remote_context()
        current = self._model_type.model_validate(deepcopy(dict(remote.state())))
        candidate = self._model_type.model_validate(deepcopy(dict(values)))
        current_dump = current.model_dump(mode="python")
        candidate_dump = candidate.model_dump(mode="python")
        if candidate_dump == current_dump:
            return False
        for field_name, field_value in candidate_dump.items():
            if field_value != current_dump.get(field_name):
                remote.set(field_name, deepcopy(field_value))
        return True

    def _remote_context(self):
        credentials = self._control.require("context_credentials")(self._context_id)
        if not isinstance(credentials, Mapping):
            raise TypeError("ROBA context credentials must be a mapping")
        locator = _required_string(credentials.get("context_locator"), "context_locator")
        token = _required_string(credentials.get("owner_token"), "owner_token")
        return RobaClient(timeout=5.0).context(locator=locator, token=token)


def _load_model_spec(config_base_dir: Path, configured_path: object) -> dict[str, object]:
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise ValueError("ROBA state model path must be a non-empty string")
    relative_path = Path(configured_path)
    if relative_path.is_absolute():
        raise ValueError("ROBA state model path must be relative to config base directory")
    root = config_base_dir.expanduser().resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"ROBA state model path escapes config base directory: {configured_path}")
    if not path.is_file():
        raise ValueError(f"ROBA state model path is not a file: {configured_path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
