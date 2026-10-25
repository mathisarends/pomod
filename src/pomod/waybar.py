"""Render the timer state as a Waybar custom module (return-type: json).

CSS classes: offline, idle, work, short-break, long-break, break, running, paused.
"""

from .display import describe
from .durations import format_clock
from .protocol import Message

ICONS = {
    "idle": "🍅",
    "work": "🍅",
    "short_break": "☕",
    "long_break": "🌴",
    "paused": "⏸",
}


def render(state: Message | None) -> Message:
    """Build one Waybar line. `None` means pomod is unreachable."""
    if state is None:
        return _static("offline", "pomod is not running")
    if state["status"] == "idle":
        return _static("idle", "Click to start a work session")

    phase, status = state["phase"], state["status"]
    classes = [phase.replace("_", "-"), status]
    if phase != "work":
        classes.append("break")
    icon = ICONS["paused"] if status == "paused" else ICONS[phase]
    elapsed = 1 - state["remaining"] / state["duration"] if state["duration"] else 1.0
    return {
        "text": f"{icon} {format_clock(state['remaining'])}",
        "alt": phase,
        "class": classes,
        "percentage": round(100 * elapsed),
        "tooltip": describe(state),
    }


def _static(name: str, tooltip: str) -> Message:
    return {"text": ICONS["idle"], "alt": name, "class": [name], "tooltip": tooltip}
