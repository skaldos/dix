from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

SourceKind = Literal["default", "file", "env"]


@dataclass(frozen=True)
class ConfigSource:
    key: str
    value: Any
    source: SourceKind
    detail: str


@dataclass(frozen=True)
class EffectiveConfig:
    values: dict[str, Any]
    sources: dict[str, ConfigSource]
    loaded_files: list[Path]

    def explain(self, key: str) -> ConfigSource:
        if key not in self.sources:
            raise KeyError(key)
        return self.sources[key]


DEFAULT_CONFIG: dict[str, Any] = {
    "runtime_root": ".dix/runtime",
    "interface_dirs": ["examples/interfaces"],
    "theme": "default",
    "host": "127.0.0.1",
    "port": 8000,
}

ENV_KEYS = {
    "DIX_RUNTIME_ROOT": "runtime_root",
    "DIX_INTERFACE_DIRS": "interface_dirs",
    "DIX_THEME": "theme",
    "DIX_HOST": "host",
    "DIX_PORT": "port",
}


def default_config_paths(cwd: Path | None = None) -> list[Path]:
    base = cwd or Path.cwd()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [Path("/etc/dix/config.toml"), xdg / "dix" / "config.toml", base / "dix.toml"]


def _coerce_env_value(key: str, raw: str) -> Any:
    if key == "port":
        return int(raw)
    if key == "interface_dirs":
        return [item.strip() for item in raw.split(os.pathsep) if item.strip()]
    return raw


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    # Keep v1 intentionally flat. Accept either top-level keys or [dix] for convenience.
    if "dix" in data and isinstance(data["dix"], dict):
        merged = dict(data)
        nested = merged.pop("dix")
        merged.update(nested)
        return merged
    return data


def load_effective_config(
    *, cwd: Path | None = None, paths: list[Path] | None = None, env: dict[str, str] | None = None
) -> EffectiveConfig:
    search_paths = paths if paths is not None else default_config_paths(cwd)
    env_map = env if env is not None else os.environ

    values = dict(DEFAULT_CONFIG)
    sources = {
        key: ConfigSource(key=key, value=value, source="default", detail="built-in default")
        for key, value in values.items()
    }
    loaded_files: list[Path] = []

    for path in search_paths:
        if not path.exists():
            continue
        raw = tomllib.loads(path.read_text())
        data = _flatten_config(raw)
        loaded_files.append(path)
        for key in DEFAULT_CONFIG:
            if key in data:
                values[key] = data[key]
                sources[key] = ConfigSource(
                    key=key, value=data[key], source="file", detail=str(path)
                )

    for env_key, key in ENV_KEYS.items():
        if env_key in env_map:
            value = _coerce_env_value(key, env_map[env_key])
            values[key] = value
            sources[key] = ConfigSource(key=key, value=value, source="env", detail=env_key)

    validate_config_values(values)
    return EffectiveConfig(values=values, sources=sources, loaded_files=loaded_files)


def validate_config_values(values: dict[str, Any]) -> None:
    if not isinstance(values.get("runtime_root"), str) or not values["runtime_root"]:
        raise ValueError("runtime_root must be a non-empty string")
    dirs = values.get("interface_dirs")
    if not isinstance(dirs, list) or not all(isinstance(item, str) and item for item in dirs):
        raise ValueError("interface_dirs must be a non-empty list of strings")
    if not isinstance(values.get("theme"), str) or not values["theme"]:
        raise ValueError("theme must be a non-empty string")
    if not isinstance(values.get("host"), str) or not values["host"]:
        raise ValueError("host must be a non-empty string")
    port = values.get("port")
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("port must be an integer between 1 and 65535")


def write_default_config(path: Path) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# dix local configuration\n"
        "runtime_root = \".dix/runtime\"\n"
        "interface_dirs = [\"examples/interfaces\"]\n"
        "theme = \"default\"\n"
        "host = \"127.0.0.1\"\n"
        "port = 8000\n"
    )
    return True
