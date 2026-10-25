"""pomod: owns the timer and serves it over a Unix socket."""

import asyncio
import contextlib
import logging
import math
import signal
import socket
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from . import __version__, paths
from .config import load_settings
from .hooks import HookRunner
from .protocol import (
    BAD_REQUEST,
    NOT_RUNNING,
    SUBSCRIBE,
    UNKNOWN_COMMAND,
    Message,
    RequestError,
    decode,
    encode,
)
from .store import StateStore
from .timer import Event, NotRunningError, Outcome, Status, Timer

log = logging.getLogger("pomod")

Clock = Callable[[], float]

# A phase whose deadline passed longer ago than this when the daemon starts
# (machine was off, daemon was stopped) is dropped instead of resumed.
STALE_AFTER = 60 * 60

_START_ARGS = frozenset({"work", "short_break", "long_break", "cycles"})


class DaemonAlreadyRunningError(Exception):
    pass


class Daemon:
    def __init__(
        self,
        timer: Timer,
        store: StateStore,
        hooks: HookRunner | None = None,
        clock: Clock = time.time,
    ) -> None:
        self.timer = timer
        self.store = store
        self.hooks = hooks
        self.clock = clock
        self._subscribers: set[asyncio.Queue[Message]] = set()
        self._connections: set[asyncio.Task[None]] = set()

    # -- commands --------------------------------------------------------------

    def handle_request(self, request: Message) -> Message:
        now = self.clock()
        try:
            outcome = self._dispatch(request, now)
        except RequestError as error:
            return self._error(error.code, error.message, now)
        except NotRunningError as error:
            return self._error(NOT_RUNNING, str(error), now)

        if outcome.changed:
            self._publish(outcome.events, now)
        return {
            "ok": True,
            "changed": outcome.changed,
            "message": outcome.message,
            "state": self.timer.snapshot(now),
        }

    def _dispatch(self, request: Message, now: float) -> Outcome:
        command = request.get("cmd")
        args = request.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise RequestError(BAD_REQUEST, "args must be an object")

        match command:
            case "status":
                _int_args(args, allowed=frozenset())
                return Outcome(False, "")
            case "start":
                return self.timer.start(now, **_int_args(args, allowed=_START_ARGS))
            case "add":
                seconds = _int_args(args, allowed=frozenset({"seconds"})).get("seconds")
                if seconds is None:
                    raise RequestError(BAD_REQUEST, "add needs args.seconds")
                return self.timer.add(now, seconds)
            case "pause" | "resume" | "toggle" | "skip" | "stop":
                _int_args(args, allowed=frozenset())
                return getattr(self.timer, command)(now)
            case _:
                raise RequestError(UNKNOWN_COMMAND, f"unknown command: {command!r}")

    def _error(self, code: str, message: str, now: float) -> Message:
        return {
            "ok": False,
            "error": {"code": code, "message": message},
            "state": self.timer.snapshot(now),
        }

    # -- clock -----------------------------------------------------------------

    def tick(self) -> float:
        """Advance the timer if a phase ended. Returns seconds until the next tick."""
        now = self.clock()
        if events := self.timer.advance(now):
            self._publish(events, now)
        elif self.timer.status is Status.RUNNING:
            self._broadcast({"event": "tick", "state": self.timer.snapshot(now)})

        if self.timer.status is not Status.RUNNING:
            return 1.0
        # Wake up when the displayed second changes, so clients count smoothly.
        remaining = self.timer.remaining(now)
        until_next_second = remaining - math.floor(remaining)
        return until_next_second if until_next_second > 0.05 else until_next_second + 1.0

    async def _run_clock(self) -> None:
        # Short sleeps against the wall clock instead of one long sleep until the
        # deadline: asyncio's monotonic clock stands still during suspend.
        while True:
            await asyncio.sleep(self.tick())

    # -- events ----------------------------------------------------------------

    def _publish(self, events: tuple[Event, ...], now: float) -> None:
        self.store.save(self.timer)
        state = self.timer.snapshot(now)
        for event in events:
            log.info("%s (%s, cycle %s)", event, state["phase"], state["cycle"])
            self._broadcast({"event": event.value, "state": state})
            if self.hooks:
                self.hooks.run(event, state)

    def _broadcast(self, message: Message) -> None:
        for queue in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):  # slow client, skip a beat
                queue.put_nowait(message)

    # -- socket ----------------------------------------------------------------

    async def serve(self, socket_path: Path, stop: asyncio.Event) -> None:
        _claim_socket(socket_path)
        server = await asyncio.start_unix_server(self._handle_client, path=socket_path)
        socket_path.chmod(0o600)
        clock = asyncio.create_task(self._run_clock())
        log.info("pomod %s listening on %s", __version__, socket_path)
        try:
            await stop.wait()
        finally:
            clock.cancel()
            server.close()
            # Subscribers (e.g. Waybar) never hang up on their own, so end them.
            for connection in self._connections:
                connection.cancel()
            await asyncio.gather(*self._connections, return_exceptions=True)
            await server.wait_closed()
            if self.hooks:
                await self.hooks.wait()
            socket_path.unlink(missing_ok=True)
            self.store.save(self.timer)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        connection = asyncio.current_task()
        assert connection is not None
        self._connections.add(connection)
        try:
            line = await reader.readline()
            if not line:
                return
            try:
                request = decode(line)
            except RequestError as error:
                response = self._error(error.code, error.message, self.clock())
            else:
                if request.get("cmd") == SUBSCRIBE:
                    await self._stream(reader, writer)
                    return
                response = self.handle_request(request)
            writer.write(encode(response))
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            self._connections.discard(connection)
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def _stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=64)
        queue.put_nowait({"event": "state", "state": self.timer.snapshot(self.clock())})
        self._subscribers.add(queue)

        async def pump() -> None:
            while True:
                writer.write(encode(await queue.get()))
                await writer.drain()

        pump_task = asyncio.create_task(pump())
        # Clients send nothing after subscribing, so a finished read means they left.
        disconnected = asyncio.create_task(reader.read())
        try:
            await asyncio.wait({pump_task, disconnected}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._subscribers.discard(queue)
            pump_task.cancel()
            disconnected.cancel()
            await asyncio.gather(pump_task, disconnected, return_exceptions=True)


def _int_args(args: dict[str, Any], allowed: frozenset[str]) -> dict[str, int]:
    if unknown := set(args) - allowed:
        raise RequestError(BAD_REQUEST, f"unexpected args: {', '.join(sorted(unknown))}")
    for name, value in args.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise RequestError(BAD_REQUEST, f"{name} must be an integer (seconds)")
    return args


def _claim_socket(path: Path) -> None:
    """Remove a leftover socket file, unless another daemon is still behind it."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        return
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.connect(str(path))
        except OSError:
            path.unlink()
            return
    raise DaemonAlreadyRunningError(f"another pomod is already listening on {path}")


def restore_timer(store: StateStore, config_path: Path, now: float) -> Timer:
    timer = store.load(load_settings(config_path))
    is_stale = timer.deadline is not None and timer.deadline < now - STALE_AFTER
    if timer.status is Status.RUNNING and is_stale:
        log.info("Dropping stale %s phase from %s", timer.phase, store.path)
        timer.stop(now)
    return timer


async def _serve_until_signal(daemon: Daemon, socket_path: Path) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await daemon.serve(socket_path, stop)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--socket",
    "socket_path",
    type=click.Path(path_type=Path),
    default=paths.socket_path,
    show_default="$XDG_RUNTIME_DIR/pomo.sock",
    help="Where to listen.",
)
@click.option("-v", "--verbose", is_flag=True, help="Log debug output.")
@click.version_option(__version__)
def main(socket_path: Path, verbose: bool) -> None:
    """Run the pomod daemon. Control it with `pomo`."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    store = StateStore(paths.state_file())
    try:
        timer = restore_timer(store, paths.config_file(), time.time())
    except ValueError as error:
        raise click.ClickException(f"invalid config {paths.config_file()}: {error}") from None

    try:
        daemon = Daemon(timer, store, hooks=HookRunner(paths.hooks_dir()))
        asyncio.run(_serve_until_signal(daemon, socket_path))
    except DaemonAlreadyRunningError as error:
        raise click.ClickException(str(error)) from None
