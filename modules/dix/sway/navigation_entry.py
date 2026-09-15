from __future__ import annotations

from collections.abc import Callable
import importlib.util
from pathlib import Path
from types import ModuleType

from dix.core.application import ApplicationRuntimeContext
from dix.core.composition import CompositionRuntimeContext


class _Api:
    def __init__(self, functions: dict[str, Callable[..., object]]) -> None:
        self._functions = functions

    def require(self, function_id: str) -> Callable[..., object]:
        return self._functions[function_id]


def run(module_root: Path, projection_path: Path, direction: str) -> dict[str, object]:
    """Assemble and execute only the productive Sway navigation owners."""
    if direction not in {"left", "right", "up", "down"}:
        raise ValueError(f"unsupported Sway navigation direction: {direction!r}")

    active_module = _load(module_root / "compositions/active_members/runtime.py", "dix_sway_entry_active")
    ipc_module = _load(module_root / "compositions/ipc/runtime.py", "dix_sway_entry_ipc")
    basic_module = _load(module_root / "apps/navigation_basic/runtime.py", "dix_sway_entry_basic")
    group_module = _load(module_root / "apps/navigation_group/runtime.py", "dix_sway_entry_group")

    composition_context = CompositionRuntimeContext(
        instance_id="navigation-entry", composition_id="dix/sway/ipc", module_id="dix/sway",
        module_root=module_root, composition_root=module_root, config_base_dir=module_root,
        owner_scope_id="navigation-entry",
    )
    active = active_module.Runtime(
        context=composition_context, config={"path": str(projection_path)}
    )
    ipc = ipc_module.Runtime(context=composition_context, config={})
    ipc_api = _Api({
        "focused_con_id": ipc.focused_con_id,
        "focus_direction": ipc.focus_direction,
        "focus_con_id": ipc.focus_con_id,
        "live_con_ids": ipc.live_con_ids,
    })
    application_context = ApplicationRuntimeContext(
        instance_id="navigation-entry", application_id="dix/sway/navigation_group",
        module_id="dix/sway", module_root=module_root, application_root=module_root,
        config_base_dir=module_root, owner_scope_id="navigation-entry",
    )
    basic = basic_module.Runtime(context=application_context, config={}, ipc=ipc_api)
    basic_api = _Api({name: getattr(basic, name) for name in ("left", "right", "up", "down")})
    group = group_module.Runtime(
        context=application_context,
        config={},
        basic=basic_api,
        active_members=_Api({"get": active.get}),
        ipc=ipc_api,
    )
    result = getattr(group, direction)()
    if not isinstance(result, dict):
        raise TypeError("Sway navigation entry must return a dictionary")
    return result


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Sway runtime owner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
