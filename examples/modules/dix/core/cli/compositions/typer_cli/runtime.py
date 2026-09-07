from __future__ import annotations

import inspect
import json
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from uuid import uuid4

import click
import typer
from click.testing import CliRunner
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dix.core import (
    DatamodelComponent,
    ElementSpec,
    ModelDefinition,
    RegisteredModel,
    StrandDescriptor,
    model_definition,
)
from dix.core.application import ApplicationDescriptor, ApplicationFunctionDescriptor
from dix.core.composition import CompositionRuntimeContext


class DeclarativeCliError(Exception):
    """Raised when a CLI declaration cannot be normalized or built safely."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CliHeader(_StrictModel):
    name: str = Field(min_length=1)
    description: str = ""
    no_args: Literal["help", "error"] = "error"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _nonempty(value, "CLI name")


class _GroupDeclaration(_StrictModel):
    description: str = ""


class _OptionDeclaration(_StrictModel):
    names: list[str] | None = None
    description: str = ""
    env: list[str] = Field(default_factory=list)
    show_env: bool = True


class _CommandDeclaration(_StrictModel):
    path: list[str] = Field(min_length=1)
    target: str = Field(min_length=1)
    model: str = Field(min_length=1)
    description: str = ""
    options: dict[str, _OptionDeclaration]


class _CliDeclaration(_StrictModel):
    cli: _CliHeader
    groups: dict[str, _GroupDeclaration] = Field(default_factory=dict)
    commands: dict[str, _CommandDeclaration]


class _ModelHeader(_StrictModel):
    name: str = Field(min_length=1)
    version: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _nonempty(value, "model name")

    @field_validator("version")
    @classmethod
    def normalize_version(cls, value: str | None) -> str | None:
        return None if value is None else _nonempty(value, "model version")


class _FieldDeclaration(_StrictModel):
    type: Literal["string", "integer", "boolean"]


class _ModelDeclaration(_StrictModel):
    model: _ModelHeader
    fields: dict[str, _FieldDeclaration]


@dataclass(frozen=True)
class _Target:
    function: Callable[..., object]
    function_id: str
    signature: inspect.Signature


@dataclass(frozen=True)
class _Option:
    field: str
    type_name: Literal["string", "integer", "boolean"]
    names: tuple[str, ...]
    description: str
    env: tuple[str, ...]
    show_env: bool


@dataclass(frozen=True)
class _Command:
    id: str
    path: tuple[str, ...]
    target_id: str
    target: _Target
    model_path: Path
    model: RegisteredModel
    description: str
    options: Mapping[str, _Option]

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True)
class _Cli:
    name: str
    description: str
    no_args: Literal["help", "error"]
    groups: Mapping[str, str]
    commands: Mapping[str, _Command]

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", MappingProxyType(dict(self.groups)))
        object.__setattr__(self, "commands", MappingProxyType(dict(self.commands)))


@dataclass(frozen=True)
class _AutomaticCommand:
    id: str
    descriptor: ApplicationFunctionDescriptor


@dataclass(frozen=True)
class _AutomaticCli:
    name: str
    description: str
    commands: tuple[_AutomaticCommand, ...]


@dataclass(frozen=True)
class _StrandCommand:
    id: str
    descriptor: StrandDescriptor
    model: ModelDefinition


@dataclass(frozen=True)
class _StrandCli:
    name: str
    description: str
    commands: tuple[_StrandCommand, ...]


class Runtime:
    """First-party Typer adapter over explicit DIX application call targets."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
        datamodel: DatamodelComponent,
    ) -> None:
        self.context = context
        self.config = config
        self.datamodel = datamodel
        self._models: dict[Path, RegisteredModel] = {}

    def describe(
        self,
        *,
        spec_path: Path,
        targets: Mapping[str, Mapping[str, object]],
    ) -> Mapping[str, object]:
        """Return one JSON-serializable normalized CLI contract."""
        return _describe_cli(self._normalize(spec_path, targets))

    def build(
        self,
        *,
        spec_path: Path,
        targets: Mapping[str, Mapping[str, object]],
    ) -> typer.Typer:
        """Build a fresh Typer command tree for one normalized declaration."""
        return self._build_cli(self._normalize(spec_path, targets))

    def invoke(
        self,
        *,
        spec_path: Path,
        targets: Mapping[str, Mapping[str, object]],
        argv: Sequence[str],
    ) -> int:
        """Invoke one CLI without terminating the embedding process."""
        try:
            application = self.build(spec_path=spec_path, targets=targets)
        except (DeclarativeCliError, ValidationError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

        command = typer.main.get_command(application)
        result = CliRunner().invoke(
            command,
            list(argv),
            prog_name=application.info.name or "dix",
            catch_exceptions=True,
        )
        if result.stdout:
            sys.stdout.write(result.stdout)
        if result.stderr:
            sys.stderr.write(result.stderr)
        if (
            result.exception is not None
            and not isinstance(result.exception, SystemExit)
            and result.exit_code == 1
        ):
            print(f"Error: {result.exception}", file=sys.stderr)
        return int(result.exit_code)

    def describe_application(
        self,
        *,
        descriptor: ApplicationDescriptor,
    ) -> Mapping[str, object]:
        """Describe the strict automatic CLI projection without creating an app instance."""
        cli = self._normalize_application(descriptor)
        return {
            "name": cli.name,
            "description": cli.description,
            "commands": {
                command.id: _describe_function_contract(command.descriptor)
                for command in cli.commands
            },
        }

    def build_application(
        self,
        *,
        descriptor: ApplicationDescriptor,
        invoke: Callable[[str, Sequence[object], Mapping[str, object]], object],
    ) -> typer.Typer:
        """Build a fresh CLI directly from one loaded application descriptor."""
        return self._build_application_cli(
            self._normalize_application(descriptor),
            invoke,
        )

    def invoke_application(
        self,
        *,
        descriptor: ApplicationDescriptor,
        invoke: Callable[[str, Sequence[object], Mapping[str, object]], object],
        argv: Sequence[str],
    ) -> int:
        """Invoke an automatic CLI without terminating the embedding process."""
        try:
            application = self.build_application(descriptor=descriptor, invoke=invoke)
        except (DeclarativeCliError, ValidationError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return _invoke_typer(application, argv)

    def describe_strands(
        self,
        *,
        name: str,
        descriptors: Sequence[StrandDescriptor],
    ) -> Mapping[str, object]:
        """Describe a CLI projected only from bound strand contracts."""
        cli = self._normalize_strands(name, descriptors)
        return {
            "name": cli.name,
            "description": cli.description,
            "commands": {
                command.id: _describe_strand_contract(command)
                for command in cli.commands
            },
        }

    def build_strands(
        self,
        *,
        name: str,
        descriptors: Sequence[StrandDescriptor],
        invoke: Callable[[str, Mapping[str, object]], object],
    ) -> typer.Typer:
        """Build a fresh CLI from bound strand contracts."""
        return self._build_strand_cli(
            self._normalize_strands(name, descriptors),
            invoke,
        )

    def invoke_strands(
        self,
        *,
        name: str,
        descriptors: Sequence[StrandDescriptor],
        invoke: Callable[[str, Mapping[str, object]], object],
        argv: Sequence[str],
    ) -> int:
        """Invoke a strand-driven CLI without terminating the embedding process."""
        try:
            application = self.build_strands(
                name=name,
                descriptors=descriptors,
                invoke=invoke,
            )
        except (DeclarativeCliError, ValidationError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return _invoke_typer(application, argv)

    def _normalize(
        self,
        spec_path: Path,
        targets: Mapping[str, Mapping[str, object]],
    ) -> _Cli:
        path = _canonical_file(spec_path, "CLI declaration")
        declaration = _parse_cli(path)
        normalized_targets = _normalize_targets(targets)
        groups = {
            _identifier(group_id, "group id"): group.description
            for group_id, group in declaration.groups.items()
        }
        command_paths: set[tuple[str, ...]] = set()
        environment_names: set[str] = set()
        commands: dict[str, _Command] = {}
        for raw_id, command in declaration.commands.items():
            command_id = _identifier(raw_id, "command id")
            command_path = tuple(
                _command_segment(segment, command_id) for segment in command.path
            )
            if len(command_path) > 2:
                raise DeclarativeCliError(
                    f"command '{command_id}' supports at most one group in this contract"
                )
            if len(command_path) == 2 and command_path[0] not in groups:
                raise DeclarativeCliError(
                    f"command '{command_id}' references unknown group '{command_path[0]}'"
                )
            if command_path in command_paths:
                raise DeclarativeCliError(
                    f"duplicate command path: {' '.join(command_path)}"
                )
            command_paths.add(command_path)
            try:
                target = normalized_targets[command.target]
            except KeyError as exc:
                raise DeclarativeCliError(
                    f"command '{command_id}' references unavailable target '{command.target}'"
                ) from exc
            model_path = _resolve_relative(path.parent, command.model)
            model = self._load_model(model_path)
            model_fields = set(model.definition.schema)
            option_fields = set(command.options)
            if model_fields != option_fields:
                missing = sorted(model_fields - option_fields)
                additional = sorted(option_fields - model_fields)
                raise DeclarativeCliError(
                    f"command '{command_id}' option/model mismatch: "
                    f"missing={missing}, additional={additional}"
                )
            _validate_target_binding(command_id, model_fields, target.signature)
            options: dict[str, _Option] = {}
            used_names: set[str] = set()
            for field_name in model.definition.schema:
                field_id = _identifier(field_name, "model field")
                option = command.options[field_name]
                names = _option_names(field_id, option.names)
                duplicate_names = sorted(used_names.intersection(names))
                if duplicate_names:
                    raise DeclarativeCliError(
                        f"duplicate option name in command '{command_id}': {duplicate_names[0]}"
                    )
                used_names.update(names)
                env = tuple(_environment_name(item, command_id) for item in option.env)
                duplicate_env = sorted(environment_names.intersection(env))
                if duplicate_env:
                    raise DeclarativeCliError(
                        f"environment name is used more than once: {duplicate_env[0]}"
                    )
                environment_names.update(env)
                type_name = model.definition.schema[field_name].type
                if type_name not in {"string", "integer", "boolean"}:
                    raise DeclarativeCliError(
                        f"unsupported CLI model type for '{field_name}': {type_name}"
                    )
                options[field_name] = _Option(
                    field=field_name,
                    type_name=type_name,
                    names=names,
                    description=option.description,
                    env=env,
                    show_env=option.show_env,
                )
            commands[command_id] = _Command(
                id=command_id,
                path=command_path,
                target_id=command.target,
                target=target,
                model_path=model_path,
                model=model,
                description=command.description,
                options=options,
            )
        return _Cli(
            name=declaration.cli.name,
            description=declaration.cli.description,
            no_args=declaration.cli.no_args,
            groups=groups,
            commands=commands,
        )

    def _load_model(self, path: Path) -> RegisteredModel:
        cached = self._models.get(path)
        if cached is not None:
            return cached
        declaration = _parse_model(path)
        definition = ModelDefinition(
            uid=uuid4(),
            name=declaration.model.name,
            version=declaration.model.version,
            schema={
                field_name: ElementSpec(type=field.type)
                for field_name, field in declaration.fields.items()
            },
        )
        registered = self.datamodel.register_model(definition)
        self._models[path] = registered
        return registered

    def _build_cli(self, cli: _Cli) -> typer.Typer:
        application = typer.Typer(
            name=cli.name,
            help=cli.description,
            add_completion=False,
            no_args_is_help=False,
            invoke_without_command=True,
            pretty_exceptions_enable=False,
        )

        @application.callback()
        def root(context: typer.Context) -> None:
            if context.invoked_subcommand is not None:
                return
            if cli.no_args == "help":
                typer.echo(context.get_help())
                return
            raise click.UsageError("Missing command.", context)

        group_apps: dict[str, typer.Typer] = {}
        for group_id, description in cli.groups.items():
            group = typer.Typer(
                help=description,
                add_completion=False,
                no_args_is_help=True,
                pretty_exceptions_enable=False,
            )
            application.add_typer(group, name=group_id, help=description)
            group_apps[group_id] = group
        for command in cli.commands.values():
            parent = application if len(command.path) == 1 else group_apps[command.path[0]]
            callback = self._command_callback(command)
            parent.command(name=command.path[-1], help=command.description)(callback)
        return application

    def _normalize_application(self, descriptor: ApplicationDescriptor) -> _AutomaticCli:
        if not isinstance(descriptor, ApplicationDescriptor):
            raise DeclarativeCliError("automatic CLI requires an ApplicationDescriptor")
        commands: list[_AutomaticCommand] = []
        command_names: set[str] = set()
        for function in descriptor.functions:
            command_id = function.id.replace("_", "-")
            if command_id in command_names:
                raise DeclarativeCliError(
                    f"automatic CLI command name collision: {command_id}"
                )
            command_names.add(command_id)
            for parameter in function.contract.parameters:
                if parameter.kind in {
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                }:
                    raise DeclarativeCliError(
                        f"function '{function.id}' uses unsupported variadic parameter "
                        f"'{parameter.name}'"
                    )
                if parameter.projection != "exact":
                    raise DeclarativeCliError(
                        f"function '{function.id}' parameter '{parameter.name}' uses "
                        "unsupported fallback_any projection"
                    )
            commands.append(_AutomaticCommand(command_id, function))
        definition = descriptor.definition
        return _AutomaticCli(
            name=definition.id,
            description=f"Automatic CLI for {definition.id}.",
            commands=tuple(commands),
        )

    def _build_application_cli(
        self,
        cli: _AutomaticCli,
        invoke: Callable[[str, Sequence[object], Mapping[str, object]], object],
    ) -> typer.Typer:
        if not callable(invoke):
            raise DeclarativeCliError("automatic CLI invoke target must be callable")
        application = typer.Typer(
            name=cli.name,
            help=cli.description,
            add_completion=False,
            no_args_is_help=True,
            pretty_exceptions_enable=False,
        )

        @application.callback()
        def automatic_root() -> None:
            """Automatic application command group."""

        for command in cli.commands:
            callback = _automatic_callback(command, invoke)
            application.command(
                name=command.id,
                help=command.descriptor.docstring or command.descriptor.id,
            )(callback)
        return application

    def _normalize_strands(
        self,
        name: str,
        descriptors: Sequence[StrandDescriptor],
    ) -> _StrandCli:
        cli_name = _nonempty(name, "strand CLI name")
        commands: list[_StrandCommand] = []
        command_names: set[str] = set()
        strand_ids: set[str] = set()
        for descriptor in descriptors:
            if not isinstance(descriptor, StrandDescriptor):
                raise DeclarativeCliError("strand CLI requires StrandDescriptor values")
            if descriptor.id in strand_ids:
                raise DeclarativeCliError(f"duplicate strand descriptor: {descriptor.id}")
            strand_ids.add(descriptor.id)
            if not descriptor.bound:
                raise DeclarativeCliError(f"strand is not bound: {descriptor.id}")
            try:
                model = model_definition(descriptor.input_element)
            except Exception as exc:
                raise DeclarativeCliError(
                    f"strand input is not a model element: {descriptor.id}"
                ) from exc
            command_id = descriptor.id.rsplit("/", 1)[-1].replace("_", "-")
            if command_id in command_names:
                raise DeclarativeCliError(
                    f"strand CLI command name collision: {command_id}"
                )
            command_names.add(command_id)
            for field_name, element in model.schema.items():
                _identifier(field_name, "strand model field")
                if element.type not in {"string", "integer", "number", "boolean"}:
                    raise DeclarativeCliError(
                        f"unsupported strand CLI model type for '{field_name}': {element.type}"
                    )
            commands.append(_StrandCommand(command_id, descriptor, model))
        return _StrandCli(
            name=cli_name,
            description=f"Automatic strand CLI for {cli_name}.",
            commands=tuple(commands),
        )

    def _build_strand_cli(
        self,
        cli: _StrandCli,
        invoke: Callable[[str, Mapping[str, object]], object],
    ) -> typer.Typer:
        if not callable(invoke):
            raise DeclarativeCliError("strand CLI invoke target must be callable")
        application = typer.Typer(
            name=cli.name,
            help=cli.description,
            add_completion=False,
            no_args_is_help=True,
            pretty_exceptions_enable=False,
        )

        @application.callback()
        def strand_root() -> None:
            """Automatic strand command group."""

        for command in cli.commands:
            callback = _strand_callback(command, invoke)
            application.command(name=command.id, help=command.descriptor.id)(callback)
        return application

    def _command_callback(self, command: _Command) -> Callable[..., None]:
        def callback(**values: object) -> None:
            result = self.datamodel.instantiate(command.model, values)
            if not result.compatible:
                details = "; ".join(
                    f"{issue.field or '<model>'}: {issue.message}" for issue in result.issues
                )
                raise click.UsageError(f"datamodel rejected input: {details}")
            output = command.target.function(**dict(result.values))
            if isinstance(output, str):
                typer.echo(output)
            elif output is not None:
                raise DeclarativeCliError(
                    f"target '{command.target_id}' returned unsupported output type "
                    f"'{type(output).__name__}'"
                )

        callback.__name__ = f"command_{command.id}"
        callback.__doc__ = command.description
        callback.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            parameters=tuple(_parameter(option) for option in command.options.values())
        )
        return callback


def _parameter(option: _Option) -> inspect.Parameter:
    # A bool annotation makes Typer build a presence-only flag. DIX booleans are required
    # values in this profile, so the adapter parses explicit true/false strings itself.
    annotation = {"string": str, "integer": int, "boolean": str}[option.type_name]
    boolean_value = option.type_name == "boolean"
    default = typer.Option(
        ...,
        *option.names,
        help=option.description,
        envvar=option.env[0] if len(option.env) == 1 else list(option.env) or None,
        show_envvar=option.show_env,
        callback=_parse_boolean if boolean_value else None,
        metavar="TRUE|FALSE" if boolean_value else None,
    )
    return inspect.Parameter(
        option.field,
        inspect.Parameter.KEYWORD_ONLY,
        default=default,
        annotation=annotation,
    )


def _automatic_callback(
    command: _AutomaticCommand,
    invoke: Callable[[str, Sequence[object], Mapping[str, object]], object],
) -> Callable[..., None]:
    descriptor = command.descriptor

    def callback(**values: object) -> None:
        positional: list[object] = []
        keyword: dict[str, object] = {}
        for parameter in descriptor.contract.parameters:
            value = values[parameter.name]
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(value)
            else:
                keyword[parameter.name] = value
        output = invoke(descriptor.id, tuple(positional), keyword)
        _write_automatic_output(descriptor.id, output)

    callback.__name__ = f"automatic_{command.id.replace('-', '_')}"
    callback.__doc__ = descriptor.docstring or descriptor.id
    callback.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=tuple(
            _automatic_parameter(parameter)
            for parameter in descriptor.contract.parameters
        )
    )
    return callback


def _automatic_parameter(parameter) -> inspect.Parameter:
    annotation = {
        "string": str,
        "integer": int,
        "boolean": str,
    }[parameter.element_type]
    boolean_value = parameter.element_type == "boolean"
    default_value = ... if parameter.required else parameter.default
    if boolean_value and default_value is not ... and isinstance(default_value, bool):
        default_value = "true" if default_value else "false"
    default = typer.Option(
        default_value,
        f"--{parameter.name.replace('_', '-')}",
        help=f"{parameter.name} ({parameter.element_type}).",
        callback=_parse_boolean if boolean_value else None,
        metavar="TRUE|FALSE" if boolean_value else None,
    )
    return inspect.Parameter(
        parameter.name,
        inspect.Parameter.KEYWORD_ONLY,
        default=default,
        annotation=annotation,
    )


def _strand_callback(
    command: _StrandCommand,
    invoke: Callable[[str, Mapping[str, object]], object],
) -> Callable[..., None]:
    def callback(**values: object) -> None:
        output = invoke(command.descriptor.id, values)
        _write_automatic_output(command.descriptor.id, output)

    callback.__name__ = f"strand_{command.id.replace('-', '_')}"
    callback.__doc__ = command.descriptor.id
    callback.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=tuple(
            _strand_parameter(field_name, element)
            for field_name, element in command.model.schema.items()
        )
    )
    return callback


def _strand_parameter(field_name: str, element: ElementSpec) -> inspect.Parameter:
    annotation = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": str,
    }[element.type]
    boolean_value = element.type == "boolean"
    option = typer.Option(
        ...,
        f"--{field_name.replace('_', '-')}",
        help=f"{field_name} ({element.type}).",
        callback=_parse_boolean if boolean_value else None,
        metavar="TRUE|FALSE" if boolean_value else None,
    )
    return inspect.Parameter(
        field_name,
        inspect.Parameter.KEYWORD_ONLY,
        default=option,
        annotation=annotation,
    )


def _write_automatic_output(function_id: str, output: object) -> None:
    if output is None:
        return
    if isinstance(output, str):
        typer.echo(output)
        return
    if isinstance(output, bool):
        typer.echo("true" if output else "false")
        return
    if isinstance(output, int):
        typer.echo(str(output))
        return
    if isinstance(output, float):
        typer.echo(str(output))
        return
    if isinstance(output, (Mapping, list)):
        try:
            rendered = json.dumps(
                _json_value(output),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise DeclarativeCliError(
                f"function '{function_id}' returned non-JSON-compatible output"
            ) from exc
        typer.echo(rendered)
        return
    raise DeclarativeCliError(
        f"function '{function_id}' returned unsupported output type "
        f"'{type(output).__name__}'"
    )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _invoke_typer(application: typer.Typer, argv: Sequence[str]) -> int:
    command = typer.main.get_command(application)
    result = CliRunner().invoke(
        command,
        list(argv),
        prog_name=application.info.name or "dix",
        catch_exceptions=True,
    )
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    if (
        result.exception is not None
        and not isinstance(result.exception, SystemExit)
        and result.exit_code == 1
    ):
        print(f"Error: {result.exception}", file=sys.stderr)
    return int(result.exit_code)


def _describe_function_contract(
    descriptor: ApplicationFunctionDescriptor,
) -> Mapping[str, object]:
    return {
        "function": descriptor.id,
        "async": descriptor.is_async,
        "input_model": {
            "uid": str(descriptor.contract.input_model.uid),
            "name": descriptor.contract.input_model.name,
            "version": descriptor.contract.input_model.version,
        },
        "parameters": [
            {
                "name": parameter.name,
                "kind": parameter.kind.name,
                "required": parameter.required,
                "has_default": parameter.has_default,
                "default": (
                    parameter.default
                    if parameter.has_default
                    and isinstance(parameter.default, (str, int, bool, type(None)))
                    else None
                ),
                "annotation": _annotation_text(parameter.annotation),
                "element_type": parameter.element_type,
                "projection": parameter.projection,
            }
            for parameter in descriptor.contract.parameters
        ],
        "output": {
            "annotation": _annotation_text(descriptor.contract.output.annotation),
            "element_type": descriptor.contract.output.element.type,
            "projection": descriptor.contract.output.projection,
        },
    }


def _describe_strand_contract(command: _StrandCommand) -> Mapping[str, object]:
    descriptor = command.descriptor
    return {
        "strand": descriptor.id,
        "bound": descriptor.bound,
        "handler": descriptor.handler_id,
        "input_model": {
            "uid": str(command.model.uid),
            "name": command.model.name,
            "version": command.model.version,
            "fields": {
                field_name: {"type": element.type}
                for field_name, element in command.model.schema.items()
            },
        },
        "output": {"type": descriptor.output_element.type},
    }


def _annotation_text(annotation: object) -> str | None:
    if annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", repr(annotation))


def _parse_boolean(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise typer.BadParameter("expected 'true' or 'false'")


def _parse_cli(path: Path) -> _CliDeclaration:
    try:
        return _CliDeclaration.model_validate(tomllib.loads(path.read_text()))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise DeclarativeCliError(f"invalid CLI declaration {path}: {exc}") from exc


def _parse_model(path: Path) -> _ModelDeclaration:
    try:
        return _ModelDeclaration.model_validate(tomllib.loads(path.read_text()))
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise DeclarativeCliError(f"invalid model declaration {path}: {exc}") from exc


def _normalize_targets(
    targets: Mapping[str, Mapping[str, object]],
) -> Mapping[str, _Target]:
    if not isinstance(targets, Mapping):
        raise DeclarativeCliError("targets must be a mapping")
    normalized: dict[str, _Target] = {}
    for raw_id, raw_target in targets.items():
        target_id = _target_id(raw_id)
        if not isinstance(raw_target, Mapping) or set(raw_target) != {"function", "descriptor"}:
            raise DeclarativeCliError(
                f"target '{target_id}' must contain exactly 'function' and 'descriptor'"
            )
        function = raw_target["function"]
        descriptor = raw_target["descriptor"]
        signature = getattr(descriptor, "signature", None)
        function_id = getattr(descriptor, "id", None)
        if not callable(function):
            raise DeclarativeCliError(f"target '{target_id}' function is not callable")
        if not isinstance(signature, inspect.Signature) or not isinstance(function_id, str):
            raise DeclarativeCliError(f"target '{target_id}' descriptor is invalid")
        normalized[target_id] = _Target(function, function_id, signature)
    return MappingProxyType(normalized)


def _validate_target_binding(
    command_id: str,
    model_fields: set[str],
    signature: inspect.Signature,
) -> None:
    parameters = tuple(signature.parameters.values())
    invalid = [
        parameter.name
        for parameter in parameters
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }
    ]
    if invalid:
        raise DeclarativeCliError(
            f"command '{command_id}' target uses unsupported parameters: {invalid}"
        )
    parameter_names = {parameter.name for parameter in parameters}
    if model_fields != parameter_names:
        raise DeclarativeCliError(
            f"command '{command_id}' model/target mismatch: "
            f"missing={sorted(parameter_names - model_fields)}, "
            f"additional={sorted(model_fields - parameter_names)}"
        )


def _describe_cli(cli: _Cli) -> Mapping[str, object]:
    return {
        "cli": {
            "name": cli.name,
            "description": cli.description,
            "no_args": cli.no_args,
        },
        "groups": {
            group_id: {"description": description}
            for group_id, description in cli.groups.items()
        },
        "commands": {
            command_id: {
                "path": list(command.path),
                "target": command.target_id,
                "model": str(command.model_path),
                "description": command.description,
                "options": {
                    field: {
                        "type": option.type_name,
                        "names": list(option.names),
                        "description": option.description,
                        "env": list(option.env),
                        "show_env": option.show_env,
                    }
                    for field, option in command.options.items()
                },
            }
            for command_id, command in cli.commands.items()
        },
    }


def _canonical_file(path: Path, label: str) -> Path:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise DeclarativeCliError(f"{label} does not exist: {path}") from exc
    if not resolved.is_file():
        raise DeclarativeCliError(f"{label} is not a file: {resolved}")
    return resolved


def _resolve_relative(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return _canonical_file(path if path.is_absolute() else base / path, "model declaration")


def _nonempty(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _identifier(value: str, label: str) -> str:
    normalized = _nonempty(value, label)
    if not normalized.isidentifier():
        raise DeclarativeCliError(f"invalid {label}: {value!r}")
    return normalized


def _command_segment(value: str, command_id: str) -> str:
    normalized = _nonempty(value, f"command path segment for '{command_id}'")
    if normalized.startswith("-") or any(character.isspace() for character in normalized):
        raise DeclarativeCliError(
            f"invalid command path segment for '{command_id}': {value!r}"
        )
    return normalized


def _target_id(value: object) -> str:
    if not isinstance(value, str):
        raise DeclarativeCliError("target id must be a string")
    normalized = _nonempty(value, "target id")
    parts = normalized.split(".")
    if len(parts) != 2 or any(not part.isidentifier() for part in parts):
        raise DeclarativeCliError(f"invalid target id: {value!r}")
    return normalized


def _option_names(field: str, configured: list[str] | None) -> tuple[str, ...]:
    names = tuple(configured) if configured is not None else (f"--{field.replace('_', '-')}",)
    if not names:
        raise DeclarativeCliError(f"option '{field}' must declare at least one name")
    normalized: list[str] = []
    for name in names:
        if not isinstance(name, str) or not name.startswith("-") or name in {"-", "--"}:
            raise DeclarativeCliError(f"invalid option name for '{field}': {name!r}")
        if name.startswith("--") and len(name) < 3:
            raise DeclarativeCliError(f"invalid option name for '{field}': {name!r}")
        if name.startswith("-") and not name.startswith("--") and len(name) != 2:
            raise DeclarativeCliError(f"invalid short option name for '{field}': {name!r}")
        if any(character.isspace() for character in name):
            raise DeclarativeCliError(f"invalid option name for '{field}': {name!r}")
        normalized.append(name)
    if len(set(normalized)) != len(normalized):
        raise DeclarativeCliError(f"duplicate option name for '{field}'")
    return tuple(normalized)


def _environment_name(value: str, command_id: str) -> str:
    normalized = _nonempty(value, f"environment name for '{command_id}'")
    if not normalized.replace("_", "A").isalnum() or normalized[0].isdigit():
        raise DeclarativeCliError(
            f"invalid environment name for command '{command_id}': {value!r}"
        )
    return normalized
