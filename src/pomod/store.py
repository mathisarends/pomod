"""Persist the timer so a daemon restart picks up where it left off."""

import json
import logging
import os
from pathlib import Path

from .config import Settings
from .timer import Timer

log = logging.getLogger(__name__)

_FORMAT_VERSION = 1


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, defaults: Settings) -> Timer:
        """Return the saved timer, or a fresh one if nothing usable is on disk."""
        fresh = Timer(defaults=defaults, settings=defaults)
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return fresh
        except (OSError, ValueError) as error:
            log.warning("Ignoring unreadable state file %s: %s", self.path, error)
            return fresh

        if data.get("version") != _FORMAT_VERSION:
            log.warning("Ignoring state file with unknown version: %s", self.path)
            return fresh
        try:
            return Timer.from_dict(data["timer"], defaults)
        except (KeyError, TypeError, ValueError) as error:
            log.warning("Ignoring corrupt state file %s: %s", self.path, error)
            return fresh

    def save(self, timer: Timer) -> None:
        """Write atomically, so a crash never leaves a half-written file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": _FORMAT_VERSION, "timer": timer.to_dict()}, indent=2)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        tmp_path.write_text(payload)
        os.replace(tmp_path, self.path)
