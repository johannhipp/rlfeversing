## Continue

Status: open-source

## Evidence

- Public GitHub repo: `continuedev/continue`
- License: Apache 2.0 in the root README
- `extensions/cli/package.json` declares `license: Apache-2.0` and repository `https://github.com/continuedev/continue.git`
- The root README states that AI checks are powered by the open-source Continue CLI (`cn`)
- The relevant coding-agent harness is the CLI package under `extensions/cli/`, not the whole monorepo in the abstract

## What The Harness Is

Continue currently exposes an open-source coding-agent CLI called `cn` inside the monorepo at `extensions/cli/`.

That distinction matters because the top-level repo also contains IDE/editor integrations and other product surfaces. For reverse-engineering the coding harness itself, the CLI package is the right center of gravity.

Relevant files:

- `README.md`
- `extensions/cli/README.md`
- `extensions/cli/package.json`
- `extensions/cli/src/tools/index.tsx`
- `extensions/cli/src/stream/handleToolCalls.ts`
- `extensions/cli/src/stream/streamChatResponse.helpers.ts`
- `extensions/cli/src/subagent/executor.ts`
- `extensions/cli/src/subagent/get-agents.ts`
- `extensions/cli/src/tools/subagent.ts`
- `extensions/cli/src/services/ModelService.ts`

## Subagents

Continue does have subagent support in the CLI, but it is not the core execution model and it is beta-gated.

Observed behavior:

- The `Subagent` tool is only added when `isBetaSubagentToolEnabled()` is true in `extensions/cli/src/tools/index.tsx`.
- Available subagents are assistant models whose config includes:
  - a `name`
  - the role `subagent`
  - a `chatOptions.baseSystemMessage`
- Those models are discovered by `ModelService.getSubagentModels()` in `extensions/cli/src/services/ModelService.ts`.
- The tool description is generated dynamically from the configured subagent models in `extensions/cli/src/subagent/get-agents.ts`.
- Invoking the tool calls `executeSubAgent()` from `extensions/cli/src/subagent/executor.ts`.
- The wrapper in `extensions/cli/src/tools/subagent.ts` validates `subagent_name`, emits a spawn preview during preprocessing, and streams child output back through the parent tool result while the child is still running.

Execution details:

- A subagent is run as a child chat session using `streamChatResponse(...)`.
- Continue temporarily overrides the system prompt for that run with the selected subagent's base system message.
- It also temporarily forces tool permissions to `allow` for all tools during subagent execution.
- Partial subagent output is streamed back into the parent tool call via `chatHistory.addToolResult(..., "calling")`.
- Final output is returned to the parent agent with:
  - the subagent response
  - `<task_metadata>`
  - `status: completed|failed`
  - `</task_metadata>`

Assessment:

- This is a real subagent mechanism, not just a prompt label.
- It is useful for role-specialization when the assistant config actually defines multiple named subagent models.
- It is less mature than Codex-style delegation. There is no visible scheduler, no ownership model, no worktree isolation, no explicit parallel-worker orchestration, and permissions are currently widened with a TODO comment.

## Tool Calling

Continue uses tool calling as a first-class part of the CLI loop.

Observed behavior:

- `streamChatResponse.ts` sends tool definitions to the model as chat-completion function tools.
- The request tool list is rebuilt each iteration from built-ins, model capability checks, beta flags, headless state, and MCP tools.
- Tool calls are streamed back, collected, executed, and then fed back into the conversation loop.
- The loop continues while valid tool calls are present.
- Permission checks are performed in order, then approved tool calls in the same batch are executed in parallel by `executeStreamedToolCalls(...)`.

Built-in tools registered in the CLI include:

- `Read`
- `WriteFile`
- `ListFiles`
- `Bash`
- `Fetch`
- `Search`
- `WriteChecklist`
- `AskQuestion`
- `ViewDiff`
- `ReportFailure`
- `UploadArtifact`
- `PromptFile`
- `Edit` or `MultiEdit` depending on model capability
- `Exit` in headless mode
- `Subagent` behind the beta flag
- `Skills`
- MCP tools from connected servers

Notable implementation details:

- `Bash` uses the user's login shell, streams stdout/stderr, supports background jobs, and truncates output to avoid context blowups.
- `Search` prefers `rg` and falls back to `grep/findstr`.
- `Read` enforces file-size limits and tracks which files were read.
- `MultiEdit` is preferred for "capable" models and requires the file to have been read in-session first.
- MCP tools are converted into Continue tools at runtime and executed through `services.mcp?.runTool(...)`.
- Tools receive `parallelToolCallCount`, and high-output tools like `Read` and `Bash` reduce their output budgets when several tool calls are executed together.

Assessment:

- Tool use is the main way Continue gets real work done.
- The toolset is practical for codebase navigation and edit loops.
- The harness is closer to a conventional single-agent tool-using CLI with parallel tool batches than to a deeply agentic multi-worker harness.

## Are The Subagents And Tools Useful?

Tools: yes, clearly.

- The tool surface is broad enough for normal coding-agent tasks.
- The loop architecture is coherent: request tools, stream tool calls, execute, append results, continue.
- The design around `Read` + `MultiEdit` is sensible for controlled file editing.
- Parallel execution of approved tool-call batches is genuinely useful for search/read-heavy reconnaissance, even if the harness does not expose a richer planner/worker architecture.

Subagents: conditionally useful.

- Useful when the operator supplies multiple role-specific subagent models.
- Less useful out of the box if the config only defines one main chat model or if the beta flag is off.
- The current implementation looks early-stage because permissions are temporarily set to allow-all and the source still contains TODOs around richer UX and permission prompting.

## Who Would Be A Good Judge?

Best judges:

- Maintainers of coding-agent harnesses who care about execution semantics, not demos
- Power users who run headless agents in CI and large repos
- Benchmark and evals people studying whether a harness meaningfully improves task completion rather than just exposing more knobs
- Security-conscious tool and platform maintainers who care about permission boundaries inside delegated execution

What they would likely say:

- Positive: the tool loop is solid and the CLI is meaningfully agentic, especially with MCP integration and headless support.
- Positive: the harness is stronger than a toy function-calling wrapper because it supports permissioned tool use, MCP passthrough, and parallel execution of approved tool batches.
- Positive: subagents are a genuine capability, because the harness can discover specialized models and launch them as child sessions.
- Skeptical: the subagent system is not yet a major differentiator because it is beta-gated, config-dependent, and operationally simple.
- Skeptical: `allow all tools for now` inside subagent execution weakens the safety story and suggests the delegation layer is not yet fully productized.
- Net: useful harness, especially for tool use; subagents are promising but not yet the strongest part of the system.

## Local Runtime Notes

- `cn` was not installed in this workspace host, so local binary inspection was not possible here.
- GNU `timeout` is also not installed on this host, so safe non-interactive probing would need a substitute such as `python3` with `subprocess.run(..., timeout=10)`.

## Proxy

A dedicated reverse proxy repo now exists at `continue-proxy/` at the repository root, with its own `.git` directory as requested.

Contents:

- `continue-proxy/server.py`: HTTP reverse proxy with optional HTTPS listener, upstream forwarding, request/response body capture, per-exchange JSONL logging, and header/query redaction by default
- `continue-proxy/run_capture.sh`: project runner that sources `.env`, writes a Continue config, starts the proxy, and runs `cn --config ... -p ...` through a hard timeout
- `continue-proxy/test_server.py`: offline unit coverage for path joining, redaction, forwarded-header rewriting, and stubbed OpenAI-compatible `/responses` plus `/chat/completions` payload shapes
- Forwarded upstream requests now force `Accept-Encoding: identity` so captured provider JSON/SSE bodies stay readable rather than getting logged as compressed blobs

Offline verification completed in this workspace:

- `python3 -m unittest discover -s continue-proxy -p 'test_server.py'` passed (`10` tests)
- `python3 continue-proxy/server.py --help` succeeded
- `sh -n continue-proxy/run_capture.sh` and `bash -n continue-proxy/run_capture.sh` both succeeded
- Fresh rerun on `2026-03-28` reconfirmed the same state:
  - `command -v cn` returned nothing on this host
  - `perl -e 'alarm shift; exec @ARGV' 10 ./continue-proxy/run_capture.sh "Say hello"` exited immediately with `continue CLI command not found: cn`
  - a direct Python socket bind probe still failed with `PermissionError: [Errno 1] Operation not permitted` on `127.0.0.1:18431`
- `run_capture.sh` now parses multi-word launchers from `CONTINUE_CMD` and `CONTINUE_CMD_ARGS`, so outside this sandbox it can drive Continue even when the CLI is invoked via package-manager prefixes such as `npx -y @continuedev/cli` rather than a bare `cn` binary
- `continue-proxy/run_capture.sh` now sources `.env` before any command checks and polls the proxy `/health` endpoint before launching `cn`, which makes startup failures easier to distinguish from later CLI/provider failures
- `continue-proxy/server.py` can stub both the OpenAI `Responses` API and legacy `chat/completions` shapes in addition to forwarding to a real upstream, which makes the proxy usable both for offline sanity checks and for live provider interception
- A direct Python socket probe still fails with `PermissionError: [Errno 1] Operation not permitted` on `bind(('127.0.0.1', 18431))`, confirming the loopback-listener blocker is environmental rather than proxy-specific

Redirect mechanism:

- Continue's OpenAI-provider model config supports `apiBase`
- The runner writes `targets/continue/proxy-config.yaml` with:
  - `provider: openai`
  - `model: gpt-4o-mini` by default
  - `apiBase: http://127.0.0.1:18431/v1`
- That means Continue can be redirected at the provider layer even though there is no proprietary Continue backend to impersonate

Artifacts written by the proxy flow:

- `targets/continue/proxy-exchanges.jsonl`
- `targets/continue/proxy-requests/*.bin`
- `targets/continue/proxy-responses/*.bin`
- `targets/continue/proxy-server.stdout.log`
- `targets/continue/proxy-server.stderr.log`
- `targets/continue/continue.stdout.log`
- `targets/continue/continue.stderr.log`

Current blocker status on this host:

- `cn` is not installed on PATH, so the runner cannot drive a real Continue CLI session here
- A direct runner probe (`perl -e 'alarm shift; exec @ARGV' 10 ./continue-proxy/run_capture.sh "Say hello"`) fails immediately with `continue CLI command not found: cn`
- This sandbox also rejects loopback listeners with `PermissionError: [Errno 1] Operation not permitted`, so even with `cn` present, live interception cannot be completed inside this environment
- As a result, the proxy repo is implemented and the redirect path is documented, but no real Continue traffic was captured in this sandbox run
