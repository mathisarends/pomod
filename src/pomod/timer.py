"""The Pomodoro state machine.

Pure logic without I/O: every method takes the current time as ``now`` (Unix
timestamp). A running phase stores an absolute ``deadline`` instead of the
remaining time, so the timer stays correct across suspend and restarts.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Self

from .config import Settings


class Phase(StrEnum):
    IDLE = "idle"
    WORK = "work"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class Status(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"


class Event(StrEnum):
    """Emitted on state changes. Drives hooks and subscriber streams."""

    WORK_START = "work-start"
    BREAK_START = "break-start"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    UPDATE = "update"  # changed, but nothing worth a hook (e.g. `add`)


class NotRunningError(Exception):
    """The command needs an active phase, but the timer is idle."""


@dataclass(frozen=True)
class Outcome:
    changed: bool
    message: str
    events: tuple[Event, ...] = ()


@dataclass
class Timer:
    defaults: Settings = field(default_factory=Settings)
    settings: Settings = field(default_factory=Settings)
    phase: Phase = Phase.IDLE
    duration: int = 0
    deadline: float | None = None  # set while running
    paused_remaining: float | None = None  # set while paused
    cycle: int = 0
    completed: int = 0

    @property
    def status(self) -> Status:
        if self.phase is Phase.IDLE:
            return Status.IDLE
        if self.paused_remaining is not None:
            return Status.PAUSED
        return Status.RUNNING

    def remaining(self, now: float) -> float:
        if self.paused_remaining is not None:
            return self.paused_remaining
        if self.deadline is not None:
            return max(0.0, self.deadline - now)
        return 0.0

    def snapshot(self, now: float) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "status": self.status.value,
            "remaining": round(self.remaining(now), 3),
            "duration": self.duration,
            "deadline": self.deadline,
            "cycle": self.cycle,
            "cycles": self.settings.cycles,
            "completed": self.completed,
            "settings": self.settings.to_dict(),
        }

    def start(
        self,
        now: float,
        *,
        work: int | None = None,
        short_break: int | None = None,
        long_break: int | None = None,
        cycles: int | None = None,
    ) -> Outcome:
        if self.status is not Status.IDLE:
            return Outcome(
                False,
                f"Already {self.status} ({self.phase}). Run `pomo stop` first to restart.",
            )
        self.settings = self.defaults.with_overrides(
            work=work, short_break=short_break, long_break=long_break, cycles=cycles
        )
        self.cycle = 1
        self.completed = 0
        self._enter(Phase.WORK, now)
        return Outcome(True, "Work session started.", (Event.WORK_START,))

    def pause(self, now: float) -> Outcome:
        self._require_active("pause")
        if self.status is Status.PAUSED:
            return Outcome(False, "Already paused.")
        self.paused_remaining = self.remaining(now)
        self.deadline = None
        return Outcome(True, "Paused.", (Event.PAUSE,))

    def resume(self, now: float) -> Outcome:
        self._require_active("resume")
        if self.paused_remaining is None:
            return Outcome(False, "Already running.")
        self.deadline = now + self.paused_remaining
        self.paused_remaining = None
        return Outcome(True, "Resumed.", (Event.RESUME,))

    def toggle(self, now: float) -> Outcome:
        match self.status:
            case Status.IDLE:
                return self.start(now)
            case Status.RUNNING:
                return self.pause(now)
            case Status.PAUSED:
                return self.resume(now)

    def skip(self, now: float) -> Outcome:
        self._require_active("skip")
        was_paused = self.status is Status.PAUSED
        event = self._next_phase(now, finished=False)
        if was_paused:
            self.pause(now)
        return Outcome(True, f"Skipped to {self.phase}.", (event,))

    def stop(self, now: float) -> Outcome:
        if self.status is Status.IDLE:
            return Outcome(False, "Already stopped.")
        self.phase = Phase.IDLE
        self.duration = 0
        self.deadline = None
        self.paused_remaining = None
        self.cycle = 0
        return Outcome(True, "Stopped.", (Event.STOP,))

    def add(self, now: float, seconds: int) -> Outcome:
        """Extend the current phase, or shorten it with a negative value."""
        self._require_active("extend")
        if self.paused_remaining is not None:
            self.paused_remaining = max(0.0, self.paused_remaining + seconds)
        elif self.deadline is not None:
            self.deadline = max(now, self.deadline + seconds)
        self.duration = max(0, self.duration + seconds)
        verb = "Added" if seconds >= 0 else "Removed"
        return Outcome(True, f"{verb} {abs(seconds)}s.", (Event.UPDATE,))

    def advance(self, now: float) -> tuple[Event, ...]:
        """Move on to the next phase once the deadline has passed."""
        if self.status is not Status.RUNNING or self.remaining(now) > 0:
            return ()
        return (self._next_phase(now, finished=True),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings.to_dict(),
            "phase": self.phase.value,
            "duration": self.duration,
            "deadline": self.deadline,
            "paused_remaining": self.paused_remaining,
            "cycle": self.cycle,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: Settings) -> Self:
        return cls(
            defaults=defaults,
            settings=Settings(**data["settings"]),
            phase=Phase(data["phase"]),
            duration=data["duration"],
            deadline=data["deadline"],
            paused_remaining=data["paused_remaining"],
            cycle=data["cycle"],
            completed=data["completed"],
        )

    def _require_active(self, action: str) -> None:
        if self.status is Status.IDLE:
            raise NotRunningError(f"Nothing to {action}, the timer is idle.")

    def _enter(self, phase: Phase, now: float) -> None:
        durations = {
            Phase.WORK: self.settings.work,
            Phase.SHORT_BREAK: self.settings.short_break,
            Phase.LONG_BREAK: self.settings.long_break,
        }
        self.phase = phase
        self.duration = durations[phase]
        # Count from `now`, not from the old deadline: after a long suspend we
        # want one fresh phase, not a burst of phases that ended while asleep.
        self.deadline = now + self.duration
        self.paused_remaining = None

    def _next_phase(self, now: float, *, finished: bool) -> Event:
        if self.phase is Phase.WORK:
            if finished:
                self.completed += 1
            is_long = self.cycle >= self.settings.cycles
            self._enter(Phase.LONG_BREAK if is_long else Phase.SHORT_BREAK, now)
            return Event.BREAK_START
        self.cycle = 1 if self.phase is Phase.LONG_BREAK else self.cycle + 1
        self._enter(Phase.WORK, now)
        return Event.WORK_START
