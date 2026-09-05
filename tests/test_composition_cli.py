from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

import pytest

from dix.cli import main


def write_composition(module: Path, local_id: str, body: str, runtime: str) -> None:
    root = module / "compositions" / local_id
    root.mkdir(parents=True)
    (root / "composition.toml").write_text(body)
    (root / "runtime.py").write_text(runtime)


def configured_project(tmp_path: Path) -> Path:
    modules = tmp_path / "modules"
    module = modules / "acme" / "demo"
    write_composition(
        module,
        "base",
        """[composition]
id = "base"
[functions.echo]
description = "Echo a value."
""",
        """class Runtime:
    def __init__(self, *, context, config): pass
    def echo(self, value: str) -> str:
        return value
""",
    )
    write_composition(
        module,
        "child",
        """[composition]
id = "child"
[components]
model = "datamodel"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
""",
        """class Runtime:
    def __init__(self, *, context, config, model, base): pass
    def echo(self, value: str) -> str:
        return self.base.echo(value)
""",
    )
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    return module


def test_module_and_composition_json_introspection(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    configured_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["module", "list", "--json"]) == 0
    modules = json.loads(capsys.readouterr().out)
    assert modules[0]["id"] == "acme/demo"
    assert modules[0]["composition_ids"] == ["acme/demo/base", "acme/demo/child"]

    assert main(["module", "show", "acme/demo", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown == modules[0]

    assert main(["module", "graph", "acme/demo", "--json"]) == 0
    graph = json.loads(capsys.readouterr().out)
    child_graph = next(item for item in graph["graphs"] if item["root"] == "acme/demo/child")
    assert child_graph["edges"] == [
        {
            "alias": "model",
            "kind": "component",
            "source": "acme/demo/child",
            "target": "datamodel",
        },
        {
            "alias": "base",
            "kind": "composition",
            "source": "acme/demo/child",
            "target": "acme/demo/base",
        },
    ]

    assert main(["composition", "list", "--json"]) == 0
    definitions = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in definitions] == ["acme/demo/base", "acme/demo/child"]

    assert main(["composition", "functions", "acme/demo/child", "--json"]) == 0
    functions = json.loads(capsys.readouterr().out)
    assert functions[0]["origin"] == "base.echo"
    assert functions[0]["signature"] == "(value: str) -> str"

    assert main(["composition", "show", "acme/demo/child", "--json"]) == 0
    shown_composition = json.loads(capsys.readouterr().out)
    assert shown_composition["definition"]["id"] == "acme/demo/child"
    assert shown_composition["functions"] == functions

    assert main(["composition", "instance", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_human_introspection_contains_same_id_origin_and_signature(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    configured_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["module", "list"]) == 0
    assert "acme/demo" in capsys.readouterr().out
    assert main(["composition", "functions", "acme/demo/child"]) == 0
    output = capsys.readouterr().out
    assert "base.echo" in output
    assert "(value: str) -> str" in output


def test_module_inspect_is_static_and_requires_explicit_id(
    tmp_path: Path,
    capsys,
) -> None:
    module = tmp_path / "candidate"
    marker = tmp_path / "imported"
    write_composition(
        module,
        "item",
        '[composition]\nid = "item"\n',
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nclass Runtime: pass\n",
    )

    assert main(["module", "inspect", str(module), "--id", "external/demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "external/demo"
    assert payload["composition_definitions"][0]["id"] == "external/demo/item"
    assert payload["application_definitions"] == []
    assert marker.exists() is False


def test_module_and_composition_scaffolds_are_small_and_non_overwriting(
    tmp_path: Path,
    capsys,
) -> None:
    root = tmp_path / "modules"
    assert main(["module", "new", "--id", "my/new_stuff", "--root", str(root)]) == 0
    module = root / "my" / "new_stuff"
    assert (module / "compositions").is_dir()
    assert (module / "module.toml").exists() is False
    capsys.readouterr()

    command = [
        "composition",
        "new",
        "--module",
        str(module),
        "--id",
        "processor",
        "--component",
        "model=datamodel",
        "--composition",
        "base=acme/demo/base",
        "--export",
        "base.echo",
        "--export",
        "base.echo=echo_alias",
        "--function",
        "local_value",
    ]
    assert main(command) == 0
    spec_path = module / "compositions" / "processor" / "composition.toml"
    payload = tomllib.loads(spec_path.read_text())
    assert payload["components"] == {"model": "datamodel"}
    assert payload["compositions"]["base"] == {
        "use": "acme/demo/base",
        "export": ["echo"],
    }
    assert payload["functions"]["echo_alias"]["export"] == "base.echo"
    assert "TODO" in payload["functions"]["local_value"]["description"]
    assert (spec_path.parent / "runtime.py").exists() is False
    original = spec_path.read_text()
    capsys.readouterr()

    assert main(command) == 2
    assert "already exists" in capsys.readouterr().err
    assert spec_path.read_text() == original
    assert main(["module", "new", "--id", "my/new_stuff", "--root", str(root)]) == 2


def test_scaffold_collision_writes_no_partial_composition(tmp_path: Path, capsys) -> None:
    module = tmp_path / "module"
    (module / "compositions").mkdir(parents=True)

    result = main(
        [
            "composition",
            "new",
            "--module",
            str(module),
            "--id",
            "broken",
            "--composition",
            "base=acme/demo/base",
            "--export",
            "base.echo",
            "--function",
            "echo",
        ]
    )

    assert result == 2
    assert "duplicate effective function" in capsys.readouterr().err
    assert (module / "compositions" / "broken").exists() is False


def test_export_all_expands_authoritative_dependency_functions(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    configured_project(tmp_path)
    target = tmp_path / "target"
    (target / "compositions").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "composition",
                "new",
                "--module",
                str(target),
                "--id",
                "consumer",
                "--composition",
                "base=acme/demo/base",
                "--export-all",
                "base",
            ]
        )
        == 0
    )
    capsys.readouterr()
    payload = tomllib.loads((target / "compositions" / "consumer" / "composition.toml").read_text())
    assert payload["compositions"]["base"]["export"] == ["echo"]


def test_composition_generate_cli_uses_loaded_dependency_descriptors(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    configured_project(tmp_path)
    target = tmp_path / "target"
    source = target / "compositions" / "consumer"
    source.mkdir(parents=True)
    spec = source / "composition.toml"
    spec.write_text(
        """[composition]
id = "consumer"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
"""
    )
    monkeypatch.chdir(tmp_path)

    assert main(["composition", "generate", str(spec)]) == 0

    output = capsys.readouterr().out
    assert "runtime.py" in output
    generated = (source / "runtime.py").read_text()
    assert "def echo(self, value: str) -> str:" in generated


def test_composition_generate_resolves_sibling_before_module_is_complete(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    modules = tmp_path / "modules"
    module = modules / "acme" / "demo"
    base = module / "compositions" / "base"
    base.mkdir(parents=True)
    (base / "composition.toml").write_text(
        '[composition]\nid = "base"\n[functions.echo]\ndescription = "Echo."\n'
    )
    (base / "helper.py").write_text("PREFIX = 'base:'\n")
    (base / "runtime.py").write_text(
        "from .helper import PREFIX\n"
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self, value: str) -> str: return PREFIX + value\n"
    )
    child = module / "compositions" / "child"
    child.mkdir()
    child_spec = child / "composition.toml"
    child_spec.write_text(
        """[composition]
id = "child"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
"""
    )
    unrelated = module / "compositions" / "unfinished"
    unrelated.mkdir()
    (unrelated / "composition.toml").write_text('[composition]\nid = "unfinished"\n')
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    monkeypatch.chdir(tmp_path)

    assert main(["composition", "generate", str(child_spec)]) == 0

    assert "runtime.py" in capsys.readouterr().out
    generated = (child / "runtime.py").read_text()
    assert "def echo(self, value: str) -> str:" in generated
    assert not any(name.startswith("_dix_build_") for name in sys.modules)


def test_composition_generate_rejects_duplicate_dependency_across_trusted_roots(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    for root_name in ("one", "two"):
        base = tmp_path / root_name / "acme" / "demo" / "compositions" / "base"
        base.mkdir(parents=True)
        (base / "composition.toml").write_text(
            '[composition]\nid = "base"\n[functions.echo]\ndescription = "Echo."\n'
        )
        (base / "runtime.py").write_text(
            "class Runtime:\n"
            "    def __init__(self, *, context, config): pass\n"
            "    def echo(self): return None\n"
        )
    target = tmp_path / "target" / "compositions" / "child"
    target.mkdir(parents=True)
    spec = target / "composition.toml"
    spec.write_text(
        """[composition]
id = "child"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
"""
    )
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["one", "two"]\n')
    monkeypatch.chdir(tmp_path)

    assert main(["composition", "generate", str(spec)]) == 2

    assert "duplicate composition dependency" in capsys.readouterr().err
    assert (target / "runtime.py").exists() is False


def test_composition_generate_rejects_unknown_dependency_component(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    modules = tmp_path / "modules"
    base = modules / "acme" / "demo" / "compositions" / "base"
    base.mkdir(parents=True)
    (base / "composition.toml").write_text(
        """[composition]
id = "base"
[components]
unknown = "not_registered"
[functions.echo]
description = "Echo."
"""
    )
    (base / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config, unknown): pass\n"
        "    def echo(self): return None\n"
    )
    target = modules / "acme" / "demo" / "compositions" / "child"
    target.mkdir()
    spec = target / "composition.toml"
    spec.write_text(
        """[composition]
id = "child"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
"""
    )
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    monkeypatch.chdir(tmp_path)

    assert main(["composition", "generate", str(spec)]) == 2

    assert "unknown component 'not_registered'" in capsys.readouterr().err
    assert (target / "runtime.py").exists() is False


def test_composition_generate_rejects_dependency_symlink_outside_trusted_module(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    external = tmp_path / "external" / "module" / "compositions" / "base"
    external.mkdir(parents=True)
    (external / "composition.toml").write_text(
        '[composition]\nid = "base"\n[functions.echo]\ndescription = "Echo."\n'
    )
    (external / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config): pass\n"
        "    def echo(self): return None\n"
    )
    module = tmp_path / "modules" / "acme" / "demo"
    compositions = module / "compositions"
    compositions.mkdir(parents=True)
    (compositions / "base").symlink_to(external, target_is_directory=True)
    target = compositions / "child"
    target.mkdir()
    spec = target / "composition.toml"
    spec.write_text(
        """[composition]
id = "child"
[compositions.base]
use = "acme/demo/base"
export = ["echo"]
"""
    )
    (tmp_path / "dix.toml").write_text('[composition]\ntrusted_module_roots = ["modules"]\n')
    monkeypatch.chdir(tmp_path)

    assert main(["composition", "generate", str(spec)]) == 2

    assert "escapes trusted module root" in capsys.readouterr().err
    assert (target / "runtime.py").exists() is False


@pytest.mark.parametrize(
    "argv",
    [
        ["module", "new", "--help"],
        ["module", "list", "--help"],
        ["module", "show", "--help"],
        ["module", "inspect", "--help"],
        ["module", "graph", "--help"],
        ["composition", "new", "--help"],
        ["composition", "list", "--help"],
        ["composition", "show", "--help"],
        ["composition", "functions", "--help"],
        ["composition", "generate", "--help"],
        ["composition", "instance", "list", "--help"],
    ],
)
def test_composition_commands_have_help(argv: list[str], capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(argv)
    assert "usage:" in capsys.readouterr().out
