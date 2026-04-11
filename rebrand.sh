#!/usr/bin/env bash
# Rebrand user-facing Hermes → Argo for the Argo fork.
#
# Full workflow docs: docs/argo-fork.md
#
# Usage:
#   bash rebrand.sh
#
# To rebuild the argo branch from scratch:
#   git checkout -B argo main
#   bash rebrand.sh
#   git add -A && git commit -m "argo: rebrand user-facing strings"
#
# Idempotent — running it on already-rebranded code is a no-op.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# ---- AGENTS.md fork notice (idempotent) ----
# Prepends a notice at the top of AGENTS.md so any agent reading it
# immediately knows this is the argo fork, not upstream hermes-agent.
if ! grep -q "ARGO FORK" AGENTS.md 2>/dev/null; then
    tmp=$(mktemp)
    head -1 AGENTS.md > "$tmp"
    cat >> "$tmp" <<'NOTICE'

> **ARGO FORK**: You are on the **argo fork** of hermes-agent. The `argo` branch
> rebrands user-facing strings (Hermes → Argo) for messaging bot deployments.
>
> - **Workflow & branch model**: see `docs/argo-fork.md`
> - **Rebrand rules**: see `rebrand.sh` at the repo root
> - **Branch model**: `main` = pristine `upstream/main` (no local commits).
>   `argo` = `main` + one commit containing `rebrand.sh` and the rebranded
>   source/test files. Always deploy from `argo`, never `main`.
> - **Do NOT rename** env vars (`HERMES_HOME`, `HERMES_TIMEZONE`), module paths
>   (`hermes_cli/`, `hermes_constants.py`), config paths (`~/.hermes/`), or
>   anything admin-facing. Only text that **reaches end users on messaging
>   platforms** gets renamed. See `docs/argo-fork.md` for the full list.

NOTICE
    tail -n +2 AGENTS.md >> "$tmp"
    mv "$tmp" AGENTS.md
fi

# System prompt identity
sed -i 's/"You are Hermes Agent, /"You are Argo Agent, /' \
    hermes_cli/default_soul.py \
    agent/prompt_builder.py

# Anthropic adapter — preserve Claude Code masquerade after rename
sed -i \
    -e 's|text.replace("Hermes Agent", "Claude Code")|text.replace("Argo Agent", "Claude Code")|' \
    -e 's|text.replace("Hermes agent", "Claude Code")|text.replace("Argo agent", "Claude Code")|' \
    -e 's|text.replace("hermes-agent", "claude-code")|text.replace("argo-agent", "claude-code")|' \
    agent/anthropic_adapter.py

# Discord slash commands & thread labels
sed -i \
    -e 's/"Reset your Hermes session"/"Reset your Argo session"/' \
    -e 's/"Show Hermes session status"/"Show Argo session status"/' \
    -e 's/"Stop the running Hermes agent"/"Stop the running Argo agent"/' \
    -e 's/"Update Hermes Agent to the latest version"/"Update Argo Agent to the latest version"/' \
    -e 's/"Create a new thread and start a Hermes session in it"/"Create a new thread and start an Argo session in it"/' \
    -e 's/"Optional first message to send to Hermes in the thread"/"Optional first message to send to Argo in the thread"/' \
    -e 's/Thread created by Hermes:/Thread created by Argo:/' \
    -e 's/ else "Hermes"$/ else "Argo"/' \
    gateway/platforms/discord.py

# Slack slash command (also update Slack app dashboard)
sed -i 's|app.command("/hermes")|app.command("/argo")|' \
    gateway/platforms/slack.py

# Email: subjects and Message-ID prefixes
sed -i \
    -e 's/ctx.get("subject", "Hermes Agent")/ctx.get("subject", "Argo Agent")/g' \
    -e 's|f"<hermes-|f"<argo-|g' \
    gateway/platforms/email.py
sed -i 's/msg\["Subject"\] = "Hermes Agent"/msg["Subject"] = "Argo Agent"/' \
    tools/send_message_tool.py

# Notification titles & device names
sed -i 's/"title": "Hermes Agent"/"title": "Argo Agent"/' \
    gateway/platforms/homeassistant.py
sed -i 's/"markdown": {"title": "Hermes"/"markdown": {"title": "Argo"/' \
    gateway/platforms/dingtalk.py
sed -i 's/device_name="Hermes Agent"/device_name="Argo Agent"/' \
    gateway/platforms/matrix.py

# API server (/health, /v1/models, default fallback)
sed -i \
    -e 's/"platform": "hermes-agent"/"platform": "argo-agent"/' \
    -e 's/"id": "hermes-agent"/"id": "argo-agent"/' \
    -e 's/"owned_by": "hermes"/"owned_by": "argo"/' \
    -e 's/"root": "hermes-agent"/"root": "argo-agent"/' \
    -e 's/body.get("model", "hermes-agent")/body.get("model", "argo-agent")/g' \
    gateway/platforms/api_server.py

# Insights (gateway format only; terminal format stays admin-only)
sed -i 's/\*\*Hermes Insights\*\*/**Argo Insights**/' agent/insights.py

# OAuth browser redirect + default MCP client name
sed -i \
    -e 's|return to Hermes\.</p>|return to Argo.</p>|' \
    -e 's|cfg.get("client_name", "Hermes Agent")|cfg.get("client_name", "Argo Agent")|' \
    tools/mcp_oauth.py

# Hindsight memory plugin retain_context
sed -i 's/conversation between Hermes Agent and the User/conversation between Argo Agent and the User/g' \
    plugins/memory/hindsight/__init__.py

# ---- Tests (lockstep) ----

sed -i 's/"Hermes Agent"/"Argo Agent"/g' \
    tests/agent/test_prompt_builder.py \
    tests/run_agent/test_run_agent.py \
    tests/integration/test_ha_integration.py \
    tests/gateway/test_homeassistant.py

sed -i 's/"Re: Hermes Agent"/"Re: Argo Agent"/g' tests/gateway/test_email.py
sed -i 's/payload\["markdown"\]\["title"\] == "Hermes"/payload["markdown"]["title"] == "Argo"/' tests/gateway/test_dingtalk.py
sed -i 's|"/hermes" in|"/argo" in|' tests/gateway/test_slack.py
sed -i \
    -e 's/assert data\["platform"\] == "hermes-agent"/assert data["platform"] == "argo-agent"/' \
    -e 's/assert data\["data"\]\[0\]\["id"\] == "hermes-agent"/assert data["data"][0]["id"] == "argo-agent"/' \
    tests/gateway/test_api_server.py
sed -i 's/conversation between Hermes Agent and the User/conversation between Argo Agent and the User/g' \
    tests/plugins/memory/test_hindsight_provider.py

echo "done"
