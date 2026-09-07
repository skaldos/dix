from __future__ import annotations

import json
import tomllib
from pathlib import Path

from dix.cli import main


def write_composition(module: Path) -> None:
    root = module / "compositions" / "base"
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(
        '[composition]\nid = "base"\n[functions.echo]\ndescription = "Echo a value."\n'
    )
    (root / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self, value: str) -> str:\n"
        '        """Echo a value."""\n'
        "        return value\n"
    )


def write_application(module: Path, local_id: str, spec: str, runtime: str) -> None:
    root = module / "apps" / local_id
    root.mkdir(parents=True)
    (root / "app.toml").write_text(spec)
    (root / "runtime.py").write_text(runtime)


def configured_project(tmp_path: Path) -> Path:
    module = tmp_path / "modules" / "acme" / "demo"
    write_composition(module)
    write_application(
        module,
        "base",
        '[app]\nid = "base"\n[functions.ping]\ndescription = "Return a pong."\n',
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def ping(self) -> str:\n"
        '        """Return a pong."""\n'
        "        return 'pong'\n",
    )
    write_application(
        module,
        "child",
        """[app]
id = "child"
[compositions.values]
use = "acme/demo/base"
export = ["echo"]
[apps.worker]
use = "acme/demo/base"
export = ["ping"]
""",
        "class Runtime:\n"
        "    def __init__(self, *, context, config, values, worker):\n"
        "        self.values = values\n"
        "        self.worker = worker\n"
        "    def echo(self, value: str) -> str:\n"
        "        return self.values.echo(value)\n"
        "    def ping(self) -> str:\n"
        "        return self.worker.ping()\n",
    )
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    return module


def test_mixed_module_and_application_introspection(tmp_path: Path, monkeypatch, capsys) -> None:
    module = configured_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["module", "list", "--json"]) == 0
    modules = json.loads(capsys.readouterr().out)
    assert modules[0]["composition_ids"] == ["acme/demo/base"]
    assert modules[0]["application_ids"] == ["acme/demo/base", "acme/demo/child"]

    assert main(["module", "inspect", str(module), "--id", "acme/demo", "--json"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["composition_definitions"][0]["id"] == "acme/demo/base"
    assert [item["id"] for item in inspected["application_definitions"]] == [
        "acme/demo/base",
        "acme/demo/child",
    ]
    assert inspected["application_definitions"][1]["applications"]["worker"]["use"] == (
        "acme/demo/base"
    )

    assert main(["module", "graph", "acme/demo", "--json"]) == 0
    module_graph = json.loads(capsys.readouterr().out)
    child = next(
        graph for graph in module_graph["application_graphs"] if graph["root"] == "acme/demo/child"
    )
    assert {edge["kind"] for edge in child["edges"]} == {"composition", "application"}

    assert main(["app", "list", "--json"]) == 0
    apps = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in apps] == ["acme/demo/base", "acme/demo/child"]

    assert main(["app", "functions", "acme/demo/child", "--json"]) == 0
    functions = json.loads(capsys.readouterr().out)
    echo = next(item for item in functions if item["id"] == "echo")
    assert echo["application_id"] == "acme/demo/child"
    assert echo["origin"] == "values.echo"
    assert echo["signature"] == "(value: str) -> str"
    assert echo["return_annotation"] == "str"
    assert echo["is_async"] is False

    assert main(["app", "show", "acme/demo/child", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["definition"]["id"] == "acme/demo/child"
    assert shown["functions"] == functions

    assert main(["app", "graph", "acme/demo/child", "--json"]) == 0
    graph = json.loads(capsys.readouterr().out)
    assert {edge["kind"] for edge in graph["edges"]} == {"composition", "application"}


def test_human_application_output_uses_descriptor_fields(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    configured_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["app", "functions", "acme/demo/child"]) == 0
    output = capsys.readouterr().out
    assert "values.echo" in output
    assert "(value: str) -> str" in output
    assert main(["app", "graph", "acme/demo/child"]) == 0
    output = capsys.readouterr().out
    assert "composition values -> acme/demo/base" in output
    assert "application worker -> acme/demo/base" in output


def test_application_scaffold_is_sorted_small_and_non_overwriting(tmp_path: Path, capsys) -> None:
    root = tmp_path / "modules"
    assert main(["module", "new", "--id", "my/new_stuff", "--root", str(root)]) == 0
    module = root / "my" / "new_stuff"
    assert (module / "compositions").is_dir()
    assert (module / "apps").is_dir()
    capsys.readouterr()

    command = [
        "app",
        "new",
        "--module",
        str(module),
        "--id",
        "runner",
        "--composition",
        "values=acme/demo/base",
        "--app",
        "worker=acme/demo/worker",
        "--export",
        "values.echo",
        "--export",
        "worker.ping",
        "--function",
        "local_value",
    ]
    assert main(command) == 0
    spec = module / "apps" / "runner" / "app.toml"
    payload = tomllib.loads(spec.read_text())
    assert payload["compositions"]["values"]["export"] == ["echo"]
    assert payload["apps"]["worker"]["export"] == ["ping"]
    assert "TODO" in payload["functions"]["local_value"]["description"]
    assert (spec.parent / "runtime.py").exists() is False
    original = spec.read_text()
    capsys.readouterr()

    assert main(command) == 2
    assert "already exists" in capsys.readouterr().err
    assert spec.read_text() == original


def test_application_scaffold_validation_leaves_no_partial_app(tmp_path: Path, capsys) -> None:
    module = tmp_path / "module"
    module.mkdir()
    result = main(
        [
            "app",
            "new",
            "--module",
            str(module),
            "--id",
            "broken",
            "--composition",
            "same=acme/demo/base",
            "--app",
            "same=acme/demo/base",
        ]
    )
    assert result == 2
    assert "both composition and app" in capsys.readouterr().err
    assert (module / "apps" / "broken").exists() is False

    result = main(
        [
            "app",
            "new",
            "--module",
            str(module),
            "--id",
            "broken",
            "--composition",
            "base=acme/demo/base",
            "--export",
            "missing.echo",
        ]
    )
    assert result == 2
    assert "unknown dependency alias" in capsys.readouterr().err
    assert (module / "apps" / "broken").exists() is False


def test_application_export_all_uses_live_composition_and_app_descriptors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    configured_project(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "app",
                "new",
                "--module",
                str(target),
                "--id",
                "consumer",
                "--composition",
                "values=acme/demo/base",
                "--app",
                "worker=acme/demo/base",
                "--export-all",
                "values",
                "--export-all",
                "worker",
            ]
        )
        == 0
    )
    capsys.readouterr()
    payload = tomllib.loads((target / "apps" / "consumer" / "app.toml").read_text())
    assert payload["compositions"]["values"]["export"] == ["echo"]
    assert payload["apps"]["worker"]["export"] == ["ping"]


def test_application_generate_cli_uses_trusted_dependency_descriptors(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = configured_project(tmp_path)
    target = module / "apps" / "generated"
    target.mkdir()
    spec = target / "app.toml"
    spec.write_text(
        """[app]
id = "generated"
[compositions.values]
use = "acme/demo/base"
export = ["echo"]
[apps.worker]
use = "acme/demo/base"
export = ["ping"]
"""
    )
    monkeypatch.chdir(tmp_path)

    assert main(["app", "generate", str(spec)]) == 0

    assert "runtime.py" in capsys.readouterr().out
    generated = (target / "runtime.py").read_text()
    assert "def echo(self, value: str) -> str:" in generated
    assert "def ping(self) -> str:" in generated
    assert "def start(self)" not in generated
    assert "def stop(self)" not in generated
    original = generated

    assert main(["app", "generate", str(spec)]) == 2
    assert "already exists" in capsys.readouterr().err
    assert (target / "runtime.py").read_text() == original


def test_application_cli_has_no_execution_surface(capsys) -> None:
    for command in ("list", "show", "functions", "graph", "new", "generate"):
        try:
            main(["app", command, "--help"])
        except SystemExit as exc:
            assert exc.code == 0
        else:
            raise AssertionError(f"missing app help exit: {command}")
        capsys.readouterr()
    for command in ("run", "start", "invoke", "call", "instance"):
        try:
            main(["app", command])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"unexpected app command: {command}")
        capsys.readouterr()
