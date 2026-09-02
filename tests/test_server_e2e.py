from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dix.server import create_app


def write_demo_interface(root: Path) -> None:
    interface_dir = root / "interfaces"
    interface_dir.mkdir()
    (interface_dir / "demo_request.toml").write_text(
        '[interface]\n'
        'id = "demo_request"\n'
        'title = "Demo Request"\n'
        'access = { mode = "public" }\n\n'
        '[[components]]\n'
        'id = "request_title"\n'
        'use = "input"\n'
        'config = { label = "Title", placeholder = "Short request title" }\n\n'
        '[[components]]\n'
        'id = "request_kind"\n'
        'use = "select"\n'
        'config = { label = "Kind", mode = "single", options = [{ id = "access", label = "Access" }, { id = "hardware", label = "Hardware" }] }\n'
    )


def test_server_renders_and_updates_runtime_state(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    app = create_app(
        {
            "runtime_root": str(tmp_path / "runtime"),
            "interface_dirs": [str(tmp_path / "interfaces")],
            "theme": "default",
            "host": "127.0.0.1",
            "port": 8000,
        }
    )
    client = TestClient(app)

    html = client.get("/interfaces/demo_request")
    assert html.status_code == 200
    assert "Demo Request" in html.text
    assert "request_title" in html.text
    assert "request_kind" in html.text

    before = client.get("/api/interfaces/demo_request/model")
    assert before.status_code == 200
    assert before.json()["component_output"]["request_title"]["value"] is None

    title_update = client.post(
        "/api/interfaces/demo_request/components/request_title/update",
        json={"value": "Need access"},
    )
    assert title_update.status_code == 200
    assert title_update.json()["component_output"]["request_title"]["value"] == "Need access"

    select_update = client.post(
        "/api/interfaces/demo_request/components/request_kind/update",
        json={"selected": "access"},
    )
    assert select_update.status_code == 200
    body = select_update.json()
    assert body["component_output"]["request_kind"]["selected"] == "access"
    assert body["component_output"]["request_kind"]["selected_items"] == [
        {"id": "access", "label": "Access"}
    ]


def test_htmx_update_returns_component_partial(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    app = create_app(
        {
            "runtime_root": str(tmp_path / "runtime"),
            "interface_dirs": [str(tmp_path / "interfaces")],
            "theme": "default",
            "host": "127.0.0.1",
            "port": 8000,
        }
    )
    client = TestClient(app)
    res = client.post(
        "/api/interfaces/demo_request/components/request_title/update",
        data={"value": "Partial"},
        headers={"HX-Request": "true"},
    )
    assert res.status_code == 200
    assert 'data-component="request_title"' in res.text
    assert "Partial" in res.text
