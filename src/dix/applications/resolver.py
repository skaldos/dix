from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Self
from uuid import uuid4

from dix.compositions.errors import CompositionGeneratorError
from dix.compositions.resolver import TrustedBuildFunctionResolver
from dix.core.application import (
    ApplicationDefinition,
    ApplicationFunctionDescriptor,
    ApplicationSpecError,
    inspect_spec,
    normalize_effective_application_id,
)
from dix.core.application.runtime import (
    describe_runtime_functions,
    validate_runtime_constructor,
)
from dix.core.composition import CompositionFunctionDescriptor

from .errors import ApplicationGeneratorError


class TrustedBuildApplicationResolver:
    """Resolve application and composition functions from trusted authoring roots."""

    def __init__(self, trusted_module_roots: Iterable[Path]) -> None:
        self._trusted_roots = tuple(
            dict.fromkeys(self._resolve_trusted_root(path) for path in trusted_module_roots)
        )
        self._compositions = TrustedBuildFunctionResolver(self._trusted_roots)
        self._namespace = uuid4().hex
        self._definitions: dict[str, ApplicationDefinition] = {}
        self._descriptors: dict[str, tuple[ApplicationFunctionDescriptor, ...]] = {}
        self._runtime_types: dict[str, type[object]] = {}
        self._runtime_modules: list[str] = []
        self._visiting: list[str] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        for module_name in reversed(self._runtime_modules):
            self._remove_runtime_modules(module_name)
        self._runtime_modules.clear()
        self._compositions.close()

    def describe_composition_function(
        self, composition_id: str, function_id: str
    ) -> CompositionFunctionDescriptor:
        for descriptor in self.describe_composition(composition_id):
            if descriptor.id == function_id:
                return descriptor
        raise ApplicationGeneratorError(
            f"composition function is not declared: {composition_id}.{function_id}"
        )

    def describe_composition(
        self, composition_id: str
    ) -> tuple[CompositionFunctionDescriptor, ...]:
        try:
            return self._compositions.describe_composition(composition_id)
        except CompositionGeneratorError as exc:
            raise ApplicationGeneratorError(str(exc)) from exc

    def describe_application_function(
        self, application_id: str, function_id: str
    ) -> ApplicationFunctionDescriptor:
        normalized_id = normalize_effective_application_id(application_id)
        for descriptor in self.describe_application(normalized_id):
            if descriptor.id == function_id:
                return descriptor
        raise ApplicationGeneratorError(
            f"application function is not declared: {normalized_id}.{function_id}"
        )

    def describe_application(
        self, application_id: str
    ) -> tuple[ApplicationFunctionDescriptor, ...]:
        normalized_id = normalize_effective_application_id(application_id)
        return self._describe_application(normalized_id)

    def _describe_application(
        self, application_id: str
    ) -> tuple[ApplicationFunctionDescriptor, ...]:
        if application_id in self._descriptors:
            return self._descriptors[application_id]
        if application_id in self._visiting:
            start = self._visiting.index(application_id)
            cycle = (*self._visiting[start:], application_id)
            raise ApplicationGeneratorError(
                f"application dependency cycle during generation: {' -> '.join(cycle)}"
            )
        self._visiting.append(application_id)
        try:
            definition = self._resolve_definition(application_id)
            dependency_functions: dict[str, set[str]] = {}
            for alias, dependency in definition.compositions.items():
                requested = _required_functions(definition, alias, dependency.export)
                dependency_functions[alias] = {
                    self.describe_composition_function(dependency.use, function_id).id
                    for function_id in requested
                }
            for alias, dependency in definition.applications.items():
                available = {item.id for item in self._describe_application(dependency.use)}
                requested = _required_functions(definition, alias, dependency.export)
                missing = sorted(set(requested) - available)
                if missing:
                    raise ApplicationGeneratorError(
                        f"application function is not declared: {dependency.use}.{missing[0]}"
                    )
                dependency_functions[alias] = available

            runtime_type = self._import_runtime(definition)
            aliases = (*sorted(definition.compositions), *sorted(definition.applications))
            validate_runtime_constructor(runtime_type, aliases)
            descriptors = describe_runtime_functions(definition, runtime_type)
            for descriptor in descriptors:
                if descriptor.origin is None:
                    continue
                alias, function_id = descriptor.origin.split(".", 1)
                if function_id not in dependency_functions[alias]:
                    target = (
                        definition.compositions[alias].use
                        if alias in definition.compositions
                        else definition.applications[alias].use
                    )
                    raise ApplicationGeneratorError(
                        f"wrapper origin '{descriptor.origin}' in '{application_id}' refers to "
                        f"undeclared function '{target}.{function_id}'"
                    )
            self._descriptors[application_id] = descriptors
            return descriptors
        except ApplicationGeneratorError:
            raise
        except Exception as exc:
            raise ApplicationGeneratorError(
                f"cannot inspect application dependency '{application_id}': {exc}"
            ) from exc
        finally:
            self._visiting.pop()

    def _resolve_definition(self, application_id: str) -> ApplicationDefinition:
        if application_id in self._definitions:
            return self._definitions[application_id]
        module_id, local_id = application_id.rsplit("/", 1)
        module_parts = module_id.split("/")
        candidates: list[tuple[Path, Path]] = []
        for trusted_root in self._trusted_roots:
            unresolved_module = trusted_root.joinpath(*module_parts)
            if not unresolved_module.exists():
                continue
            module_root = unresolved_module.resolve(strict=True)
            try:
                module_root.relative_to(trusted_root)
            except ValueError as exc:
                raise ApplicationGeneratorError(
                    f"application module escapes trusted root '{trusted_root}': {module_root}"
                ) from exc
            spec_path = module_root / "apps" / local_id / "app.toml"
            if spec_path.exists():
                candidates.append((spec_path, module_root))
        if not candidates:
            raise ApplicationGeneratorError(
                f"application dependency is not present in trusted roots: {application_id}"
            )
        if len(candidates) > 1:
            locations = ", ".join(str(item[0]) for item in sorted(candidates))
            raise ApplicationGeneratorError(
                f"duplicate application dependency across trusted roots: "
                f"{application_id} ({locations})"
            )
        spec_path, expected_module_root = candidates[0]
        try:
            definition = inspect_spec(spec_path, module_id=module_id)
        except ApplicationSpecError as exc:
            raise ApplicationGeneratorError(
                f"cannot inspect application dependency '{application_id}': {exc}"
            ) from exc
        if definition.module_root != expected_module_root:
            raise ApplicationGeneratorError(
                f"application dependency escapes trusted module root: {application_id}"
            )
        self._definitions[application_id] = definition
        return definition

    def _import_runtime(self, definition: ApplicationDefinition) -> type[object]:
        if definition.id in self._runtime_types:
            return self._runtime_types[definition.id]
        safe_id = definition.id.replace("/", "_").replace("-", "_")
        identity = hashlib.sha256(definition.id.encode()).hexdigest()[:16]
        module_name = f"_dix_app_build_{self._namespace}_{safe_id}_{identity}"
        module_spec = importlib.util.spec_from_file_location(
            module_name,
            definition.runtime_path,
            submodule_search_locations=[str(definition.application_root)],
        )
        if module_spec is None or module_spec.loader is None:
            raise ApplicationGeneratorError(
                f"cannot create build-time runtime import for: {definition.id}"
            )
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        try:
            module_spec.loader.exec_module(module)
            runtime_type = getattr(module, "Runtime", None)
            if not inspect.isclass(runtime_type) or runtime_type.__module__ != module_name:
                raise ApplicationGeneratorError(
                    f"application '{definition.id}' must define runtime.py:Runtime"
                )
        except ApplicationGeneratorError:
            self._remove_runtime_modules(module_name)
            raise
        except Exception as exc:
            self._remove_runtime_modules(module_name)
            raise ApplicationGeneratorError(
                f"cannot import application dependency runtime '{definition.id}': {exc}"
            ) from exc
        self._runtime_modules.append(module_name)
        self._runtime_types[definition.id] = runtime_type
        return runtime_type

    @staticmethod
    def _resolve_trusted_root(path: Path) -> Path:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise ApplicationGeneratorError(f"trusted module root does not exist: {path}") from exc
        if not resolved.is_dir():
            raise ApplicationGeneratorError(f"trusted module root is not a directory: {resolved}")
        return resolved

    @staticmethod
    def _remove_runtime_modules(module_name: str) -> None:
        for active_name in tuple(sys.modules):
            if active_name == module_name or active_name.startswith(f"{module_name}."):
                sys.modules.pop(active_name, None)


def _required_functions(
    definition: ApplicationDefinition, alias: str, direct_exports: tuple[str, ...]
) -> tuple[str, ...]:
    result = set(direct_exports)
    for function in definition.functions.values():
        if function.export is None:
            continue
        origin_alias, function_id = function.export.split(".", 1)
        if origin_alias == alias:
            result.add(function_id)
    return tuple(sorted(result))
