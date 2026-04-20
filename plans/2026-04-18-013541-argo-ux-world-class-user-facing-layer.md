# Argo Agent User-Facing UX Overhaul Plan

> For Hermes: planning only. Do not implement from this file without a separate execution pass.

## Goal

Make Argo Agent feel world class at the user-facing layer by fixing the experience around messages, commands, tool execution, progress, approvals, and final outputs.

This plan is specifically about the adoption bottleneck where the assistant is powerful but the experience of using it still feels too operator-centric, too fragmented, and too raw.

## Scope

In scope:
- user-facing message UX
- command discoverability and semantics
- tool execution and progress feedback
- approval / interrupt / busy-state UX
- final answer shaping
- platform consistency across CLI and messaging surfaces
- routing / session clarity when sending or receiving messages

Out of scope:
- model quality improvements
- backend infra changes that do not affect UX directly
- full rebrand work outside the existing Argo fork rules
- dashboard / website redesign unless needed to support the same UX contract later

## Current context

This repo already has strong foundations:
- central command registry in `hermes_cli/commands.py`
- core agent loop in `run_agent.py`
- shared tool dispatch in `model_tools.py`
- CLI/TUI presentation in `cli.py` and `agent/display.py`
- messaging orchestration in `gateway/run.py`
- per-platform adapters in `gateway/platforms/*`
- cross-channel delivery in `tools/send_message_tool.py`

The problem is not lack of capability.
The problem is that the UX contract is weak.

Today the system exposes a lot of power, but the user experience still has these failure modes:
- startup and help are feature-heavy instead of task-first
- commands are centralized technically, but not organized around user intent
- progress is visible, but not coherent
- tool completion is often under-explained
- approval flows are safe, but not decision-quality
- reasoning and verbose controls are overloaded and inconsistent
- chat platforms do not share a strong common interaction model
- final answers often do not clearly communicate what was done, what changed, and what was verified

## UX principles for the overhaul

1. Clarity over cleverness
- Default tone should be calm, direct, and trustworthy.
- Cute or playful presentation should be optional, not the baseline.

2. Task-first, not feature-first
- The product should answer “what do I do next?” before it lists all capabilities.

3. Execution must feel legible
- Users should always know:
  - what is happening now
  - whether the assistant is blocked or making progress
  - whether approval is needed
  - what completed
  - what was verified

4. Same semantics across surfaces
- CLI and messaging should not feel like two different products.
- Platform-specific rendering can differ, but the mental model should stay the same.

5. Final answers should close the loop
- Tool-heavy turns should end with a concise, reliable recap.
- The user should not have to reconstruct the work from scattered progress lines.

## Proposed architecture decision

Introduce a single user-facing UX contract that all presentation layers consume.

That contract should standardize:
- command metadata
- turn lifecycle states
- tool event structure
- approval state structure
- delivery receipt structure
- completion summary structure

The CLI, Telegram, Slack, Discord, and any other platforms should render the same semantic events through native UI affordances, instead of each surface inventing its own interpretation.

## Workstream 1: Command taxonomy and discoverability

### Problem
Commands exist, but discovery is still too registry-shaped instead of user-shaped.
The user sees command catalogs, not a guided path to outcomes.

### Objectives
- make help task-oriented
- reduce command overload
- remove semantic ambiguity between similar toggles
- make availability obvious per platform

### Changes

1. Extend command metadata in `hermes_cli/commands.py`
Add richer metadata for every command:
- intent category
- user-facing examples
- platform availability
- visibility tier (`core`, `advanced`, `debug`)
- whether the command changes session state, runtime state, or display state
- whether the command is low-risk or high-risk

2. Redesign help surfaces
Update help so it is organized around jobs:
- start chatting
- switch provider/model
- inspect session
- control tools and skills
- manage approvals and safety
- connect messaging platforms
- debug and recover

3. Improve unknown-command recovery
When a command fails, provide:
- closest valid commands
- one-line explanation
- one suggested next action

4. Split overloaded command semantics
Review and clarify the behavior and naming of:
- `/verbose`
- `/reasoning`
- any platform-gated progress commands

If one command is trying to do multiple jobs, split it.

### Likely files
- `hermes_cli/commands.py`
- `cli.py`
- `gateway/run.py`
- `gateway/platforms/telegram.py`
- `gateway/platforms/discord.py`
- `gateway/platforms/slack.py`

## Workstream 2: Onboarding, startup, and readiness UX

### Problem
The product exposes a lot of information early, but not enough “you are ready / not ready / do this next”.

### Objectives
- make startup legible in 5 seconds
- reduce cognitive load for first-time users
- make readiness and blockers obvious

### Changes

1. Replace feature-dump startup with readiness summary
On startup, lead with:
- ready to chat: yes/no
- missing critical setup: provider? tools? gateway?
- one next step

2. Make tips contextual
Replace random tips with state-aware tips:
- if no provider: teach model setup
- if gateway not configured: teach messaging setup
- if session already healthy: teach the next useful command

3. Redesign first-run guidance
Make setup copy answer:
- can I use this now?
- what is optional?
- what is blocking?
- what is the shortest path to value?

4. Redesign status output around urgency
Lead with:
- blocking issues
- degraded-but-usable issues
- optional improvements

### Likely files
- `hermes_cli/main.py`
- `hermes_cli/setup.py`
- `hermes_cli/banner.py`
- `hermes_cli/tips.py`
- `hermes_cli/status.py`
- `hermes_cli/cli_output.py`

## Workstream 3: Unified execution lifecycle

### Problem
Execution feedback exists, but it does not feel like a coherent lifecycle.
Users see pieces of state rather than a consistent story.

### Objectives
- make turns feel trackable
- unify progress semantics across CLI and messaging
- expose important intermediate states without noise

### Changes

1. Define canonical turn states
Standardize these lifecycle states:
- queued
- thinking
- tool_started
- tool_running
- waiting_for_approval
- tool_completed
- verifying
- completed
- failed
- interrupted

2. Emit lifecycle events consistently from the core loop
The agent loop should provide a stable event model that presentation layers consume.

3. Make progress status user-meaningful
Progress should answer:
- which tool is running
- why it is running
- how long it has been running
- whether the assistant is blocked or still working

4. Add proper busy-state UX
When a session is busy and the user sends a new message, tell them:
- what is currently happening
- whether the new message interrupted or queued
- what to do next if they want to stop or redirect

### Likely files
- `run_agent.py`
- `model_tools.py`
- `cli.py`
- `gateway/run.py`
- `gateway/platforms/base.py`
- `agent/display.py`

## Workstream 4: Tool execution transparency

### Problem
Tool calls are visible, but many completions are still too opaque.
File diffs get better treatment than most other tool results.

### Objectives
- make tool outcomes understandable without reading raw tool output
- reduce uncertainty after tool completion
- create consistent success/failure summaries

### Changes

1. Standardize tool preview and result summaries
Every tool should support a normalized user-facing shape:
- intent preview
- key inputs
- result summary
- duration
- success/failure
- warning flags

2. Improve non-file tool outcomes
Examples:
- browser tools should summarize what page/state changed
- send_message should summarize destination resolution and delivery
- search/query tools should summarize what was found
- cron/delegate/process tools should summarize what started, where, and what the user should expect next

3. Preserve raw details but collapse them by default
The default view should be short.
A detail path should still exist for debugging.

4. Make failures actionable
A failure should tell the user:
- what failed
- why
- whether retry is safe
- what to do next

### Likely files
- `agent/display.py`
- `model_tools.py`
- `tools/registry.py`
- `tools/send_message_tool.py`
- `tools/terminal_tool.py`
- `tools/file_tools.py`
- `tools/delegate_tool.py`
- `tools/browser_tool.py`
- `tools/web_tools.py`
- `tools/process_tool.py` or equivalent process-management surfaces

## Workstream 5: Approval, interrupt, and safety UX

### Problem
Approval is present, but the decision surface is still too raw and inconsistent across platforms.

### Objectives
- increase user confidence in dangerous actions
- make interrupt behavior predictable
- make approvals understandable, not just functional

### Changes

1. Standardize approval cards / prompts
Every approval surface should show:
- the exact risky action
- why it is risky
- scope of approval (`once`, `session`, `always`)
- expiry / staleness behavior
- what happens if denied

2. Improve command previews
Make large shell commands and mutating actions easy to inspect before approval.

3. Clarify interrupt behavior
The user should know whether a new message:
- interrupts
- queues
- is ignored
- or requires `/stop`

4. Unify stale / duplicate / expired approval messaging
Handle these states with strong user guidance.

### Likely files
- `hermes_cli/callbacks.py`
- `tools/approval.py`
- `tools/terminal_tool.py`
- `gateway/run.py`
- `gateway/platforms/telegram.py`
- `gateway/platforms/discord.py`
- `gateway/platforms/slack.py`

## Workstream 6: Final answer shaping

### Problem
Final answers often return raw completion text without enough closure, especially after heavy tool use.

### Objectives
- close the loop on every execution-heavy turn
- make final results easy to trust
- clearly separate answer, verification, and next steps

### Changes

1. Introduce a completion-summary format
For tool-heavy tasks, final output should naturally support:
- what I did
- what happened
- what was verified
- what remains or what comes next

2. Keep reasoning separate from the final answer
Reasoning should not pollute the main reply by default.
If exposed, it should be an optional secondary surface.

3. Make verification visible
When the assistant checked output, say so.
If it did not verify something, also say so.

4. Align prompt contract with UI contract
Update system/developer prompt behavior so the model tends toward:
- concise progress updates
- direct completion summaries
- explicit verification language

### Likely files
- `run_agent.py`
- `agent/prompt_builder.py`
- `cli.py`
- `gateway/run.py`
- `agent/display.py`

## Workstream 7: Messaging-platform consistency

### Problem
Each platform has useful native behavior, but the product-level interaction model still feels uneven.

### Objectives
- same mental model everywhere
- native affordances without semantic drift
- consistent delivery, progress, and completion behavior

### Changes

1. Build a shared platform capability matrix
Track support for:
- typing indicators
- editable messages
- buttons
- menus
- embeds/cards
- reply threading
- markdown richness
- delivery receipts

2. Render the same semantics per platform
For each state, define the native representation on Telegram, Slack, Discord, and others.

3. Improve session and routing clarity
Make it easier to understand:
- which chat/thread the session belongs to
- where replies are going
- what the home channel is
- what target a send action resolved to

### Likely files
- `gateway/platforms/base.py`
- `gateway/platforms/telegram.py`
- `gateway/platforms/slack.py`
- `gateway/platforms/discord.py`
- `gateway/platforms/helpers.py`
- `tools/send_message_tool.py`
- `gateway/session.py`

## Recommended implementation order

### Phase 1: Define the UX contract
Deliverable:
- one shared semantic model for commands, turn states, tool events, approvals, and completion summaries

Primary files:
- `hermes_cli/commands.py`
- `run_agent.py`
- `gateway/platforms/base.py`
- `agent/display.py`

### Phase 2: Fix command/help/readiness surfaces
Deliverable:
- task-first help
- readiness-first startup
- reduced first-run overload

Primary files:
- `hermes_cli/main.py`
- `hermes_cli/setup.py`
- `hermes_cli/banner.py`
- `hermes_cli/tips.py`
- `hermes_cli/status.py`
- `cli.py`
- `gateway/run.py`

### Phase 3: Fix execution and approval lifecycle
Deliverable:
- consistent turn states
- coherent progress model
- better approval and interrupt UX

Primary files:
- `run_agent.py`
- `model_tools.py`
- `cli.py`
- `gateway/run.py`
- `tools/approval.py`
- `tools/terminal_tool.py`
- `hermes_cli/callbacks.py`

### Phase 4: Fix tool-result and final-answer shaping
Deliverable:
- structured, trustworthy execution summaries
- clearer final answers
- better delivery summaries

Primary files:
- `agent/display.py`
- `tools/send_message_tool.py`
- `tools/registry.py`
- selected tool modules
- `agent/prompt_builder.py`
- `gateway/run.py`
- `cli.py`

### Phase 5: Normalize platform rendering
Deliverable:
- consistent UX semantics across Telegram, Slack, Discord, and other supported adapters

Primary files:
- `gateway/platforms/base.py`
- `gateway/platforms/telegram.py`
- `gateway/platforms/slack.py`
- `gateway/platforms/discord.py`
- `gateway/platforms/helpers.py`
- `gateway/session.py`

## Validation plan

### Code-level validation
- update or add tests around command registry and help generation
- add tests for turn lifecycle event emission
- add tests for busy-state and approval-state rendering
- add tests for send-message delivery summaries
- add tests for reasoning visibility behavior
- add platform-specific rendering tests where possible

### UX validation
Create concrete golden-path reviews for these scenarios:

1. First run in CLI
- user installs and starts the assistant
- should understand next step immediately

2. Common command discovery
- user wants to switch model, inspect status, or configure tools
- should find the right command without reading a wall of text

3. Long-running execution
- user starts a coding or browsing task
- should understand what is happening while it runs

4. Dangerous command approval
- user triggers a risky shell action
- should understand the risk and options immediately

5. Chat-platform turn
- user asks Argo to do something via Telegram/Slack/Discord
- should receive consistent execution feedback and completion quality

6. Cross-channel send
- user asks the agent to send to another target
- should understand exactly where the message went and why

### Success criteria
The overhaul is successful if:
- a new user can get to first value without confusion
- a running turn feels trackable instead of opaque
- command discovery feels task-oriented
- tool-heavy turns end in clear, verified summaries
- approvals feel trustworthy
- Telegram, Slack, Discord, and CLI feel like one product with different shells

## Risks and tradeoffs

1. Over-design risk
A richer UX model can add complexity if not kept strict.
Mitigation: define one semantic contract first, then render it simply.

2. Platform divergence risk
Native affordances differ.
Mitigation: keep semantics shared, vary only rendering.

3. Copy churn risk
A lot of files will need user-facing copy updates.
Mitigation: centralize templates where possible.

4. Prompt/UI mismatch risk
If prompt behavior is not aligned with presentation changes, the experience will still feel inconsistent.
Mitigation: treat prompt-builder changes as part of the UX plan, not an afterthought.

## Open questions to resolve before implementation

1. Should the default CLI tone stay playful, or should playful skins become opt-in only?
2. Should reasoning ever appear inline by default on messaging platforms?
3. Should progress be message-edit based where possible, instead of sending new status lines?
4. Should verbose/debug surfaces be separated more aggressively from mainstream user surfaces?
5. Should send_message and other cross-channel actions always show a delivery receipt, even when successful and obvious?

## Bottom line

Argo does not need more capability to feel better.
It needs a stronger UX contract.

The right path is not a cosmetic pass.
It is:
- define one user-facing semantic model
- align command/help/readiness around user intent
- make execution states legible
- make tool outcomes comprehensible
- make final answers close the loop cleanly
- render the same semantics consistently across CLI and messaging platforms
