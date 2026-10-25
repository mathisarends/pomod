import pytest

from pomod.config import Settings
from pomod.timer import Event, NotRunningError, Phase, Status, Timer

SETTINGS = Settings(work=100, short_break=10, long_break=30, cycles=2)


@pytest.fixture
def timer():
    return Timer(defaults=SETTINGS, settings=SETTINGS)


def test_starts_idle(timer):
    assert timer.status is Status.IDLE
    assert timer.remaining(0) == 0


def test_start_sets_deadline(timer):
    outcome = timer.start(now=1000)
    assert outcome.changed and outcome.events == (Event.WORK_START,)
    assert timer.phase is Phase.WORK
    assert timer.deadline == 1100
    assert timer.remaining(1040) == 60


def test_start_while_running_is_a_noop(timer):
    timer.start(now=0)
    outcome = timer.start(now=5, work=999)
    assert not outcome.changed
    assert "Already running" in outcome.message
    assert timer.deadline == 100


def test_start_overrides_apply_to_session_only(timer):
    timer.start(now=0, work=3000)
    assert timer.duration == 3000
    timer.stop(now=1)
    timer.start(now=2)
    assert timer.duration == 100


def test_pause_and_resume_preserve_remaining(timer):
    timer.start(now=0)
    assert timer.pause(now=30).events == (Event.PAUSE,)
    assert timer.status is Status.PAUSED
    assert timer.remaining(10_000) == 70
    assert timer.resume(now=500).events == (Event.RESUME,)
    assert timer.deadline == 570


def test_pause_twice_is_a_noop(timer):
    timer.start(now=0)
    timer.pause(now=1)
    assert not timer.pause(now=2).changed


def test_commands_on_idle_timer_raise(timer):
    for command in (timer.pause, timer.resume, timer.skip):
        with pytest.raises(NotRunningError):
            command(now=0)
    with pytest.raises(NotRunningError):
        timer.add(now=0, seconds=60)


def test_toggle_goes_start_pause_resume(timer):
    assert timer.toggle(now=0).events == (Event.WORK_START,)
    assert timer.toggle(now=1).events == (Event.PAUSE,)
    assert timer.toggle(now=2).events == (Event.RESUME,)


def test_full_cycle_with_long_break(timer):
    timer.start(now=0)
    assert timer.advance(now=99) == ()
    assert timer.advance(now=100) == (Event.BREAK_START,)
    assert (timer.phase, timer.completed, timer.cycle) == (Phase.SHORT_BREAK, 1, 1)
    assert timer.advance(now=110) == (Event.WORK_START,)
    assert (timer.phase, timer.cycle) == (Phase.WORK, 2)
    timer.advance(now=210)
    assert timer.phase is Phase.LONG_BREAK
    assert timer.completed == 2
    timer.advance(now=240)
    assert (timer.phase, timer.cycle) == (Phase.WORK, 1)


def test_late_advance_starts_next_phase_from_now(timer):
    timer.start(now=0)
    timer.advance(now=5000)  # e.g. woke up from suspend
    assert timer.deadline == 5010


def test_paused_timer_never_advances(timer):
    timer.start(now=0)
    timer.pause(now=50)
    assert timer.advance(now=10_000) == ()


def test_skip_does_not_count_as_completed(timer):
    timer.start(now=0)
    assert timer.skip(now=10).events == (Event.BREAK_START,)
    assert timer.completed == 0
    assert timer.phase is Phase.SHORT_BREAK


def test_skip_while_paused_stays_paused(timer):
    timer.start(now=0)
    timer.pause(now=10)
    timer.skip(now=20)
    assert timer.status is Status.PAUSED
    assert timer.remaining(999) == 10


def test_add_extends_running_and_paused(timer):
    timer.start(now=0)
    timer.add(now=10, seconds=60)
    assert timer.remaining(10) == 150
    timer.pause(now=10)
    timer.add(now=10, seconds=-1000)
    assert timer.remaining(10) == 0


def test_stop(timer):
    timer.start(now=0)
    assert timer.stop(now=1).events == (Event.STOP,)
    assert timer.status is Status.IDLE
    assert not timer.stop(now=2).changed


def test_roundtrip(timer):
    timer.start(now=0, work=200)
    timer.pause(now=20)
    restored = Timer.from_dict(timer.to_dict(), defaults=SETTINGS)
    assert restored.snapshot(50) == timer.snapshot(50)
