# Argo Fork

This is the `argo` branch of a fork of NousResearch/hermes-agent. It exists
to deploy messaging bots (Telegram, WhatsApp, Discord, Slack, etc.) under the
"Argo" brand instead of "Hermes".

Argo is a **stable deploy branch**: it tracks upstream **release tags**, not
`upstream/main`. Main is the upstream dev branch where new code lands hourly
and is not curated for release. Releases are cut as tags (`v2026.4.8`,
`v2026.4.3`, …, CalVer `vYYYY.M.D` + semver `v0.x.0` naming) every 3-7 days.
Argo merges each new release tag on a daily scheduled sync.

Only text that **reaches end users on messaging platforms** is rebranded.
The CLI, setup wizard, env vars, module names, config paths, docs, etc. are
all unchanged because only operators see them. This keeps merges from
upstream lightweight.

## Branch model

- **`argo`** — deployment branch. Built from the latest upstream release tag
  plus two layers of local modifications:
  1. **Honcho session-rebind fix** for NousResearch/hermes-agent#5947 Bug A
     (per-turn `_session_key` refresh in `HonchoMemoryProvider`, touches
     `plugins/memory/honcho/__init__.py` and `run_agent.py`). Applied as a
     `git apply` of `nadicode-agent-fleet/patches/hermes-agent/0001-rebind-session-per-turn.patch`.
     Should go upstream eventually; once merged, drop it.
  2. **Rebrand** of user-facing strings via `rebrand.sh`. Idempotent,
     tolerant of missing files (see the script), so the same rules work
     across different upstream release tags without editing.
- **`main`** — not used by this fork. Upstream's dev branch moves too fast
  to track safely (hundreds of commits per week). If you need to see what's
  brewing upstream, use `git fetch upstream && git log upstream/main`.
  There is no local `main` branch maintained in this fork's workflow.

**Always deploy from `argo`, never from anything else.**

## Sync workflow (release-tag tracking, merge-based, no force-push)

The daily scheduled agent (and you, when syncing by hand) follow the same
recipe: fetch upstream tags, find the latest release tag, if it isn't
already in argo's ancestry merge it in, re-run rebrand, push.

```bash
git fetch upstream --tags
LATEST_TAG=$(git tag -l 'v2*.*.*' --sort=-v:refname | head -1)
git checkout argo
git pull origin argo --ff-only

if git merge-base --is-ancestor "$LATEST_TAG" argo; then
    echo "argo already contains $LATEST_TAG — nothing to sync"
    exit 0
fi

git merge "$LATEST_TAG" --no-edit      # regular merge commit
bash rebrand.sh                        # catches any new "Hermes" strings
git add -A
git commit --amend --no-edit           # fold rebrand refresh into merge commit
git push origin argo                   # plain push, no -f, ever
```

If the merge hits conflicts, they'll usually be on lines where upstream
touched code near a rebranded string. Resolve by keeping upstream's
structural change and letting `rebrand.sh` re-apply the sed patterns in
the next step. If `rebrand.sh` itself fails, it's because a rebrand rule's
target file was renamed or restructured upstream — update the rule and
re-run.

### Why release tags and not main

Tracking `upstream/main` means every sync pulls in whatever landed in the
last 24h — half-finished features, pre-fix bugs, refactor dust. For a stable
deploy branch serving real users on messaging platforms, that's an
unacceptable risk surface. Tracking release tags gives you upstream's own
curated snapshots at the cost of at most ~7 days of lag on new features.

### Why merge and not rebase

Rebase would require `git push -f` on every sync. Most permission systems
and agent sandboxes block force-push by default for a reason: it destroys
the remote's record of what was there. Merge-based keeps `origin/argo` as
an ancestor of every new tip, so plain `git push` always works. The cost
is a longer commit history (one merge commit per sync), which nobody reads
anyway — argo is a deploy branch, not an authored project.

## When the honcho fix (or any other local patch) lands upstream

Check after each release sync: the scheduled agent reports any upstream
commits touching `plugins/memory/honcho/` or `run_agent.py` — that's the
early-warning signal. When a release tag ships that contains the upstreamed
fix, drop the local patch:

1. Remove the `git apply` step from the next argo rebuild (see `rebrand.sh`
   and the scheduled trigger prompt).
2. The next sync's merge will bring in upstream's version of the file; the
   local patched version gets superseded. No action needed beyond the normal
   merge.
3. If the merge conflicts on honcho files, prefer upstream's version:
   `git checkout --theirs plugins/memory/honcho/__init__.py run_agent.py`

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
