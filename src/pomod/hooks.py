"""Run user scripts from ~/.config/pomo/hooks/ when the timer changes.

A hook is any executable named after an event, e.g. ``on-work-start`` or
``on-break-start``. It gets the timer state as POMO_* environment variables
and runs in the background, so a slow hook never delays the timer.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from .protocol import Message
from .timer import Event

log = logging.getLogger(__name__)

HOOK_EVENTS = frozenset(Event) - {Event.UPDATE}


class HookRunner:
    def __init__(self, directory: Path, timeout: float = 30.0) -> None:
        self.directory = directory
        self.timeout = timeout
        self._running: set[asyncio.Task[None]] = set()

    def script_for(self, event: Event) -> Path | None:
        script = self.directory / f"on-{event}"
        if event in HOOK_EVENTS and script.is_file() and os.access(script, os.X_OK):
            return script
        return None

    def run(self, event: Event, state: Message) -> None:
        """Start the hook for `event`, if there is one. Needs a running event loop."""
        if script := self.script_for(event):
            task = asyncio.create_task(self._execute(script, hook_env(event, state)))
            self._running.add(task)
            task.add_done_callback(self._running.discard)

    async def wait(self) -> None:
        """Wait for all hooks that are still running."""
        await asyncio.gather(*self._running, return_exceptions=True)

    async def _execute(self, script: Path, env: dict[str, str]) -> None:
        # Output goes straight to the daemon's stdout/stderr (the journal).
        # Capturing it would make us wait for anything the hook starts in
        # the background, since those children inherit the pipe.
        try:
            process = await asyncio.create_subprocess_exec(
                script, env=env, stdin=asyncio.subprocess.DEVNULL
            )
        except OSError as error:
            log.warning("Hook %s could not start: %s", script.name, error)
            return

        try:
            returncode = await asyncio.wait_for(process.wait(), self.timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            log.warning("Hook %s killed after %ss", script.name, self.timeout)
            return

        if returncode:
            log.warning("Hook %s exited with %s", script.name, returncode)


def hook_env(event: Event, state: Message) -> dict[str, str]:
    return {
        **os.environ,
        "POMO_EVENT": event.value,
        "POMO_PHASE": state["phase"],
        "POMO_STATUS": state["status"],
        "POMO_REMAINING": str(round(state["remaining"])),
        "POMO_DURATION": str(state["duration"]),
        "POMO_CYCLE": str(state["cycle"]),
        "POMO_CYCLES": str(state["cycles"]),
        "POMO_COMPLETED": str(state["completed"]),
        "POMO_STATE": json.dumps(state),
    }
