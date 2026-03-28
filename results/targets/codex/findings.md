# Codex Findings

## Verdict

Codex is open-source.

The local install on this machine is the npm package `@openai/codex` version `0.117.0`. Its manifest declares:

- license: `Apache-2.0`
- repository: `git+https://github.com/openai/codex.git`
- source subdirectory: `codex-cli`

The installed npm package is not the full source tree. It ships a readable Node launcher plus an optional platform package containing the native executable, and the actual source lives in the public `openai/codex` repo.

The shipped README also describes the CLI as open-source and points to the public GitHub repo and releases.

Primary source URLs used for source-guided RE:

- https://github.com/openai/codex
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/spawn.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/request_user_input.rs

## Local Evidence

### Install layout

- `/opt/homebrew/bin/codex` is a symlink to `../lib/node_modules/@openai/codex/bin/codex.js`
- `bin/codex.js` is a readable Node launcher, not an opaque binary
- The launcher resolves an optional platform package such as `@openai/codex-darwin-arm64`
- That package contains the real native executable at:
  `/opt/homebrew/lib/node_modules/@openai/codex/node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/codex/codex`
- `bin/codex.js` maps the current target triple to a package like `@openai/codex-darwin-arm64`, resolves that package’s `vendor/<triple>/codex/codex`, and `spawn(...)`s the native binary

### Open-source proof points

- `/opt/homebrew/lib/node_modules/@openai/codex/package.json`
  confirms `license: "Apache-2.0"` and `repository.url: "git+https://github.com/openai/codex.git"`
- `/opt/homebrew/lib/node_modules/@openai/codex/README.md`
  links to GitHub releases, contributing docs, install/build docs, and states the repository is Apache-2.0 licensed
- The packaged native binary leaks repo-relative Rust paths via `strings`, e.g.:
  - `codex-rs/core/src/mcp_connection_manager.rs`
  - `codex-rs/app-server/src/dynamic_tools.rs`
  - `codex-rs/mcp-server/src/codex_tool_runner.rs`

That combination makes the open-source classification unambiguous. There was no need to treat it as proprietary.

## Harness Architecture

### Front door

`codex --help` shows these top-level modes:

- `exec`: non-interactive run
- `review`: non-interactive code review
- `mcp`: manage external MCP servers
- `mcp-server`: run Codex as an MCP server
- `app-server`: app-server tooling
- `app`: desktop app entrypoint
- `sandbox`, `debug`, `apply`, `resume`, `fork`, `cloud`, `features`

This is a local agent harness with several execution surfaces rather than a single chat CLI.

### Tool calls

The tool story is clear from help, config, feature flags, strings, and the public source:

- MCP is a first-class capability:
  - `codex mcp list|get|add|remove|login|logout`
  - `codex mcp-server` exposes Codex itself as an MCP server
- In the public repo, `codex-rs/core/src/tools/spec.rs` defines first-class tool schemas for:
  - `exec_command`
  - `write_stdin`
  - `spawn_agent`
  - `send_input`
  - `wait_agent`
  - `close_agent`
  - `request_user_input`
  - `tool_search`
  - `tool_suggest`
- The shipped binary also exposes evidence of the next layer of that contract:
  - `core/src/tools/handlers/unified_exec.rs`
  - `core/src/tools/handlers/multi_agents_v2/spawn.rs`
  - `core/src/tools/handlers/multi_agents_v2/list_agents.rs`
  - `core/src/tools/handlers/multi_agents_v2/send_message.rs`
  - `core/src/tools/handlers/multi_agents_v2/wait.rs`
- `exec_command` is a real process-control primitive rather than a toy one-shot shell call. Its schema supports:
  - working directory selection
  - explicit shell selection
  - PTY allocation
  - incremental output via `yield_time_ms`
  - long-running sessions via `session_id`, continued with `write_stdin`
  - approval-oriented escalation parameters when exec permission approvals are enabled
- The binary contains explicit `tools/list` and `tools/call` strings
- The binary also contains modules and messages for:
  - `dynamic_tools`
  - `DynamicToolCallRequest`
  - `DynamicToolResponse`
  - approval flows for exec commands, patches, permissions, and file changes
- Feature flags show these tool-adjacent capabilities enabled or available:
  - `apps` stable `true`
  - `plugins` stable `true`
  - `shell_tool` stable `true`
  - `unified_exec` stable `true`
  - `tool_call_mcp_elicitation` stable `true`
  - `tool_suggest` stable `true`
  - `apply_patch_freeform` under development `true`
- The non-interactive `exec` front door is also stronger than a bare "run once" wrapper. `codex exec --help` exposes:
  - `--json` for JSONL event output
  - `--output-schema` for structured final responses
  - `--output-last-message` for capture-friendly automation
  - `--ephemeral` to avoid persisting session files

Interpretation: Codex’s harness is built around tool invocation with explicit approval/sandbox layers, resumable command execution, and MCP-based extensibility for external tools and plugins.

## Subagents / Multi-Agent Behavior

Codex appears to have real collaboration/subagent support, but it is only partially user-facing in the current CLI surface.

### Evidence

- `codex features list` reports:
  - `multi_agent` stable `true`
  - `multi_agent_v2` under development `false`
  - `child_agents_md` under development `false`
  - `enable_fanout` under development `false`
- The local `~/.codex/config.toml` also has:
  - `[features]`
  - `multi_agent = true`
- `strings` on the native binary exposed collaboration protocol/event names:
  - `CollabAgentSpawnBegin`
  - `CollabAgentSpawnEnd`
  - `CollabInteraction`
  - `WaitingOnCollaborator`
  - `ResumeThread`
  - `CloseThread`
- The public repo contains an actual multi-agent spawn handler in
  `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs`
- That handler:
  - accepts structured `spawn_agent` inputs including `message`, `items`, `agent_type`, `model`, `reasoning_effort`, and `fork_context`
  - computes child depth from the current session source
  - enforces an `agent_max_depth` limit before spawning
  - emits spawn-begin and spawn-end collaboration events
  - calls `spawn_agent_with_metadata(...)`
- The binary also leaks parallel v2 handler paths for `spawn`, `assign_task`, `send_message`, `wait`, `close_agent`, and `list_agents`, so Codex is not limited to a single experimental one-off spawn primitive

### What this means

- Multi-agent execution is not just marketing. It exists in the shipped code and is feature-gated.
- The current public CLI does not expose a simple top-level `subagent` or `spawn` command.
- The collaboration machinery is driven inside sessions and tool handlers rather than a standalone shell command.
- `child_agents_md` being present but disabled suggests the harness is evolving conventions/instructions for delegated child agents.
- The source and binary both restrict `request_user_input` by mode. The shipped binary contains strings such as `request_user_input is not supported in exec mode` and `request_user_input is only supported on api v2`, which suggests the parent/child split is deliberate rather than accidental.

## Usefulness

### Tool calls

These are clearly useful in this harness, and the source backs that up.

- MCP support makes the agent extensible without hardcoding every integration into the CLI
- Sandboxing and approval flows let the same harness operate in both low-friction and safer review modes
- `exec_command` plus `write_stdin` give the harness a practical long-running process model instead of one-shot shell calls
- `exec`, `review`, `apply`, and MCP server mode give the tool system multiple practical surfaces: local automation, CI-ish runs, reviews, and external integration
- `codex exec --json`, `--output-schema`, and `--output-last-message` make the harness much more usable for benchmark/eval runners and wrapper tooling than a TUI-only agent would be

### Subagents

Useful and clearly real, but probably less mature than the base tool system.

- The feature is present and enabled, so Codex itself believes multi-agent execution is worth shipping
- The source-visible `spawn_agent` and `wait_agent` handlers make delegation more than a hidden implementation detail
- The absence of a clean user-facing command suggests the ergonomics or product framing are still in motion
- `multi_agent_v2`, `child_agents_md`, and `enable_fanout` being non-stable or disabled suggests the collaboration layer is still being refined

My read: tool calls are core and proven; subagents are real, useful for bounded parallel side work, but still somewhat productized behind the scenes.

## Good Judges

The best judges of usefulness here would be:

- Maintainers of agent harnesses and coding CLIs
  - They can judge whether MCP, approvals, patch workflows, and multi-agent fanout are architecturally sound
- Power users doing real repo work every day
  - They can judge whether multi-agent behavior saves time or just adds orchestration overhead
- MCP/plugin authors
  - They can judge whether Codex’s tool plumbing is pleasant to integrate with
- People building agent evaluation harnesses
  - They can judge whether spawn/wait delegation actually improves throughput, quality, and observability on realistic coding tasks
  - They are also the right audience to judge whether `exec --json` and output-schema support make the harness composable enough for repeatable experiments

## What Those Judges Would Likely Say

### Harness maintainers

They would likely say the tool architecture is strong:

- MCP as a first-class primitive is the right call
- approvals and sandbox policy are necessary for a real coding harness
- exposing Codex itself as an MCP server is a useful inversion point

They would probably also say the multi-agent UX is not fully settled yet, because the capability is stronger in the internal tool contract than in the main CLI contract.

### Power users

They would likely rate the tool system as immediately valuable because it changes what the agent can actually do in a repo.

They would be more mixed on subagents:

- positive if delegation speeds up broad repo analysis or parallel work
- skeptical if it adds latency, complexity, or unclear provenance
- cautiously positive if the delegated work stays narrow, because Codex has explicit spawn/wait/send primitives instead of vague "agentic" prompting

### MCP and plugin authors

They would likely view the harness favorably because the product is explicitly designed to consume and expose MCP tools, not merely call a fixed built-in toolset.

### Evaluation and infra engineers

They would likely say Codex is unusually inspectable for an agent harness because:

- the tool schema is explicit and versionable in source
- collaboration emits structured begin/end/wait events
- feature flags make it possible to separate shipped behavior from in-flight experiments

They would probably still want benchmarks before over-crediting subagents, because the code proves the mechanism exists but not that it always improves throughput on real tasks.

## Practical RE Notes

- On this machine, GNU `timeout` is missing. A portable safe wrapper is:
  `perl -e 'alarm shift; exec @ARGV' 10 <cmd> ...`
- `codex --help`, `codex features list`, `codex exec --help`, `codex mcp --help`, and `codex -V` all returned under a 10-second wrapper on this machine.
- When probing through an async exec harness, an empty first read is not evidence of a hang. My first 1-second poll for `codex exec --help` and `codex mcp --help` returned nothing, but both commands completed successfully once I waited past the full timeout window.
- `strings` was high signal for the native executable even though the project is open-source, because it revealed internal module names and collaboration/tool protocol concepts quickly.
- For Codex specifically, the clearest source files were:
  - `codex-rs/core/src/tools/spec.rs`
  - `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs`
  - `codex-rs/core/src/tools/handlers/unified_exec.rs`
  - `codex-rs/core/src/tools/handlers/request_user_input.rs`

## Proxying / Transport

- Codex is redirectable with the config key `openai_base_url`. The native binary leaks both the key itself and a deprecation string indicating an older setting was replaced by `openai_base_url`.
- A controlled non-interactive probe confirmed the override is live:
  - command shape:
    `perl -e 'alarm shift; exec @ARGV' 20 codex exec --skip-git-repo-check --sandbox read-only --json -c 'openai_base_url="http://127.0.0.1:18456/v1"' 'Say hello in one sentence.'`
  - Codex then attempted to contact the overridden local endpoint instead of the default OpenAI host
- The important transport detail is that current Codex does not only hit plain HTTP. On `0.117.0`, the redirected run emitted:
  - `failed to connect to websocket ... url: ws://127.0.0.1:18456/v1/responses`
  - retry messages mentioning `error sending request for url (http://127.0.0.1:18456/v1/responses)`
- Interpretation:
  - the harness uses `/v1/responses`
  - WebSocket support matters for a useful Codex capture proxy
  - HTTP-only forwarding is insufficient if the goal is to observe realistic live traffic

## codex-proxy

- Built repo-root `codex-proxy/` and initialized it as a standalone git repo
- The proxy implementation is in `codex-proxy/server.py`
- Added `codex-proxy/run_capture.sh` as the reproducible outside-sandbox runner:
  - sources repo-root `.env`
  - starts `server.py`
  - runs `codex exec` through `-c 'openai_base_url="http://127.0.0.1:18456/v1"'`
  - leaves artifacts under `targets/codex/`
- Relative to the simpler `amp-proxy` reference, the Codex proxy now supports:
  - normal HTTP reverse proxying with request/response body capture
  - WebSocket upgrade forwarding
  - best-effort WebSocket frame/message logging in both directions
  - optional HTTPS listener mode via `--cert-file` plus `--key-file`
  - sanitized header logging plus raw body/frame dumps under `targets/codex/`
- The proxy repo has offline validation coverage:
  - `python3 -m unittest codex-proxy/test_server.py`
  - current result in this workspace: `Ran 7 tests ... OK`
- The README documents the redirection method with `openai_base_url`, the wrapper script, and the artifact paths

## Capture Status

- Full live capture was blocked in this sandbox because local TCP bind/connect is restricted here:
  - starting `python3 server.py` in `codex-proxy/` failed on `bind()` with `PermissionError: [Errno 1] Operation not permitted`
  - a minimal direct probe `python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0))'` failed with the same error, so this is a sandbox policy issue rather than a proxy bug
  - the redirected Codex run also failed to connect to `127.0.0.1:18456` with `Operation not permitted (os error 1)` rather than a normal `connection refused`
- So the transport path is proven and the proxy is implemented, but an actual end-to-end capture must be run outside this restricted harness environment.
- The intended outside-sandbox replay path is now explicit:
  - `cd codex-proxy && ./run_capture.sh 'Say hello in one sentence.'`
  - inspect `targets/codex/proxy-requests.jsonl` plus `targets/codex/proxy-bodies/`

## Verification Update (2026-03-28)

- Re-ran `perl -e 'alarm shift; exec @ARGV' 10 codex -V` and confirmed the local target is still `codex-cli 0.117.0`
- Re-ran the redirect probe:
  `perl -e 'alarm shift; exec @ARGV' 20 codex exec --skip-git-repo-check --sandbox read-only --json -c 'openai_base_url="http://127.0.0.1:18456/v1"' 'Say hello in one sentence.'`
- Re-ran `perl -e 'alarm shift; exec @ARGV' 10 codex features list` and noted an important mismatch:
  - `responses_websockets` and `responses_websockets_v2` are listed as `removed false`
  - the redirected runtime still actively attempts `ws://127.0.0.1:18456/v1/responses`
- Current observed sequence is:
  - repeated WebSocket connection failures to `ws://127.0.0.1:18456/v1/responses`
  - then reconnect/error messages for `http://127.0.0.1:18456/v1/responses`
- So the earlier transport conclusion still holds on the current local install:
  - `openai_base_url` really does redirect the Responses API traffic
  - Codex is WebSocket-first on this path, with HTTP fallback/retry behavior
  - a useful interception proxy must handle both
  - feature-flag listings are useful hints, but they do not fully describe live transport behavior on their own
- Re-ran offline proxy validation:
  - `cd codex-proxy && python3 -m unittest test_server.py`
  - result: `Ran 7 tests ... OK`
