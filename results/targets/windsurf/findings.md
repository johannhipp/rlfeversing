# Windsurf Findings

## Verdict

Windsurf's harness is closed-source.

Primary evidence:

- As of 2026-03-28, Windsurf’s official download/release surfaces are binary-first: macOS `.zip`/`.dmg`, Windows `.exe`/`.zip`, and Linux `.tar.gz`/`.deb` editor artifacts rather than a public editor source tree.
- Windsurf’s official docs describe the product as a VS Code fork with Cascade, terminal integration, hooks, MCP, skills, workflows, and rules, but they do not point to a public repository for the main editor/harness implementation.
- Exafunction does publish adjacent public repos and support assets, but those are integrations and companion projects rather than the core Windsurf Editor harness. The visible public org surface is things like `windsurf.vim`, `windsurf.nvim`, `WindsurfVisualStudio`, `windsurf-demo`, and `codeium`.

## Local Artifact Status

I could not perform binary-level reversing on this machine because there is no local Windsurf install to inspect.

Observed in a fresh non-interactive probe on 2026-03-28:

- `which windsurf` returned `NOT_FOUND`
- no `Windsurf.app` was present in `/Applications` or `~/Applications`
- no documented Windsurf state directories were present under `~/.codeium/windsurf` or `~/.windsurf`
- a targeted filesystem search under `~/.codeium`, `~/.config`, and `~/.local/share` did not find any `*windsurf*` artifact paths

I also could not fetch a release artifact directly from the shell because DNS resolution failed for both `windsurf.com` and `docs.windsurf.com` in this environment. That is an environment limitation, not evidence about Windsurf itself.

Practical consequence:

- no `strings` pass on a shipped binary
- no safe `timeout 10 <binary> --help` style probe
- classification relies on official docs/download surfaces plus local absence of an installed binary

## What the Harness Is

Windsurf is a proprietary AI IDE built as a VS Code fork, with its agentic assistant exposed as `Cascade`.

The public docs show that Cascade supports:

- Code and Chat modes
- tool calling
- terminal integration
- web/docs search
- MCP integration
- memories and rules
- skills
- workflows
- checkpoints/reverts
- real-time awareness
- simultaneous Cascade sessions

This is enough to characterize the harness at the product-surface level even without source access.

The getting-started docs also describe installing a `windsurf` command into PATH from the editor, which is consistent with a packaged desktop app exposing a CLI shim rather than a separately published open harness.

## Evidence It Is Not Open-Source

The strongest evidence is what is missing:

- no official public source repo for the main Windsurf Editor
- no public license for the editor/harness itself
- official installation guidance is binary-first: download and install the editor for macOS, Windows, or Linux

At the same time, the vendor does have public GitHub repos for adjacent tools and integrations, which makes the absence of the editor source more meaningful rather than less.

## Subagents

Windsurf publicly documents at least one explicit internal subagent: `Fast Context`.

What the docs say:

- Fast Context is a "specialized subagent" for code retrieval.
- It triggers automatically when Cascade needs code search.
- It uses custom SWE-grep models for retrieval.
- It is optimized around parallel tool calling rather than general execution.

Important documented limits:

- up to 8 parallel tool calls per turn
- up to 4 turns
- restricted tool set: `grep`, `read`, `glob`

Interpretation: Windsurf does have real delegated internal specialization, but not in the form of user-addressable general worker agents. The subagent is narrow and infrastructural: retrieval, not implementation.

## Planning / Multi-Agent Structure

Windsurf also documents a split planning architecture:

- a specialized planning agent continuously refines the long-term plan
- the user-selected model focuses on short-term actions
- the system maintains a todo list inside the conversation

That matters because it suggests at least two internal agent roles inside the harness:

- planning
- execution

Combined with Fast Context, the public architecture looks like:

- main conversational/execution model
- background planning agent
- retrieval subagent for search-heavy tasks

## Tool Calling Architecture

Windsurf does not publish the implementation, but the docs expose a meaningful part of the tool surface.

Cascade tool categories explicitly documented:

- Search
- Analyze
- Web Search
- MCP
- terminal

Other documented behaviors:

- Cascade can make up to 20 tool calls per prompt.
- If the trajectory stops, the user can press `continue` and Cascade resumes, with additional prompt-credit cost.
- Auto-Continue can be enabled to keep going after tool limits are reached.
- Cascade can detect missing packages/tools and propose or perform installation.

This suggests a fairly standard agent harness loop:

1. user prompt enters Cascade
2. model chooses tools
3. harness executes tool calls
4. results are fed back to the model
5. loop halts on completion or tool budget exhaustion

That part is inference from the documented behavior, not source-confirmed implementation.

## Local vs Remote Execution

The docs reveal a mixed architecture:

- web search can use open-Internet search when enabled
- specific page reads happen locally on the user’s machine within the user’s network
- terminal commands run through the local machine
- MCP servers are configured locally and exposed to Cascade through a local config file
- worktree setup and tool activity can be intercepted with local hooks

Important local paths documented:

- `~/.codeium/windsurf/mcp_config.json`
- `~/.codeium/windsurf/memories/`
- `.windsurf/workflows/`
- `.windsurf/skills/`

The MCP docs also say:

- Cascade supports `stdio`, `Streamable HTTP`, and `SSE` MCP transports
- Cascade has a limit of 100 total MCP-exposed tools at once

The hooks docs add stronger architectural evidence. Windsurf documents named hook events for:

- `pre_read_code` / `post_read_code`
- `pre_write_code` / `post_write_code`
- `pre_run_command` / `post_run_command`
- `pre_mcp_tool_use` / `post_mcp_tool_use`
- `pre_user_prompt`
- `post_cascade_response`
- `post_cascade_response_with_transcript`
- `post_setup_worktree`

These hooks can observe or block actions, and `post_setup_worktree` runs after a git worktree is created. That strongly suggests file IO, terminal execution, MCP calls, prompt ingress, and worktree setup are explicit harness actions rather than purely product-copy abstractions.

The hooks docs also expose an unusually rich audit surface for a closed product:

- pre-hooks can block reads, writes, commands, MCP calls, and prompt processing by exiting with code `2`
- `post_cascade_response` receives a markdown summary that includes planner responses, tool actions, and triggered rules
- `post_cascade_response_with_transcript` writes a full JSONL transcript to `~/.windsurf/transcripts/{trajectory_id}.jsonl`
- documented transcript step types include `user_input`, `planner_response`, and `code_action`

Interpretation: even without the binary, Windsurf’s own hooks docs confirm that the harness has explicit internal action types and a persisted trajectory representation, not just a monolithic chat surface.

## Command Execution and Safety Controls

Windsurf’s terminal docs expose a clear approval model.

Auto-execution levels:

- Disabled
- Allowlist Only
- Auto
- Turbo

Behavior:

- in `Disabled`, all commands need approval
- in `Allowlist Only`, only matching allowlisted commands auto-run
- in `Auto`, Cascade decides whether a command seems safe
- in `Turbo`, commands auto-run except denylisted ones

This is useful harness evidence because it shows Windsurf treats terminal execution as a first-class capability with policy controls instead of a hidden implementation detail.

## Skills, Rules, AGENTS.md, and Workflows

Windsurf exposes several customization layers that reveal how the harness manages context.

`AGENTS.md`

- automatically discovered
- root file is always on
- subdirectory files are auto-scoped to `<directory>/**`
- fed into the same rules engine as `.windsurf/rules/`

`Skills`

- stored in `.windsurf/skills/<skill-name>/` or `~/.codeium/windsurf/skills/<skill-name>/`
- use progressive disclosure: only `name` and `description` are initially shown to the model
- full `SKILL.md` and support files load only when Cascade invokes the skill or the user `@mentions` it
- can also be auto-discovered from `.agents/skills/` and `~/.agents/skills/`

`Workflows`

- stored in `.windsurf/workflows/`
- invoked manually via `/workflow-name`
- never invoked automatically
- processed sequentially
- can call other workflows
- built-in workflows exist, including `/plan`

These are all useful for reverse engineering because they expose how Windsurf divides:

- persistent prompt-level guidance
- reusable multi-step procedures
- explicit user-invoked trajectories

## Are the Subagents / Tool Calls Useful?

Yes, within the harness Windsurf’s documented architecture looks useful.

Fast Context seems useful because:

- it offloads retrieval from the main model
- it uses parallel tool calls
- it reduces context pollution
- it should improve latency on large codebases

The planning agent also looks useful because:

- it separates long-horizon task planning from immediate execution
- it gives the harness a better chance on multi-step tasks

The general tool layer also looks useful because:

- terminal, MCP, search, and local page reading make the assistant operational rather than purely advisory
- approval levels keep that power somewhat governable
- hooks provide an auditable interception layer around reads, writes, terminal commands, MCP calls, prompts, and worktree setup

The main caveat is that the most interesting delegated capability documented publicly is narrow. Windsurf’s exposed subagent story is retrieval/planning specialization, not user-controlled swarms of independent worker agents.

## Who Would Be a Good Judge?

Best judges:

- staff-plus engineers or power users working in large codebases
- agent/evals researchers comparing harnesses on long-horizon tasks
- IDE-agent platform engineers who have built tool routers, retrieval systems, or planner layers themselves
- security/compliance engineers evaluating local execution and approval controls

Likely weak judges:

- users expecting fully programmable open-source internals
- anyone looking for transparent implementation details instead of product behavior
- evaluators who only judge raw model quality and ignore harness affordances such as retrieval, terminal controls, and hooks

## What They Would Likely Say

Reasonable judge summary:

- Positive: "This harness seems stronger than a plain chat-in-editor setup because retrieval, planning, terminal execution, MCP, and local page reads are explicitly integrated."
- Positive: "Fast Context is a pragmatic subagent design. Retrieval is exactly where narrow delegated workers make sense."
- Mixed: "The architecture looks useful, but we only see the product surface, not the implementation quality."
- Negative: "Because the harness is closed-source, you cannot audit how robust the tool router, planner, or safety layers actually are."

In the context of the harness, the useful parts are probably:

- retrieval specialization
- long-task planning
- local terminal/MCP execution
- scoped rules/skills/workflows

The less convincing part, from a reverse-engineering perspective, is that the interesting machinery is mostly documented behavior rather than inspectable code.

Another caveat is that Windsurf exposes rich trajectory-level customization through rules, skills, workflows, hooks, and worktrees, but the public docs do not reveal how the planner or tool router behaves under failure, rollback, or adversarial inputs. That remains opaque without source or artifact inspection.

One more positive note: the documented transcript hook and worktree hook make Windsurf easier to observe than many closed-source harnesses. A strong evaluator could inspect actual JSONL trajectories, planner/tool sequencing, and worktree setup behavior locally without needing source access.

## Closed-Source RE Path

I attempted the closed-source route, but the environment limited how far I could go:

- no local Windsurf installation or `windsurf` CLI was present
- no `~/.codeium/windsurf/` local state directory was present to inspect
- shell DNS/network resolution was unavailable, so I could not download a release artifact directly for `strings` or `--help` inspection
- therefore I could not perform binary-level reverse engineering in this workspace

If artifact access becomes available, the next steps should be:

1. Download a Linux `.tar.gz` or macOS `.zip` release.
2. Inspect bundle structure for Electron / VS Code fork markers.
3. Run `strings` on primary binaries and ASAR/package contents.
4. Probe the PATH-installed `windsurf` launcher in non-interactive mode using a timeout wrapper.
5. Inspect `~/.codeium/windsurf/`, `~/.windsurf/`, and transcript/hook outputs for remote endpoints, MCP behavior, trajectories, and any user-overridable service URLs.

## Sources

- Windsurf download page: <https://windsurf.com/windsurf/download>
- Windsurf releases page: <https://windsurf.com/editor/releases>
- Getting started docs: <https://docs.windsurf.com/windsurf/getting-started>
- Cascade overview: <https://docs.windsurf.com/windsurf/cascade/cascade>
- Fast Context docs: <https://docs.windsurf.com/context-awareness/fast-context>
- Hooks docs: <https://docs.windsurf.com/windsurf/cascade/hooks>
- Terminal docs: <https://docs.windsurf.com/windsurf/terminal>
- Web and Docs Search docs: <https://docs.windsurf.com/windsurf/cascade/web-search>
- MCP docs: <https://docs.windsurf.com/windsurf/cascade/mcp>
- AGENTS.md docs: <https://docs.windsurf.com/windsurf/cascade/agents-md>
- Skills docs: <https://docs.windsurf.com/windsurf/cascade/skills>
- Workflows docs: <https://docs.windsurf.com/windsurf/cascade/workflows>
- Memories & Rules docs: <https://docs.windsurf.com/fr/windsurf/cascade/memories>
- Exafunction GitHub org overview: <https://github.com/Exafunction>
