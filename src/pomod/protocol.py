"""Wire format between pomod and its clients: one JSON object per line.

Each connection carries exactly one request:

    -> {"cmd": "start", "args": {"work": 1500}}
    <- {"ok": true, "changed": true, "message": "...", "state": {...}}
    <- {"ok": false, "error": {"code": "not_running", "message": "..."}, "state": {...}}

After {"cmd": "subscribe"} the connection stays open and the daemon streams
{"event": "...", "state": {...}} lines until the client disconnects.
"""

import json
from typing import Any

SUBSCRIBE = "subscribe"
COMMANDS = ("status", "start", "pause", "resume", "toggle", "skip", "stop", "add", SUBSCRIBE)

# Error codes. Stable, so agents can branch on them.
BAD_REQUEST = "bad_request"
UNKNOWN_COMMAND = "unknown_command"
NOT_RUNNING = "not_running"

Message = dict[str, Any]


class RequestError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def encode(message: Message) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode()


def decode(line: bytes) -> Message:
    try:
        message = json.loads(line)
    except ValueError as error:
        raise RequestError(BAD_REQUEST, f"invalid JSON: {error}") from None
    if not isinstance(message, dict):
        raise RequestError(BAD_REQUEST, "expected a JSON object")
    return message
