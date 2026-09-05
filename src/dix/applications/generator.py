from __future__ import annotations

import ast
import inspect
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from dix.core.application import (
    ApplicationFunctionDescriptor,
    ApplicationSource,
    inspect_application_source,
)
from dix.core.composition import CompositionFunctionDescriptor

from .errors import ApplicationGeneratorError


class ApplicationDependencyResolver(Protocol):
    def describe_composition(
        self, composition_id: str
    ) -> tuple[CompositionFunctionDescriptor, ...]: ...

    def describe_application(
        self, application_id: str
    ) -> tuple[ApplicationFunctionDescriptor, ...]: ...


def generate_runtime(
    spec_path: Path,
    dependencies: ApplicationDependencyResolver,
    *,
    include_lifecycle: bool = False,
) -> Path:
    """Generate one new application runtime from live dependency descriptors."""
    source = inspect_application_source(spec_path)
    target = source.application_root / "runtime.py"
    if target.exists():
        raise ApplicationGeneratorError(f"runtime already exists: {target}")
    descriptors = _dependency_descriptors(source, dependencies)
    payload = _render_runtime(source, descriptors, include_lifecycle=include_lifecycle)
    temporary_dir = Path(tempfile.mkdtemp(prefix=".runtime.", dir=source.application_root))
    temporary = temporary_dir / "runtime.py"
    try:
        temporary.write_text(payload)
        compile(payload, str(target), "exec")
        temporary.rename(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return target


def _dependency_descriptors(
    source: ApplicationSource,
    resolver: ApplicationDependencyResolver,
) -> dict[str, dict[str, CompositionFunctionDescriptor | ApplicationFunctionDescriptor]]:
    required: dict[str, set[str]] = {
        alias: set(dependency.export) for alias, dependency in source.compositions.items()
    }
    required.update(
        {alias: set(dependency.export) for alias, dependency in source.applications.items()}
    )
    for function in source.functions.values():
        if function.export is None:
            continue
        alias, function_id = function.export.split(".", 1)
        required[alias].add(function_id)
    result: dict[str, dict[str, CompositionFunctionDescriptor | ApplicationFunctionDescriptor]] = {}
    for alias, function_ids in required.items():
        if alias in source.compositions:
            dependency_id = source.compositions[alias].use
            available = {item.id: item for item in resolver.describe_composition(dependency_id)}
        else:
            dependency_id = source.applications[alias].use
            available = {item.id: item for item in resolver.describe_application(dependency_id)}
        missing = sorted(set(function_ids) - set(available))
        if missing:
            raise ApplicationGeneratorError(
                f"dependency function is not declared: {dependency_id}.{missing[0]}"
            )
        result[alias] = {
            function_id: available[function_id] for function_id in sorted(function_ids)
        }
    return result


def _render_runtime(
    source: ApplicationSource,
    descriptors: dict[
        str, dict[str, CompositionFunctionDescriptor | ApplicationFunctionDescriptor]
    ],
    *,
    include_lifecycle: bool,
) -> str:
    protocol_names = _protocol_names(source)
    lines = [
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from typing import Protocol",
        "",
        "from dix.core.application import ApplicationRuntimeContext",
    ]
    for alias in (*source.compositions, *source.applications):
        lines.extend(("", "", f"class {protocol_names[alias]}(Protocol):"))
        functions = descriptors[alias]
        if not functions:
            lines.append("    pass")
        for descriptor in functions.values():
            signature = _safe_method_signature(descriptor.signature)
            prefix = "async def" if descriptor.is_async else "def"
            lines.append(f"    {prefix} {descriptor.id}{signature}: ...")

    lines.extend(("", "", "class Runtime:"))
    constructor = [
        "self",
        "*",
        "context: ApplicationRuntimeContext",
        "config: Mapping[str, object]",
    ]
    constructor.extend(
        f"{alias}: {protocol_names[alias]}"
        for alias in (*source.compositions, *source.applications)
    )
    lines.append(f"    def __init__({', '.join(constructor)}) -> None:")
    lines.append("        self.context = context")
    lines.append("        self.config = config")
    for alias in (*source.compositions, *source.applications):
        lines.append(f"        self.{alias} = {alias}")

    for local_id, origin in sorted(_effective_exports(source).items()):
        alias, function_id = origin.split(".", 1)
        descriptor = descriptors[alias][function_id]
        signature = _safe_method_signature(descriptor.signature)
        prefix = "async def" if descriptor.is_async else "def"
        lines.extend(("", f"    {prefix} {local_id}{signature}:"))
        if descriptor.docstring:
            lines.append(f"        {descriptor.docstring!r}")
        call = f"self.{alias}.{function_id}({_call_arguments(descriptor.signature)})"
        lines.append(f"        return {'await ' if descriptor.is_async else ''}{call}")

    for function_id, function in source.functions.items():
        if function.export is not None:
            continue
        lines.extend(
            (
                "",
                f"    def {function_id}(self) -> object:",
                f"        {(function.description or f'TODO: Describe {function_id}.')!r}",
                "        raise NotImplementedError",
            )
        )
    if include_lifecycle:
        lines.extend(
            (
                "",
                "    def start(self) -> None:",
                "        pass",
                "",
                "    def stop(self) -> None:",
                "        pass",
            )
        )
    return "\n".join(lines) + "\n"


def _effective_exports(source: ApplicationSource) -> dict[str, str]:
    exports: dict[str, str] = {}
    for dependencies in (source.compositions, source.applications):
        for alias, dependency in dependencies.items():
            for function_id in dependency.export:
                exports[function_id] = f"{alias}.{function_id}"
    for function_id, function in source.functions.items():
        if function.export is not None:
            exports[function_id] = function.export
    return exports


def _safe_method_signature(signature: inspect.Signature) -> inspect.Signature:
    parameters = tuple(_safe_parameter(item) for item in signature.parameters.values())
    self_kind = (
        inspect.Parameter.POSITIONAL_ONLY
        if parameters and parameters[0].kind is inspect.Parameter.POSITIONAL_ONLY
        else inspect.Parameter.POSITIONAL_OR_KEYWORD
    )
    self_parameter = inspect.Parameter("self", self_kind)
    return signature.replace(
        parameters=(self_parameter, *parameters),
        return_annotation=_safe_annotation(signature.return_annotation),
    )


def _safe_parameter(parameter: inspect.Parameter) -> inspect.Parameter:
    if parameter.default is not inspect.Parameter.empty:
        _validate_default(parameter.name, parameter.default)
    return parameter.replace(annotation=_safe_annotation(parameter.annotation))


def _safe_annotation(annotation: object) -> object:
    if annotation is inspect.Signature.empty or isinstance(annotation, str):
        return annotation
    if annotation is None or annotation is type(None):
        return None
    if isinstance(annotation, type) and annotation.__module__ == "builtins":
        return annotation
    return object


def _validate_default(name: str, value: object) -> None:
    rendered = repr(value)
    try:
        parsed = ast.literal_eval(rendered)
    except (SyntaxError, ValueError) as exc:
        raise ApplicationGeneratorError(
            f"parameter '{name}' has a default that cannot be represented as stable source: "
            f"{rendered}"
        ) from exc
    if type(parsed) is not type(value) or parsed != value:
        raise ApplicationGeneratorError(
            f"parameter '{name}' has a default that cannot be reproduced exactly: {rendered}"
        )


def _call_arguments(signature: inspect.Signature) -> str:
    arguments: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            arguments.append(parameter.name)
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            arguments.append(f"*{parameter.name}")
        elif parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            arguments.append(f"{parameter.name}={parameter.name}")
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            arguments.append(f"**{parameter.name}")
    return ", ".join(arguments)


def _protocol_names(source: ApplicationSource) -> dict[str, str]:
    result: dict[str, str] = {}
    used: set[str] = set()
    for kind, aliases in (
        ("Composition", source.compositions),
        ("Application", source.applications),
    ):
        for alias in aliases:
            base = "".join(part.capitalize() for part in alias.split("_")) or "Dependency"
            candidate = f"{base}{kind}Api"
            index = 2
            while candidate in used:
                candidate = f"{base}{kind}Api{index}"
                index += 1
            result[alias] = candidate
            used.add(candidate)
    return result
