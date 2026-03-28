# Knowledge Base

Central repository of all reverse-engineering findings across all target agents.

## Index

<!-- Auto-maintained by agents. Each entry links to detailed findings. -->
- `amp`: closed-source/publicly distributed Bun-compiled CLI with documented subagents (`Task`, `oracle`, `Librarian`) and a redirectable backend via `amp.url`. See `targets/amp/findings.md`.

- `claude-code`: `targets/claude-code/findings.md`
- `codex`: `targets/codex/findings.md`
- `continue`: `targets/continue/findings.md`
- `opencode`: `targets/opencode/findings.md`
- `aider`: `targets/aider/findings.md`

- `factory`: `targets/factory/findings.md`
- `cursor`: `targets/cursor/findings.md`
- `windsurf`: `targets/windsurf/findings.md`
- `cline`: `targets/cline/findings.md`

## Cross-Agent Patterns

<!-- Patterns observed across multiple agents go here. -->
- Public docs plus package metadata can be enough to classify a harness as closed-source even when the binary is locally installed: look for npm license metadata, absence of a public repo, and compiled single-file executables.
- Closed-source harnesses with rich local transcript stores can often be reverse-engineered further by mining their own conversation/state JSON. Those files may expose actual tool names, model IDs, delegation primitives, thread-memory tools, and persisted tool artifacts even when the shipped runtime is opaque.

- Open-source agent harnesses often reveal almost everything important from three places: the main README, the tool registry, and the chat or execution loop. Delegation or subagent support is usually isolated in its own module and can be confirmed quickly from there.
- Open-source harnesses may still differ materially in how "tool calling" works. Some expose prompt-defined tool contracts directly in docs/source instead of relying purely on provider-native function calling; that distinction matters when judging how portable or robust the harness is across models/providers.
- Closed-source npm agent CLIs can still expose a high-value RE surface locally through package metadata, CLI help, and shipped TypeScript declaration files, even when the implementation itself is a minified bundle.
- Packaging can obscure openness. Codex ships a packaged native binary, but the local npm metadata, readable launcher script, bundled README, and repo links were enough to classify it as open-source before deeper reversing.
- Bun-packaged agent CLIs can also be classified from local artifacts alone. Adjacent SDK/plugin typings, cached prompts, and package licenses may reveal more about subagents and tools than the compiled binary itself.
- Mode switches are not automatically subagents. If an open-source harness routes specialized roles through one factory/clone path and reuses the same IO, history, and file context inside one process, treat that as in-process handoff rather than true delegated workers.

### Factory

- Factory exposes a public repo/docs/plugin marketplace, but the practical harness is a shipped proprietary CLI binary (`droid`) downloaded from Factory infrastructure.
- Factory’s subagents are called **custom droids** and are markdown files with YAML frontmatter that the parent agent can invoke through a Task tool using `subagent_type`.
- Factory persists unusually rich local state in `~/.factory/`, including session transcripts, tool result artifacts, snapshot manifests, plugin metadata, and delegated droid definitions. This is a strong RE surface even when the runtime itself is closed.
- Factory session JSONL files persist raw `tool_use` / `tool_result` exchanges, so you can often recover the actual tool taxonomy and execution pattern from disk without successfully driving the live CLI.
- The closed `droid` bundle leaks structured protocol evidence in `strings`, including orchestrator/worker roles, autonomy permission actions, and session update event types such as `tool_call_update` and `agent_thought_chunk`.
- Cursor also exposes a public-facing repo without the real harness source. Its installer downloads a prebuilt `cursor-agent` tarball, so the practical harness is closed-source even though public docs are extensive.
- Cursor’s installed CLI package is locally inspectable but still not open-source: the shipped package is a private bundled runtime (`@anysphere/agent-cli-runtime`) with a shell launcher, bundled Node, webpacked `index.js`, and chunk files rather than a public source repository.
- Cursor’s shipped local harness contains first-class task/subagent plumbing, not just marketing claims:
  - `task-tool` and `running-agents-ui` modules refer to `Subagent task`, `subagentType`, `subagentState`, and background subagent completion
  - the running-agent UI maps subagent states to concrete tool actions like reading, editing, listing, grepping, globbing, and shell execution
- Cursor’s local bundle exposes a broad real tool surface through dedicated modules for read, edit, delete, ls, glob, grep, shell, shell-stdin, web fetch, web search, MCP tools/resources, todo updates, and plan creation.
- Cursor has a distinct background-agent path in both bundle and user state:
  - bundle modules for `background-composer-*` and `use-send-to-background`
  - local workspace URIs under `vscode-remote://background-composer+...`
- Cursor also has local worker infrastructure: a hidden `worker-server` command plus `worker-manager.ts` that spawns workers over a socket/log path with JSON worker options.

### Windsurf

- Windsurf is a proprietary VS Code-fork IDE distributed as downloadable binaries, with public docs but no public repository for the main editor/harness.
- On this machine there was no local `windsurf` CLI, no `Windsurf.app`, and no `~/.codeium/windsurf` or `~/.windsurf` state directory, so binary-level RE was blocked by artifact absence rather than by an interactive-probe failure.
- Public docs expose a multi-agent shape even without source:
  - a specialized planning agent for long-horizon todo refinement
  - a specialized retrieval subagent called Fast Context
  - a main Cascade execution/chat model with tool calling
- Fast Context is documented as using a restricted tool set (`grep`, `read`, `glob`) with up to 8 parallel tool calls per turn over at most 4 turns.
- Cascade itself is documented as supporting up to 20 tool calls per prompt, plus terminal, web/docs search, MCP, workflows, skills, memories/rules, and AGENTS.md ingestion.
- Windsurf’s hooks docs expose the harness action surface unusually clearly for a closed product: file reads/writes, terminal commands, MCP calls, prompt interception, response logging, and post-worktree setup all have named hook events, and pre-hooks can block execution.
- Those same hooks docs also expose a concrete local observability surface:
  - `post_cascade_response_with_transcript` writes JSONL transcripts to `~/.windsurf/transcripts/{trajectory_id}.jsonl`
  - documented transcript step types include `user_input`, `planner_response`, and `code_action`
  - `post_cascade_response` summarizes planner/tool activity and triggered rules
- Workflows are manual-only trajectory scripts; skills use progressive disclosure; AGENTS.md is fed into the same rules engine with root always-on and subdirectory auto-glob scoping.
- Exafunction’s public GitHub org mostly shows integrations and adjacent tooling (`windsurf.vim`, `windsurf.nvim`, `WindsurfVisualStudio`, `windsurf-demo`, `codeium`), which strengthens the inference that the editor harness itself is closed.
- Windsurf’s getting-started flow reinforces the packaged-product model: the docs tell users to install a `windsurf` command into PATH from inside the editor, which is consistent with a desktop-app CLI shim rather than a separately published open harness.
- A fast local triage confirmed the closed-source path was blocked here by artifact absence, not by a failed probe: no `windsurf` binary on PATH, no `Windsurf.app`, and no `~/.codeium/windsurf` / `~/.windsurf` state roots were present.

## Techniques That Work

<!-- Proven techniques get promoted here before being added to skill.md -->
- The GitHub connector may reject `raw.githubusercontent.com` URLs even when the repo is public. In that case, fetch primary-source files via repo/path/ref APIs instead of raw URLs.
- For Amp specifically, inspect the binary with `strings` before spending time on CLI help. In this environment even `amp login --help` and `amp permissions list --builtin` timed out, but the binary still exposed modes, flags, and hidden runtime options.
- For Amp specifically, retry top-level help with a different hard-timeout wrapper before giving up on CLI probing. `amp --help` and `amp version` succeeded under `perl -e 'alarm shift; exec @ARGV' 10 ...` even though several earlier probes looked hung.
- Check user config paths before deeper reversing. Amp stores settings in `~/.config/amp/settings.json`, and the `amp.url` setting can redirect traffic to a local proxy.
- For Amp specifically, mine `~/.local/share/amp/threads/*.json` and `~/.amp/file-changes/` early. They expose real tool names (`Task`, `oracle`, `read_thread`, `find_thread`, `shell_command`, `Read`, `Bash`, `Grep`, GitHub/web tools), model metadata, and persisted per-tool artifacts.

- When a target is public/open-source but local cloning is blocked, fetch primary-source files directly from GitHub and focus on:
  - repo README and license for classification
  - tool registry for capabilities
  - stream or execution loop for how tool calls are handled
  - subagent or delegation modules for worker semantics
- For open-source Python harnesses with many strategy classes, inspect the exported class list in `__init__.py` before over-weighting individual modules. That quickly separates supported modes from deprecated experiments.
- If the environment lacks GNU `timeout`, use a language runtime timeout wrapper for safe binary probing instead of dropping the guardrail.
- For npm-distributed proprietary CLIs, inspect `package.json`, `LICENSE.md`, the installed entrypoint, and any shipped `.d.ts` files before deeper reversing. This can reveal open-vs-closed status, tool schemas, and subagent contracts quickly.
- For Bun/TypeScript agent CLIs, inspect shipped `.d.ts` files before spending too long on `strings`. The type surface often exposes session APIs, PTY support, agent/subtask message parts, permission rules, and plugin hook names directly.
- Cached instruction files in app state directories can be high-signal evidence. Opencode's local cache explicitly self-identifies the harness as open-source.
- Read installer scripts for closed-source targets before hunting binaries. Cursor's installer exposed the exact package URL pattern, version pin, install path, and executable names.
- For closed-source agents with local transcript history, inspect persisted JSONL before deeper binary reversing. Factory exposed real `tool_use` / `tool_result` records there, which were more concrete than the marketing/docs surface.
- When binary fetch is blocked, product/docs pages can still reveal harness shape: Cursor's public materials exposed tool families, headless CLI modes, remote background agents, and parallel subagent claims.
- For npm/brew-installed open-source CLIs, inspect the local package first. Codex exposed license, repository, launcher behavior, and platform package layout immediately from the installed files.
- If a target has multiple public repos across org renames or rewrites, verify which repo matches the shipped artifact before drawing architecture conclusions. Opencode exposed an older archived Go repo and a newer live TypeScript/Bun repo; only the latter matched the installed harness.
- `strings` on shipped native binaries is still useful for open-source targets. Codex leaked internal Rust paths, collaboration events, MCP modules, and dynamic tool call identifiers that confirmed real harness behavior quickly.
- Once a target is confirmed open-source, switch from artifact-only RE to source-guided RE quickly. For Codex, `tools/spec.rs` and the handler files gave a cleaner picture of tool and subagent semantics than more binary scraping.
- For closed-source IDE agents, product docs can still reveal the harness shape: Windsurf exposed planning/retrieval specialization, local page reads, MCP limits, approval modes for terminal execution, and concrete config/customization paths.
- Hook documentation is especially high-signal for closed IDE harnesses. Named pre/post events around reads, writes, commands, MCP calls, prompts, and worktree setup reveal the real action surface and policy boundaries even without source.
- For closed IDE agents, do a quick absence triage before planning binary RE: check the PATH launcher, the obvious app bundle, and vendor state roots. If all three are missing, pivot to docs/hooks/state-schema RE instead of broad filesystem spelunking.
- Docs for instruction-layering features such as `AGENTS.md`, rules, skills, and workflows are also high-signal. They reveal prompt scoping, progressive disclosure, and whether procedures are automatic or strictly user-invoked.
- For bundled JS/webpack CLIs, extract internal module paths first. The module map often reveals the harness topology immediately: commands, headless mode, task/subagent UI, MCP support, background-agent flows, worker daemons, and protocol layers.

## Continue

- Classification: open-source
- Repo: `continuedev/continue`
- License: Apache 2.0
- Main harness examined: `extensions/cli/`
- Repo-scope caveat: Continue is a broader monorepo, but the coding-agent harness is specifically the `extensions/cli/` package. Root-level docs alone are not enough to judge the harness shape.
- CLI package manifest is public and explicit: `extensions/cli/package.json` declares `@continuedev/cli`, `license: Apache-2.0`, and the GitHub repository URL
- Tool calling is first-class in the CLI loop and includes built-ins plus MCP tool passthrough.
- The main loop rebuilds the tool list each iteration, streams function-tool calls from the model, executes them, appends results, and continues until no more valid tool calls remain.
- Continue queues permission checks sequentially, then executes approved tool calls in parallel within a single batch; it passes `parallelToolCallCount` into tools so high-output tools can reduce output limits.
- Subagents exist, but are beta-gated and driven by assistant model config with `roles` containing `subagent` and a base system message.
- The `Subagent` tool description and accepted agent names are generated dynamically from configured subagent models.
- Subagent execution runs a child `streamChatResponse(...)` session, temporarily overrides the system prompt, streams child output back through the parent tool result, and currently widens tool permissions to allow-all during the child run.
- Current built-in CLI tools extend beyond the basic read/write/search loop and include review/reporting helpers such as `ViewDiff`, `ReportFailure`, `UploadArtifact`, and `PromptFile`, alongside Bash, file tools, checklisting, skills, and MCP passthrough.
- Practical take: tool use looks mature and central; subagents are real but appear less mature and less central than the core tool loop.
- Continue is redirectable at the provider layer via model `apiBase`, so proxying does not require a proprietary backend setting; a local `continue-proxy/` reverse proxy can sit in front of the OpenAI-compatible upstream instead.
- `continue-proxy/` now forces `Accept-Encoding: identity` on forwarded upstream requests so captured provider JSON/SSE bodies stay readable in the stored response artifacts.
- `continue-proxy/` is useful even without live provider access because it can stub both OpenAI `Responses` and legacy `chat/completions` payload shapes, which is enough to sanity-check the redirect seam and the harness launch flow offline.
- The `continue-proxy/` repo has offline sanity coverage: `python3 -m unittest discover -s continue-proxy -p 'test_server.py'` passed, `server.py --help` parses cleanly, and `run_capture.sh` is shell-valid under both `sh -n` and `bash -n`.
- `continue-proxy/run_capture.sh` now actively polls the local proxy `/health` endpoint before launching `cn`, which is a better capture wrapper pattern than checking only that the proxy PID still exists.
- `continue-proxy/run_capture.sh` now also parses multi-word launchers from `CONTINUE_CMD` and `CONTINUE_CMD_ARGS`, which matters for open-source CLIs that may be run via `npx`, `bun`, or another package-manager wrapper instead of an installed bare binary.
- On this host, live capture was blocked for environmental reasons rather than design reasons: `cn` was not installed and the sandbox forbids loopback binds (`127.0.0.1` listener creation raises `PermissionError: [Errno 1] Operation not permitted`).

## Aider

- Classification: open-source
- Repo: `Aider-AI/aider`
- License: Apache 2.0
- Main harness examined: `aider/main.py`, `aider/coders/*`, `aider/commands.py`, `aider/repomap.py`
- Local artifact note: no `aider` binary was present on this machine, so the classification and architecture notes below are source-guided from the public repo.
- Aider's mainline harness is prompt construction, text edit output, local parsing/application, and optional human-approved side effects rather than a frontier autonomous tool loop.
- Its nearest thing to subagents is in-process coder handoff:
  - `ArchitectCoder` plans, then instantiates an `editor_coder`
  - the handoff path runs through `Coder.create(from_coder=...)` / `clone(...)`, so the same repo, file sets, IO, chat history, and command layer are reused inside one process rather than delegated to a separate worker
  - `/lint` clones a temporary coder to repair lint findings
  - `/ask`, `/help`, `/context`, `/architect` switch among specialized coder modes
- Legacy function-calling support exists in the tree but does not look live in the main harness:
  - `editblock_func_coder.py` defines a JSON-style `replace_lines` tool schema
  - that coder is marked deprecated / needing refactor
  - supported coder exports in `aider/coders/__init__.py` point to text-edit coders instead
- Shell execution is useful but not a first-class tool loop:
  - shell commands are parsed from assistant text blocks
  - execution remains user-mediated in the command/base-coder layer
- Repo-map looks more central to Aider's effectiveness than tool calling:
  - it builds ranked code context from tags, symbol/reference graphs, and personalized PageRank
- Practical take: Aider looks strongest as a controlled edit harness for real repos, especially where reviewability and git hygiene matter more than autonomous tool loops or parallel workers.
- Aider is proxyable at the provider layer rather than through a harness-specific remote:
  - repo-root `aider-proxy/` now contains a minimal OpenAI-compatible reverse proxy plus `run_capture.sh`
  - the intended redirect seam is Aider's configurable OpenAI base URL (`--openai-api-base` in the capture wrapper)
  - unlike the `amp-proxy` stub, the Aider capture point has to forward real upstream traffic because the harness expects valid model responses for a one-shot `--message` run to complete
  - forcing `Accept-Encoding: identity` at the proxy is a practical RE tweak for provider-backed harnesses because it keeps logged response bodies readable instead of storing compressed blobs
  - for real captures, keep the JSONL log compact by default and store raw bodies separately on disk; duplicating full request/response payloads inline makes provider-traffic captures unnecessarily large and noisy
  - capture wrappers should poll a local health endpoint before launching the harness so listener startup failures are separated cleanly from harness/auth/provider failures
  - Aider-specific capture wrappers should support both the standalone `aider` executable and `python3 -m aider`; the Python-module path is a real install/launch pattern and should not be treated as an edge case
  - `aider-proxy/run_capture.sh` now also supports a full multi-word launcher prefix via `AIDER_CMD_PREFIX`, which is the cleaner pattern when the harness is started through `python3 -m ...`, `uvx ...`, or another wrapper command
  - offline verification should cover the whole deliverable, not just the proxy helpers: unit tests, `server.py --help`, and shell syntax for the capture wrapper are all worth checking when listener startup is blocked by the sandbox
  - in this sandbox, live interception was blocked by environment limits rather than by Aider itself: there is no local `aider` binary on `PATH`, and loopback `bind(('127.0.0.1', ...))` fails with `PermissionError(1, 'Operation not permitted')`
  - practical implication: the proxy is built and syntax-checked, but real traffic capture must be run outside the restricted harness

## Cline

- Classification: open-source
- Repo: `cline/cline`
- Version observed from `package.json`: `3.76.0`
- License: Apache-2.0
- Main evidence: public GitHub repo, public docs, and public tool/subagent source files
- Tool use is first-class and mostly defined in the public harness through `src/core/prompts/system-prompt/tools/`
- The public tool registry exports not only file/shell/browser/MCP tools but also orchestration/meta tools like `apply_patch`, `focus_chain`, `plan_mode_respond`, `act_mode_respond`, and `load_mcp_documentation`
- Public docs show the default tool contract in prompt space using XML-like tags such as `<write_to_file>` and `<execute_command>`, so Cline's tool loop is not purely "native function calling"
- Cline also exposes a separate "Native Tool Call (Experimental)" setting for some providers/models, which implies a mixed model: prompt-defined tool contracts remain important even where native tool calling exists
- Subagents are real but intentionally narrow:
  - exposed via `use_subagents`
  - up to five in parallel
  - described in source as "in-process subagents"
  - gated by `context.subagentsEnabled === true && !context.isSubagentRun`
  - read-only research workers
  - no edits, browser, MCP, web search, or nested delegation
- Launches follow the same read-file auto-approve path as other low-risk operations; explicit approval is only needed when auto-approve is off
- Practical take: Cline's subagents look useful for parallel reconnaissance and context compression, but not like full-capability delegated worker agents; the docs explicitly frame them as broad-exploration helpers that add overhead on small focused tasks

## Opencode

- Classification: open-source
- Local version observed: `1.3.3`
- Current public source: `anomalyco/opencode` (`packages/opencode/src/`)
- Historical repo also surfaced: `opencode-ai/opencode`, but that is an older archived Go codebase and not the current harness
- Open-vs-closed evidence:
  - current public GitHub repo with readable TypeScript/Bun source
  - local `@opencode-ai/sdk` and `@opencode-ai/plugin` packages declare `MIT`
  - cached local instructions explicitly say opencode is open source
- Tool use is central and real:
  - `session/prompt.ts` rebuilds the tool list inside the main loop and continues iterating on `tool-calls`
  - `tool/registry.ts` combines built-ins, config/flag-gated tools, filesystem-loaded tools, plugin tools, and MCP tools
  - plugin hooks wrap tool execution before and after calls, and can also rewrite tool definitions
  - local plugin typings expose concrete hook names: `permission.ask`, `tool.execute.before`, `tool.execute.after`, `shell.env`, and `tool.definition`
- Subagents are central and real:
  - `agent/agent.ts` defines agent modes `subagent | primary | all`
  - built-in subagents include `general` and `explore`
  - `tool/task.ts` creates or resumes child sessions for delegated work and returns resumable `task_id`s
  - explicit `@agent` mentions are converted into structured `agent`/`subtask` message parts that route into the `task` tool
- The CLI surface confirms the harness is reusable beyond the TUI:
  - `serve` starts a headless server
  - `run` supports `--format json`
  - top-level help exposes `attach`, `web`, `session`, `export`, `import`, `github`, `pr`, and `db`
- Practical take: Opencode has one of the clearest open-source harness designs in this set for studying delegated sessions, permission-scoped subagents, and hookable tool execution. The main caveat is network-sensitive startup behavior; even low-risk CLI probes tried to contact `models.dev`.

- For Factory specifically, inspect `~/.factory/droids/*.md` first to understand delegation semantics and tool restrictions.
- Mining `~/.factory/sessions/**/*.jsonl` and `~/.factory/artifacts/tool-outputs/*.log` yields concrete tool names (`Execute`, `FetchUrl`, grep-style tools) and real usage traces.
- Installer scripts can reveal more than the public repo: Factory’s installer directly exposes the binary release host, version, architecture handling, and bundled sidecar binaries.

## Codex

- Classification: open-source
- Installed package: `@openai/codex`
- Version observed: `0.117.0`
- Local binary: `/opt/homebrew/bin/codex`
- License: Apache-2.0
- Repository: `openai/codex` (`codex-cli` subdirectory in the package manifest)
- Local install is a readable Node launcher that selects a packaged platform-native binary from `node_modules/@openai/codex-<platform>/vendor/.../codex/codex`
- CLI surface shows first-class support for `exec`, `review`, `mcp`, `mcp-server`, `app-server`, `sandbox`, `apply`, `resume`, `fork`, `cloud`, and feature inspection
- Tool use is clearly central:
  - explicit MCP management and Codex-as-MCP-server support
  - public source defines first-class tool schemas for `exec_command`, `write_stdin`, `spawn_agent`, `send_input`, `wait_agent`, `close_agent`, `request_user_input`, `tool_search`, and `tool_suggest`
  - binary strings include `tools/list`, `tools/call`, `dynamic_tools`, approval flows, and app-server tool plumbing
  - feature flags expose `apps`, `plugins`, `shell_tool`, `unified_exec`, `tool_call_mcp_elicitation`, and `tool_suggest`
  - `codex exec` has real automation affordances: `--json`, `--output-schema`, `--output-last-message`, and `--ephemeral`
- Multi-agent support is real but not fully surfaced:
  - `multi_agent` is stable and enabled
  - `multi_agent_v2`, `child_agents_md`, and `enable_fanout` are present but not enabled
  - `strings` exposes collaboration events like `CollabAgentSpawnBegin`, `CollabAgentSpawnEnd`, `CollabInteraction`, and `WaitingOnCollaborator`
  - public source includes a real spawn handler that enforces `agent_max_depth`, emits collaboration events, and calls `spawn_agent_with_metadata(...)`
- Codex is redirectable for proxying:
  - the binary exposes `openai_base_url`
  - `codex exec -c 'openai_base_url="http://127.0.0.1:18456/v1"' ...` redirected the client to the local base URL
  - current `0.117.0` traffic is not purely HTTP; it attempted `ws://127.0.0.1:18456/v1/responses` and also retried against `http://127.0.0.1:18456/v1/responses`
  - a fresh local rerun on 2026-03-28 showed the same sequence again: WebSocket connection attempts to `/v1/responses`, then retry messages for plain HTTP on the same path
  - the same rerun also showed that `codex features list` now marks `responses_websockets` and `responses_websockets_v2` as `removed`, so stale or tombstoned feature flags should not overrule live transport probes
  - practical implication: a useful Codex proxy needs WebSocket support, not just JSON-over-HTTP logging
  - repo-root `codex-proxy/` supports optional HTTPS listener mode as well as plain HTTP, plus an outside-sandbox `run_capture.sh` wrapper for reproducible capture attempts
  - repo-root `codex-proxy/` now contains that reverse proxy implementation plus `run_capture.sh`, an outside-sandbox wrapper that sources `.env`, starts the proxy, and runs `codex exec` through the redirected base URL
- Local probing caveat:
  - `codex --help` and `codex features list` returned quickly
  - `codex exec --help`, `codex mcp --help`, and `codex -V` also returned under the same 10-second wrapper on the installed `0.117.0` build
  - when probing through an async exec harness, an empty first read is not enough to classify a command as hung; both subcommand help calls initially produced no output before completing successfully on a later poll
- In this RE sandbox, local loopback interception was blocked by environment policy rather than by Codex itself:
  - binding a local proxy listener failed with `PermissionError: [Errno 1] Operation not permitted`
  - a minimal direct `socket.bind(("127.0.0.1", 0))` probe failed with the same error, which narrows the issue to sandbox policy rather than proxy implementation
  - redirected Codex traffic to `127.0.0.1` failed with `Operation not permitted (os error 1)`
- Practical take: Codex’s tool architecture is mature and central; its subagent layer is also real and useful, but the ergonomic/public CLI layer still lags the internal tool contract. For proxying, the redirect hook is present and usable, but a complete capture setup must handle WebSockets.

## Claude Code

- Classification: closed-source
- Installed package: `@anthropic-ai/claude-code`
- Local binary: `/opt/homebrew/bin/claude`
- Version observed: `2.1.80`
- Public repo exists at `anthropics/claude-code`, but its current license is still all-rights-reserved, so the harness is not open-source in the OSI sense.
- The public repo README currently says the repository includes Claude Code plugins, which is useful for extension/plugin RE but not sufficient to audit the core harness runtime.
- Local package shows an all-rights-reserved license and ships a minified `cli.js` bundle rather than a readable source tree.
- The strongest local RE artifact is `sdk-tools.d.ts`, which exposes first-class tools including `Agent`, `Bash`, file read/edit/write, `Glob`, `Grep`, `WebFetch`, `WebSearch`, MCP list/read/subscribe/poll, todo writing, and worktree enter/exit.
- Claude Code is redirectable enough for proxying:
  - local debug logs react to `ANTHROPIC_BASE_URL=http://127.0.0.1:18456`
  - when redirected to a non-first-party host, Claude disables optimistic Tool Search unless `ENABLE_TOOL_SEARCH=true`
  - with no listener present, the client retries and logs repeated API connection failures, which is strong evidence the inference path honors the redirect
- The minified bundle also contains useful endpoint evidence:
  - default `BASE_API_URL` is `https://api.anthropic.com`
  - embedded API docs say the main request path is `POST /v1/messages`
  - supporting endpoints include `/v1/messages/batches`, `/v1/files`, and `/v1/models`
- `CLAUDE_CODE_CUSTOM_OAUTH_URL` exists, but it is allowlisted and is not a general arbitrary-endpoint redirect hook; `ANTHROPIC_BASE_URL` is the useful proxy lever.
- Repo-root `claude-code-proxy/` now includes a forwarding capture proxy plus `run_capture.sh`; the runner sources `.env`, waits for `/health`, preserves the current `HOME` by default so existing Claude auth still works, and drives a non-interactive `claude -p` request through `ANTHROPIC_BASE_URL`.
- The proxy forces `Accept-Encoding: identity` upstream by default so Anthropic JSON/SSE bodies land in the capture logs uncompressed unless `--preserve-accept-encoding` is requested.
- In this RE sandbox, loopback listeners are blocked (`bind('127.0.0.1', ...) -> PermissionError(1, 'Operation not permitted')`), so a local request-capture proxy could be built but not exercised end-to-end here.
- Claude Code subagents are real harness primitives, not just prompt-level roles: the `Agent` input schema includes `subagent_type`, model override, background execution, teammate naming, permission mode, and optional worktree isolation.
- The `Agent` output schema supports both synchronous completion and async launch with `agentId`, `outputFile`, and `canReadOutputFile`, which implies a mature delegated-task path.
- Worktree support is explicit in the typed contract: enter returns `worktreePath`/branch, and exit can keep or remove the worktree, optionally discarding dirty files/commits and reporting a tmux session name.
- CLI help also exposes custom agents, plugins, MCP config, tool allow/deny lists, and worktree support.
- `~/.claude/` is a useful runtime artifact surface: plugin manifests/cache, plans, sessions, and many per-agent todo JSON files align with the typed tool/delegation model.

## Amp

- Classification: closed-source
- Installed binary: `/Users/johann/.amp/bin/amp`
- Symlink on PATH: `/Users/johann/.local/bin/amp`
- Packaging: standalone arm64 Mach-O; `strings` shows Bun compile marker `bun build --compile`
- Open-vs-closed evidence:
  - npm package `@sourcegraph/amp` is published with license `none`
  - no public repo for the actual CLI/runtime was surfaced during RE
  - the distributed runtime is a compiled binary, not a readable shipped source tree
- Config/state paths:
  - `~/.config/amp/settings.json`
  - `~/.local/share/amp/`
  - `~/.amp/`
- Local config confirms backend redirection via `amp.url`, which was set here to `http://localhost:18317`
- Public docs describe a real delegation/tooling layer:
  - `Task` subagents
  - `oracle` second-opinion tool
  - `Librarian` code-search subagent
  - per-check review fan-out via `amp review`
  - skills, MCP, toolboxes, plugins, and the `Painter` image tool
- Direct CLI help confirms first-class command groups for `threads`, `tools`, `review`, `skill`, `permissions`, and `mcp`, plus execute/programmatic flags `--execute`, `--stream-json`, `--stream-json-thinking`, and `--stream-json-input`.
- Direct CLI help also confirms config knobs for `amp.mcpServers`, `amp.permissions`, `amp.tools.disable`, `amp.tools.enable`, `amp.toolbox.path`, and `amp.skills.path`, which is strong evidence of real tool-policy plumbing in the harness.
- Local thread JSON confirms these are not only documented concepts:
  - transcript tool names include `Task`, `oracle`, `find_thread`, `read_thread`, `shell_command`, `Read`, `Bash`, `Grep`, `glob`, `skill`, `read_github`, `search_github`, `read_web_page`, and `web_search`
  - one sampled thread explicitly recorded main-agent model `gpt-5.3-codex`
  - corpus counts found `Task` 70 times and `oracle` 27 times in thread JSON
- Practical take: Amp appears to have a strong, real orchestration layer with first-class delegation, thread-memory tools, shell/FS tools, remote code research, and extension surfaces, but the core harness remains proprietary and therefore not directly auditable.

## Techniques That Don't Work

<!-- Dead ends documented here so agents don't repeat them. -->
- On this machine, Amp CLI probe results depend on the timeout wrapper. `amp --help` and `amp version` returned under a Perl `alarm` wrapper, while `amp tools list`, `amp permissions list --builtin`, and several subcommand help invocations still failed to finish within 10 seconds.

- `droid --help` and similar naïve CLI probes may hang; do not assume conventional fast help/version output from proprietary agent CLIs.
- Browser access and shell network access may differ. In this environment, Cursor webpages were reachable via the web tool while `curl` to `downloads.cursor.com` failed with DNS resolution errors.
- Anonymous GitHub code search is unreliable. Once local artifacts reveal likely repo paths, fetch raw file URLs directly or use the installed package contents instead.
- Shell DNS failure blocks artifact download but does not block browser/docs-based RE. Record the limitation explicitly and avoid overstating what could not be verified locally.
- Some Bun-based agent CLIs try to contact remote model registries even for `--help` and debug commands. For opencode, `models.dev` fetches happened during `agent list`, `debug skill`, and other low-risk probes.
