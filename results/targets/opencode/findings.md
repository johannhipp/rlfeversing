# Opencode Findings

## Classification

Status: open-source.

Date inspected: 2026-03-28
Local version inspected: `opencode 1.3.3`
Current public source recovered: `anomalyco/opencode` on GitHub (`dev` branch)
Historical repo also found: `opencode-ai/opencode` (older Go codebase, archived on 2025-09-18)

## Primary Artifacts Inspected

- Local binary: `/Users/johann/.opencode/bin/opencode`
- Local SDK package: `/Users/johann/.opencode/node_modules/@opencode-ai/sdk/package.json`
- Local plugin package: `/Users/johann/.opencode/node_modules/@opencode-ai/plugin/package.json`
- Local generated SDK types:
  - `/Users/johann/.opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts`
  - `/Users/johann/.opencode/node_modules/@opencode-ai/plugin/dist/index.d.ts`
- Safe CLI probes:
  - `perl -e 'alarm shift; exec @ARGV' 10 /Users/johann/.opencode/bin/opencode --help`
  - `perl -e 'alarm shift; exec @ARGV' 10 /Users/johann/.opencode/bin/opencode run --help`
  - `perl -e 'alarm shift; exec @ARGV' 10 /Users/johann/.opencode/bin/opencode agent --help`
  - `perl -e 'alarm shift; exec @ARGV' 10 /Users/johann/.opencode/bin/opencode serve --help`

## Evidence

1. The current harness source is public at `https://github.com/anomalyco/opencode`, which exposes the live TypeScript/Bun runtime under `packages/opencode/src/`.
2. The public repo includes an MIT license and readable source for the exact harness subsystems that matter here:
   - `packages/opencode/src/session/prompt.ts`
   - `packages/opencode/src/tool/task.ts`
   - `packages/opencode/src/tool/registry.ts`
   - `packages/opencode/src/agent/agent.ts`
3. The local binary at `/Users/johann/.opencode/bin/opencode` is a Bun-compiled Mach-O executable, not a stripped native-only app. `strings` shows Bun runtime internals and TypeScript/Bun-style symbols.
4. The local install also contains public npm-style packages:
   - `/Users/johann/.opencode/node_modules/@opencode-ai/plugin/package.json`
   - `/Users/johann/.opencode/node_modules/@opencode-ai/sdk/package.json`
5. Both installed packages declare `license: "MIT"`.
6. The cached instruction file used for Codex inside opencode explicitly says: `opencode is an open source project.`
7. Public docs at `https://opencode.ai/docs/plugins/` document TypeScript plugin authoring against `@opencode-ai/plugin`, including custom tools and event hooks.
8. Safe local CLI probes show a normal product command surface instead of a sealed single-purpose binary:
   - `serve` starts a headless server
   - `attach` connects to a running server
   - `run` supports `--format json`
   - `agent` exposes `create` and `list`

Conclusion: this is an open-source project that ships a compiled Bun distribution.

Important lineage note:

- There are two public repos in play.
- `opencode-ai/opencode` is an older archived Go implementation.
- The current Bun/TypeScript harness reflected by local packages, docs, and current source is `anomalyco/opencode`.

## Harness Shape

Opencode is not just a terminal wrapper. The current source and installed SDK expose a server-oriented harness with:

- headless/server modes: `serve`, `web`, `attach`
- agent management: `agent`, `/agent` API
- session/message APIs: session create/list/fork/share/export/import
- PTY management: explicit PTY session APIs in the SDK
- MCP integration: `opencode mcp`
- plugin hooks and custom tools

This makes it closer to a programmable agent runtime than a thin single-process CLI.

CLI evidence for that shape:

- `opencode serve --help` advertises a headless server mode.
- `opencode --help` advertises `attach`, `web`, `session`, `export`, `import`, `github`, `pr`, and `db`.
- `opencode run --help` exposes `--format default|json`, `--attach`, `--agent`, `--session`, and `--fork`.

## Subagents

Subagents are first-class in both the protocol and the runtime.

Evidence from current public source:

- `packages/opencode/src/agent/agent.ts` defines agent modes as `"subagent" | "primary" | "all"`.
- Built-in subagents include at least:
  - `general`
  - `explore`
- `general` is described as a general-purpose subagent for multi-step work in parallel.
- `explore` is described as a fast codebase exploration agent with a narrowed permission surface.
- `packages/opencode/src/session/prompt.ts` accepts both `AgentPartInput` and `SubtaskPartInput` as structured message parts.
- User `@agent` references are converted into a synthetic instruction telling the model to call the `task` tool with that subagent.
- `packages/opencode/src/tool/task.ts` implements the `task` tool by:
  - validating `description`, `prompt`, `subagent_type`, optional `task_id`, optional `command`
  - creating or resuming a child session
  - selecting the target agent
  - inheriting or overriding the model
  - calling `SessionPrompt.prompt(...)` inside the child session
  - returning a resumable `task_id`

Evidence from local SDK typings matches this:

- `AgentConfig.mode?: "subagent" | "primary" | "all"`
- `AgentConfig.hidden?: boolean`
- `AgentConfig.steps?: number`
- `SubtaskPartInput` carries `prompt`, `description`, `agent`, optional `model`, and optional `command`
- Plugin types expose hook points around execution and policy:
  - `permission.ask`
  - `tool.execute.before`
  - `tool.execute.after`
  - `shell.env`
  - `tool.definition`

What this means:

- delegation is a real harness primitive, not just a prompt convention
- subagents run as child sessions with their own permissions
- the harness supports resumable delegated work through `task_id`
- commands can explicitly force subtask execution instead of leaving delegation entirely to model free text

## Tool Calls

Tool calling is also first-class.

Evidence from current public source:

- `packages/opencode/src/tool/registry.ts` builds the active tool list each turn from:
  - built-ins like `bash`, `read`, `glob`, `grep`, `edit`, `write`, `task`, `webfetch`, `todowrite`, `websearch`, `codesearch`, `skill`, `apply_patch`
  - optional tools gated by flags/config
  - custom filesystem-loaded tools
  - plugin-provided tools
- Tool definitions are materialized through `ToolRegistry.tools(...)`, which also lets plugins rewrite tool descriptions/parameters via `tool.definition`.
- `packages/opencode/src/session/prompt.ts` turns registry entries into model-callable tools and wraps each execution with:
  - `tool.execute.before`
  - `tool.execute.after`
  - permission checks through `ctx.ask(...)`
- MCP tools are wrapped into the same execution path, including plugin hooks, permission asks, output normalization, and attachment handling.
- `packages/opencode/src/tool/tool.ts` enforces zod validation before execution and truncates oversized outputs consistently.

Permission controls are granular enough to show the intended tool surface:

- `read`, `edit`, `glob`, `grep`, `list`, `bash`, `task`
- `external_directory`
- `todowrite`, `todoread`, `question`
- `webfetch`, `websearch`, `codesearch`, `lsp`, `skill`

This is a serious harness design, not a toy wrapper around one shell tool.

Execution-loop detail that matters:

- `packages/opencode/src/session/prompt.ts` is the central loop.
- Each step it:
  - reloads message history
  - processes pending `subtask` or compaction parts first
  - resolves the active tool list for the current agent/model
  - hands messages plus tools to the session processor
  - continues if the model finished with `tool-calls`
- That is real iterative tool orchestration, not one-shot function calling.

## Are The Subagents/Tools Useful?

Yes, in the context of the harness.

Why:

1. Subagents are represented structurally, so the runtime can reason about delegation instead of relying on prompt text alone.
2. The `task` tool creates resumable child sessions with scoped permissions, which is a useful delegation model for real work instead of fake "ask another agent in plain English" delegation.
3. Tool execution has explicit pre/post hooks, permission interception, schema validation, and truncation, which makes observability and policy enforcement possible.
4. The SDK/server split means external clients, plugins, or alternate UIs can reuse the same runtime behavior.
5. PTY, session, and permission APIs indicate the harness is designed for long-running, inspectable agent workflows rather than one-shot prompts.

Practical limitation:

- In this offline environment, many CLI commands attempt to reach `models.dev` before completing, so the runtime has network-sensitive startup behavior.
- That likely reduces robustness for local-only or degraded-network scenarios.

## Who Is A Good Judge?

Best judges:

1. Plugin authors building custom tools and policy hooks on top of opencode.
2. SDK consumers embedding the headless/server runtime into other products.
3. Power users running multi-step coding tasks where delegation, permissions, and session continuity matter.
4. Maintainers of other coding-agent harnesses comparing runtime architecture, not just model quality.

Named examples of credible judges:

- maintainers of Codex, Cline, Aider, or other coding-agent harnesses
- plugin/tool authors extending opencode itself
- teams embedding agent runtimes behind custom UIs or internal developer platforms

## What Would They Say?

Likely judgments:

1. Plugin authors would say the tool/hook surface is useful because it is explicit and interceptable. `tool.execute.before/after`, `permission.ask`, and `shell.env` are the kinds of hooks you need to make a harness extensible.
2. SDK consumers would say the harness is more useful than a CLI-only agent because it exposes server APIs for sessions, tools, PTYs, agents, and events.
3. Multi-agent workflow users would say subagents are useful because they are modeled directly in the message protocol and executed through child sessions returned with resumable `task_id`s.
4. A harness maintainer would probably judge the `explore` agent favorably because it narrows permissions substantially, which is exactly the kind of specialization that makes subagents more than branding.
5. A skeptical harness author would still say usefulness depends on execution quality. The architecture is good, but actual value depends on whether the model reliably chooses the right agent/tool and whether network dependencies like `models.dev` stay available.

## Reverse-Engineering Notes

- Safe non-interactive entrypoints:
  - `perl -e 'alarm shift; exec @ARGV' 10 /Users/johann/.opencode/bin/opencode --help`
  - same wrapper for `run --help`, `agent --help`, `debug --help`
- `timeout` is not installed on this machine, so `perl alarm` is a workable substitute.
- Even help/debug commands may try to contact `models.dev` first.
- Local installed type definitions were more informative than raw `strings` for understanding protocol-level agent/tool behavior.
- For opencode specifically, do not stop at the older archived `opencode-ai/opencode` repo. The current harness source is public, but it lives in `anomalyco/opencode`.
