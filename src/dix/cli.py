from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import load_effective_config, write_default_config


def _json_print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def cmd_config(args: argparse.Namespace) -> int:
    path = Path(args.path) if getattr(args, "path", None) else Path.cwd() / "dix.toml"
    if args.config_cmd == "init":
        created = write_default_config(path)
        print(f"created: {path!s}" if created else f"exists: {path!s}")
        return 0

    cfg = load_effective_config()
    if args.config_cmd == "validate":
        print("config valid")
        return 0
    if args.config_cmd == "effective":
        _json_print(
            {
                "values": cfg.values,
                "sources": {
                    key: {"source": src.source, "detail": src.detail, "value": src.value}
                    for key, src in cfg.sources.items()
                },
                "loaded_files": [str(p) for p in cfg.loaded_files],
            }
        )
        return 0
    if args.config_cmd == "explain":
        src = cfg.explain(args.key)
        _json_print(
            {"key": src.key, "value": src.value, "source": src.source, "detail": src.detail}
        )
        return 0
    if args.config_cmd == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            raise SystemExit("VISUAL or EDITOR must be set")
        if not path.exists():
            write_default_config(path)
        return subprocess.call([editor, str(path)])
    raise SystemExit(f"unknown config command: {args.config_cmd}")


def _interface_dirs() -> list[Path]:
    cfg = load_effective_config()
    return [Path(item) for item in cfg.values["interface_dirs"]]


def _interface_path(interface_id: str) -> Path:
    base = _interface_dirs()[0]
    return base / f"{interface_id}.toml"


def _read_interface_title(path: Path) -> str:
    from .registry import load_interface

    return load_interface(path).interface.title


def cmd_interface(args: argparse.Namespace) -> int:
    if args.interface_cmd == "list":
        rows = []
        for directory in _interface_dirs():
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.toml")):
                rows.append(
                    {"id": path.stem, "title": _read_interface_title(path), "path": str(path)}
                )
        _json_print(rows)
        return 0

    path = _interface_path(args.id)
    if args.interface_cmd == "new":
        if path.exists():
            raise SystemExit(f"interface already exists: {args.id}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"[interface]\n"
            f'id = "{args.id}"\n'
            f'title = "{args.id.replace("_", " ").title()}"\n'
            f'access = {{ mode = "public" }}\n\n'
            f"[[components]]\n"
            f'id = "title"\n'
            f'use = "input"\n'
            f'config = {{ label = "Title", placeholder = "Enter a title" }}\n\n'
            f"[[components]]\n"
            f'id = "kind"\n'
            f'use = "select"\n'
            f'config = {{ label = "Kind", mode = "single", options = [{{ id = "demo", label = "Demo" }}] }}\n'
        )
        print(f"created: {path}")
        return 0
    if args.interface_cmd == "delete":
        if not path.exists():
            raise SystemExit(f"interface not found: {args.id}")
        if not args.force:
            raise SystemExit("refusing to delete without --force")
        path.unlink()
        print(f"deleted: {path}")
        return 0
    if args.interface_cmd == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            raise SystemExit("VISUAL or EDITOR must be set")
        if not path.exists():
            raise SystemExit(f"interface not found: {args.id}")
        return subprocess.call([editor, str(path)])
    raise SystemExit(f"unknown interface command: {args.interface_cmd}")


def cmd_component(args: argparse.Namespace) -> int:
    if args.component_cmd == "list":
        from .registry import component_definitions

        _json_print([definition.model_dump() for definition in component_definitions()])
        return 0
    raise SystemExit(f"unknown component command: {args.component_cmd}")


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    return serve()


def _composition_runtime():
    from .assembly import assemble_compositions

    effective = load_effective_config()
    return assemble_compositions(effective.composition).compositions


def _module_runtime():
    from .assembly import assemble_compositions

    effective = load_effective_config()
    return assemble_compositions(effective.composition)


def _module_payload(descriptor) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "root": str(descriptor.root),
        "artifact_digest": descriptor.artifact_digest,
        "loaded": descriptor.loaded,
        "composition_ids": list(descriptor.composition_ids),
        "application_ids": list(descriptor.application_ids),
    }


def _definition_payload(definition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "local_id": definition.local_id,
        "module_id": definition.module_id,
        "module_root": str(definition.module_root),
        "composition_root": str(definition.composition_root),
        "spec_path": str(definition.spec_path),
        "runtime_path": str(definition.runtime_path),
        "components": dict(definition.components),
        "compositions": {
            alias: {
                "use": dependency.use,
                "config": dict(dependency.config),
                "export": list(dependency.export),
            }
            for alias, dependency in definition.compositions.items()
        },
        "functions": {
            name: {
                "description": function.description,
                "export": function.export,
            }
            for name, function in definition.functions.items()
        },
    }


def _annotation_text(value: Any) -> str:
    import inspect

    if value is inspect.Signature.empty:
        return ""
    return inspect.formatannotation(value)


def _function_payload(descriptor) -> dict[str, Any]:
    return {
        "id": descriptor.id,
        "composition_id": descriptor.composition_id,
        "source": descriptor.source,
        "origin": descriptor.origin,
        "signature": str(descriptor.signature),
        "return_annotation": _annotation_text(descriptor.return_annotation),
        "docstring": descriptor.docstring,
        "is_async": descriptor.is_async,
    }


def _emit_rows(rows: list[dict[str, Any]], *, json_output: bool, empty: str) -> None:
    if json_output:
        _json_print(rows)
        return
    if not rows:
        print(empty)
        return
    for row in rows:
        identity = row.get("id", "")
        details = ", ".join(
            f"{key}={value}"
            for key, value in row.items()
            if key != "id" and value not in (None, "", [])
        )
        print(f"{identity}: {details}" if details else str(identity))


def cmd_module(args: argparse.Namespace) -> int:
    from .compositions.scaffold import create_module_scaffold

    if args.module_cmd == "new":
        target = create_module_scaffold(Path(args.root), args.id)
        print(f"created: {target}")
        return 0
    if args.module_cmd == "inspect":
        from .core import ModuleComponent, create_core_component_registry

        registry = create_core_component_registry()
        component = registry.require("module", ModuleComponent)
        inspection = component.inspect_module(Path(args.path), module_id=args.id)
        payload = {
            "id": inspection.id,
            "root": str(inspection.root),
            "artifact_digest": inspection.artifact_digest,
            "composition_definitions": [
                _definition_payload(item) for item in inspection.composition_definitions
            ],
            "application_definitions": [
                {
                    "id": item.id,
                    "local_id": item.local_id,
                    "module_id": item.module_id,
                    "spec_path": str(item.spec_path),
                    "runtime_path": str(item.runtime_path),
                }
                for item in inspection.application_definitions
            ],
        }
        if args.json:
            _json_print(payload)
        else:
            _emit_rows([payload], json_output=False, empty="no module")
        return 0

    assembly = _module_runtime()
    modules = assembly.modules
    compositions = assembly.compositions
    from .core import ApplicationComponent

    applications = assembly.components.require("application", ApplicationComponent)
    if args.module_cmd == "list":
        rows = [_module_payload(item) for item in modules.module_descriptors()]
        _emit_rows(rows, json_output=args.json, empty="no loaded modules")
        return 0
    if args.module_cmd == "show":
        modules.require_module(args.id)
        descriptor = next(item for item in modules.module_descriptors() if item.id == args.id)
        payload = _module_payload(descriptor)
        if args.json:
            _json_print(payload)
        else:
            _emit_rows([payload], json_output=False, empty="module not found")
        return 0
    if args.module_cmd == "graph":
        module = modules.require_module(args.id)
        graphs = [
            compositions.describe_dependency_graph(composition_id)
            for composition_id in sorted(module.compositions)
        ]
        application_graphs = [
            applications.describe_dependency_graph(application_id)
            for application_id in sorted(module.applications)
        ]
        payload = {
            "module_id": args.id,
            "compositions": sorted(module.compositions),
            "applications": sorted(module.applications),
            "graphs": [
                {
                    "root": graph.root,
                    "nodes": list(graph.nodes),
                    "edges": [
                        {
                            "source": edge.source,
                            "alias": edge.alias,
                            "target": edge.target,
                            "kind": edge.kind,
                        }
                        for edge in graph.edges
                    ],
                }
                for graph in graphs
            ],
            "application_graphs": [
                {
                    "root": graph.root,
                    "nodes": list(graph.nodes),
                    "edges": [
                        {
                            "source": edge.source,
                            "alias": edge.alias,
                            "target": edge.target,
                            "kind": edge.kind,
                        }
                        for edge in graph.edges
                    ],
                }
                for graph in application_graphs
            ],
        }
        if args.json:
            _json_print(payload)
        else:
            print(f"module: {args.id}")
            for graph in payload["graphs"]:
                print(f"  {graph['root']}")
                for edge in graph["edges"]:
                    print(f"    {edge['kind']} {edge['alias']} -> {edge['target']}")
        return 0
    raise SystemExit(f"unknown module command: {args.module_cmd}")


def cmd_composition(args: argparse.Namespace) -> int:
    from .compositions.scaffold import create_composition_scaffold

    if args.composition_cmd == "generate":
        from .compositions.generator import generate_runtime
        from .compositions.resolver import TrustedBuildFunctionResolver

        effective = load_effective_config()
        with TrustedBuildFunctionResolver(effective.composition.trusted_module_roots) as resolver:
            path = generate_runtime(
                Path(args.path),
                resolver,
                include_lifecycle=args.lifecycle,
            )
        print(f"created: {path}")
        return 0
    if args.composition_cmd == "new":
        exports = list(args.export)
        if args.export_all:
            runtime = _composition_runtime()
            dependencies: dict[str, str] = {}
            for raw_dependency in args.composition:
                alias, separator, target = raw_dependency.partition("=")
                if not separator or not alias or not target:
                    raise ValueError(
                        f"composition must use <alias>=<effective-id>: {raw_dependency}"
                    )
                if alias in dependencies:
                    raise ValueError(f"duplicate composition alias: {alias}")
                dependencies[alias] = target
            for alias in args.export_all:
                if alias not in dependencies:
                    raise ValueError(f"export-all uses unknown composition alias: {alias}")
                exports.extend(
                    f"{alias}.{descriptor.id}"
                    for descriptor in runtime.describe_composition(dependencies[alias]).functions
                )
        path = create_composition_scaffold(
            Path(args.module),
            args.id,
            components=tuple(args.component),
            compositions=tuple(args.composition),
            exports=tuple(exports),
            functions=tuple(args.function),
        )
        print(f"created: {path}")
        return 0

    runtime = _composition_runtime()
    if args.composition_cmd == "list":
        rows = [
            {"id": item.id, "module_id": item.module_id, "local_id": item.local_id}
            for item in runtime.definitions()
        ]
        _emit_rows(rows, json_output=args.json, empty="no loaded compositions")
        return 0
    if args.composition_cmd == "show":
        descriptor = runtime.describe_composition(args.id)
        payload = {
            "definition": _definition_payload(descriptor.definition),
            "module": _module_payload(descriptor.module),
            "functions": [_function_payload(item) for item in descriptor.functions],
        }
        if args.json:
            _json_print(payload)
        else:
            print(f"composition: {descriptor.definition.id}")
            print(f"module: {descriptor.module.id}")
            print(f"source: {descriptor.definition.spec_path}")
        return 0
    if args.composition_cmd == "functions":
        rows = [_function_payload(item) for item in runtime.describe_composition(args.id).functions]
        _emit_rows(rows, json_output=args.json, empty="no declared functions")
        return 0
    if args.composition_cmd == "instance" and args.instance_cmd == "list":
        rows = [
            {
                "id": item.id,
                "scope_id": item.scope_id,
                "root_instance_id": item.root_instance_id,
                "parent_instance_id": item.parent_instance_id,
                "definition_id": item.definition_id,
                "module_id": item.module_id,
                "state": item.state,
            }
            for item in runtime.instances()
        ]
        _emit_rows(rows, json_output=args.json, empty="no composition instances")
        return 0
    raise SystemExit(f"unknown composition command: {args.composition_cmd}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dix", description="Declarative Interface eXecutor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    config_init = config_sub.add_parser("init")
    config_init.add_argument("--path", default=None)
    config_sub.add_parser("validate")
    config_sub.add_parser("effective")
    config_explain = config_sub.add_parser("explain")
    config_explain.add_argument("key")
    config_edit = config_sub.add_parser("edit")
    config_edit.add_argument("--path", default=None)
    config.set_defaults(func=cmd_config)

    interface = sub.add_parser("interface")
    interface_sub = interface.add_subparsers(dest="interface_cmd", required=True)
    interface_sub.add_parser("list")
    interface_new = interface_sub.add_parser("new")
    interface_new.add_argument("id")
    interface_edit = interface_sub.add_parser("edit")
    interface_edit.add_argument("id")
    interface_delete = interface_sub.add_parser("delete")
    interface_delete.add_argument("id")
    interface_delete.add_argument("--force", action="store_true")
    interface.set_defaults(func=cmd_interface)

    component = sub.add_parser("component")
    component_sub = component.add_subparsers(dest="component_cmd", required=True)
    component_sub.add_parser("list")
    component.set_defaults(func=cmd_component)

    module = sub.add_parser("module")
    module_sub = module.add_subparsers(dest="module_cmd", required=True)
    module_new = module_sub.add_parser("new")
    module_new.add_argument("--id", required=True)
    module_new.add_argument("--root", required=True)
    module_list = module_sub.add_parser("list")
    module_list.add_argument("--json", action="store_true")
    module_show = module_sub.add_parser("show")
    module_show.add_argument("id")
    module_show.add_argument("--json", action="store_true")
    module_inspect = module_sub.add_parser("inspect")
    module_inspect.add_argument("path")
    module_inspect.add_argument("--id", required=True)
    module_inspect.add_argument("--json", action="store_true")
    module_graph = module_sub.add_parser("graph")
    module_graph.add_argument("id")
    module_graph.add_argument("--json", action="store_true")
    module.set_defaults(func=cmd_module)

    composition = sub.add_parser("composition")
    composition_sub = composition.add_subparsers(dest="composition_cmd", required=True)
    composition_list = composition_sub.add_parser("list")
    composition_list.add_argument("--json", action="store_true")
    composition_show = composition_sub.add_parser("show")
    composition_show.add_argument("id")
    composition_show.add_argument("--json", action="store_true")
    composition_functions = composition_sub.add_parser("functions")
    composition_functions.add_argument("id")
    composition_functions.add_argument("--json", action="store_true")
    composition_instance = composition_sub.add_parser("instance")
    instance_sub = composition_instance.add_subparsers(dest="instance_cmd", required=True)
    instance_list = instance_sub.add_parser("list")
    instance_list.add_argument("--json", action="store_true")
    composition_new = composition_sub.add_parser("new")
    composition_new.add_argument("--module", required=True)
    composition_new.add_argument("--id", required=True)
    composition_new.add_argument("--component", action="append", default=[])
    composition_new.add_argument("--composition", action="append", default=[])
    composition_new.add_argument("--export", action="append", default=[])
    composition_new.add_argument("--export-all", action="append", default=[])
    composition_new.add_argument("--function", action="append", default=[])
    composition_generate = composition_sub.add_parser("generate")
    composition_generate.add_argument("path")
    composition_generate.add_argument("--lifecycle", action="store_true")
    composition.set_defaults(func=cmd_composition)

    serve = sub.add_parser("serve")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyError as e:
        print(f"unknown key: {e.args[0]}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:
        from .assembly import CompositionAssemblyError
        from .compositions.errors import CompositionGeneratorError
        from .compositions.scaffold import CompositionScaffoldError
        from .core.application import ApplicationComponentError, ApplicationRuntimeError
        from .core.composition import (
            CompositionComponentError,
            CompositionRuntimeError,
            CompositionSpecError,
        )
        from .core.module import ModuleSpecError
        from .core.module.component import ModuleComponentError

        if not isinstance(
            e,
            (
                CompositionAssemblyError,
                CompositionComponentError,
                CompositionRuntimeError,
                CompositionScaffoldError,
                CompositionGeneratorError,
                CompositionSpecError,
                ApplicationComponentError,
                ApplicationRuntimeError,
                ModuleComponentError,
                ModuleSpecError,
            ),
        ):
            raise
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
