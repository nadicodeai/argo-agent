# Langfuse Observability Plugin

This plugin ships bundled with Argo but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

```bash
pip install langfuse
argo plugins enable observability/langfuse
```

Or check the box in the interactive `argo plugins` UI.

## Required credentials

Set these in `~/.argo/.env`:

```bash
ARGO_LANGFUSE_PUBLIC_KEY=pk-lf-...
ARGO_LANGFUSE_SECRET_KEY=sk-lf-...
ARGO_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
argo plugins list                 # observability/langfuse should show "enabled"
argo chat -q "hello"              # then check Langfuse for a "Argo turn" trace
```

## Optional tuning

```bash
ARGO_LANGFUSE_ENV=production       # environment tag
ARGO_LANGFUSE_RELEASE=v1.0.0       # release tag
ARGO_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ARGO_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ARGO_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
argo plugins disable observability/langfuse
```
