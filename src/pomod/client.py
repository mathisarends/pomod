"""Blocking client for the pomod socket. Kept free of asyncio for fast startup."""

import json
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .protocol import SUBSCRIBE, Message, encode

# Error code for responses the client makes up itself when it can't connect.
DAEMON_UNAVAILABLE = "daemon_unavailable"


class DaemonUnavailableError(Exception):
    pass


def request(socket_path: Path, command: str, args: dict[str, Any] | None = None) -> Message:
    with _connect(socket_path, timeout=5.0) as sock, sock.makefile("rb") as stream:
        sock.sendall(encode({"cmd": command, "args": args or {}}))
        line = stream.readline()
    if not line:
        raise DaemonUnavailableError("pomod closed the connection without answering")
    return json.loads(line)


def subscribe(socket_path: Path) -> Iterator[Message]:
    """Yield events until the daemon goes away."""
    with _connect(socket_path, timeout=None) as sock, sock.makefile("rb") as stream:
        sock.sendall(encode({"cmd": SUBSCRIBE}))
        for line in stream:
            yield json.loads(line)


def _connect(socket_path: Path, timeout: float | None) -> socket.socket:
    if not hasattr(socket, "AF_UNIX"):
        raise DaemonUnavailableError("this platform has no Unix sockets")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(socket_path))
    except OSError as error:
        sock.close()
        raise DaemonUnavailableError(
            f"pomod is not running ({socket_path}: {error.strerror}). "
            "Start it with `systemctl --user start pomod` or just `pomod`."
        ) from None
    return sock
