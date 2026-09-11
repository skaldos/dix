from __future__ import annotations

import importlib.util
from pathlib import Path


_PATH = Path(__file__).parents[1] / "modules/dix/sway/apps/cli/runtime.py"
_SPEC = importlib.util.spec_from_file_location("dix_sway_cli_application_runtime", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
Runtime = _MODULE.Runtime
