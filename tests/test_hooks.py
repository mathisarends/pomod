import asyncio
import logging
import os

import pytest

from pomod.hooks import HookRunner, hook_env
from pomod.timer import Event

pytestmark = pytest.mark.skipif(os.name != "posix", reason="hooks are shell scripts")

STATE = {
    "phase": "work",
    "status": "running",
    "remaining": 1499.6,
    "duration": 1500,
    "cycle": 2,
    "cycles": 4,
    "completed": 1,
}


def write_hook(directory, name, body):
    script = directory / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


def run_hook(runner, event):
    async def scenario():
        runner.run(event, STATE)
        await runner.wait()

    asyncio.run(scenario())


def test_hook_receives_state_as_env(tmp_path):
    out = tmp_path / "out"
    write_hook(tmp_path, "on-work-start", f'echo "$POMO_EVENT $POMO_PHASE $POMO_REMAINING" > {out}')
    run_hook(HookRunner(tmp_path), Event.WORK_START)
    assert out.read_text() == "work-start work 1500\n"


def test_missing_and_non_executable_hooks_are_ignored(tmp_path):
    (tmp_path / "on-pause").write_text("#!/bin/sh\nexit 1\n")
    runner = HookRunner(tmp_path)
    assert runner.script_for(Event.PAUSE) is None
    assert runner.script_for(Event.STOP) is None


def test_update_never_runs_a_hook(tmp_path):
    write_hook(tmp_path, "on-update", "exit 0")
    assert HookRunner(tmp_path).script_for(Event.UPDATE) is None


def test_failing_hook_is_logged(tmp_path, caplog):
    write_hook(tmp_path, "on-stop", "exit 3")
    with caplog.at_level(logging.WARNING):
        run_hook(HookRunner(tmp_path), Event.STOP)
    assert "on-stop exited with 3" in caplog.text


def test_slow_hook_is_killed(tmp_path, caplog):
    write_hook(tmp_path, "on-resume", "sleep 10")
    with caplog.at_level(logging.WARNING):
        run_hook(HookRunner(tmp_path, timeout=0.2), Event.RESUME)
    assert "killed after 0.2s" in caplog.text


def test_env_contains_full_state_json():
    env = hook_env(Event.BREAK_START, STATE)
    assert env["POMO_CYCLE"] == "2"
    assert '"completed": 1' in env["POMO_STATE"]


def test_background_children_do_not_block_the_hook(tmp_path, caplog):
    write_hook(tmp_path, "on-pause", "sleep 10 &")
    with caplog.at_level(logging.WARNING):
        run_hook(HookRunner(tmp_path, timeout=2), Event.PAUSE)
    assert "killed" not in caplog.text
