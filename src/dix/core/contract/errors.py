from dix.core.module.errors import ModuleSpecError


class ContractSpecError(ModuleSpecError):
    """Raised when a declarative contract artifact is invalid."""


class ContractNotFound(LookupError):
    """Raised when an exact loaded contract identity cannot be resolved."""
