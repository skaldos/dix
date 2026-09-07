from __future__ import annotations

from dix.core.element import ElementIssue


class FunctionBindingError(Exception):
    """Raised when a Python function cannot implement an authoritative contract."""


class FunctionInvocationError(Exception):
    """Base error for contract-bound function invocation."""


class FunctionInputError(FunctionInvocationError):
    """Raised when a value is incompatible with the function contract input."""

    def __init__(self, function_id: str, issues: tuple[ElementIssue, ...]) -> None:
        super().__init__(f"function input is incompatible with contract: {function_id}")
        self.function_id = function_id
        self.issues = issues


class FunctionOutputError(FunctionInvocationError):
    """Raised when a function result is incompatible with its contract output."""

    def __init__(self, function_id: str, issues: tuple[ElementIssue, ...]) -> None:
        super().__init__(f"function output is incompatible with contract: {function_id}")
        self.function_id = function_id
        self.issues = issues


class FunctionExecutionError(FunctionInvocationError):
    """Raised when the bound Python function itself fails."""

    def __init__(self, function_id: str) -> None:
        super().__init__(f"contract-bound function failed: {function_id}")
        self.function_id = function_id
