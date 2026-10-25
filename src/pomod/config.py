"""Daemon settings, read from ~/.config/pomo/config.toml.

Example:

    work = "25m"
    short_break = "5m"
    long_break = "15m"
    cycles = 4          # long break after every 4th work session
"""

import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Self

from .durations import parse_duration

_DURATION_FIELDS = ("work", "short_break", "long_break")


@dataclass(frozen=True)
class Settings:
    """All durations in seconds."""

    work: int = 25 * 60
    short_break: int = 5 * 60
    long_break: int = 15 * 60
    cycles: int = 4

    def __post_init__(self) -> None:
        for name in _DURATION_FIELDS:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.cycles < 1:
            raise ValueError("cycles must be at least 1")

    def with_overrides(self, **overrides: int | None) -> Self:
        return replace(
            self, **{key: value for key, value in overrides.items() if value is not None}
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> Self:
        """Build from config file values, where durations are human strings."""
        values = {name: parse_duration(data[name]) for name in _DURATION_FIELDS if name in data}
        if "cycles" in data:
            values["cycles"] = int(data["cycles"])
        return cls(**values)


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    with path.open("rb") as file:
        return Settings.from_config(tomllib.load(file))
