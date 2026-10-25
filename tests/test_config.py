import pytest

from pomod.config import Settings, load_settings


def test_missing_file_gives_defaults(tmp_path):
    assert load_settings(tmp_path / "nope.toml") == Settings()


def test_reads_toml(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('work = "50m"\nshort_break = 10\ncycles = 3\n')
    assert load_settings(path) == Settings(work=3000, short_break=600, cycles=3)


def test_rejects_nonsense():
    with pytest.raises(ValueError):
        Settings(work=0)
    with pytest.raises(ValueError):
        Settings(cycles=0)


def test_overrides_ignore_none():
    assert Settings().with_overrides(work=60, short_break=None).work == 60
