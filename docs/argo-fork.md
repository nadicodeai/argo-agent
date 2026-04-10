# Argo Fork

This is the `argo` branch of a fork of NousResearch/hermes-agent. It exists
to deploy messaging bots (Telegram, WhatsApp, Discord, Slack, etc.) under the
"Argo" brand instead of "Hermes".

Only text that **reaches end users on messaging platforms** is rebranded.
The CLI, setup wizard, env vars, module names, config paths, docs, etc. are
all unchanged because only operators see them. This keeps merges from
upstream lightweight.

## Branch model

- **`main`** — pristine mirror of `upstream/main`. No local commits.
- **`argo`** — deployment branch. A single commit on top of `main`
  containing `rebrand.sh` and the rebranded source/test files.

**Always deploy from `argo`, never from `main`.** `main` is raw upstream
code and still says "Hermes" everywhere.

## Pulling upstream updates

```bash
git checkout main
git pull upstream main          # fast-forward main to latest upstream
git checkout argo
git rebase main                 # rebase the rebrand commit onto new main
git push -f origin argo         # deploy
```

If the rebase hits conflicts, they'll usually be on lines where upstream
touched code near a rebranded string. Resolve by keeping both changes (the
rebrand sed patterns will still match if upstream didn't touch the exact
string).

## Nuke and rebuild

If rebase gets too messy — or if you just want to regenerate argo from
scratch — reset to main and re-run the sed script:

```bash
git checkout -B argo main
bash rebrand.sh
git add -A
git commit -m "argo: rebrand user-facing strings"
git push -f origin argo
```

This works because `rebrand.sh` uses **literal string sed patterns** (not
line numbers), so it's robust to upstream line shifts. If upstream **renames**
a rebranded string entirely, sed silently misses it — the next deployment
test will catch it.

## What gets rebranded

See `rebrand.sh` for the full list. Summary: ~33 source lines across 14
files + ~13 test lines across 9 files.

- **System prompt / identity** (`default_soul.py`, `prompt_builder.py`) —
  "You are Hermes Agent" → "You are Argo Agent"
- **Anthropic adapter** (`anthropic_adapter.py`) — updates the
  `replace("Hermes Agent", "Claude Code")` masquerade pattern so it keeps
  working after the rename
- **Discord** — slash command descriptions, thread labels, default thread name
- **Slack** — `/hermes` → `/argo` slash command
- **Email** — subject defaults, Message-ID prefixes (gateway adapter + send_message tool)
- **Notifications** — HomeAssistant / DingTalk / Matrix titles and device name
- **API server** — `/health` platform, `/v1/models` id/owned_by/root, default fallback
- **Insights** — gateway report header (terminal format left alone, admin-only)
- **OAuth** — browser redirect page, default MCP client name
- **Hindsight plugin** — `retain_context` label

## What does NOT get rebranded

**Admin-only** (never reaches messaging users):
- CLI (`cli.py`, `hermes_cli/*`), banner, setup wizard, doctor, status
- Startup/lock errors (`"Another local Hermes gateway..."`) — logged to
  admin console, users just see the bot go offline
- `agent/insights.py:623` — terminal format of insights

**Structural** (upstream-tracked, conflict-prone if changed):
- Module / directory / file names (`hermes_cli/`, `hermes_constants.py`, ...)
- Env vars (`HERMES_HOME`, `HERMES_TIMEZONE`, ...)
- Config paths (`~/.hermes/`, `SOUL.md`, `config.yaml`)
- All `hermes_cli.*` imports, `pyproject.toml`, Docker, CI, README, AGENTS.md

**Third-party API identifiers** (sent to external services, not user-visible):
- `X-OpenRouter-Title`, `product=hermes-agent` Nous tag
- `User-Agent: HermesAgent/1.0` headers to WeChat / Feishu
- Copilot ACP `clientInfo`
- `X-Hermes-Session-Id` HTTP header (API contract for session continuity)

**Internal protocol identifiers** (wire-level, not displayed):
- Slack `hermes_approve_*` action IDs, Feishu `hermes_action` button field
- `hermes_pkce` OAuth source identifier

**CRITICAL — must never touch:**
- `gateway/platforms/matrix.py:62` — `_KEY_EXPORT_PASSPHRASE = "hermes-matrix-e2ee-keys"`
  (E2EE key-export passphrase; changing it breaks encrypted Matrix sessions)
- LLM model names (`hermes-3-*`, `nous-hermes-*`) — third-party model IDs

## Runtime gotcha: existing deployments

`hermes_cli/default_soul.py` only seeds `~/.hermes/SOUL.md` on **first run**.
If a deployment was set up before the rebrand, its SOUL.md still says
"You are Hermes Agent" and the LLM will produce "Hermes"-flavored replies
(e.g. "Hermes logs", "Hermes can help with…") until you fix it.

On each existing deployment, either:

```bash
rm ~/.hermes/SOUL.md           # let it re-seed from the new default
# ...or...
sed -i 's/Hermes Agent/Argo Agent/g' ~/.hermes/SOUL.md
# then restart the bot
```

The LLM may also pull "Hermes" from context files like `AGENTS.md` /
`.hermes.md` if they're loaded as context. Those are intentionally not
rebranded because they're developer-facing, but their content leaks into
the LLM's responses. If that becomes a problem, edit those files on the
specific deployment.

## Adding a new rebranding rule

When upstream introduces a new user-facing "Hermes" string:

1. Edit `rebrand.sh` — add a targeted `sed` rule. **Use literal strings,
   not line numbers**, so the rule survives upstream line shifts.
2. Re-run `bash rebrand.sh` and inspect `git diff` to confirm the rule matches.
3. Rebuild argo (either rebase or nuke-and-rebuild).
