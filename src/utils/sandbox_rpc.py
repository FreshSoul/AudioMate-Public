"""JSON-lines RPC protocol shared by the sandbox host (main process) and the
sandbox worker (isolated subprocess).

Transport: one compact JSON object per line over the worker's stdin/stdout.
The worker's own ``print()`` output is captured *inside* the worker and shipped
back in the terminal ``done`` message, so it never collides with this control
channel.

Message shapes
--------------
Host -> Worker (written to worker stdin):
  {"t": "execute", "code": <str>, "mode": <str>}
  {"t": "rpc_result", "id": <int>, "ok": <bool>, "value": <json>, "error": <str>}
  {"t": "cancel"}

Worker -> Host (written to worker stdout):
  {"t": "ready"}
  {"t": "rpc_call", "id": <int>, "target": <str>, "args": <list>, "kwargs": <dict>}
  {"t": "confirm", "id": <int>, "kind": "import"|"powershell", "payload": <json>}
  {"t": "done", "stdout": <str>, "result": <str>, "error": <str|null>}

``target`` is either a bare callable name (``"analyze_audio_file"``) or a
dotted object-method (``"waapi_client.call"``) resolved on the host side.
"""

from __future__ import annotations

import json

# Message type tags
EXECUTE = "execute"
RPC_RESULT = "rpc_result"
CANCEL = "cancel"
READY = "ready"
RPC_CALL = "rpc_call"
CONFIRM = "confirm"
DONE = "done"


def encode(message: dict) -> bytes:
    """Serialize one message to a single newline-terminated UTF-8 line.

    ``default=str`` guarantees we never crash on a value that is not natively
    JSON-serializable (e.g. a stray object in tool args/results) — it degrades
    to its string form rather than killing the channel.
    """
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
    return (line + "\n").encode("utf-8")


def decode(line: str) -> dict:
    """Parse one received line into a message dict. Raises ValueError on junk."""
    line = (line or "").strip()
    if not line:
        raise ValueError("empty line")
    obj = json.loads(line)
    if not isinstance(obj, dict) or "t" not in obj:
        raise ValueError(f"malformed message: {line[:80]}")
    return obj


# --- message constructors (host side) ---

def msg_execute(code: str, mode: str) -> dict:
    return {"t": EXECUTE, "code": code, "mode": mode}


def msg_rpc_result(call_id: int, ok: bool, value=None, error: str = "") -> dict:
    return {"t": RPC_RESULT, "id": call_id, "ok": ok, "value": value, "error": error}


def msg_cancel() -> dict:
    return {"t": CANCEL}


# --- message constructors (worker side) ---

def msg_ready() -> dict:
    return {"t": READY}


def msg_rpc_call(call_id: int, target: str, args: list, kwargs: dict) -> dict:
    return {"t": RPC_CALL, "id": call_id, "target": target, "args": list(args), "kwargs": dict(kwargs)}


def msg_confirm(call_id: int, kind: str, payload) -> dict:
    return {"t": CONFIRM, "id": call_id, "kind": kind, "payload": payload}


def msg_done(stdout: str, result: str, error: str | None = None) -> dict:
    return {"t": DONE, "stdout": stdout, "result": result, "error": error}
