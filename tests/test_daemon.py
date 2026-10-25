import json

import pytest

from pomod.daemon import STALE_AFTER, restore_timer
from pomod.store import StateStore


def request(daemon, cmd, **args):
    return daemon.handle_request({"cmd": cmd, "args": args})


def test_status_on_fresh_daemon(daemon):
    response = request(daemon, "status")
    assert response["ok"] is True
    assert response["changed"] is False
    assert response["state"]["status"] == "idle"


def test_start_returns_state(daemon):
    response = request(daemon, "start", work=60)
    assert response["ok"] and response["changed"]
    assert response["state"]["phase"] == "work"
    assert response["state"]["remaining"] == 60


def test_start_twice_is_ok_but_unchanged(daemon):
    request(daemon, "start")
    response = request(daemon, "start")
    assert response["ok"] is True
    assert response["changed"] is False
    assert "Already running" in response["message"]


def test_not_running_error(daemon):
    response = request(daemon, "pause")
    assert response["ok"] is False
    assert response["error"]["code"] == "not_running"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ({"cmd": "explode"}, "unknown_command"),
        ({"cmd": "start", "args": {"work": "25"}}, "bad_request"),
        ({"cmd": "start", "args": {"bogus": 1}}, "bad_request"),
        ({"cmd": "start", "args": {"work": True}}, "bad_request"),
        ({"cmd": "add"}, "bad_request"),
        ({"cmd": "stop", "args": []}, "bad_request"),
    ],
)
def test_bad_requests(daemon, message, code):
    response = daemon.handle_request(message)
    assert response["ok"] is False
    assert response["error"]["code"] == code


def test_changes_are_persisted(daemon):
    request(daemon, "start")
    saved = json.loads(daemon.store.path.read_text())
    assert saved["timer"]["phase"] == "work"


def test_tick_advances_phase(daemon, clock):
    request(daemon, "start")
    clock.now += 100
    daemon.tick()
    assert daemon.timer.phase == "short_break"
    assert daemon.timer.completed == 1


def test_tick_wakes_on_second_boundaries(daemon, clock):
    request(daemon, "start")
    clock.now += 0.25
    assert daemon.tick() == pytest.approx(0.75)


def test_idle_tick_sleeps_a_second(daemon):
    assert daemon.tick() == 1.0


def test_restore_drops_stale_running_phase(daemon, clock, tmp_path):
    request(daemon, "start")
    store = StateStore(daemon.store.path)
    timer = restore_timer(store, tmp_path / "missing.toml", now=clock.now + 100 + STALE_AFTER + 1)
    assert timer.status == "idle"


def test_restore_keeps_recent_phase(daemon, clock, tmp_path):
    request(daemon, "start")
    store = StateStore(daemon.store.path)
    timer = restore_timer(store, tmp_path / "missing.toml", now=clock.now + 50)
    assert timer.status == "running"
    assert timer.remaining(clock.now + 50) == 50
