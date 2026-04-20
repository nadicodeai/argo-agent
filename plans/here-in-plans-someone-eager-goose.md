# Argo customer-facing UX — as a plugin, not a sed storm

## Targets

1. **Merge safety is the floor.** Argo tracks upstream release tags and merges daily. Every change must survive that without hand-resolution. Non-negotiable.
2. **Within that floor, make the customer-facing UX beautiful** on Telegram, Slack, Discord, WhatsApp, Signal, Matrix, email.

## The architectural shift

Earlier drafts tried to express a UX overhaul as a pile of sed rules against upstream files. That was the wrong frame — sed is fine for a 33-line brand swap but collapses under 200 strings, multi-line structural changes, per-tool logic, and prompt engineering.

The repo already ships a first-class plugin system (`hermes_cli/plugins.py`, `VALID_HOOKS`, `pre_llm_call` / `post_tool_call` / etc.). That system is **designed** as a stable extension contract for exactly this kind of behavioral override. A fork-owned plugin is:

- **Zero-merge-risk by construction** — the plugin lives in a fork-owned directory upstream doesn't touch; the contract is the hook signatures, which are versioned API, not source text.
- **Full Python expressivity** — any logic, any templating, any per-platform branching. No literal-string matching.
- **Already how `hermes_cli/plugins.py` expects behavior to be extended** — we're using the system as designed, not fighting it.

So the primary mechanism is a fork-owned plugin: **`argo-voice`**. Sed has a residual role, narrower than before.

## The two mechanisms

### Mechanism A — `argo-voice` plugin (primary)

Lives at `./.hermes/plugins/argo-voice/` inside the argo-agent fork repo. Loaded automatically when `HERMES_ENABLE_PROJECT_PLUGINS=1` is set in the deployment env. Registers hooks via the standard `register(ctx)` entry point.

What it handles:
- Voice alignment (scenarios 6, 11).
- Per-turn completion format (scenario 6).
- Tool-intent narration — the model describes in human words what it's doing before calling the tool (scenario 3, part of 5).
- Error rephrasing in the model's own replies (scenario 7, partial).
- Platform-specific voice shaping (scenario 12).
- Anti-jargon rules (no "session", "turn", "provider", "context window", "gateway" in model output).

What it can't handle:
- Gateway-generated strings — pairing, approval card UI, busy-state messages, queued/interrupt prose, compression notifications, `send_message` tool errors. These are rendered by upstream gateway code before the LLM produces a reply; the plugin can't intercept them.

### Mechanism B — `rebrand.sh` sed rules (secondary, narrower)

Handles only what the plugin can't reach: gateway-generated prose. Roughly 30 rules instead of the 200+ I was heading toward.

- Pairing message prose (scenario 1).
- Approval card **header text** and **button labels** (partial scenario 4; body reshape is deferred).
- Busy/queued/interrupted prose (scenario 8).
- Cross-channel send error prose (scenario 9).
- Auto-reset / compression prose (scenario 10).
- Decorative glyph strip (kawaii faces, anime tildes) in gateway files.
- `send_message` tool error prose.

### What both mechanisms leave unaddressed (deferred, honestly)

- **Approval card body reshape** — leading with intent, collapsing the raw command, color-coded severity. Requires multi-line structural edits to Slack Block Kit / Discord Embed / Telegram HTML. Can't be done safely by sed and isn't reachable by a plugin hook. **Deferred.** Phase 1's header + button relabel already moves the card meaningfully.
- **Raw `{exc}` stripping from gateway errors** — requires removing an f-string argument. Deferred.
- **Splitting `BLOCKED:` tool messages into `user_message` + `agent_note`** — structural upstream change. Deferred. The plugin can teach the model to rephrase the `BLOCKED:` content it sees, but it can't stop the raw string from rendering in verbose gateway views.
- **Edit-in-place progress pattern** — structural. Deferred.
- **Busy-state reactions (native emoji reactions)** — structural. Deferred.

This list is where the merge-safety floor bites. The plan doesn't pretend otherwise.

## UX scenarios × mechanism coverage

| Scenario | Plugin handles | Sed handles | Deferred |
|----------|----------------|-------------|----------|
| 1. First contact / pairing | — | prose | — |
| 2. Typing indicator | — | — | verify during walkthrough |
| 3. Progress updates | narration in reply text | — | edit-in-place |
| 4. Approval | — | header + buttons | card body reshape |
| 5. Tool result | model's reply summarizes | — | structured result cards |
| 6. Completion summary | reply voice | — | — |
| 7. Error | reply voice rephrases | gateway prose | raw `{exc}` strip, `BLOCKED:` split |
| 8. Busy state | — | prose | reaction ack |
| 9. Cross-channel send | — | prose | — |
| 10. Auto-reset / compression | reply voice | prose | — |
| 11. Voice alignment | full | — | — |
| 12. Platform consistency | platform-branching voice | sed applies same prose cross-platform | — |

## Plugin design: `argo-voice`

Layout:

```
./.hermes/plugins/argo-voice/
├── plugin.yaml
├── __init__.py             # register(ctx) entry point
├── voice.py                # voice-injection logic
└── tests/
    ├── test_voice.py
    └── test_register.py
```

### `plugin.yaml`

```yaml
name: argo-voice
version: 0.1.0
description: Argo customer-facing voice, completion format, and anti-jargon rules
author: Argo Fork
provides_tools: []
provides_hooks:
  - pre_llm_call
  - post_llm_call          # for telemetry only; not UX-changing
  - on_session_start       # first-turn init
```

### `__init__.py`

```python
"""argo-voice plugin — customer-facing voice for messaging platforms.

Lives in the argo fork. Uses the stable upstream plugin API, so merges
between releases cannot break this plugin unless upstream removes a hook
name from VALID_HOOKS (at which point the hygiene test fails loudly).
"""
from .voice import (
    voice_injector,
    session_start_noop,
    post_llm_telemetry,
)

def register(ctx):
    ctx.register_hook("pre_llm_call", voice_injector)
    ctx.register_hook("on_session_start", session_start_noop)
    ctx.register_hook("post_llm_call", post_llm_telemetry)
```

### `voice.py`

Core logic. `voice_injector` is the only hook that shapes user-visible behavior.

```python
"""Voice injection for the argo-voice plugin."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# Messaging platforms where we want the customer-facing voice applied.
# CLI is explicitly excluded — it's admin-only per docs/argo-fork.md.
MESSAGING_PLATFORMS = {
    "telegram", "slack", "discord", "whatsapp",
    "signal", "matrix", "email", "weixin", "feishu",
    "homeassistant", "dingtalk", "bluebubbles",
}

FULL_VOICE_GUIDE = """\
[Voice guidance for this reply]

You are replying to a non-operator user on {platform}. Use a calm, direct,
specific voice. Short paragraphs. Trust the reader.

- Lead with what the user asked for. Be specific, not generic.
- When you used tools for a multi-step task, close with a one-sentence recap
  of what you did and what you verified. If you didn't verify something,
  say so explicitly.
- No filler: skip "I'd be happy to", "Sure!", "Great question", "Let me",
  "I'll now", and apologies for normal behavior.
- Never mention internal names: session, turn, provider, gateway, context
  window, sub-agent, iteration, compression, tool call. Say "this
  conversation" or "this chat" instead.
- Before or while running a tool, describe what you're doing in human
  language ("Looking up flights from LAX", "Checking the project files"),
  not the tool name.
- If a tool fails, tell the user what happened in plain words and what
  they can do next. Never show raw stack traces or config file paths.
- Emoji sparingly: ✓ for done, ⚠ for warnings, ❌ for failures. No
  decorative faces or tildes.
- Match {platform} formatting conventions: {platform_hint}
"""

SHORT_VOICE_REMINDER = (
    "[Keep the Argo voice: calm, specific, no filler, no internal names. "
    "Close multi-step work with a one-sentence recap.]"
)

PLATFORM_HINTS = {
    "telegram": "short paragraphs, bold for emphasis, minimal markdown.",
    "slack": "bullets welcome, `code` inline, headers sparingly.",
    "discord": "short paragraphs; embeds are rendered by the gateway, not by you.",
    "whatsapp": "plain text, *bold*, _italic_. Keep it tight.",
    "signal": "plain text, minimal markdown.",
    "matrix": "markdown supported; keep it tight.",
    "email": "plain text; paragraphs; no markdown.",
    "weixin": "plain text, short paragraphs.",
    "feishu": "plain text, short paragraphs.",
    "homeassistant": "short, action-oriented.",
    "dingtalk": "plain text, short paragraphs.",
    "bluebubbles": "plain text, short paragraphs.",
}

# Reinject the full guide every N turns to counter context compression
# dropping the earlier instance. Tunable.
REINJECT_EVERY_N_TURNS = 8


def voice_injector(
    session_id: str,
    user_message: str,
    conversation_history: list,
    is_first_turn: bool,
    model: str,
    platform: str,
    **kwargs,
):
    """Inject voice guidance into the per-turn user message.

    Strategy:
      - First turn on a messaging platform: inject the full guide.
      - Periodic turns (every REINJECT_EVERY_N_TURNS): reinject full guide.
      - Other turns: inject the short reminder.
      - CLI / admin platform: no injection (CLI is admin-only).
    """
    if platform not in MESSAGING_PLATFORMS:
        return None

    # Cheap heuristic for turn count: assistant messages in history.
    assistant_turns = sum(
        1 for m in (conversation_history or [])
        if isinstance(m, dict) and m.get("role") == "assistant"
    )

    if is_first_turn or assistant_turns % REINJECT_EVERY_N_TURNS == 0:
        hint = PLATFORM_HINTS.get(platform, "plain text.")
        return {"context": FULL_VOICE_GUIDE.format(platform=platform, platform_hint=hint)}
    else:
        return {"context": SHORT_VOICE_REMINDER}


def session_start_noop(session_id: str, model: str, platform: str, **kwargs):
    """Reserved for future session-scoped init (telemetry, state)."""
    return None


def post_llm_telemetry(
    session_id: str,
    user_message: str,
    assistant_response: str,
    model: str,
    platform: str,
    **kwargs,
):
    """Observer-only — log response length for future voice tuning.

    Not UX-changing. Kept small so the hook signature exercises the
    plugin loader on every turn (forces early failure if upstream
    removes the hook).
    """
    if platform in MESSAGING_PLATFORMS:
        logger.debug(
            "argo-voice post_llm: platform=%s chars=%d",
            platform, len(assistant_response or ""),
        )
    return None
```

### Why inject per-turn into the user message, not the system prompt?

The plugin API explicitly **does not** let plugins modify the system prompt — that's Hermes's territory (tool enforcement, core personality). Plugins contribute context alongside the user input. This is documented in `website/docs/user-guide/features/hooks.md`:

> All injected context is **ephemeral** — added at API call time only. The original user message in the conversation history is never mutated, and nothing is persisted to the session database.

The trade-off: we pay ~200 tokens of injection per first-turn / periodic turn and ~30 tokens otherwise. In exchange we get:
- Zero system-prompt modification (preserves upstream's prompt cache).
- Voice coverage on every messaging turn, not just first contact.
- Trivial tuning — edit `voice.py` and redeploy; no upstream file touched.

### Plugin tests

`tests/test_voice.py`:
- `test_cli_platform_gets_no_injection` — plugin does nothing on CLI/admin surfaces.
- `test_first_turn_gets_full_guide` — first-turn injection is the full guide.
- `test_subsequent_turn_gets_short_reminder` — returns the reminder text.
- `test_periodic_reinjection` — every Nth turn re-injects the full guide.
- `test_unknown_platform_falls_back_to_plain_hint` — platform hint defaults sensibly.
- `test_hook_signature_matches_upstream_contract` — calls `voice_injector` with every documented kwarg; asserts it accepts `**kwargs` per the plugin API forward-compatibility rule.

### Hermeticity and merge-safety analysis

- Plugin lives at `./.hermes/plugins/argo-voice/` inside the fork repo. Upstream has no `.hermes/plugins/` directory at the repo root. Zero file-level conflict potential.
- The plugin contract is `VALID_HOOKS` in `hermes_cli/plugins.py`. If upstream removes a hook we register, our plugin would fail at load — **caught by the load-time test** (next section). That's a clear, loud signal, not silent breakage.
- The plugin's `register(ctx)` call takes the context object upstream provides. The kwargs contract (`session_id`, `user_message`, `conversation_history`, `is_first_turn`, `model`, `platform`) is documented and uses `**kwargs` for forward compatibility per the plugin API rules.

## Phase 1 — sed residual

Only rules for gateway-generated prose the plugin can't shape. Added to `rebrand.sh`. Every rule is literal-anchored; interpolations and functional status emoji (`⚠️ ⛔ ⏳ ✅ ❌ ⏱ 🔄 📬 💬 ⚡`) are preserved outside the matched substring.

### `gateway/run.py`

| # | Literal to match | Replacement |
|---|------------------|-------------|
| A1 | `Hi~ I don't recognize you yet!` | `Hi — you'll need approval before I can help.` |
| A2 | `Ask the bot owner to run:` | `Share this code with the person who manages this assistant. They can approve you by running:` |
| A3 | `Too many pairing requests right now~ Please try again later!` | `Too many pairing requests right now. Please try again in a few minutes.` |
| A4 | `Gateway restarting — queued for the next turn after it comes back.` | `Argo is restarting — your message is saved and will be handled once I'm back online.` |
| A5 | `Gateway is restarting and is not accepting another turn right now.` | `Argo is restarting right now — can't take new messages yet. Please try again shortly.` |
| A6 | `Queued for the next turn.` | `Got it — I'll pick that up once the current task finishes.` |
| A7 | `Agent is running — wait or /stop first, then switch models.` | `I'm still working on something. Use /stop first if you'd like to switch models.` |
| A8 | `Session automatically reset` | `Conversation reset` |
| A9 | `Adjust reset timing in config.yaml under session_reset.` | *(empty — delete)* |
| A10 | `Session too large for the model's context window.` | `This conversation has grown too long for me to continue.` |
| A11 | `To increase the limit, set agent.gateway_timeout in config.yaml` | `Try again, or ask your administrator if this keeps happening.` |
| A12 | `Provider authentication failed:` | `Couldn't sign in to the AI service:` *(`{exc}` stripping deferred)* |
| A13 | `Dangerous command requires approval:` | `Action needs your approval:` |
| A14 | *(long /approve instructions line — see prior table row A14)* | *(same replacement as before)* |
| A15 | `Approval expired (agent is no longer waiting).` | `This confirmation expired — the action was cancelled.` |
| A16 | `No pending command to approve.` | `There's nothing waiting for approval right now.` |
| A17 | `Command denied (approval was stale).` | `That action was already cancelled or resolved.` |
| A18 | `YOLO mode **OFF** for this session — dangerous commands will require approval.` | `Auto-approve is now **off** — risky actions will ask for your confirmation.` |
| A19 | `YOLO mode **ON** for this session — all commands auto-approved. Use with caution.` | `Auto-approve is now **on** — all actions will run without asking. Use carefully.` |
| A20 | `(>_<) ` | *(empty)* |

### Platform adapter copy + button labels

Same as prior plan — see the Class B and C tables in the previous revision. Button labels become: `Just this once` · `Allow in this chat` (Telegram / Discord) or `Allow in this channel` (Slack) · `Always allow` · `Cancel`.

### `tools/send_message_tool.py` error prose

Same as prior plan Class D: strip `~/.hermes/config.yaml`, env var names, pip install instructions, internal action syntax.

### Rule count

~35 sed rules total. A fraction of the 200+ I was drifting toward.

## Phase 2 — plugin refinement based on walkthrough

After Phase 1 ships the plugin + sed, walk the 12 scenarios on each supported platform. Capture failures:

- If the model isn't following the voice, tune `FULL_VOICE_GUIDE` — add concrete before/after examples in the guide text (few-shot).
- If platform formatting is wrong, expand the platform hint in `PLATFORM_HINTS`.
- If voice decays over long conversations, decrease `REINJECT_EVERY_N_TURNS`.
- If voice injection is too heavy (tokens), compress the guide or move some rules into the short reminder.

This phase is a tight feedback loop against live usage. Weeks 2–4.

## Enforcement

### `tests/test_copy_hygiene.py`

Regex gate on messaging-user-facing files only. Runs in CI after `rebrand.sh`.

In-scope files (**reduced** from the prior draft — the plugin handles the model's output; sed handles only gateway prose):
```
gateway/run.py
gateway/platforms/telegram.py
gateway/platforms/slack.py
gateway/platforms/discord.py
gateway/platforms/matrix.py
gateway/platforms/whatsapp.py
gateway/platforms/signal.py
gateway/platforms/weixin.py
gateway/platforms/feishu.py
gateway/platforms/homeassistant.py
gateway/platforms/dingtalk.py
gateway/platforms/bluebubbles.py
gateway/platforms/email.py
tools/send_message_tool.py
```

Tests:
- `test_no_hermes_product_noun_in_messaging_strings`
- `test_no_kawaii_or_tilde_decoration_in_messaging_strings`
- `test_no_config_yaml_instruction_in_messaging_strings`
- `test_no_env_var_name_in_messaging_strings`
- `test_no_pip_install_in_messaging_strings`
- `test_no_internal_tool_action_syntax_in_messaging_strings`
- `test_no_chat_id_leak_in_send_message_success`

Plus a **plugin load-time test** (catches upstream contract drift):
- `test_argo_voice_plugin_loads_cleanly` — imports the plugin via the real plugin loader; asserts it registers hooks on `pre_llm_call`, `on_session_start`, `post_llm_call`; asserts the hook callables accept the documented kwargs.
- `test_argo_voice_injector_end_to_end` — constructs a fake `ctx` call like the hook system would; asserts the return shape is a `{"context": str}` dict on messaging platforms and `None` on CLI.

If upstream ever removes a hook name from `VALID_HOOKS`, the plugin test fails at CI, not silently at runtime.

### `docs/voice.md`

Short fork-owned doc. Codifies:
- Targets and order (merge-safe floor; UX within).
- The 12 scenarios.
- The two mechanisms (plugin primary, sed secondary) and the deferred list.
- Where the plugin lives and how it's installed.
- How to tune the plugin safely.
- The sed hygiene rules with before/after examples.

### Manual UX walkthrough

Not optional. After each phase: sandbox chats on Telegram, Slack, Discord, WhatsApp, email. Walk the 12 scenarios. Screenshot. Critique against this plan's scenario descriptions. File follow-ups on anything still raw.

## Phasing

**Phase 1** — build `./.hermes/plugins/argo-voice/` (plugin + tests); extend `rebrand.sh` with the ~35 sed rules; ship `tests/test_copy_hygiene.py` and the plugin load-time tests; author `docs/voice.md`; walkthrough.

**Phase 2** — tune `voice.py` based on walkthrough findings. Add platform hints, few-shot examples in the guide, adjust reinjection cadence. No upstream files touched.

No Phase 3 in this plan. Deferred items stay deferred unless one becomes critical and earns a specific proposal.

## Sync-workflow verification

From `docs/argo-fork.md`:

```bash
git merge "$LATEST_TAG" --no-edit
bash rebrand.sh
git add -A
git commit --amend --no-edit
git push origin argo
```

This plan's impact on that recipe:

- **Plugin dir** `./.hermes/plugins/argo-voice/`: new directory, fork-only. `git merge` never touches it. Zero conflict potential.
- **Sed rules**: idempotent. After merge, `rebrand.sh` re-applies. Drift surfaces as a no-op rule, caught by the hygiene test.
- **No upstream file is modified by the fork** except through `rebrand.sh`. Every other change lives in fork-owned new files under `./.hermes/plugins/` and `/tests/`.

The daily sync stays exactly as documented. No new steps, no hand-resolution.

## What this plan explicitly does NOT do

- Does not propose any upstream PR.
- Does not add any `.patch` file or patch pipeline step.
- Does not create `argo_*.py` helper files under `gateway/` or `agent/` with sed-inserted imports. (Prior plan drafts did this; the plugin system makes it unnecessary.)
- Does not touch `cli.py`, `hermes_cli/*`, banner, tips, status — admin-only per the fork contract.
- Does not rename any module, file, env var, or config path.
- Does not attempt the deferred items (card reshape, `{exc}` strip, `BLOCKED:` split, edit-in-place progress, reaction ack).

## Risks

| Risk | Mitigation |
|------|------------|
| Upstream removes a hook from `VALID_HOOKS` | Plugin load test fails loudly in CI; migrate to another hook or inline the logic. |
| Upstream changes hook kwargs signature | Plugin uses `**kwargs` per the documented forward-compatibility rule; signature test catches drift. |
| `HERMES_ENABLE_PROJECT_PLUGINS=1` is not set in deployment | Deployment env inspection in startup sanity-check; document in `docs/voice.md`; walkthrough catches it. |
| `pre_llm_call` context injection is too expensive on every first turn | Short reminder on non-periodic turns; compress the guide further if needed. |
| Voice guide doesn't actually change model behavior | Walkthrough is the verification; tune `voice.py` based on observed failures; extend with few-shot. |
| Sed rule anchor drifts after upstream reword | Hygiene test flags; re-anchor. |
| Scope creep toward CLI or toward patch files | `docs/voice.md` and `docs/argo-fork.md` are the hard lines. |
| Manual walkthrough is skipped | Plan says it's not optional; reviewers enforce. |

## Critical files

Fork-owned (all new except `rebrand.sh` and `docs/argo-fork.md`):
- `/home/vadim/Code/argo-agent/.hermes/plugins/argo-voice/plugin.yaml`
- `/home/vadim/Code/argo-agent/.hermes/plugins/argo-voice/__init__.py`
- `/home/vadim/Code/argo-agent/.hermes/plugins/argo-voice/voice.py`
- `/home/vadim/Code/argo-agent/.hermes/plugins/argo-voice/tests/test_voice.py`
- `/home/vadim/Code/argo-agent/.hermes/plugins/argo-voice/tests/test_register.py`
- `/home/vadim/Code/argo-agent/rebrand.sh` — extend with ~35 sed rules for gateway prose.
- `/home/vadim/Code/argo-agent/tests/test_copy_hygiene.py` — regex gate + plugin load test.
- `/home/vadim/Code/argo-agent/docs/voice.md` — targets, scenarios, mechanisms, deferred list.
- `/home/vadim/Code/argo-agent/docs/argo-fork.md` — append a section documenting the plugin path, the `HERMES_ENABLE_PROJECT_PLUGINS=1` env requirement, and the enforcement convention.

Upstream files referenced **only via `rebrand.sh` sed rules** (never directly edited):
- `gateway/run.py`, `gateway/platforms/{telegram,slack,discord}.py`, `tools/send_message_tool.py`.

## Bottom line

The plugin system is already the architecture I was reaching for. `argo-voice` ships as a fork-owned plugin at `./.hermes/plugins/argo-voice/`, uses `pre_llm_call` to inject voice and completion rules into every messaging-platform turn, and covers the majority of UX scenarios through the model's own output. Sed shrinks to its rightful scope: gateway-generated prose the plugin can't reach — roughly 35 rules. Deferred items are listed honestly. Daily upstream merge continues unchanged because no upstream file is modified outside `rebrand.sh`.
