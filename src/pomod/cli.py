"""pomo: command line client for pomod."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from . import __version__, client, paths, protocol
from .durations import format_clock, parse_duration
from .protocol import Message

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_DAEMON_UNAVAILABLE = 3
EXIT_NOT_RUNNING = 4

PHASE_LABELS = {
    "idle": "Idle",
    "work": "Work",
    "short_break": "Short break",
    "long_break": "Long break",
}

EPILOG = f"""\b
Every command accepts --json and then prints exactly one JSON object.
Exit codes:
  {EXIT_OK}  ok (also when nothing had to change, e.g. start while running)
  {EXIT_ERROR}  unexpected error
  {EXIT_USAGE}  invalid usage
  {EXIT_DAEMON_UNAVAILABLE}  pomod is not running
  {EXIT_NOT_RUNNING}  command needs an active timer (pause, resume, skip, add)
"""


class Duration(click.ParamType):
    name = "duration"

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> int:
        if isinstance(value, int):
            return value
        try:
            return parse_duration(value)
        except ValueError as error:
            self.fail(str(error), param, ctx)


DURATION = Duration()


@dataclass(frozen=True)
class Options:
    socket_path: Path


json_option = click.option("--json", "as_json", is_flag=True, help="Print the response as JSON.")


@click.group(epilog=EPILOG, context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--socket",
    "socket_path",
    type=click.Path(path_type=Path),
    default=paths.socket_path,
    show_default="$XDG_RUNTIME_DIR/pomo.sock",
    help="pomod socket to talk to.",
)
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context, socket_path: Path) -> None:
    """Control the pomod Pomodoro daemon.

    Durations accept 25 (minutes), 5m, 90s or 1h30m.
    """
    ctx.obj = Options(socket_path)


@cli.command()
@click.option("--work", type=DURATION, help="Work phase length.  [default: from config, 25m]")
@click.option("--break", "short_break", type=DURATION, help="Short break length.  [default: 5m]")
@click.option("--long-break", type=DURATION, help="Long break length.  [default: 15m]")
@click.option("--cycles", type=click.IntRange(min=1), help="Work phases until a long break.")
@json_option
@click.pass_obj
def start(
    options: Options,
    work: int | None,
    short_break: int | None,
    long_break: int | None,
    cycles: int | None,
    as_json: bool,
) -> None:
    """Start a work phase. Does nothing if a timer is already running."""
    overrides = {
        "work": work,
        "short_break": short_break,
        "long_break": long_break,
        "cycles": cycles,
    }
    args = {key: value for key, value in overrides.items() if value is not None}
    _send(options, "start", args, as_json)


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("duration", type=DURATION)
@json_option
@click.pass_obj
def add(options: Options, duration: int, as_json: bool) -> None:
    """Extend the current phase by DURATION. A negative value like -5m shortens it."""
    _send(options, "add", {"seconds": duration}, as_json)


def _register_simple(name: str, help_text: str) -> None:
    @cli.command(name, help=help_text)
    @json_option
    @click.pass_obj
    def command(options: Options, as_json: bool) -> None:
        _send(options, name, {}, as_json)


for _name, _help in (
    ("status", "Show the current phase and remaining time."),
    ("pause", "Pause the running phase."),
    ("resume", "Resume a paused phase."),
    ("toggle", "Start, pause or resume, whichever fits. Handy for a click binding."),
    ("skip", "End the current phase now and move on to the next one."),
    ("stop", "Stop the timer and reset the cycle."),
):
    _register_simple(_name, _help)


def _send(options: Options, command: str, args: dict[str, Any], as_json: bool) -> None:
    try:
        response = client.request(options.socket_path, command, args)
    except client.DaemonUnavailableError as error:
        response = {
            "ok": False,
            "error": {"code": client.DAEMON_UNAVAILABLE, "message": str(error)},
        }

    if as_json:
        click.echo(json.dumps(response))
    elif response["ok"]:
        if response["message"]:
            click.echo(response["message"])
        click.echo(describe(response["state"]))
    else:
        click.echo(f"pomo: {response['error']['message']}", err=True)
    click.get_current_context().exit(exit_code(response))


def exit_code(response: Message) -> int:
    if response["ok"]:
        return EXIT_OK
    match response["error"]["code"]:
        case client.DAEMON_UNAVAILABLE:
            return EXIT_DAEMON_UNAVAILABLE
        case protocol.NOT_RUNNING:
            return EXIT_NOT_RUNNING
        case _:
            return EXIT_ERROR


def describe(state: Message) -> str:
    """One line for humans, e.g. `Work 18:42 left · cycle 2/4 · 1 done`."""
    if state["status"] == "idle":
        return "Idle."
    label = PHASE_LABELS[state["phase"]]
    if state["status"] == "paused":
        label += " (paused)"
    return (
        f"{label} {format_clock(state['remaining'])} left"
        f" · cycle {state['cycle']}/{state['cycles']} · {state['completed']} done"
    )


def main() -> None:
    cli()
