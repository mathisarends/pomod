"""End-to-end tests over a real Unix socket."""

import json
import socket

import pytest

from pomod.daemon import DaemonAlreadyRunningError, _claim_socket, _listen

pytestmark = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets")


def connect(path):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(str(path))
    return sock


def send(path, payload: bytes) -> dict:
    with connect(path) as sock:
        sock.sendall(payload)
        return json.loads(sock.makefile("rb").readline())


def test_request_response(server):
    response = send(server.path, b'{"cmd": "start", "args": {"work": 60}}\n')
    assert response["ok"] is True
    assert response["state"]["phase"] == "work"


def test_invalid_json(server):
    response = send(server.path, b"nope\n")
    assert response["error"]["code"] == "bad_request"


def test_socket_is_private(server):
    assert server.path.stat().st_mode & 0o777 == 0o600


def test_subscribe_streams_events(server):
    with connect(server.path) as sock:
        sock.sendall(b'{"cmd": "subscribe"}\n')
        stream = sock.makefile("rb")
        assert json.loads(stream.readline())["event"] == "state"

        send(server.path, b'{"cmd": "start"}\n')
        event = json.loads(stream.readline())
        assert event["event"] == "work-start"
        assert event["state"]["status"] == "running"


def test_second_daemon_refuses_to_start(server):
    with pytest.raises(DaemonAlreadyRunningError):
        _claim_socket(server.path)
    # Connections are handled in order: once this answers, the probe is done too
    # and does not race the shutdown.
    send(server.path, b'{"cmd": "status"}\n')


def test_socket_accepts_as_soon_as_it_exists(socket_path):
    sock = _listen(socket_path)
    try:
        assert [p.name for p in socket_path.parent.iterdir()] == [socket_path.name]
        connect(socket_path).close()  # backlog accepts before the server runs
    finally:
        sock.close()


def test_leftover_socket_file_is_replaced(socket_path):
    leftover = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    leftover.bind(str(socket_path))
    leftover.close()  # file stays, nobody listens
    _claim_socket(socket_path)
    assert not socket_path.exists()


def test_shutdown_ends_subscriber_streams(server):
    with connect(server.path) as sock:
        sock.sendall(b'{"cmd": "subscribe"}\n')
        stream = sock.makefile("rb")
        stream.readline()
        server.stop()
        assert stream.readline() == b""
    assert not server.path.exists()
