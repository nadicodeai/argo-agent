# Recorded Model — Stub LLM Backend

A deterministic, in-process HTTP server that speaks the OpenAI chat-completions
protocol. Used by `tests/test_deployment_smoke.py` so the smoke run exercises
argo end-to-end without a real API key or network access.

## How it works

`server.py` exposes a `RecordedModelServer` context manager that binds to
`127.0.0.1:<free-port>` and serves:

| Endpoint | Method | Behaviour |
|---|---|---|
| `/v1/chat/completions` | POST | Returns a canned response for the last user message; falls back to a generic reply for unknown prompts. |
| `/v1/models` | GET | Returns `stub-model` in an OpenAI-format list. |

The stub is wired into a smoke test like so:

```python
from tests.fixtures.recorded_model.server import RecordedModelServer

with RecordedModelServer() as server:
    env = os.environ.copy()
    env["CUSTOM_BASE_URL"] = server.base_url   # routes argo → stub
    env["OPENAI_API_KEY"] = "stub"             # satisfies key presence check
    env["ARGO_MODEL"] = "stub-model"
    result = subprocess.run(
        [sys.executable, "-m", "argo_cli.main", "-z", "hello"],
        env=env, capture_output=True, text=True, timeout=60,
    )
```

## Adding more canned responses

Open `server.py` and extend the `_CANNED` dictionary at the top of the file.
Keys are **lowercase substrings** matched against the last user message.
Values are the assistant content the stub returns.

```python
_CANNED: dict[str, str] = {
    # existing entries …
    "your keyword": "The stub response you want.",
}
```

The lookup is ordered — the first matching key wins — so put more specific
phrases before general ones.

## Constraints

- **No upstream-identifier strings** (the old project name or any variant) in
  canned responses — the smoke test asserts zero hits for the AC-2 gate.
- Responses can be multi-line but should not reference real external services.
- The server uses stdlib only (`http.server`, `socketserver`, `threading`).
  No new runtime dependencies are allowed.

## Local pre-release vs. CI

| Context | What runs |
|---|---|
| CI (no API key) | `RecordedModelServer` stub — deterministic, offline. |
| Developer with `ARGO_TEST_MODEL` set | Real model via that key — full live path. |
| `argo doctor --live` | `--help` / `--version` fallback — no model involved. |
