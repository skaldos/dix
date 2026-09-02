from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AccessMode = Literal["public", "authenticated", "disabled", "session_match"]
SelectionMode = Literal["single", "multi"]


class AccessSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AccessMode = "public"
    path: str | None = None
    equals: Any | None = None
    contains: Any | None = None

    @model_validator(mode="after")
    def validate_session_match(self) -> "AccessSpec":
        if self.mode == "session_match" and not self.path:
            raise ValueError("access.mode='session_match' requires access.path")
        if self.mode != "session_match" and any(
            item is not None for item in (self.path, self.equals, self.contains)
        ):
            raise ValueError("access.path/equals/contains are only valid for session_match")
        return self


class ComponentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    use: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "use")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class InterfaceHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    access: AccessSpec = Field(default_factory=AccessSpec)


class InterfaceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interface: InterfaceHeader
    components: list[ComponentSpec] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None

    @model_validator(mode="after")
    def validate_component_ids(self) -> "InterfaceSpec":
        seen: set[str] = set()
        for component in self.components:
            if component.id in seen:
                raise ValueError(f"duplicate component id: {component.id}")
            seen.add(component.id)
        return self


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = "anonymous"
    authenticated: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = "default"
    title: str = "Default"


class ElementFunction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str


class ElementContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    state_fields: list[str]
    functions: list[ElementFunction]
    events: list[str]


class ComponentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str
    elements: list[str]
    outputs: list[str]


class ComponentRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    use: str
    state: dict[str, Any]
    output: dict[str, Any]
