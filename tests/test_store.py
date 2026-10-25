import json

import pytest

from pomod.config import Settings
from pomod.store import StateStore
from pomod.timer import Status

DEFAULTS = Settings(work=100)


@pytest.fixture
def store(tmp_path):
    return StateStore(tmp_path / "pomo" / "state.json")


def test_missing_file_gives_idle_timer(store):
    timer = store.load(DEFAULTS)
    assert timer.status is Status.IDLE
    assert timer.settings == DEFAULTS


def test_save_and_load_roundtrip(store):
    timer = store.load(DEFAULTS)
    timer.start(now=0)
    timer.pause(now=40)
    store.save(timer)

    restored = store.load(DEFAULTS)
    assert restored.status is Status.PAUSED
    assert restored.remaining(now=999) == 60


def test_save_leaves_no_temp_file(store):
    store.save(store.load(DEFAULTS))
    assert [p.name for p in store.path.parent.iterdir()] == ["state.json"]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps({"version": 99, "timer": {}}),
        json.dumps({"version": 1, "timer": {"phase": "nonsense"}}),
    ],
)
def test_broken_file_gives_fresh_timer(store, content):
    store.path.parent.mkdir(parents=True)
    store.path.write_text(content)
    assert store.load(DEFAULTS).status is Status.IDLE
