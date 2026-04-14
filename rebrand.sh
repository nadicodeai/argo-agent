#!/usr/bin/env bash
# Rebrand user-facing Hermes → Argo for the Argo fork.
#
# Full workflow docs: docs/argo-fork.md
#
# Usage:
#   bash rebrand.sh
#
# Idempotent — running it on already-rebranded code is a no-op.
# Tolerant of missing files — any sed rule whose target file doesn't exist in
# the current tree is silently skipped. This lets the same script work against
# different upstream release tags without editing it every time a new file is
# added or removed upstream.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# Apply sed -i expressions to files that exist; skip missing files silently.
# Usage: sed_files -e 'expr1' [-e 'expr2' ...] -- file1 [file2 ...]
sed_files() {
    local args=()
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do
        args+=("$1")
        shift
    done
    if [ "${1:-}" != "--" ]; then
        echo "sed_files: missing '--' separator before file list" >&2
        return 1
    fi
    shift
    local existing=()
    for f in "$@"; do
        [ -f "$f" ] && existing+=("$f")
    done
    if [ ${#existing[@]} -gt 0 ]; then
        sed -i "${args[@]}" "${existing[@]}"
    fi
}

# ---- CI workflow triggers: main → argo ----
# Upstream runs Tests and Nix only on main. argo fork needs them on argo pushes.
# docker-publish.yml is hand-maintained (different structure, GHCR, etc.) so it's
# not swept here.
sed_files \
    -e 's/branches: \[main\]/branches: [argo]/g' \
    -- .github/workflows/tests.yml \
       .github/workflows/nix.yml

# ---- AGENTS.md fork notice (idempotent) ----
# Prepends a notice at the top of AGENTS.md so any agent reading it
# immediately knows this is the argo fork, not upstream hermes-agent.
if [ -f AGENTS.md ] && ! grep -q "ARGO FORK" AGENTS.md 2>/dev/null; then
    tmp=$(mktemp)
    head -1 AGENTS.md > "$tmp"
    cat >> "$tmp" <<'NOTICE'

> **ARGO FORK**: You are on the **argo fork** of hermes-agent. The `argo` branch
> rebrands user-facing strings (Hermes → Argo) for messaging bot deployments
> and tracks upstream **release tags**, not upstream main.
>
> - **Workflow & branch model**: see `docs/argo-fork.md`
> - **Rebrand rules**: see `rebrand.sh` at the repo root
> - **Do NOT rename** env vars (`HERMES_HOME`, `HERMES_TIMEZONE`), module paths
>   (`hermes_cli/`, `hermes_constants.py`), config paths (`~/.hermes/`), or
>   anything admin-facing. Only text that **reaches end users on messaging
>   platforms** gets renamed. See `docs/argo-fork.md` for the full list.

NOTICE
    tail -n +2 AGENTS.md >> "$tmp"
    mv "$tmp" AGENTS.md
fi

# System prompt identity
sed_files -e 's/"You are Hermes Agent, /"You are Argo Agent, /' -- \
    hermes_cli/default_soul.py \
    agent/prompt_builder.py

# Anthropic adapter — preserve Claude Code masquerade after rename
sed_files \
    -e 's|text.replace("Hermes Agent", "Claude Code")|text.replace("Argo Agent", "Claude Code")|' \
    -e 's|text.replace("Hermes agent", "Claude Code")|text.replace("Argo agent", "Claude Code")|' \
    -e 's|text.replace("hermes-agent", "claude-code")|text.replace("argo-agent", "claude-code")|' \
    -- agent/anthropic_adapter.py

# Discord slash commands & thread labels
sed_files \
    -e 's/"Reset your Hermes session"/"Reset your Argo session"/' \
    -e 's/"Show Hermes session status"/"Show Argo session status"/' \
    -e 's/"Stop the running Hermes agent"/"Stop the running Argo agent"/' \
    -e 's/"Update Hermes Agent to the latest version"/"Update Argo Agent to the latest version"/' \
    -e 's/"Create a new thread and start a Hermes session in it"/"Create a new thread and start an Argo session in it"/' \
    -e 's/"Optional first message to send to Hermes in the thread"/"Optional first message to send to Argo in the thread"/' \
    -e 's/Thread created by Hermes:/Thread created by Argo:/' \
    -e 's/ else "Hermes"$/ else "Argo"/' \
    -- gateway/platforms/discord.py

# Slack slash command (also update Slack app dashboard)
sed_files -e 's|app.command("/hermes")|app.command("/argo")|' -- \
    gateway/platforms/slack.py

# Email: subjects and Message-ID prefixes
sed_files \
    -e 's/ctx.get("subject", "Hermes Agent")/ctx.get("subject", "Argo Agent")/g' \
    -e 's|f"<hermes-|f"<argo-|g' \
    -- gateway/platforms/email.py
sed_files -e 's/msg\["Subject"\] = "Hermes Agent"/msg["Subject"] = "Argo Agent"/' -- \
    tools/send_message_tool.py

# Notification titles & device names
sed_files -e 's/"title": "Hermes Agent"/"title": "Argo Agent"/' -- \
    gateway/platforms/homeassistant.py
sed_files -e 's/"markdown": {"title": "Hermes"/"markdown": {"title": "Argo"/' -- \
    gateway/platforms/dingtalk.py
sed_files -e 's/device_name="Hermes Agent"/device_name="Argo Agent"/' -- \
    gateway/platforms/matrix.py

# API server (/health, /v1/models, default fallback)
sed_files \
    -e 's/"platform": "hermes-agent"/"platform": "argo-agent"/' \
    -e 's/"id": "hermes-agent"/"id": "argo-agent"/' \
    -e 's/"owned_by": "hermes"/"owned_by": "argo"/' \
    -e 's/"root": "hermes-agent"/"root": "argo-agent"/' \
    -e 's/body.get("model", "hermes-agent")/body.get("model", "argo-agent")/g' \
    -- gateway/platforms/api_server.py

# Insights (gateway format only; terminal format stays admin-only)
sed_files -e 's/\*\*Hermes Insights\*\*/**Argo Insights**/' -- agent/insights.py

# OAuth browser redirect + default MCP client name
sed_files \
    -e 's|return to Hermes\.</p>|return to Argo.</p>|' \
    -e 's|cfg.get("client_name", "Hermes Agent")|cfg.get("client_name", "Argo Agent")|' \
    -- tools/mcp_oauth.py

# Hindsight memory plugin retain_context
sed_files -e 's/conversation between Hermes Agent and the User/conversation between Argo Agent and the User/g' -- \
    plugins/memory/hindsight/__init__.py

# Telegram BotCommands menu (visible to every user via setMyCommands autocomplete)
sed_files \
    -e 's/"Update Hermes Agent to the latest version"/"Update Argo Agent to the latest version"/' \
    -e 's/"Create or restore state snapshots of Hermes config\/state"/"Create or restore state snapshots of Argo config\/state"/' \
    -- hermes_cli/commands.py

# Gateway command-handler replies sent to users via adapter.send()
# All commands are reachable by any allowlisted user — no per-command gating.
sed_files \
    -e 's/A home channel is where Hermes delivers/A home channel is where Argo delivers/' \
    -e 's|`pip install faster-whisper` in the Hermes venv|`pip install faster-whisper` in the Argo venv|' \
    -e 's/📊 \*\*Hermes Gateway Status\*\*/📊 **Argo Gateway Status**/' \
    -e 's/📖 \*\*Hermes Commands\*\*/📖 **Argo Commands**/' \
    -e 's/Install or reinstall Hermes with the messaging extra/Install or reinstall Argo with the messaging extra/' \
    -e "s/format_managed_message('update Hermes Agent')/format_managed_message('update Argo Agent')/" \
    -e 's/"Hermes is running, but the update command could not find/"Argo is running, but the update command could not find/' \
    -e 's/"⚕ Starting Hermes update/"⚕ Starting Argo update/' \
    -e 's/"✅ Hermes update finished/"✅ Argo update finished/' \
    -e 's/"❌ Hermes update failed/"❌ Argo update failed/' \
    -e 's/"❌ Hermes update timed out/"❌ Argo update timed out/' \
    -e 's/users configure Hermes features/users configure Argo features/g' \
    -e 's/Share these links with the Hermes team for support/Share these links with the Argo team for support/' \
    -- gateway/run.py

# format_managed_message output (embedded in /update reply → adapter.send → user chat)
sed_files \
    -e 's/"modify this Hermes installation"/"modify this Argo installation"/' \
    -e 's/this Hermes installation is managed by/this Argo installation is managed by/g' \
    -e 's/Use your package manager to upgrade or reinstall Hermes\./Use your package manager to upgrade or reinstall Argo./' \
    -- hermes_cli/config.py

# ---- Tests (lockstep) ----

sed_files -e 's/"Hermes Agent"/"Argo Agent"/g' -- \
    tests/agent/test_prompt_builder.py \
    tests/run_agent/test_run_agent.py \
    tests/integration/test_ha_integration.py \
    tests/gateway/test_homeassistant.py

sed_files -e 's/"Re: Hermes Agent"/"Re: Argo Agent"/g' -- tests/gateway/test_email.py
sed_files -e 's/payload\["markdown"\]\["title"\] == "Hermes"/payload["markdown"]["title"] == "Argo"/' -- tests/gateway/test_dingtalk.py
sed_files -e 's|"/hermes" in|"/argo" in|' -- tests/gateway/test_slack.py
sed_files \
    -e 's/assert data\["platform"\] == "hermes-agent"/assert data["platform"] == "argo-agent"/' \
    -e 's/assert data\["data"\]\[0\]\["id"\] == "hermes-agent"/assert data["data"][0]["id"] == "argo-agent"/' \
    -- tests/gateway/test_api_server.py
sed_files -e 's/conversation between Hermes Agent and the User/conversation between Argo Agent and the User/g' -- \
    tests/plugins/memory/test_hindsight_provider.py

echo "done"
