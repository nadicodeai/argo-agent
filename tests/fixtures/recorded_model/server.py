"""Recorded-model stub HTTP server for deterministic smoke tests.

Implements a minimal OpenAI-compatible /v1/chat/completions endpoint that
returns pre-canned JSON responses. No network calls, no API keys required.

Usage (in a test):
    from tests.fixtures.recorded_model.server import RecordedModelServer

    with RecordedModelServer() as server:
        env["CUSTOM_BASE_URL"] = server.base_url
        env["ARGO_MODEL"] = "stub-model"
        # ... run argo subprocess with those env vars ...

The server binds to 127.0.0.1 on an OS-assigned free port, serves a single
worker thread, and shuts down cleanly when the context manager exits.

Design notes
------------
- Stdlib only: http.server + socketserver. Zero new runtime dependencies.
- All text is UTF-8. No raise Exception(...).
- Canned responses never contain the upstream identifier so AC-2 cannot fire
  on model output captured during the smoke run.
- For prompts not in the lookup table, returns a generic fallback response.
"""

from __future__ import annotations

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any


# ---------------------------------------------------------------------------
# Canned response library
# ---------------------------------------------------------------------------
# Keys are lowercase substrings to match against the last user message.
# Values are the "content" strings the stub assistant returns.
# IMPORTANT: None of these strings may contain the upstream identifier.
_CANNED: dict[str, str] = {
    "list files": "I can see the files in the current directory.",
    "pwd": "The current working directory is available.",
    "hello": "Hello! How can I assist you today?",
    "version": "Argo Agent is running correctly.",
    "test": "Test completed successfully.",
    "tool": "I will use the available tools to help you.",
}

_FALLBACK_CONTENT = (
    "I have processed your request and I am ready to assist you further."
)


def _pick_response(messages: list[dict[str, Any]]) -> str:
    """Return canned content for the last user message, or a fallback."""
    last_user = ""
    for msg in reversed(messages):
        if isinstance(msg, dict) and (msg.get("role") or "") == "user":
            last_user = str(msg.get("content") or "").lower()
            break
    for keyword, response in _CANNED.items():
        if keyword in last_user:
            return response
    return _FALLBACK_CONTENT


def _build_completion_response(content: str, model: str) -> dict[str, Any]:
    """Build a minimal OpenAI-compatible chat completion response."""
    return {
        "id": "stubcmpl-00000000000000000000000000000001",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
    }


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


class _StubHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible request handler."""

    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        # Silence access logs so test output is clean.
        pass

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler convention
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}

        path = self.path.split("?")[0].rstrip("/")

        if path == "/v1/chat/completions":
            messages = payload.get("messages", [])
            model = str(payload.get("model", "stub-model"))
            content = _pick_response(messages)
            self._send_json(_build_completion_response(content, model))
        else:
            self._send_json({"error": {"message": "not found", "type": "invalid_request"}}, 404)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        if path == "/v1/models":
            self._send_json(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "stub-model",
                            "object": "model",
                            "created": 1700000000,
                            "owned_by": "stub",
                        }
                    ],
                }
            )
        else:
            self._send_json({"error": {"message": "not found", "type": "invalid_request"}}, 404)


# ---------------------------------------------------------------------------
# Context-manager server
# ---------------------------------------------------------------------------


class RecordedModelServer:
    """Context manager that runs the stub OpenAI server on a free local port.

    Example
    -------
    ::

        with RecordedModelServer() as server:
            env = os.environ.copy()
            env["CUSTOM_BASE_URL"] = server.base_url
            env["OPENAI_API_KEY"] = "stub"
            env["ARGO_MODEL"] = "stub-model"
            subprocess.run([sys.executable, "-m", "argo_cli.main", "-z", "hello"],
                           env=env, capture_output=True)
    """

    def __init__(self) -> None:
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url: str = ""

    def __enter__(self) -> "RecordedModelServer":
        # socketserver.TCPServer with port=0 lets the OS assign a free port.
        self._server = socketserver.TCPServer(("127.0.0.1", 0), _StubHandler)
        self._server.allow_reuse_address = True
        _port = self._server.server_address[1]
        self.base_url = f"http://127.0.0.1:{_port}/v1"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="RecordedModelServer",
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.base_url = ""
