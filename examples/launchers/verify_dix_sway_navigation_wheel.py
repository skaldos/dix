from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

REPOSITORY = Path(__file__).resolve().parents[2]
ENTRY = Path(__file__).with_name("dix_sway_navigation.py")
ROBA = Path(os.environ.get("DIX_ROBA_SOURCE", REPOSITORY.parent / "roba")).resolve()


def run(*args: str, cwd: Path, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{result.stdout}\n{result.stderr}")
    return result


def main() -> int:
    if len(sys.argv) != 2: raise SystemExit("usage: verify_dix_sway_navigation_wheel.py OUTPUT_DIR")
    output = Path(sys.argv[1]).resolve()
    if output.exists(): raise SystemExit(f"output path already exists: {output}")
    output.mkdir(parents=True)
    wheels = output / "wheels"; wheels.mkdir()
    run("uv", "build", "--wheel", "--no-sources", "--out-dir", str(wheels), cwd=REPOSITORY)
    run("uv", "build", "--wheel", "--out-dir", str(wheels), cwd=ROBA)
    venv = output / "venv"
    run("uv", "venv", "--python", "3.12", str(venv), cwd=output)
    python = venv / "bin/python"
    dix_wheel = next(wheels.glob("dix-*.whl")); roba_wheel = next(wheels.glob("roba-*.whl"))
    run("uv", "pip", "install", "--python", str(python), f"dix[sway] @ {dix_wheel.as_uri()}", f"roba @ {roba_wheel.as_uri()}", cwd=output)
    entry = output / ENTRY.name; shutil.copy2(ENTRY, entry)
    fake = output / "fake"; fake.mkdir()
    (fake / "i3ipc.py").write_text(textwrap.dedent('''\
        import json, os
        class Node:
            def __init__(self, ident): self.id = ident
        class Tree:
            def state(self): return json.loads(open(os.environ["FAKE_STATE"]).read())
            def find_focused(self): return Node(self.state()["focused"])
            def leaves(self): return [Node(value) for value in self.state()["live"]]
        class Reply: success=True; error=None
        class Connection:
            def get_tree(self): return Tree()
            def command(self, command):
                path=os.environ["FAKE_STATE"]; state=json.loads(open(path).read())
                state["focused"]=state["steps"].pop(0); open(path,"w").write(json.dumps(state))
                return [Reply()]
    '''))
    projection = output / "active.txt"; projection.write_text("1 3\n")
    state = output / "state.json"
    env = {**os.environ, "PYTHONPATH": str(fake), "FAKE_STATE": str(state), "DIX_SWAY_ACTIVE_MEMBERS_FILE": str(projection)}
    for direction in ("left", "right", "up", "down"):
        state.write_text(json.dumps({"focused": 1, "live": [1,2,3], "steps": [2,3]}))
        completed = run(str(python), str(entry), direction, cwd=output, env=env)
        result = json.loads(completed.stdout)
        if result["focused_id"] != 3 or not result["matched"]: raise RuntimeError(str(result))
    print("wheel-sway-navigation=ok")
    return 0


if __name__ == "__main__": raise SystemExit(main())
