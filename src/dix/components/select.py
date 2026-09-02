from __future__ import annotations

from typing import Any

from dix.elements.list import ListState
from dix.elements.selection import SelectionState
from dix.models import ComponentDefinition, ComponentRuntime, ComponentSpec, SelectionMode

from .base import Component


def _normalize_options(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("select.config.options must be a list")
    options: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("select.config.options entries must be objects")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("select.config.options entries require a non-empty id")
        label = item.get("label", item_id)
        options.append({**item, "id": item_id, "label": str(label)})
    return options


class SelectComponent(Component):
    definition = ComponentDefinition(
        id="select",
        description="Selection component backed by headless list and selection elements.",
        elements=["list", "selection"],
        outputs=["selected", "selected_items"],
    )

    def create_runtime(self, spec: ComponentSpec) -> ComponentRuntime:
        mode: SelectionMode = spec.config.get("mode", "single")
        if mode not in ("single", "multi"):
            raise ValueError("select.config.mode must be 'single' or 'multi'")
        options = _normalize_options(spec.config.get("options", []))
        list_state = ListState(items=options)
        selection_state = SelectionState(mode=mode)
        return ComponentRuntime(
            id=spec.id,
            use=spec.use,
            state={"list": list_state.model_dump(), "selection": selection_state.model_dump()},
            output={"selected": selection_state.selected, "selected_items": []},
        )
