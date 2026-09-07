#!/usr/bin/env zsh
set -euo pipefail

script_dir=${0:A:h}
repo_root=${script_dir:h:h:h}
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

launcher="$work_dir/dix-seed-hello.py"

cd "$repo_root"
uv run python -m dix.bootstrap build \
  "$script_dir/launcher.toml" \
  --output "$launcher"

print -- '--- generated launcher ---'
sed -n '1,240p' "$launcher"
print -- '--- no arguments ---'
PYTHONPATH="$repo_root/src" uv run python "$launcher"
print -- '--- one argument ---'
PYTHONPATH="$repo_root/src" uv run python "$launcher" Skaldos
