import asyncio
import tempfile
import threading
import time
from pathlib import Path

import pytest

from pomod.config import Settings
from pomod.daemon import Daemon
from pomod.store import StateStore
from pomod.timer import Timer

SETTINGS = Settings(work=100, short_break=10, long_break=30, cycles=2)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def daemon(tmp_path, clock):
    timer = Timer(defaults=SETTINGS, settings=SETTINGS)
    return Daemon(timer, StateStore(tmp_path / "state.json"), clock=clock)


@pytest.fixture
def socket_path():
    # Not tmp_path: Unix socket paths are limited to ~108 characters.
    with tempfile.TemporaryDirectory(prefix="pomo-") as directory:
        yield Path(directory) / "pomo.sock"


class ServerThread:
    """Runs the daemon on a real socket in a background thread."""

    def __init__(self, daemon: Daemon, path: Path) -> None:
        self.path = path
        self._stop = asyncio.Event()
        self._runner = asyncio.Runner()
        self._thread = threading.Thread(target=self._run, args=(daemon,))

    def _run(self, daemon: Daemon) -> None:
        # Runner cleans up leftover tasks like asyncio.run() does in production,
        # e.g. a client that connected in the middle of shutdown.
        with self._runner:
            self._runner.run(daemon.serve(self.path, self._stop))

    def start(self) -> None:
        self._thread.start()
        for _ in range(500):
            if self.path.exists():
                return
            time.sleep(0.01)
        raise TimeoutError("daemon did not start")

    def stop(self) -> None:
        if self._thread.is_alive():
            self._runner.get_loop().call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=5)
            assert not self._thread.is_alive(), "daemon did not shut down"


@pytest.fixture
def server(daemon, socket_path):
    thread = ServerThread(daemon, socket_path)
    thread.start()
    yield thread
    thread.stop()
