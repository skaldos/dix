from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from dix.models import ElementContract, ElementFunction, SelectionMode


class SelectionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected: str | list[str] | None = None
    mode: SelectionMode = "single"

    def select(self, item_id: str) -> "SelectionState":
        if self.mode == "multi":
            current = set(self.selected if isinstance(self.selected, list) else [])
            current.add(item_id)
            return self.model_copy(update={"selected": sorted(current)})
        return self.model_copy(update={"selected": item_id})

    def unselect(self, item_id: str) -> "SelectionState":
        if self.mode == "multi":
            current = set(self.selected if isinstance(self.selected, list) else [])
            current.discard(item_id)
            return self.model_copy(update={"selected": sorted(current)})
        if self.selected == item_id:
            return self.clear()
        return self

    def toggle(self, item_id: str) -> "SelectionState":
        if self.mode == "multi":
            current = set(self.selected if isinstance(self.selected, list) else [])
            if item_id in current:
                current.remove(item_id)
            else:
                current.add(item_id)
            return self.model_copy(update={"selected": sorted(current)})
        return self.clear() if self.selected == item_id else self.select(item_id)

    def clear(self) -> "SelectionState":
        return self.model_copy(update={"selected": [] if self.mode == "multi" else None})


SELECTION_CONTRACT = ElementContract(
    id="selection",
    description="Headless selection state over a logical item collection.",
    state_fields=["selected", "mode"],
    functions=[
        ElementFunction(id="select", description="Select an item."),
        ElementFunction(id="unselect", description="Unselect an item."),
        ElementFunction(id="toggle", description="Toggle item selection."),
        ElementFunction(id="clear", description="Clear selection."),
    ],
    events=["changed"],
)
