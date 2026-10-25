# pomod

pomod is a tiny Pomodoro daemon with a socket API. Waybar, your terminal and your AI agents are just clients.

```
pomod (systemd --user service)          pomo (CLI client)
  ├─ owns the timer state                 start, pause, resume, toggle,
  ├─ $XDG_RUNTIME_DIR/pomo.sock  <──────  skip, stop, add, status, watch
  ├─ streams events to subscribers               ▲
  └─ runs hooks on phase changes                 │
                                     Waybar · scripts · AI agents
```

Think mpd and mpc: one daemon keeps the time, everything else talks to it.
The daemon stores an absolute deadline, not a countdown, so the timer survives
suspend and restarts.

Linux only (Unix sockets, systemd). Python 3.11+.

## Install

```sh
uv tool install git+https://github.com/mathisarends/pomod   # or: pipx install git+...
cp contrib/systemd/pomod.service ~/.config/systemd/user/
systemctl --user enable --now pomod
```

Then:

```sh
pomo start                    # 25 min work
pomo start --work 50 --break 10
pomo status                   # Work 18:42 left · cycle 2/4 · 1 done
pomo add 5m                   # five more minutes
pomo toggle                   # start / pause / resume
pomo skip                     # next phase now
pomo stop
```

Durations accept `25` (minutes), `5m`, `90s` or `1h30m`.

## Configuration

`~/.config/pomo/config.toml`, all keys optional (see [contrib/config.toml](contrib/config.toml)):

```toml
work = "25m"
short_break = "5m"
long_break = "15m"
cycles = 4  # work phases until a long break
```

pomod reads it on startup. Flags passed to `pomo start` override it for one session.

## Waybar

`pomo watch` prints one JSON line per change and reconnects by itself if pomod restarts.

```jsonc
"custom/pomo": {
  "exec": "pomo watch",
  "return-type": "json",
  "on-click": "pomo toggle",
  "on-click-right": "pomo skip",
  "on-click-middle": "pomo stop"
}
```

Output looks like `{"text": "🍅 18:42", "class": ["work", "running"], "tooltip": "Work 18:42 left · cycle 2/4 · 1 done", ...}`.
CSS classes: `offline`, `idle`, `work`, `short-break`, `long-break`, `break`, `running`, `paused`.
See [contrib/waybar/](contrib/waybar/).

## Hooks

Executables in `~/.config/pomo/hooks/` run when the timer changes:

| Hook             | When                                  |
| ---------------- | ------------------------------------- |
| `on-work-start`  | a work phase begins                   |
| `on-break-start` | a short or long break begins          |
| `on-pause`       | the timer is paused                   |
| `on-resume`      | the timer is resumed                  |
| `on-stop`        | the timer is stopped                  |

They get the state as environment variables: `POMO_EVENT`, `POMO_PHASE`
(`work`, `short_break`, `long_break`), `POMO_STATUS`, `POMO_REMAINING`,
`POMO_DURATION` (seconds), `POMO_CYCLE`, `POMO_CYCLES`, `POMO_COMPLETED` and
the full state as JSON in `POMO_STATE`.

Hooks run in the background and never delay the timer. Their output lands in
the journal (`journalctl --user -u pomod`). A hook that runs longer than 30 s is
killed; anything it started in the background keeps running.

Use them for notifications, do-not-disturb, pausing music or switching lights.
Examples: [contrib/hooks/](contrib/hooks/).

## Usage for agents

The CLI is the agent interface: anything that can run a shell command can use pomod.

- Every command takes `--json` and then prints exactly one JSON object to stdout.
- Commands are idempotent: `start` while running or `pause` while paused exits 0 with `"changed": false`.
- `pomo --help` and `pomo <command> --help` describe everything.

```sh
$ pomo status --json
{"ok": true, "changed": false, "message": "", "state": {"phase": "work", "status": "running",
 "remaining": 1122.4, "duration": 1500, "deadline": 1761428580.2, "cycle": 2, "cycles": 4,
 "completed": 1, "settings": {"work": 1500, "short_break": 300, "long_break": 900, "cycles": 4}}}

$ pomo pause --json   # while idle
{"ok": false, "error": {"code": "not_running", "message": "Nothing to pause, the timer is idle."}, "state": {...}}
```

| Exit code | Meaning                                                   |
| --------- | --------------------------------------------------------- |
| 0         | ok, including "nothing to change"                         |
| 1         | unexpected error                                          |
| 2         | invalid usage (bad flag, bad duration)                    |
| 3         | pomod is not running (`error.code: daemon_unavailable`)   |
| 4         | needs an active timer (`error.code: not_running`)         |

An agent can also react to the timer: if `state.phase` is `work`, hold back
non-urgent questions and ask them once a break starts. `pomo watch --json`
streams every event if you want to wait for one.

## Protocol

Clients can skip the CLI and talk to the socket directly: one JSON object per
line, one request per connection.

```
-> {"cmd": "start", "args": {"work": 1500}}
<- {"ok": true, "changed": true, "message": "Work session started.", "state": {...}}
```

Commands: `status`, `start` (args `work`, `short_break`, `long_break`, `cycles`,
all integers in seconds), `pause`, `resume`, `toggle`, `skip`, `stop`,
`add` (arg `seconds`), and `subscribe`, which keeps the connection open and
streams `{"event": "...", "state": {...}}` lines: `state` first, then `tick`
every second while running, plus `work-start`, `break-start`, `pause`,
`resume`, `stop` and `update`.

Try it with `echo '{"cmd": "status"}' | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/pomo.sock`.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

The socket and hook tests need Linux and are skipped elsewhere; CI runs them on Ubuntu.
