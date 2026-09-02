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
        'config = { label = "Kind", mode = "single", options = ['
        '{ id = "access", label = "Access" }, '
        '{ id = "hardware", label = "Hardware" }] }\n'
    )


def app_config(tmp_path: Path, **overrides):
    return {
        "runtime_root": str(tmp_path / "runtime"),
        "interface_dirs": [str(tmp_path / "interfaces")],
        "theme": "default",
        "host": "127.0.0.1",
        "port": 8000,
        **overrides,
    }


def test_render_route_renders_and_api_updates_json(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    client = TestClient(create_app(app_config(tmp_path)))

    html = client.get("/render/demo_request")
    assert html.status_code == 200
    assert "Demo Request" in html.text
    assert "request_title" in html.text
    assert "request_kind" in html.text
    assert 'data-interaction="value_input"' in html.text
    assert 'data-interaction="choice_input"' in html.text

    before = client.get("/api/interfaces/demo_request/model")
    assert before.status_code == 200
    before_json = before.json()
    assert before_json["component_output"]["request_title"]["value"] is None
    assert before_json["components"][0]["interaction"]["role"] == "value_input"

    title_update = client.post(
        "/api/interfaces/demo_request/components/request_title/update",
        json={"value": "Need access"},
        headers={"HX-Request": "true"},
    )
    assert title_update.status_code == 200
    assert title_update.headers["content-type"].startswith("application/json")
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


def test_render_update_returns_html_fragment(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    client = TestClient(create_app(app_config(tmp_path)))
    res = client.post(
        "/render/demo_request/components/request_title/update",
        data={"value": "Partial"},
        headers={"HX-Request": "true"},
    )
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert 'data-component="request_title"' in res.text
    assert 'hx-swap-oob="true"' in res.text
    assert "Partial" in res.text


def test_reference_renderer_can_be_disabled(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    client = TestClient(create_app(app_config(tmp_path, reference_renderer_enabled=False)))
    assert client.get("/render/demo_request").status_code == 404
    assert client.get("/api/interfaces/demo_request/model").status_code == 200

def test_reference_renderer_path_is_configurable(tmp_path: Path) -> None:
    write_demo_interface(tmp_path)
    client = TestClient(create_app(app_config(tmp_path, reference_renderer_path="/ui")))
    assert client.get("/ui/demo_request").status_code == 200
    assert client.get("/render/demo_request").status_code == 404
