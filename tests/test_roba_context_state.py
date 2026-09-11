from __future__ import annotations

from pathlib import Path

import pytest
from dix.core.composition import CompositionRuntimeContext
from dix_roba_state_test_support import (
    FakeContext,
    FakeControl,
    FakeModels,
)

import dix_roba_state_runtime_test_import as runtime_module

Runtime = runtime_module.Runtime


class _FakeClient:
    def __init__(self, *, timeout: float) -> None:
        assert timeout == 5.0

    def context(self, *, locator: str, token: str) -> FakeContext:
        assert locator == "unix:/tmp/fake-context.sock"
        assert token == "owner"
        return _CURRENT_REMOTE


_CURRENT_REMOTE: FakeContext


def _context(tmp_path: Path) -> CompositionRuntimeContext:
    return CompositionRuntimeContext(
        instance_id="state",
        composition_id="dix/roba/state",
        module_id="dix/roba",
        module_root=tmp_path,
        composition_root=tmp_path,
        config_base_dir=tmp_path,
        owner_scope_id="test",
    )


def _model_spec(path: Path, *, fields: str = '[fields.value]\ntype = "string"\n') -> None:
    path.write_text(f'name = "TestState"\n\n{fields}', encoding="utf-8")


def _runtime(tmp_path: Path, remote: FakeContext, *, config: dict[str, object] | None = None):
    global _CURRENT_REMOTE
    _CURRENT_REMOTE = remote
    runtime_module._MODULE.RobaClient = _FakeClient
    model_path = tmp_path / "state_model.toml"
    _model_spec(model_path)
    return Runtime(
        context=_context(tmp_path),
        config={"model": model_path.name, "context_id": "shared", **(config or {})},
        models=FakeModels(),
        control=FakeControl(remote),
    )


def test_get_validates_model_and_preserves_only_model_projection(tmp_path: Path) -> None:
    remote = FakeContext({"value": "ready", "foreign": "untouched"})
    runtime = _runtime(tmp_path, remote)

    assert runtime.get() == {"value": "ready"}
    assert remote.calls == [("state",)]


def test_set_validates_before_remote_mutation_and_preserves_foreign_state(tmp_path: Path) -> None:
    remote = FakeContext({"value": "before", "foreign": 7})
    runtime = _runtime(tmp_path, remote)

    assert runtime.set({"value": "after"}) is True
    assert remote.state_value == {"value": "after", "foreign": 7}
    assert remote.writes == [("value", "after")]
    assert runtime.set({"value": "after"}) is False
    assert remote.writes == [("value", "after")]


def test_invalid_set_does_not_call_remote_set(tmp_path: Path) -> None:
    remote = FakeContext({"value": "before"})
    runtime = _runtime(tmp_path, remote)

    with pytest.raises(ValueError):
        runtime.set({"value": 3})
    assert remote.writes == []


def test_missing_context_reconnect_fails_without_provisioning(tmp_path: Path) -> None:
    remote = FakeContext({}, credentials_error=RuntimeError("missing context"))
    runtime = _runtime(tmp_path, remote)

    with pytest.raises(RuntimeError, match="missing context"):
        runtime.get()
    assert remote.created is False


def test_model_path_and_context_id_are_explicitly_bounded(tmp_path: Path) -> None:
    model_path = tmp_path / "state_model.toml"
    _model_spec(model_path)
    for config in (
        {"model": str(model_path), "context_id": "shared"},
        {"model": "../state_model.toml", "context_id": "shared"},
        {"model": "state_model.toml", "context_id": ""},
    ):
        with pytest.raises(ValueError):
            Runtime(
                context=_context(tmp_path),
                config=config,
                models=FakeModels(),
                control=FakeControl(FakeContext({})),
            )


def test_remote_multifield_write_is_sequential_and_not_rollback_claim(tmp_path: Path) -> None:
    fields = (
        '[fields.first]\ntype = "string"\n\n'
        '[fields.second]\ntype = "string"\n'
    )
    model_path = tmp_path / "state_model.toml"
    _model_spec(model_path, fields=fields)
    remote = FakeContext({"first": "a", "second": "b"}, fail_on="second")
    global _CURRENT_REMOTE
    _CURRENT_REMOTE = remote
    runtime_module._MODULE.RobaClient = _FakeClient
    runtime = Runtime(
        context=_context(tmp_path),
        config={"model": model_path.name, "context_id": "shared"},
        models=FakeModels(),
        control=FakeControl(remote),
    )

    with pytest.raises(RuntimeError, match="second write failed"):
        runtime.set({"first": "x", "second": "y"})
    assert remote.writes == [("first", "x"), ("second", "y")]
    assert remote.state_value == {"first": "x", "second": "b"}
