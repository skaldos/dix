#!/usr/bin/env zsh
set -euo pipefail

script_dir=${0:A:h}
repo_root=${script_dir:h:h:h}
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

wheel_dir="$work_dir/wheel"
venv_dir="$work_dir/venv"
launcher="$work_dir/dix-seed-hello.py"
host_python=${DIX_VERIFY_PYTHON:-/usr/bin/python3}

cd "$repo_root"
uv build --wheel --no-sources --out-dir "$wheel_dir"
wheel=("$wheel_dir"/*.whl)
"$host_python" "$script_dir/verify_wheel.py" "$wheel[1]"

"$host_python" -m venv "$venv_dir"
"$venv_dir/bin/pip" install --no-deps "$wheel[1]"

# Everything below this line runs through the clean venv without uv.
"$venv_dir/bin/python" -m dix.bootstrap --help
"$venv_dir/bin/python" -m dix.bootstrap build \
  "$script_dir/launcher.toml" \
  --output "$launcher"
"$venv_dir/bin/python" "$launcher"
"$venv_dir/bin/python" "$launcher" Skaldos
