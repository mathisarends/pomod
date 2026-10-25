# Notes for coding agents

To *use* pomod as an agent, see "Usage for agents" in the README. This file is
about working on the code.

## Layout

- `timer.py`: the state machine. Pure logic, every method takes `now`. No I/O here.
- `daemon.py`: asyncio Unix socket server, clock loop, event fan-out.
- `protocol.py`: wire format and error codes shared by daemon and client.
- `client.py` / `cli.py`: blocking socket client and the `pomo` CLI (no asyncio, fast startup).
- `hooks.py`, `store.py`, `config.py`, `waybar.py`, `display.py`: one job each.

## Rules

- The daemon is the only owner of state. Clients never compute phase changes.
- Keep the JSON output, error codes and exit codes stable; agents depend on them.
  Adding fields is fine, renaming or removing them is a breaking change.
- No blanket `from __future__ import annotations`. Use `typing.Self` and quotes only where needed.
- Small, readable functions over clever ones. Comments explain why, not what.
- Run `uv run ruff format`, `uv run ruff check` and `uv run pytest` before committing.
  Socket and hook tests only run on Linux; on other systems run them in a container:
  `docker run --rm -v "$PWD:/src:ro" -w /src python:3.13-slim sh -c "pip install -q click pytest && PYTHONPATH=src python -m pytest -p no:cacheprovider"`
