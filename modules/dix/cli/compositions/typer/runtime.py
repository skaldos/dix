from __future__ import annotations

import asyncio
import inspect
import re
import sys
import typing
from collections.abc import Callable, Mapping, Sequence

import click
import typer
from click.testing import CliRunner

from dix.core.application import ApplicationApi, ApplicationFunctionDescriptor
from dix.core.composition import CompositionRuntimeContext


class TyperProjectionError(ValueError):
    """Raised when a local application API cannot be represented by this CLI adapter."""


class Runtime:
    """Project explicit application APIs into one ephemeral Typer command tree."""

    def __init__(
        self,
        *,
        context: CompositionRuntimeContext,
        config: Mapping[str, object],
    ) -> None:
        self.context = context
        self.config = config

    def invoke(
        self,
        *,
        name: str,
        targets: Mapping[str, ApplicationApi],
        argv: Sequence[str],
    ) -> int:
        """Build and invoke one CLI without terminating the embedding Python process."""
        try:
            application = _build_application(name, targets)
            command = typer.main.get_command(application)
        # The CLI adapter is the error boundary for arbitrary target applications.
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}", file=sys.stderr)
            return 2

        result = CliRunner().invoke(
            command,
            list(argv),
            prog_name=name,
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


def _build_application(name: str, targets: Mapping[str, ApplicationApi]) -> typer.Typer:
    cli_name = _nonempty(name, "CLI name")
    if not isinstance(targets, Mapping) or not targets:
        raise TyperProjectionError("targets must be a non-empty mapping")

    application = typer.Typer(
        name=cli_name,
        help=f"Commands composed by {cli_name}.",
        add_completion=False,
        no_args_is_help=True,
        pretty_exceptions_enable=False,
    )
    environment_names: set[str] = set()
    for group_id in sorted(targets):
        group_name = _nonempty(group_id, "target group id")
        target = targets[group_id]
        if not isinstance(target, ApplicationApi):
            raise TyperProjectionError(
                f"target group '{group_name}' must contain an ApplicationApi"
            )
        descriptors = target.functions()
        group = typer.Typer(
            help=f"Commands exposed by application group {group_name}.",
            add_completion=False,
            no_args_is_help=True,
            pretty_exceptions_enable=False,
        )
        application.add_typer(group, name=group_name)
        for descriptor in descriptors:
            function = target.require(descriptor.id)
            callback = _callback(
                cli_name,
                group_name,
                descriptor,
                function,
                environment_names,
            )
            group.command(
                name=descriptor.id,
                help=descriptor.docstring or descriptor.id,
            )(callback)
    return application


def _callback(
    cli_name: str,
    group_name: str,
    descriptor: ApplicationFunctionDescriptor,
    function: Callable[..., object],
    environment_names: set[str],
) -> Callable[..., None]:
    signature = inspect.signature(function)
    try:
        type_hints = typing.get_type_hints(function)
    except Exception as exc:
        raise TyperProjectionError(
            f"cannot resolve annotations for '{group_name}.{descriptor.id}': {exc}"
        ) from exc

    parameters = tuple(
        _option_parameter(
            cli_name,
            group_name,
            descriptor.id,
            parameter,
            type_hints,
            environment_names,
        )
        for parameter in signature.parameters.values()
    )

    def callback(**values: object) -> None:
        output = function(**values)
        if inspect.isawaitable(output):
            output = asyncio.run(output)
        if output is not None:
            typer.echo(output)

    callback.__name__ = f"dix_{group_name}_{descriptor.id}"
    callback.__doc__ = descriptor.docstring or descriptor.id
    callback.__signature__ = inspect.Signature(parameters=parameters)  # type: ignore[attr-defined]
    return callback


def _option_parameter(
    cli_name: str,
    group_name: str,
    function_id: str,
    parameter: inspect.Parameter,
    type_hints: Mapping[str, object],
    environment_names: set[str],
) -> inspect.Parameter:
    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
        raise TyperProjectionError(
            f"function '{group_name}.{function_id}' uses unsupported positional-only parameter "
            f"'{parameter.name}'"
        )
    if parameter.kind in {
        inspect.Parameter.VAR_POSITIONAL,
        inspect.Parameter.VAR_KEYWORD,
    }:
        raise TyperProjectionError(
            f"function '{group_name}.{function_id}' uses unsupported variadic parameter "
            f"'{parameter.name}'"
        )
    annotation = type_hints.get(parameter.name, parameter.annotation)
    if annotation is inspect.Parameter.empty:
        raise TyperProjectionError(
            f"function '{group_name}.{function_id}' parameter '{parameter.name}' "
            "has no annotation"
        )

    environment_name = _environment_name(
        cli_name,
        group_name,
        function_id,
        parameter.name,
    )
    if environment_name in environment_names:
        raise TyperProjectionError(
            f"environment name collision for '{group_name}.{function_id}.{parameter.name}': "
            f"{environment_name}"
        )
    environment_names.add(environment_name)

    required = parameter.default is inspect.Parameter.empty
    default: object = ... if required else parameter.default
    callback: Callable[[object], object] | None = None
    metavar: str | None = None
    typer_annotation = annotation
    if annotation is bool:
        typer_annotation = str
        callback = _parse_boolean
        metavar = "TRUE|FALSE"
        if isinstance(default, bool):
            default = "true" if default else "false"

    option = typer.Option(
        default,
        f"--{parameter.name}",
        help=f"Value for {parameter.name}.",
        envvar=environment_name,
        show_envvar=True,
        callback=callback,
        metavar=metavar,
    )
    return parameter.replace(
        kind=inspect.Parameter.KEYWORD_ONLY,
        default=option,
        annotation=typer_annotation,
    )


def _parse_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise click.BadParameter("must be either true or false")


def _environment_name(*parts: str) -> str:
    normalized = [re.sub(r"[^A-Z0-9]+", "_", part.upper()).strip("_") for part in parts]
    if any(not part for part in normalized):
        raise TyperProjectionError("CLI identifiers must produce non-empty environment segments")
    return "_".join(normalized)


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TyperProjectionError(f"{label} must be a non-empty string")
    return value.strip()
