from __future__ import annotations

import ast
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from roba import RobaClient, TransportError

from dix.bootstrap import build_launcher

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = REPOSITORY / "examples" / "launchers" / "dix_roba.toml"
_TOKEN = __import__("re").compile(r"control_token='([^']+)'")


def _run(launcher: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(launcher), *arguments],
        cwd=REPOSITORY,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
        text=True,
        capture_output=True,
        check=False,
    )


def _mapping(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    value = ast.literal_eval(result.stdout.strip())
    assert isinstance(value, dict), result.stdout
    return value


def _config(root: Path) -> tuple[str, ...]:
    return (
        "--daemon_id",
        "e2e-registry",
        "--runtime_root",
        str(root / "runtime"),
        "--logs_root",
        str(root / "logs"),
        "--timeout",
        "5",
    )


def _environment(root: Path) -> dict[str, str]:
    return {
        "ROBA_RUNTIME_ROOT": str(root / "runtime"),
        "ROBA_LOGS_ROOT": str(root / "logs"),
    }


def _token(value: str) -> str:
    match = _TOKEN.search(value)
    assert match is not None, value
    return match.group(1)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()


def test_cli_processes_raw_attach_rebind_capabilities_and_clear_registry(
    tmp_path: Path,
) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_roba.py")
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    config = _config(root)
    environment = _environment(root)
    bootstrap: dict[str, object] | None = None
    created: dict[str, object] | None = None
    raw_token = ""
    try:
        # Process A: raw daemon only. It must not create dix.control implicitly.
        raw = _run(launcher, "daemon", "start", *config)
        assert raw.returncode == 0, raw.stderr
        raw_token = _token(raw.stdout)
        not_bootstrapped = _run(
            launcher,
            "control",
            "control_credentials",
            *config,
        )
        assert not_bootstrapped.returncode != 0

        # Process B: attach the separately started daemon with explicit credentials.
        bootstrap = _mapping(
            _run(
                launcher,
                "control",
                "bootstrap",
                "--control_locator",
                "id:e2e-registry",
                "--control_token",
                raw_token,
                *config,
            )
        )
        assert bootstrap["control_context"] == "dix.control"
        assert bootstrap["root_socket_id"] == "admin"
        assert Path(str(bootstrap["root_socket"])).is_socket()
        assert _fingerprint(bootstrap["control_token"]) == _fingerprint(raw_token)

        # Process C: root credentials are recovered without passing a token.
        credentials = _mapping(_run(launcher, "control", "control_credentials", *config))
        assert credentials["control_locator"] == bootstrap["control_locator"]
        assert credentials["control_token"] == bootstrap["control_token"]
        assert credentials["owner_token"] == bootstrap["control_owner_token"]

        # Process D: target Context, Registry Instance and scoped manager socket.
        created = _mapping(
            _run(
                launcher,
                "control",
                "create_context",
                "--context_id",
                "test01",
                *config,
            )
        )
        assert created["manager_socket_id"] == "test01"
        assert Path(str(created["manager_socket"])).is_socket()

        # Process E: target credentials are recovered through the manager socket.
        rebound = _mapping(
            _run(
                launcher,
                "control",
                "context_credentials",
                "--context_id",
                "test01",
                *config,
            )
        )
        assert rebound == {
            "context_locator": created["context_locator"],
            "owner_token": created["owner_token"],
        }

        owner = RobaClient(env=environment, timeout=5).context(
            locator=str(rebound["context_locator"]),
            token=str(rebound["owner_token"]),
        )
        assert owner.set("e2e", "rebound")["key"] == "e2e"
        assert owner.get("e2e") == "rebound"

        root_socket = RobaClient(timeout=5).context(
            locator=f"unix:{bootstrap['root_socket']}",
            token=None,
        )
        with pytest.raises(TransportError, match="403"):
            root_socket.with_scope("id:test01").get("context_locator")

        manager_socket = RobaClient(timeout=5).context(
            locator=f"unix:{created['manager_socket']}",
            scope="id:test01",
            token=None,
        )
        with pytest.raises(TransportError, match="403"):
            manager_socket.with_scope(None).get("control_locator")
        with pytest.raises(TransportError, match="403"):
            manager_socket.with_scope("id:other").get("context_locator")

        duplicate = _run(
            launcher,
            "control",
            "create_context",
            "--context_id",
            "test01",
            *config,
        )
        assert duplicate.returncode != 0
        assert "409" in duplicate.stderr or "already" in duplicate.stderr.lower()
        assert owner.get("e2e") == "rebound"

        token_fingerprints = {
            key: _fingerprint(value)
            for key, value in {
                "control": bootstrap["control_token"],
                "control_owner": bootstrap["control_owner_token"],
                "context_owner": created["owner_token"],
            }.items()
        }
        assert len(set(token_fingerprints.values())) == 3
        assert all(len(value) == 64 for value in token_fingerprints.values())
    finally:
        if raw_token:
            stopped = _run(launcher, "daemon", "stop", *config)
            assert stopped.returncode == 0, stopped.stderr
        for path in (root / "runtime", root / "logs"):
            if path.exists():
                for file in path.rglob("*"):
                    if file.is_file():
                        content = file.read_text(errors="ignore")
                        if raw_token:
                            assert raw_token not in content
                        if bootstrap is not None:
                            assert str(bootstrap["control_owner_token"]) not in content
        shutil.rmtree(root, ignore_errors=True)

    assert bootstrap is not None
    assert created is not None
    assert not Path(str(bootstrap["root_socket"])).exists()
    assert not Path(str(created["manager_socket"])).exists()


def test_cli_managed_start_is_a_single_explicit_path(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_roba.py")
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    config = (
        "--daemon_id",
        "managed-cli",
        "--runtime_root",
        str(root / "runtime"),
        "--logs_root",
        str(root / "logs"),
        "--timeout",
        "5",
    )
    result = _run(launcher, "managed", "start", *config)
    assert result.returncode == 0, result.stderr
    try:
        value = ast.literal_eval(result.stdout.strip())
        assert value["daemon_id"] == "managed-cli"
        assert value["control_context"] == "dix.control"
        status = _run(launcher, "daemon", "status", *config)
        assert status.returncode == 0, status.stderr
        assert "managed-cli" in status.stdout
    finally:
        stopped = _run(launcher, "daemon", "stop", *config)
        assert stopped.returncode == 0, stopped.stderr
    shutil.rmtree(root, ignore_errors=True)


def test_cli_attach_failure_does_not_stop_raw_daemon(tmp_path: Path) -> None:
    launcher = build_launcher(SPEC, tmp_path / "dix_roba.py")
    root = Path(tempfile.mkdtemp(prefix="dix-r-"))
    config = _config(root)
    raw = _run(launcher, "daemon", "start", *config)
    assert raw.returncode == 0, raw.stderr
    try:
        failed = _run(
            launcher,
            "control",
            "bootstrap",
            "--control_locator",
            "id:e2e-registry",
            "--control_token",
            "roba-control1-invalid",
            *config,
        )
        assert failed.returncode != 0
        status = _run(launcher, "daemon", "status", *config)
        assert status.returncode == 0, status.stderr
        assert "e2e-registry" in status.stdout
    finally:
        stopped = _run(launcher, "daemon", "stop", *config)
        assert stopped.returncode == 0, stopped.stderr
    shutil.rmtree(root, ignore_errors=True)
