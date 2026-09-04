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
class CompositionInstanceConfig:
    id: str
    use: str
    config: dict[str, Any]
    config_base_dir: Path
    startup: bool = False


@dataclass(frozen=True)
class CompositionSettings:
    trusted_module_roots: tuple[Path, ...] = ()
    instances: tuple[CompositionInstanceConfig, ...] = ()


@dataclass(frozen=True)
class EffectiveConfig:
    values: dict[str, Any]
    sources: dict[str, ConfigSource]
    loaded_files: list[Path]
    composition: CompositionSettings

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
    "reference_renderer_enabled": True,
    "reference_renderer_path": "/render",
    "composition": {"trusted_module_roots": [], "instance": []},
}

ENV_KEYS = {
    "DIX_RUNTIME_ROOT": "runtime_root",
    "DIX_INTERFACE_DIRS": "interface_dirs",
    "DIX_THEME": "theme",
    "DIX_HOST": "host",
    "DIX_PORT": "port",
    "DIX_REFERENCE_RENDERER_ENABLED": "reference_renderer_enabled",
    "DIX_REFERENCE_RENDERER_PATH": "reference_renderer_path",
}


def default_config_paths(cwd: Path | None = None) -> list[Path]:
    base = cwd or Path.cwd()
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [Path("/etc/dix/config.toml"), xdg / "dix" / "config.toml", base / "dix.toml"]


def _coerce_env_value(key: str, raw: str) -> Any:
    if key == "port":
        return int(raw)
    if key == "reference_renderer_enabled":
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        raise ValueError("reference_renderer_enabled env value must be boolean-like")
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
    composition_base_dir: Path | None = None

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
                if key == "composition":
                    composition_base_dir = path.expanduser().resolve().parent

    for env_key, key in ENV_KEYS.items():
        if env_key in env_map:
            value = _coerce_env_value(key, env_map[env_key])
            values[key] = value
            sources[key] = ConfigSource(key=key, value=value, source="env", detail=env_key)

    validate_config_values(values)
    composition = composition_settings_from_values(
        values,
        base_dir=composition_base_dir,
    )
    return EffectiveConfig(
        values=values,
        sources=sources,
        loaded_files=loaded_files,
        composition=composition,
    )


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
    if not isinstance(values.get("reference_renderer_enabled"), bool):
        raise ValueError("reference_renderer_enabled must be a boolean")
    path = values.get("reference_renderer_path")
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/"):
        raise ValueError("reference_renderer_path must start with '/' and must not end with '/'")
    port = values.get("port")
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    _validate_composition_config(values.get("composition"))


def composition_settings_from_values(
    values: dict[str, Any],
    *,
    base_dir: Path | None,
) -> CompositionSettings:
    raw = values.get("composition", DEFAULT_CONFIG["composition"])
    _validate_composition_config(raw)
    assert isinstance(raw, dict)
    if raw.get("instance", []) and base_dir is None:
        raise ValueError("composition instances require an explicit config source directory")
    roots = tuple(
        _resolve_config_path(item, base_dir=base_dir, label="trusted module root")
        for item in raw.get("trusted_module_roots", [])
    )
    instances = tuple(
        CompositionInstanceConfig(
            id=item["id"].strip(),
            use=item["use"].strip(),
            config=dict(item.get("config", {})),
            config_base_dir=base_dir,
            startup=item.get("startup", False),
        )
        for item in raw.get("instance", [])
    )
    return CompositionSettings(trusted_module_roots=roots, instances=instances)


def _validate_composition_config(raw: object) -> None:
    if not isinstance(raw, dict):
        raise ValueError("composition must be a table")
    unknown = sorted(set(raw) - {"trusted_module_roots", "instance"})
    if unknown:
        raise ValueError(f"unknown composition config key: {unknown[0]}")
    roots = raw.get("trusted_module_roots", [])
    if not isinstance(roots, list) or not all(
        isinstance(item, str) and item.strip() for item in roots
    ):
        raise ValueError("composition.trusted_module_roots must be a list of paths")
    instance_values = raw.get("instance", [])
    if not isinstance(instance_values, list):
        raise ValueError("composition.instance must be an array of tables")
    seen: set[str] = set()
    for index, item in enumerate(instance_values):
        if not isinstance(item, dict):
            raise ValueError(f"composition.instance[{index}] must be a table")
        unexpected = sorted(set(item) - {"id", "use", "startup", "config"})
        if unexpected:
            raise ValueError(
                f"unknown composition.instance[{index}] config key: {unexpected[0]}"
            )
        for key in ("id", "use"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"composition.instance[{index}].{key} must be non-empty")
        if item["id"].strip() in seen:
            raise ValueError(f"duplicate composition instance id: {item['id'].strip()}")
        seen.add(item["id"].strip())
        if not isinstance(item.get("startup", False), bool):
            raise ValueError(f"composition.instance[{index}].startup must be a boolean")
        if not isinstance(item.get("config", {}), dict):
            raise ValueError(f"composition.instance[{index}].config must be a table")


def _resolve_config_path(raw: str, *, base_dir: Path | None, label: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    if base_dir is None:
        raise ValueError(f"relative {label} requires an explicit config source: {raw}")
    return (base_dir / path).resolve()


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
        "reference_renderer_enabled = true\n"
        "reference_renderer_path = \"/render\"\n"
        "\n[composition]\n"
        "trusted_module_roots = []\n"
    )
    return True
