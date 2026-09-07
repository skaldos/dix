from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dix.cli import main
from dix.server import create_app


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def app_for_examples(**overrides) -> TestClient:
    root = repo_root()
    app = create_app(
        {
            "runtime_root": str(root / ".dix" / "runtime"),
            "interface_dirs": [str(root / "examples" / "interfaces")],
            "theme": "default",
            "host": "127.0.0.1",
            "port": 8000,
            **overrides,
        }
    )
    return TestClient(app)


def test_example_interface_is_listed(monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo_root())
    assert main(["interface", "list"]) == 0
    out = capsys.readouterr().out
    assert "demo_request" in out


def test_demo_request_full_e2e() -> None:
    client = app_for_examples()
    html = client.get("/render/demo_request")
    assert html.status_code == 200
    assert "Demo Request" in html.text
    assert "request_title" in html.text
    assert "request_kind" in html.text

    title = client.post(
        "/api/interfaces/demo_request/components/request_title/update",
        json={"value": "Access for workstation"},
    )
    assert title.status_code == 200
    assert title.json()["component_output"]["request_title"] == {
        "value": "Access for workstation",
        "valid": True,
    }

    kind = client.post(
        "/render/demo_request/components/request_kind/update",
        data={"selected": "hardware"},
    )
    assert kind.status_code == 200
    assert kind.headers["content-type"].startswith("text/html")
    model = client.get("/api/interfaces/demo_request/model").json()
    assert model["component_output"]["request_kind"]["selected"] == "hardware"
    assert model["component_output"]["request_kind"]["selected_items"][0]["label"] == "Hardware"


def test_interface_gate_denies_disabled_interface(tmp_path: Path) -> None:
    interface_dir = tmp_path / "interfaces"
    interface_dir.mkdir()
    (interface_dir / "disabled.toml").write_text(
        '[interface]\n'
        'id = "disabled"\n'
        'title = "Disabled"\n'
        'access = { mode = "disabled" }\n'
    )
    client = TestClient(
        create_app(
            {
                "runtime_root": str(tmp_path / "runtime"),
                "interface_dirs": [str(interface_dir)],
                "theme": "default",
                "host": "127.0.0.1",
                "port": 8000,
            }
        )
    )
    assert client.get("/render/disabled").status_code == 403


def test_interface_gate_allows_session_match_group(tmp_path: Path) -> None:
    interface_dir = tmp_path / "interfaces"
    interface_dir.mkdir()
    (interface_dir / "grouped.toml").write_text(
        '[interface]\n'
        'id = "grouped"\n'
        'title = "Grouped"\n'
        'access = { mode = "session_match", path = "groups", contains = "reviewer" }\n'
    )
    client = TestClient(
        create_app(
            {
                "runtime_root": str(tmp_path / "runtime"),
                "interface_dirs": [str(interface_dir)],
                "theme": "default",
                "host": "127.0.0.1",
                "port": 8000,
            }
        )
    )
    assert client.get("/render/grouped").status_code == 403
    assert client.get(
        "/render/grouped", headers={"X-DIX-User": "alice", "X-DIX-Groups": "reviewer"}
    ).status_code == 200
