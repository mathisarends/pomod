import json
import socket

import pytest
from click.testing import CliRunner

from pomod.cli import (
    EXIT_DAEMON_UNAVAILABLE,
    EXIT_NOT_RUNNING,
    EXIT_OK,
    EXIT_USAGE,
    cli,
    watch_lines,
)
from pomod.display import describe

needs_unix_socket = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs Unix sockets")


@pytest.fixture
def pomo(server):
    runner = CliRunner()

    def run(*args):
        return runner.invoke(cli, ["--socket", str(server.path), *args])

    return run


def test_describe_idle():
    assert describe({"status": "idle", "phase": "idle"}) == "Idle."


def test_describe_paused_break():
    state = {
        "status": "paused",
        "phase": "short_break",
        "remaining": 61.2,
        "cycle": 2,
        "cycles": 4,
        "completed": 2,
    }
    assert describe(state) == "Short break (paused) 01:02 left · cycle 2/4 · 2 done"


def test_unreachable_daemon(tmp_path):
    result = CliRunner().invoke(cli, ["--socket", str(tmp_path / "nope.sock"), "status", "--json"])
    assert result.exit_code == EXIT_DAEMON_UNAVAILABLE
    assert json.loads(result.output)["error"]["code"] == "daemon_unavailable"


def test_bad_duration_is_a_usage_error(tmp_path):
    result = CliRunner().invoke(cli, ["--socket", str(tmp_path / "x"), "start", "--work", "lots"])
    assert result.exit_code == EXIT_USAGE
    assert "invalid duration" in result.output


@needs_unix_socket
def test_start_and_status(pomo):
    result = pomo("start", "--work", "50")
    assert result.exit_code == EXIT_OK
    assert "Work 50:00 left" in result.output

    status = json.loads(pomo("status", "--json").output)
    assert status["state"]["settings"]["work"] == 3000


@needs_unix_socket
def test_start_twice_exits_ok_with_message(pomo):
    pomo("start")
    result = pomo("start", "--json")
    assert result.exit_code == EXIT_OK
    response = json.loads(result.output)
    assert response["changed"] is False


@needs_unix_socket
def test_pause_without_timer(pomo):
    result = pomo("pause")
    assert result.exit_code == EXIT_NOT_RUNNING
    assert "idle" in result.output


@needs_unix_socket
def test_add_accepts_negative_durations(pomo):
    pomo("start", "--work", "10")
    pomo("pause")
    response = json.loads(pomo("add", "-2m", "--json").output)
    assert response["state"]["remaining"] == 480


@needs_unix_socket
def test_toggle_skip_stop(pomo):
    assert "Work session started" in pomo("toggle").output
    assert "Paused" in pomo("toggle").output
    assert "Skipped to short_break" in pomo("skip").output
    assert "Stopped" in pomo("stop").output


def test_watch_reports_offline_daemon(tmp_path):
    lines = watch_lines(tmp_path / "nope.sock", as_json=False)
    assert json.loads(next(lines))["class"] == ["offline"]


@needs_unix_socket
def test_watch_streams_waybar_lines(server, pomo):
    lines = watch_lines(server.path, as_json=False)
    assert json.loads(next(lines))["class"] == ["idle"]
    pomo("start")
    line = json.loads(next(lines))
    assert line["class"] == ["work", "running"]
    assert line["text"] == "🍅 01:40"


@needs_unix_socket
def test_watch_json_mode_passes_events_through(server, pomo):
    lines = watch_lines(server.path, as_json=True)
    assert json.loads(next(lines))["event"] == "state"
    pomo("start")
    assert json.loads(next(lines))["event"] == "work-start"
