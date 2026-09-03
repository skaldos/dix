from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dix.core import DatamodelComponent
from dix.server import create_app


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def app_config(interface_dir: Path) -> dict[str, object]:
    return {
        "runtime_root": ".dix/runtime",
        "interface_dirs": [str(interface_dir)],
        "theme": "default",
        "host": "127.0.0.1",
        "port": 8000,
    }


def test_example_function_runs_headless_datamodel_chain_once() -> None:
    app = create_app(app_config(repo_root() / "examples" / "interfaces"))
    client = TestClient(app)
    datamodel = app.state.capability_components.require("datamodel", DatamodelComponent)

    first = client.get("/api/interfaces/demo_datamodel/functions/run")
    second = client.get("/api/interfaces/demo_datamodel/functions/run")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["compatible"] is True
    assert first.json()["values"] == {
        "username": "demo-user",
        "age": 42,
        "metadata": {
            "source": "example",
            "labels": ["headless", "trusted"],
        },
    }
    assert first.json()["issues"] == []
    assert datamodel.registration_count == 1


def test_unknown_composition_is_rejected_during_interface_binding(tmp_path: Path) -> None:
    interface_dir = tmp_path / "interfaces"
    interface_dir.mkdir()
    (interface_dir / "bad.toml").write_text(
        '[interface]\n'
        'id = "bad"\n'
        'title = "Bad"\n\n'
        '[[compositions]]\n'
        'id = "data"\n'
        'use = "arbitrary.module.Factory"\n\n'
        '[[functions]]\n'
        'id = "run"\n'
        'call = "data.run"\n'
    )
    client = TestClient(create_app(app_config(interface_dir)))

    response = client.get("/api/interfaces/bad/functions/run")

    assert response.status_code == 422
    assert "composition not found" in response.json()["detail"]


def test_unknown_operation_is_rejected_during_interface_binding(tmp_path: Path) -> None:
    interface_dir = tmp_path / "interfaces"
    fixture_dir = tmp_path / "fixtures"
    interface_dir.mkdir()
    fixture_dir.mkdir()
    (fixture_dir / "model.toml").write_text(
        '[model]\nname = "demo"\nversion = "1"\n\n'
        '[fields.value]\ntype = "string"\n'
    )
    (fixture_dir / "data.json").write_text(
        '{"model":{"name":"demo","version":"1"},"data":{"value":"ok"}}'
    )
    (interface_dir / "bad.toml").write_text(
        '[interface]\n'
        'id = "bad"\n'
        'title = "Bad"\n\n'
        '[[compositions]]\n'
        'id = "data"\n'
        'use = "datamodel_files"\n'
        'config = { model_path = "../fixtures/model.toml", '
        'data_path = "../fixtures/data.json" }\n\n'
        '[[functions]]\n'
        'id = "run"\n'
        'call = "data.missing"\n'
    )
    client = TestClient(create_app(app_config(interface_dir)))

    response = client.get("/api/interfaces/bad/functions/run")

    assert response.status_code == 422
    assert "unknown operation 'missing'" in response.json()["detail"]


def test_missing_function_returns_not_found_and_existing_routes_still_work() -> None:
    client = TestClient(
        create_app(app_config(repo_root() / "examples" / "interfaces"))
    )

    missing = client.get("/api/interfaces/demo_datamodel/functions/missing")
    model = client.get("/api/interfaces/demo_request/model")
    rendered = client.get("/render/demo_request")

    assert missing.status_code == 404
    assert model.status_code == 200
    assert rendered.status_code == 200
