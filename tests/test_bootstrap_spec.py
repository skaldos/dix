from __future__ import annotations

from pathlib import Path

import pytest

from dix.bootstrap import LauncherSpecError, load_launcher_spec, render_launcher


def write_module(root: Path, *, application_id: str = "main") -> Path:
    application = root / "apps" / application_id
    application.mkdir(parents=True)
    (application / "app.toml").write_text(f'[app]\nid = "{application_id}"\n')
    (application / "runtime.py").write_text(
        "class Runtime:\n"
        "    def __init__(self, *, context, config):\n"
        "        self.context = context\n"
        "        self.config = config\n"
    )
    return root


def write_spec(path: Path, module_source: str, **launcher: str) -> Path:
    values = {
        "name": "test-launcher",
        "adapter": "python_cli",
        "application": "acme/example/main",
        "function": "main",
        **launcher,
    }
    path.write_text(
        "[launcher]\n"
        f'name = "{values["name"]}"\n'
        f'adapter = "{values["adapter"]}"\n'
        f'application = "{values["application"]}"\n'
        f'function = "{values["function"]}"\n\n'
        "[[modules]]\n"
        'id = "acme/example"\n'
        f'source = "{module_source}"\n'
    )
    return path


def test_launcher_spec_normalizes_relative_module_source(tmp_path: Path) -> None:
    module = write_module(tmp_path / "module")
    spec = write_spec(tmp_path / "launcher.toml", "module")

    definition = load_launcher_spec(spec)

    assert definition.name == "test-launcher"
    assert definition.adapter == "python_cli"
    assert definition.application == "acme/example/main"
    assert definition.function == "main"
    assert definition.modules[0].id == "acme/example"
    assert definition.modules[0].source == module.resolve()
    assert definition.spec_path == spec.resolve()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ('extra = "no"\n', "unknown key in launcher"),
        ('adapter = "unknown"\n', "unknown launcher adapter"),
    ],
)
def test_launcher_spec_rejects_unknown_surface(
    tmp_path: Path,
    change: str,
    message: str,
) -> None:
    write_module(tmp_path / "module")
    spec = write_spec(tmp_path / "launcher.toml", "module")
    if change.startswith("adapter"):
        spec.write_text(spec.read_text().replace('adapter = "python_cli"\n', change))
    else:
        spec.write_text(spec.read_text().replace("[launcher]\n", f"[launcher]\n{change}"))

    with pytest.raises(LauncherSpecError, match=message):
        load_launcher_spec(spec)


def test_launcher_spec_rejects_duplicate_module_ids(tmp_path: Path) -> None:
    write_module(tmp_path / "module")
    spec = write_spec(tmp_path / "launcher.toml", "module")
    spec.write_text(
        spec.read_text()
        + '\n[[modules]]\nid = "acme/example"\nsource = "module"\n'
    )

    with pytest.raises(LauncherSpecError, match="duplicate module id"):
        load_launcher_spec(spec)


def test_launcher_spec_requires_application_from_configured_modules(tmp_path: Path) -> None:
    write_module(tmp_path / "module")
    spec = write_spec(
        tmp_path / "launcher.toml",
        "module",
        application="acme/example/missing",
    )

    with pytest.raises(LauncherSpecError, match="application is not provided"):
        load_launcher_spec(spec)


def test_renderer_is_deterministic_and_embeds_normalized_definition(tmp_path: Path) -> None:
    module = write_module(tmp_path / "module")
    definition = load_launcher_spec(write_spec(tmp_path / "launcher.toml", "module"))

    first = render_launcher(definition)
    second = render_launcher(definition)

    assert first == second
    assert repr(str(module.resolve())) in first
    assert "APPLICATION_ID = 'acme/example/main'" in first
    assert "FUNCTION_ID = 'main'" in first
    compile(first, "generated_launcher.py", "exec")
