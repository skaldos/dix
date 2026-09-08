from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Literal

from dix.core.contract import ContractDefinition
from dix.core.norn import StrandDefinition

FunctionSource = Literal["local", "local_wrapper"]
FunctionCallStyle = Literal["positional", "keyword"]


@dataclass(frozen=True)
class FunctionDescriptor:
    """Code-authoritative facts about one selected Python function."""

    id: str
    owner_id: str
    source: FunctionSource
    origin: str | None
    signature: inspect.Signature
    return_annotation: object
    docstring: str | None
    is_async: bool = False


@dataclass(frozen=True)
class FunctionBinding:
    """Validated connection from one Python function to an authoritative contract."""

    function_id: str
    owner_id: str
    contract: ContractDefinition
    strand: StrandDefinition
    parameter_name: str
    call_style: FunctionCallStyle


@dataclass(frozen=True)
class FunctionRuntimeBinding:
    """Instance-local Norn binding for one structurally bound function."""

    function: FunctionBinding
    handler_id: str
