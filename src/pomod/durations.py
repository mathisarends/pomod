"""Parse and format human durations like "25", "5m", "90s" or "1h30m"."""

import math
import re

_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WITH_UNITS = re.compile(r"(?:\d+(?:\.\d+)?[hms])+")
_PART = re.compile(r"(\d+(?:\.\d+)?)([hms])")


def parse_duration(value: str | int | float) -> int:
    """Return the duration in seconds. A bare number means minutes."""
    if isinstance(value, bool):
        raise ValueError(f"invalid duration: {value!r}")
    if isinstance(value, int | float):
        return round(value * 60)

    text = value.strip().lower().replace(" ", "")
    sign = -1 if text.startswith("-") else 1
    if text[:1] in ("+", "-"):
        text = text[1:]

    if _NUMBER.fullmatch(text):
        return sign * round(float(text) * 60)
    if _WITH_UNITS.fullmatch(text):
        seconds = sum(float(n) * _UNIT_SECONDS[unit] for n, unit in _PART.findall(text))
        return sign * round(seconds)
    raise ValueError(f"invalid duration: {value!r} (try 25, 5m, 90s or 1h30m)")


def format_clock(seconds: float) -> str:
    """Countdown style: 25:00, 04:05, 1:02:03. Rounds up, so 00:00 means done."""
    total = max(0, math.ceil(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
