"""User-level configuration stored in ``~/.config/era5-etl/config.toml``.

Holds preferences that survive across sessions of the web UI: the chosen
``data_dir`` (where ``climate_data_store_db`` lives), default dataset,
last-used CDS endpoint URL, etc. Sensitive credentials are NOT stored here --
those still live in ``~/.cdsapirc`` or environment variables.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

import tomli_w

logger = logging.getLogger(__name__)


@dataclass
class UserConfig:
    """Persisted user preferences for the web UI."""

    data_dir: str = ""
    default_dataset: str = "era5-land"
    last_pick_dir: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _config_dir() -> Path:
    """Return the directory where the config file lives (created on demand)."""
    env_dir = os.environ.get("ERA5_ETL_CONFIG_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(base) / "era5-etl"
    return Path.home() / ".config" / "era5-etl"


def config_path() -> Path:
    return _config_dir() / "config.toml"


def load_user_config() -> UserConfig:
    """Load the user config from disk; return defaults if absent or corrupt."""
    path = config_path()
    if not path.exists():
        return UserConfig()
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("Failed to read %s: %s -- using defaults", path, exc)
        return UserConfig()
    return UserConfig(
        data_dir=str(data.get("data_dir", "")),
        default_dataset=str(data.get("default_dataset", "era5-land")),
        last_pick_dir=str(data.get("last_pick_dir", "")),
    )


def save_user_config(cfg: UserConfig) -> Path:
    """Write the user config to disk, creating directories as needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(cfg.as_dict(), f)
    logger.debug("Saved user config to %s", path)
    return path


def update_user_config(**changes: object) -> UserConfig:
    """Read, apply ``changes``, persist, and return the new config."""
    current = load_user_config()
    str_changes = {k: str(v) for k, v in changes.items() if hasattr(current, k)}
    new = replace(current, **str_changes)  # type: ignore[arg-type]
    save_user_config(new)
    return new


__all__ = [
    "UserConfig",
    "config_path",
    "load_user_config",
    "save_user_config",
    "update_user_config",
    "field",  # re-exported so tests can introspect dataclass fields
]
