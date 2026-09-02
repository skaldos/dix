from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from dix.models import ElementContract, ElementFunction


class ListState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]] = Field(default_factory=list)
    loading: bool = False
    error: str | None = None

    def set_items(self, items: list[dict[str, Any]]) -> "ListState":
        return self.model_copy(update={"items": items, "loading": False, "error": None})

    def clear(self) -> "ListState":
        return self.model_copy(update={"items": [], "loading": False, "error": None})


LIST_CONTRACT = ElementContract(
    id="list",
    description="Headless item collection state.",
    state_fields=["items", "loading", "error"],
    functions=[
        ElementFunction(id="set_items", description="Replace items."),
        ElementFunction(id="clear", description="Clear items."),
        ElementFunction(id="refresh", description="Refresh hook; external loading is not part of the element."),
    ],
    events=["changed", "refreshed"],
)
