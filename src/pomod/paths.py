"""Where pomod keeps its socket, state, config and hooks (XDG base dirs)."""

import os
from pathlib import Path


def _xdg_dir(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


def socket_path() -> Path:
    if override := os.environ.get("POMO_SOCKET"):
        return Path(override)
    if runtime_dir := os.environ.get("XDG_RUNTIME_DIR"):
        return Path(runtime_dir) / "pomo.sock"
    return Path(f"/tmp/pomo-{os.getuid()}.sock")


def config_dir() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / "pomo"


def config_file() -> Path:
    return config_dir() / "config.toml"


def hooks_dir() -> Path:
    return config_dir() / "hooks"


def state_file() -> Path:
    return _xdg_dir("XDG_STATE_HOME", ".local/state") / "pomo" / "state.json"
