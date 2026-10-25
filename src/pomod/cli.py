"""pomo: command line client for pomod."""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from . import __version__, client, paths, protocol, waybar
from .display import describe
from .durations import parse_duration
from .protocol import Message

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_DAEMON_UNAVAILABLE = 3
EXIT_NOT_RUNNING = 4

RECONNECT_DELAY = 2.0

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


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Print raw daemon events instead.")
@click.pass_obj
def watch(options: Options, as_json: bool) -> None:
    """Stream the state as Waybar JSON, one line per change.

    Keeps running when pomod is down and reconnects once it is back.
    """
    try:
        for line in watch_lines(options.socket_path, as_json):
            click.echo(line)
    except (BrokenPipeError, KeyboardInterrupt):
        pass  # Waybar reloaded or the user hit Ctrl-C


def watch_lines(
    socket_path: Path, as_json: bool, reconnect_delay: float = RECONNECT_DELAY
) -> Iterator[str]:
    def render(message: Message) -> str:
        if as_json:
            return json.dumps(message)
        return json.dumps(waybar.render(message["state"]), ensure_ascii=False)

    previous = None
    while True:
        try:
            for message in client.subscribe(socket_path):
                line = render(message)
                if line != previous:
                    yield line
                    previous = line
        except (client.DaemonUnavailableError, ConnectionError):
            pass
        line = render({"event": "offline", "state": None})
        if line != previous:
            yield line
            previous = line
        time.sleep(reconnect_delay)


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


def main() -> None:
    cli()
