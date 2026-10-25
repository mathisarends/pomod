import pytest

from pomod.durations import format_clock, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("25", 1500),
        ("5m", 300),
        ("90s", 90),
        ("1h30m", 5400),
        ("1h 30m", 5400),
        ("+5m", 300),
        ("-2m", -120),
        ("0.5", 30),
        (25, 1500),
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "5x", "m", "5m3", "-"])
def test_parse_duration_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize(
    ("seconds", "clock"),
    [
        (1500, "25:00"),
        (245, "04:05"),
        (0.2, "00:01"),
        (0, "00:00"),
        (-3, "00:00"),
        (3723, "1:02:03"),
    ],
)
def test_format_clock(seconds, clock):
    assert format_clock(seconds) == clock
