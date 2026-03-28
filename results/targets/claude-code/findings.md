# Claude Code Findings

## Classification

Claude Code is closed-source in the practical harness sense.

Evidence from the installed package at `/opt/homebrew/lib/node_modules/@anthropic-ai/claude-code`:

- `LICENSE.md`: `© Anthropic PBC. All rights reserved.`
- implementation shipped as a single minified bundle: `cli.js`
- bundle banner: `Want to see the unminified source? We're hiring!`
- package metadata points to a GitHub repo, but the shipped artifact does not include a readable source tree

Additional current public-repo evidence:

- the public repo exists at `anthropics/claude-code`
- the current repo `README.md` says the repository includes Claude Code plugins
- the current repo `LICENSE.md` is still all-rights-reserved, not an OSI-style license

Conclusion: this is a proprietary distributed Node CLI, not an open-source harness with auditable implementation. The repo is public, but the harness itself is closed-source; the readable repo surface is mostly around plugins/docs.

## Local Artifact Layout

- binary symlink: `/opt/homebrew/bin/claude -> ../lib/node_modules/@anthropic-ai/claude-code/cli.js`
- package version: `2.1.80 (Claude Code)`
- notable files:
  - `cli.js`
  - `sdk-tools.d.ts`
  - `resvg.wasm`
  - `README.md`
  - `LICENSE.md`
- bundled native helpers:
  - `vendor/ripgrep/<platform>/rg`
  - `vendor/tree-sitter-bash/<platform>/tree-sitter-bash.node`
  - `vendor/audio-capture/<platform>/audio-capture.node`

The shipped bundle header is also useful evidence:

- `// (c) Anthropic PBC. All rights reserved.`
- `// Want to see the unminified source? We're hiring!`

## Safe Probing

`timeout` is not installed on this machine, so interactive probes were wrapped with Perl alarm:

```sh
perl -e 'alarm shift @ARGV; exec @ARGV' 10 /opt/homebrew/bin/claude --help
```

Useful non-interactive commands:

- `claude --help`
- `claude --version`
- `claude agents --help`

Caveats from this machine:

- `claude --help` timed out once under Python `subprocess.run(..., timeout=10)`, but completed under the Perl alarm wrapper above
- `claude agents --help` returned quickly
- `claude agents` and `claude plugin list --json` did not return before the 10-second alarm on this machine

## CLI Surface

`claude --help` shows built-in support for:

- interactive mode by default, with `-p/--print` for non-interactive runs
- custom agents via `--agents <json>`
- MCP config via `--mcp-config`
- tool allow/deny lists
- permission modes
- plugins
- git worktrees

The help output also exposes the control surface around those features:

- `--allowed-tools` / `--disallowed-tools`
- `--permission-mode` with `acceptEdits`, `bypassPermissions`, `default`, `dontAsk`, `plan`, `auto`
- `--plugin-dir`
- `-w/--worktree` and optional `--tmux`

Bundle-level CLI strings expose more surface than the top-level help text:

- plugin subcommands for validate/list/install/uninstall/enable/disable/update
- marketplace management under `claude plugin marketplace ...`
- `mcp`, `remote-control` / `rc`, `doctor`, `update`, and `install`
- a worktree + tmux fast path guarded by `--tmux` with `--worktree`

## Subagents

The cleanest evidence is in `sdk-tools.d.ts`.

`AgentInput` exposes:

- `description`
- `prompt`
- `subagent_type?: string`
- `model?: "sonnet" | "opus" | "haiku"`
- `run_in_background?: boolean`
- `name?: string`
- `team_name?: string`
- `mode?: "acceptEdits" | "bypassPermissions" | "default" | "dontAsk" | "plan"`
- `isolation?: "worktree"`

`AgentOutput` exposes two execution modes:

- synchronous completion with `content`, `totalToolUseCount`, `totalDurationMs`, `totalTokens`, `usage`
- async launch with `status: "async_launched"`, `agentId`, `description`, `prompt`, `outputFile`, and `canReadOutputFile`

What that means:

- subagents are first-class harness primitives
- they can run in the background
- they support explicit teammate naming and team context
- they can run in isolated git worktrees
- plan-mode permissions are part of the delegated-agent contract

Additional bundle-level signals:

- `task_progress` messages for subagent operations
- `agent_summary` timer logic
- subagent handoff review logic
- `allowedAgentTypes` filtering
- hook payloads that include `agent_id` and `agent_type`

Additional runtime evidence from local traces:

- transcript JSONL can persist `tool_name: "delegate_task"` with inputs like `subagent_type: "explore"` and `run_in_background: true`
- project session JSONL under `~/.claude/projects/.../*.jsonl` records `type: "agent_progress"` entries with stable `agentId` values
- those `agent_progress` records can include nested tool activity from the spawned worker, not just a final summary

This is real delegation support, not just prompt-level roleplay.

## Tool Surface

From `sdk-tools.d.ts`, the harness exposes first-class tools/interfaces for:

- `Agent`
- `Bash`
- `TaskOutput`
- `TaskStop`
- `FileRead`
- `FileEdit`
- `FileWrite`
- `Glob`
- `Grep`
- `NotebookEdit`
- `TodoWrite`
- `WebFetch`
- `WebSearch`
- `ListMcpResources`
- `ReadMcpResource`
- generic `Mcp`
- MCP subscriptions and polling
- `AskUserQuestion`
- `Config`
- `EnterWorktree`
- `ExitWorktree`
- `ExitPlanMode`

Notable harness properties:

- background execution exists for both shell commands and subagents
- MCP is integrated deeply enough to have list/read/subscribe/poll primitives
- worktree lifecycle is explicit
- todo management and user-question tools are typed, not ad hoc
- the shipped package vendors `ripgrep` and `tree-sitter-bash`, which suggests the file/search and shell-adjacent path uses bundled local helpers rather than only generic Node libraries

Important trace-level nuance:

- the typed SDK surface uses PascalCase names like `FileRead`, `FileEdit`, `WebFetch`, and `AskUserQuestion`
- persisted transcript records normalize these to lowercase runtime tool names such as `read`, `glob`, `grep`, and `bash`
- transcript logs therefore matter for learning the live harness vocabulary, not just the typed API names

Worktree support is stronger than a marketing bullet:

- `EnterWorktreeInput` can create a named worktree
- `ExitWorktreeInput` supports `keep` versus `remove`
- forced removal can require `discard_changes` when the worktree is dirty
- `EnterWorktreeOutput` returns `worktreePath` and optional branch
- `ExitWorktreeOutput` returns original cwd, worktree path, optional branch, optional tmux session, and discarded file/commit counts

That is strong evidence that worktree isolation is built into the harness contract rather than being prompt theater.

## Local State Surface

Claude Code also leaves a useful RE surface in `~/.claude/`:

- `plugins/config.json`
- `plugins/installed_plugins.json`
- `plugins/cache/...`
- `plans/`
- `sessions/`
- `todos/`
- `transcripts/`
- `projects/`
- `history.jsonl`
- `session-env/`
- `shell-snapshots/`

Useful observations from this machine:

- installed plugins are tracked with scope, install path, version, and optional git SHA
- plugin cache directories contain readable plugin source trees
- the large `todos/*.json` corpus matches the existence of a first-class `TodoWrite` tool and per-agent execution model
- transcript JSONL shows concrete `tool_use` / `tool_result` traces
- project JSONL appears to preserve richer multi-agent progress state than raw transcripts alone
- `history.jsonl` can expose user-visible subagent failures, model names, and delegation behavior

## How The Harness Gets Work Done

At a high level, Claude Code appears to combine:

- a main interactive session
- specialized or custom subagents
- a typed local tool layer for shell, file edits, search, planning, and web access
- MCP extension points
- optional worktree isolation for delegated tasks
- progress and handoff messaging across agent boundaries
- a persistent local trace layer in transcripts and project logs that records delegated activity

That makes the harness useful for:

- decomposition: bounded research or implementation tasks can be delegated
- parallelization: background tasks and async agents can keep running
- containment: worktree isolation reduces edit collisions
- observability: progress events and usage counters show what delegated work did

The clearest runtime pattern seen locally is:

- a parent session issues `delegate_task`
- Claude persists the child task in transcripts and project logs
- child work emits `agent_progress` messages and its own tool activity
- the parent can continue while background delegates run

## Are The Subagents And Tool Calls Useful?

Yes, materially useful inside the harness.

Why:

- the subagent API is richer than a simple “spawn another prompt”
- async launch plus output-file tracking gives a workable background model
- worktree isolation is exactly the kind of feature that makes delegated code edits safer
- tool allow/deny lists and permission modes make delegation constrainable
- MCP support gives the harness extension headroom beyond built-ins

Limits:

- because the implementation is closed and minified, safety and execution quality are harder to audit
- interface richness does not prove strong routing, prompting, or model selection
- local interface RE can show capability, not necessarily product-quality execution in every workflow

One important distinction:

- the public repo does appear useful for understanding Claude Code's plugin ecosystem and extension model
- it is not a good source for auditing the core runtime, because the shipped harness remains a proprietary minified bundle

## Good Judges

The strongest judges of usefulness would be:

- maintainers of other coding-agent harnesses
- heavy users who run long coding workflows and depend on delegation
- MCP/plugin authors
- evaluation researchers comparing throughput, edit quality, and coordination overhead

Likely judgment in context:

- harness engineers would probably rate this as a strong delegation surface because of async agents, typed outputs, plan-mode controls, and worktree isolation
- power users would likely value the background-agent and tool-filtering model because those are the features that make delegation practical
- extension authors would see MCP and plugin support as serious harness infrastructure
- reverse engineers would still classify it as proprietary because the shipped implementation is bundled and closed

## Bottom Line

Claude Code is not open-source, but it is locally inspectable enough to reverse engineer at the interface level.

The main useful findings are:

- proprietary minified Node CLI, not an auditable OSS source tree
- public repo exists, but current license is all-rights-reserved and the readable repo surface is mostly plugins/docs
- real harness-level subagents
- broad first-class tool surface
- meaningful support for MCP, worktrees, progress events, and delegated execution
- `~/.claude/` is a high-signal runtime artifact surface for plugins, plans, sessions, transcripts, project logs, and per-agent todos

## Proxy / Redirectability

Claude Code is redirectable enough to support a capture proxy.

The most useful hook is `ANTHROPIC_BASE_URL`:

- local debug output explicitly reacts to `ANTHROPIC_BASE_URL=http://127.0.0.1:18456`
- when that env var points at a non-first-party host, Claude logs:
  - `[ToolSearch:optimistic] disabled: ANTHROPIC_BASE_URL=http://127.0.0.1:18456 is not a first-party Anthropic host`
- with no listener on that port, Claude retries API requests and logs repeated `Connection error` failures

That is strong evidence that the main inference traffic can be redirected away from `https://api.anthropic.com` without patching the binary.

Other useful endpoint/config evidence in the bundle:

- bundled OAuth config includes a default `BASE_API_URL: "https://api.anthropic.com"`
- bundle text also embeds first-party API docs that state:
  - `Everything goes through POST /v1/messages`
  - supporting endpoints include `/v1/messages/batches`, `/v1/files`, and `/v1/models`
- `CLAUDE_CODE_CUSTOM_OAUTH_URL` exists, but it is restricted to an approved allowlist and is not a general-purpose arbitrary proxy hook

Practical implication:

- for Claude Code, the simplest proxy strategy is `ANTHROPIC_BASE_URL`, not OAuth URL rewriting
- if the proxy needs Claude's optimistic tool-search path, also set `ENABLE_TOOL_SEARCH=true`

## claude-code-proxy

Built repo: `claude-code-proxy/` at the repo root, with its own `.git/`.

Implementation notes:

- simple Python HTTP proxy that forwards to `https://api.anthropic.com`
- logs requests to `targets/claude-code/proxy-requests.jsonl`
- logs responses to `targets/claude-code/proxy-responses.jsonl`
- stores raw request/response bodies under `targets/claude-code/proxy-bodies/`
- now supports optional HTTPS listener mode via `--https-port --cert --key`
- forces `Accept-Encoding: identity` upstream by default so captured Anthropic responses stay readable in the body logs
- includes `claude-code-proxy/run_capture.sh`, which sources repo `.env`, waits for `/health`, and runs a safe non-interactive `claude -p` probe through `ANTHROPIC_BASE_URL`

## Capture Attempt In This Sandbox

I could verify the redirect hook, but not complete a real local capture on this machine.

What succeeded:

- a direct socket bind probe against `127.0.0.1:18441` failed with `PermissionError(1, 'Operation not permitted')`
- existing trace `targets/claude-code/redirect-debug.txt` shows Claude Code honoring `ANTHROPIC_BASE_URL` and then failing to connect when nothing is listening
- a cleaner repro with `HOME=$PWD/.tmp-claude-home` avoids most `~/.claude` write errors and confirms the same startup path

What blocked full capture:

- this sandbox does not allow opening a local listener on loopback, so `claude-code-proxy` cannot be run here end-to-end
- a fresh repo-local `HOME` is useful for clean redirect sanity checks, but Claude Code is not logged in there, so the headless probe stops before any authenticated request is sent
- for real traffic capture, keep the existing authenticated `HOME` by default; `claude-code-proxy/run_capture.sh` now does that unless `CLAUDE_HOME=...` is set explicitly

Artifacts produced:

- `targets/claude-code/redirect-debug.txt`
- `targets/claude-code/redirect-debug-local-home.txt`

Observed result:

- there are still no `proxy-requests.jsonl` / `proxy-responses.jsonl` files for Claude, because the local proxy listener could not be started in this environment

Recommended next run on a non-restricted host:

```sh
cd claude-code-proxy
./run_capture.sh
```
