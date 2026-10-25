"""Human-readable text for a timer state, shared by the CLI and Waybar."""

from .durations import format_clock
from .protocol import Message

PHASE_LABELS = {
    "idle": "Idle",
    "work": "Work",
    "short_break": "Short break",
    "long_break": "Long break",
}


def describe(state: Message) -> str:
    """One line, e.g. `Work 18:42 left · cycle 2/4 · 1 done`."""
    if state["status"] == "idle":
        return "Idle."
    label = PHASE_LABELS[state["phase"]]
    if state["status"] == "paused":
        label += " (paused)"
    return (
        f"{label} {format_clock(state['remaining'])} left"
        f" · cycle {state['cycle']}/{state['cycles']} · {state['completed']} done"
    )
