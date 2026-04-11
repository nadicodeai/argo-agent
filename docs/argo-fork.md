# Argo Fork

This is the `argo` branch of a fork of NousResearch/hermes-agent. It exists
to deploy messaging bots (Telegram, WhatsApp, Discord, Slack, etc.) under the
"Argo" brand instead of "Hermes".

Only text that **reaches end users on messaging platforms** is rebranded.
The CLI, setup wizard, env vars, module names, config paths, docs, etc. are
all unchanged because only operators see them. This keeps merges from
upstream lightweight.

## Branch model

- **`main`** — pristine mirror of `upstream/main`. Only fast-forward pulls
  from upstream; no local commits ever.
- **`argo`** — deployment branch. Contains the fork modifications on top
  of whatever upstream merged-in last:
  - The honcho session-rebind fix for NousResearch/hermes-agent#5947 Bug A
    (per-turn `_session_key` refresh in `HonchoMemoryProvider`, touches
    `plugins/memory/honcho/__init__.py` and `run_agent.py`). Should go
    upstream eventually; once merged, drop it.
  - The rebrand of user-facing strings via `rebrand.sh`.

**Always deploy from `argo`, never from `main`.** `main` is raw upstream
code, still says "Hermes" everywhere, and is missing the honcho rebind fix.

## Sync workflow (merge-based, no force-push)

This fork uses a **merge-based** sync, not rebase. Every upstream sync
produces a regular merge commit on `argo`, and pushes are plain `git push`
with no `-f`. The branch history grows over time but never gets rewritten,
so `origin/argo` is always an ancestor of local `argo` and the permission
system never gates a force-push.

```bash
git checkout main
git pull upstream main --ff-only       # main stays pristine
git checkout argo
git merge main                         # regular merge commit
bash rebrand.sh                        # catches any new "Hermes" strings
git add -A
git commit --amend --no-edit           # fold rebrand refresh into merge commit
git push origin argo                   # plain push, no -f, ever
```

If the merge hits conflicts, they'll usually be on lines where upstream
touched code near a rebranded string. Resolve by keeping upstream's
structural change and letting `rebrand.sh` re-apply the sed patterns in
the next step.

### Why merge and not rebase

Rebase gives a cleaner linear history (always "main + honcho + rebrand"),
but requires `git push -f` on every sync, which is blocked by default by
most permission systems and agent sandboxes for a reason: force-push
destroys the remote's record of what was there. For a solo deploy branch
it's technically safe, but "technically safe" and "safety system wants to
block it by default" is a smell.

Merge-based trades a longer commit history (one merge commit + rebrand
refresh per sync) for zero force-pushes. Nobody reads `argo`'s commit
history anyway — it's a deploy branch, not an authored project. The
meaningful diff (`git diff main argo`) stays exactly the same either way:
honcho fix + current rebrand output.

## When a patch goes upstream

When the honcho fix (or any other local patch) is accepted upstream, drop
it from argo. Simplest way:

```bash
git checkout main
git pull upstream main --ff-only       # now includes the upstreamed fix
git checkout argo
git merge main                         # merge normally; upstream commit replaces local one
# If the merge conflicts on honcho files (upstream's version vs ours),
# take upstream's version since it's now the authoritative fix:
#   git checkout --theirs plugins/memory/honcho/__init__.py run_agent.py
bash rebrand.sh && git add -A && git commit --amend --no-edit
git push origin argo
```

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
