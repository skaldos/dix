from pathlib import Path
import os
import pytest
from dix.core.composition import CompositionRuntimeContext
import dix_sway_active_members_runtime_test_import as runtime_module


def _runtime(tmp_path: Path):
    context = CompositionRuntimeContext(instance_id="active", composition_id="dix/sway/active_members", module_id="dix/sway", module_root=tmp_path, composition_root=tmp_path, config_base_dir=tmp_path, owner_scope_id="test")
    path = tmp_path / "active.txt"
    return runtime_module.Runtime(context=context, config={"path": str(path)}), path


def test_missing_empty_and_roundtrip_are_canonical_and_detached(tmp_path: Path) -> None:
    runtime, path = _runtime(tmp_path)
    assert runtime.get() == []
    runtime.set([])
    assert path.read_bytes() == b"\n"
    assert runtime.get() == []
    runtime.set([32, 392])
    assert path.read_bytes() == b"32 392\n"
    result = runtime.get(); result.append(9)
    assert runtime.get() == [32, 392]


@pytest.mark.parametrize("payload", [
    b"", b"0\n", b"01\n", b"+1\n", b"-1\n", b" 1\n", b"1 \n", b"1  2\n",
    b"1\t2\n", b"1,2\n", b"1 #x\n", b"1\n2\n", b"1 1\n", b"\xff\n",
])
def test_reader_rejects_every_noncanonical_form(tmp_path: Path, payload: bytes) -> None:
    runtime, path = _runtime(tmp_path)
    path.write_bytes(payload)
    with pytest.raises(ValueError): runtime.get()


def test_writer_rejects_invalid_values_and_uses_same_directory_replace(tmp_path: Path, monkeypatch) -> None:
    runtime, path = _runtime(tmp_path)
    for value in ([0], [-1], [True], [1, 1]):
        with pytest.raises((TypeError, ValueError)): runtime.set(value)
    calls = []
    original = os.replace
    def replace(source, target):
        calls.append((Path(source), Path(target))); original(source, target)
    monkeypatch.setattr(os, "replace", replace)
    runtime.set([3, 2])
    assert calls[0][0].parent == path.parent and calls[0][1] == path
