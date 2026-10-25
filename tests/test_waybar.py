from pomod.waybar import render


def state(**overrides):
    return {
        "phase": "work",
        "status": "running",
        "remaining": 1122.4,
        "duration": 1500,
        "cycle": 2,
        "cycles": 4,
        "completed": 1,
    } | overrides


def test_running_work_phase():
    line = render(state())
    assert line == {
        "text": "🍅 18:43",
        "alt": "work",
        "class": ["work", "running"],
        "percentage": 25,
        "tooltip": "Work 18:43 left · cycle 2/4 · 1 done",
    }


def test_paused_break_gets_break_classes_and_pause_icon():
    line = render(state(phase="long_break", status="paused", remaining=600, duration=900))
    assert line["class"] == ["long-break", "paused", "break"]
    assert line["text"] == "⏸ 10:00"
    assert "(paused)" in line["tooltip"]


def test_idle_and_offline():
    assert render(state(phase="idle", status="idle"))["class"] == ["idle"]
    assert render(None)["class"] == ["offline"]
