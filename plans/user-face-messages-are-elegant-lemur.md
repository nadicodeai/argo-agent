# Friendly user-facing messages for argo-agent

## Context

argo deploys hermes-agent messaging bots to **non-technical end users**.
Today the bots leak engineer-grade text in some places. We want
friendlier UX without violating the fork's design constraints.

## What's been ruled out (for clarity)

- **PRs upstream** — argo does not control NousResearch/hermes-agent
- **Sed in `rebrand.sh` for UX** — branding only
- **Plugins, monkey-patches, subclass walks, `format_message` wrappers**
- **`.patch` files against upstream sources** — every patch is a future merge-conflict surface
- **HTTPS proxy / sidecar** — operational overkill for ~15 string changes

The remaining solution-space for in-tree work is empty. Acknowledged.

## The frame shift

Most user-visible text in a hermes-agent bot is the **LLM's own
generated reply**, not a hardcoded gateway string. The hardcoded
strings (the ones the audits keep finding in `gateway/run.py`,
`cron/jobs.py`, `agent/context_references.py`) are **fallbacks**:
they fire when the LLM call fails or returns nothing. In normal
operation, the user sees the model's voice.

Re-categorizing the audit findings by frequency-on-real-traffic:

- **High frequency / always visible:** the model's actual replies →
  governed by SOUL.md / system prompt → **fork-controllable**
- **Low frequency / appears on errors:** context-overflow message,
  request-failed, rate-limit, generic 500/400 fallback → fires only
  when an API call errors → **not fork-controllable without a rejected mechanism**
- **Rare / appears at flow boundaries:** pairing throttle, cron-add
  parse error, file-attach refusal → fires on user mistakes or
  account-management edges → **not fork-controllable without a rejected mechanism**

The first bucket is the bulk of UX. Tuning it via SOUL.md is a
single-file fork-owned change with zero merge-friction implications.
The other two buckets stay engineer-grade. That is the real cost of
the constraints; no architecture changes it.

## Decision

Tune SOUL.md to maximize the LLM's reach into plain language and
graceful failure recovery. Accept that hardcoded fallback strings
remain as they are.

This is YAGNI applied honestly: the highest-leverage fix is config,
not code; the lower-leverage cases aren't worth the architectural
cost any of the rejected mechanisms would impose.

### SOUL.md additions

A new section appended to argo's SOUL.md (deployed to
`~/.hermes/SOUL.md`, which the per-deploy override already supports
per `agent/prompt_builder.py:893-917`):

```markdown
## Voice and recovery

You are speaking to non-technical people on consumer messaging
platforms. Keep these in mind always:

- Use plain, everyday language. Avoid jargon ("rate limit", "context
  window", "API", "session", "workspace", "compact", "cron
  expression", "stack trace", "exception"). When you must reference a
  technical concept, name it the way a non-engineer would.
- When something goes wrong on your side, say so simply, suggest one
  thing to try, and offer /reset as a last resort. Never quote raw
  error text, status codes, or paths back to the user.
- When the user asks for something you can't do (file outside allowed
  folder, unsafe command, etc.), say what you can't do and what you
  *could* do instead. One sentence each.
- When a tool call fails, summarize what you tried and what went
  wrong in plain language. Don't paste the tool's raw output.
- When you need to ask permission, frame it as a question with the
  consequence ("I'd like to run X, which will Y. Is that OK?"), not
  a yes/no demand.
- For schedule inputs, accept natural language ("every 30 minutes",
  "9am daily") and translate yourself before passing to the
  scheduling tool. Never ask the user for cron syntax.
```

The exact wording lives in `argo/SOUL.md` and is deployed to
`~/.hermes/SOUL.md` per existing deploy practice (the runtime
gotcha in `docs/argo-fork.md` §"Runtime gotcha" already documents
this override path).

### What this does NOT fix

The hardcoded fallback strings the audits enumerated — context
overflow, request-failed, rate-limit, generic catch-all, pairing
throttle, cron parse error, workspace refusal — **continue to appear
verbatim** when those code paths fire. The fork has no mechanism
left to rewrite them given the rejected list. This is the cost.

In production, these paths fire on:
- API outages (rare, transient)
- Sustained spam (self-correcting)
- User typos on `/cron` (small minority)
- File-attachment requests for restricted paths (small minority)

If observed user-impact data later shows one of these is hit
frequently enough to matter, that's the moment to relax one of the
ruled-out constraints — and the choice of which to relax becomes a
data-informed decision rather than an architectural guess.

## Files

**Modified:**
- `argo/SOUL.md` (or wherever argo's deployed SOUL lives; ship via
  deploy pipeline to `~/.hermes/SOUL.md`)
- `docs/argo-fork.md` — short note: "User-facing voice is governed
  by SOUL.md. Hardcoded fallback strings remain upstream's; see plan
  in `plans/user-face-messages-are-elegant-lemur.md` for the
  rationale."

**NOT modified:**
- `gateway/`, `cron/`, `agent/`, `hermes_cli/`, `gateway/platforms/*`
- `rebrand.sh`
- No new Python module, no plugin, no sidecar, no proxy

## Verification

1. Deploy updated `~/.hermes/SOUL.md` to one Telegram bot.
2. Ask the bot 10-20 questions covering the categories above (one
   that triggers a tool failure, one that asks for a restricted file,
   one that asks for a recurring task, one that asks something
   outside its capability, etc.).
3. Confirm replies sound like a friendly assistant, not an engineer.
4. Iterate on SOUL.md wording based on what you actually see. The
   model is the variable; this is a copy-tuning exercise, not an
   engineering one.

## Lifecycle

- **New voice problem observed:** add a sentence to SOUL.md.
  Re-deploy. No code, no merge. Cycle time: minutes.
- **Hardcoded fallback hits a real user often:** open the question
  again — relax one constraint with eyes open, choose the right
  mechanism for that specific case.
- **Upstream introduces a new fallback string:** noted in the next
  audit. If hit-rate matters, see above. If not, ignore.

## Out of scope

- Touching `gateway/`, `cron/`, `agent/`, `hermes_cli/` in any way
- Plugins / monkey-patches / wrappers / sidecars / proxies / patches
- Localization
- Hardcoded fallback strings (covered by this plan only via the
  observation that they fire rarely; not "fixed")
