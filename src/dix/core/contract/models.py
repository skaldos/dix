from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dix.core.norn import StrandDefinition


@dataclass(frozen=True, order=True)
class ContractReference:
    use: str
    version: str | None = None

    def __post_init__(self) -> None:
        use = self.use.strip()
        if not use:
            raise ValueError("contract reference use must not be empty")
        version = self.version
        if version is not None:
            version = version.strip()
            if not version:
                raise ValueError("contract reference version must not be empty")
        object.__setattr__(self, "use", use)
        object.__setattr__(self, "version", version)


@dataclass(frozen=True)
class ContractDefinition:
    id: str
    local_id: str
    module_id: str
    version: str | None
    strand: StrandDefinition
    spec_path: Path

    @property
    def reference(self) -> ContractReference:
        return ContractReference(self.id, self.version)
