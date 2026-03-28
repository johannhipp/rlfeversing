# Aider Findings

## Status

Aider is open-source.

Primary evidence:

- Public GitHub repo: https://github.com/Aider-AI/aider
- Apache 2.0 license: https://github.com/Aider-AI/aider/blob/main/LICENSE.txt
- README presents the project as a public GitHub-hosted AI pair programming tool: https://github.com/Aider-AI/aider/blob/main/README.md
- The public repo contains the live harness source, not just docs or plugins: `aider/main.py`, `aider/coders/base_coder.py`, `aider/commands.py`, and `aider/repomap.py` are all present in the same repo.
- There was no local `aider` binary on this machine (`which aider` returned nothing), so this RE pass is source-guided rather than binary-guided.

## Harness Architecture

Aider is a Python CLI harness centered on a `Coder` abstraction.

- Entry point: [`aider/main.py`](https://github.com/Aider-AI/aider/blob/main/aider/main.py)
- Coder factory and main loop: [`aider/coders/base_coder.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/base_coder.py)
- Available coder modes: [`aider/coders/__init__.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/__init__.py)
- Command layer: [`aider/commands.py`](https://github.com/Aider-AI/aider/blob/main/aider/commands.py)
- Repo-map implementation: [`aider/repomap.py`](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py)

Startup flow:

1. `main.py` parses CLI/config/env and builds model settings, IO, git repo, and command objects.
2. `Coder.create(...)` selects a coder class by `edit_format`.
3. The active `Coder` builds a prompt from system text, repo map, editable files, read-only files, and chat history.
4. The model replies in an edit format such as search/replace blocks or unified diff.
5. Aider parses the textual edit format and applies edits locally.
6. Optional follow-up loops run lint, tests, shell commands, and auto-commits.

The important architectural point is that most "agentic" behavior is implemented as coder selection, coder cloning, and prompt/parse/apply loops inside one Python process.

## Subagents

Aider does not appear to use separate worker processes or remote subagents in the modern harness. What it does have is in-process coder handoff.

### Architect mode

The clearest example is [`aider/coders/architect_coder.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/architect_coder.py):

- `ArchitectCoder` first asks an "architect" model for a change plan.
- In `reply_completed()`, it creates a second `Coder` instance named `editor_coder`.
- That handoff is routed through the normal coder factory path (`Coder.create(from_coder=...)` / `clone(...)` in `base_coder.py`), which carries chat/history/file context forward.
- That second coder runs the generated plan against the files using the editor model and edit format.
- `base_coder.py`'s clone path reuses the same repo, file lists, chat history, command layer, and IO object, which is the strongest source-level evidence that this is mode handoff inside one session rather than a separate worker harness.
- The handoff is confirmed in-process, with the planner asking before invoking the editor phase.

This is subagent-like, but only inside one process. It is better described as a two-phase planner/editor pipeline than as a true multi-agent harness.

### Other coder handoffs

`commands.py` also switches or clones coders for specialized tasks:

- `/architect`, `/ask`, `/context`, `/help` create new coder instances and then switch back.
- `/lint` can spin up a temporary cloned coder to repair lint errors.
- `ContextCoder` iteratively narrows the relevant file set and re-prompts.

These are useful role-specialized loops, but they are still not independent agents with separate tool budgets, memory, or parallel execution.

The practical distinction matters: aider has mode changes and handoffs, but not the orchestrator/worker pattern seen in more agentic harnesses.

## Tool Calls

### Current harness pattern

The current harness is not primarily built around model-native tool calling.

Instead, modern aider mostly uses:

- structured prompts
- repo-map context
- text edit formats
- user-confirmed shell and web actions

The default code-edit path is prompt-constrained text output, not JSON tool calls:

- `EditBlockCoder` parses `SEARCH/REPLACE` blocks from plain text: [`aider/coders/editblock_coder.py`](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_coder.py)
- `base_coder.py` applies parsed edits locally after validation and permission checks.

### Shell commands

The model can suggest shell commands as part of an edit response. Aider collects those fenced shell snippets from the assistant text and asks the user before execution.

- `EditBlockCoder.get_edits()` extracts shell blocks into `self.shell_commands`.
- `base_coder.py` keeps shell execution user-mediated rather than autonomous.

This makes shell usage conservative and human-gated. It is useful, but it is not a first-class autonomous tool API in the way MCP/function-calling harnesses use one.

### Web fetching

Web content is also user-mediated:

- `Commands.cmd_web()` scrapes a URL and inserts the content into chat.
- `base_coder.py` can detect URLs in user input and offer to add them to the chat via `cmd_web(...)`.

So the model can benefit from web content, but aider does not run a free-form browsing agent loop.

### Function/tool calling support

There is evidence of older or secondary support for function-style tool schemas, but not in the mainline harness path:

- `aider/coders/editblock_func_coder.py` defines a `replace_lines` JSON schema.
- That coder raises immediately as deprecated and "needs to be refactored".
- `aider/coders/__init__.py` does not export it among the supported coder classes, which is the simplest source-level sign that it is not part of the live default harness.

So native/provider tool calling is not the mainline harness design today. The mainline path is still prompt-shaped text output plus local parsing and guarded execution.

That distinction also makes aider more portable across model backends than a harness that depends deeply on provider-specific function-call APIs, but it means the harness itself owns more of the parsing discipline.

## Repo Map

Repo-map is one of the most important harness features.

[`aider/repomap.py`](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py) builds a codebase summary using:

- tree-sitter and grep-ast tags
- cached symbol extraction
- a graph over definitions and references
- personalized PageRank to rank relevant files/symbols

This is not a subagent, but it gives the model a wider codebase view without stuffing every file into context. In practice this is one of the main reasons aider works well in larger repos.

## Usefulness

### What seems genuinely useful

- Planner/editor split in architect mode.
- Repo-map for large repositories.
- Tight git integration with auto-commit and undo.
- Human-gated shell and web actions.
- File-scoped edit formats that keep changes surgical.

### What seems limited

- No true parallel subagents.
- No autonomous multi-tool planning loop of the kind used by more agentic harnesses.
- Tool calling exists mostly as legacy plumbing; the modern path is still text-in/text-out with local parsing.

## Who Would Be A Good Judge?

Best judges:

- Maintainers of medium-to-large OSS repos who care about precise edits and reviewability.
- People who benchmark coding assistants on real codebases rather than toy tasks.
- Power users comparing harness ergonomics for day-to-day terminal coding.
- Reviewers who want explicit git diffs and human approval around shell/web side effects.

Why them:

- Aider's strengths are not "maximum autonomy".
- Its strengths are controlled edits, git hygiene, and effective context shaping.
- Those matter most to users editing real repositories with review constraints.

## What Would They Likely Say?

Inference from the source and the README testimonials:

- They would likely say aider is useful because it is disciplined, predictable, and strong at surgical code edits in existing repos.
- They would likely not describe it as a frontier agent harness for subagents or tool orchestration.
- They would probably see architect mode as a practical planner/editor split, not true multi-agent delegation.

The README user quotes and positioning point in that direction. The strongest relevant signals are:

- It is the "best free open source AI coding assistant."
- It is the "best agent for actual dev work in existing codebases."
- The README also says it is "the AI code assistant to benchmark against."

Those fit the code. The harness is optimized for real-repo editing discipline, context shaping, and git-aware workflows more than for autonomous multi-tool exploration.

## Bottom Line

Aider is open-source and its harness is inspectable.

Its "subagents" are really coder-mode transitions and in-process planner/editor handoffs. Its current tool use is conservative and mostly human-approved. The design is useful for precise, reviewable code editing, but it is less agentic than harnesses built around autonomous tool loops or parallel worker agents.

## Proxy Build

Because Aider is open-source and exposes an OpenAI-compatible provider base URL setting, the right interception point is the model provider traffic rather than a proprietary harness backend.

Built deliverable:

- Repo-root `aider-proxy/`
- Nested `git init` completed there
- `server.py` implements a minimal HTTP/HTTPS reverse proxy
- Request/response exchanges are logged to `targets/aider/proxy-traffic.jsonl`
- Raw request/response bodies are written under `targets/aider/proxy-bodies/`
- `run_capture.sh` sources repo-root `.env`, starts the proxy, and runs a one-shot `aider --message ...` call through `--openai-api-base http://127.0.0.1:18457/v1`

Implementation notes:

- The proxy normalizes path joining so a client configured with `/v1` works whether it sends `/v1/...` or bare endpoint paths.
- Health checks on `/`, `/health`, `/status`, and `/ready` return JSON and are also logged.
- Sensitive headers are redacted in the JSONL exchange log, and raw request/response bodies are preserved on disk for RE.
- The JSONL log now stays compact by default: it records body paths, sizes, SHA-256 digests, previews, and JSON summaries instead of duplicating every full payload inline. There is an `--inline-bodies` escape hatch when a single self-contained log file is more useful than compact capture artifacts.
- Unlike the `amp-proxy` capture stub, `aider-proxy` has to be a real reverse proxy. Aider needs valid upstream model responses to complete a non-interactive `--message` run, so a fake 200/ready server is not enough to capture realistic traffic.
- The proxy now forces `Accept-Encoding: identity` upstream by default so response bodies stay readable in the RE logs instead of arriving as gzip blobs. There is an escape hatch via `--preserve-accept-encoding` if exact header pass-through matters more than readability.
- `run_capture.sh` now polls `/health` before launching Aider and supports both `AIDER_BIN=...` and the documented Python-module launch path (`python3 -m aider`), which makes outside-sandbox capture less brittle and separates "proxy failed to start" from "Aider failed after startup".
- `run_capture.sh` now also accepts `AIDER_CMD_PREFIX="..."` for multi-word launcher prefixes such as `python3 -m aider` or `uvx --from aider-chat aider`, so outside-sandbox capture does not require editing the wrapper when Aider is launched through a module or package-manager shim.
- `verify_offline.py` now checks the full offline deliverable rather than only the unit tests: it runs the Python test suite, parses `server.py --help`, and syntax-checks `run_capture.sh` with `bash -n`.

## Capture Status

Live capture could not be completed inside this Codex sandbox.

Observed blockers:

- No local `aider` binary was installed on this machine (`command -v aider` returned nothing).
- Loopback listeners are blocked here: a direct Python `socket.bind(('127.0.0.1', 0))` probe failed with `PermissionError(1, 'Operation not permitted')`.

What was verified locally:

- `python3 -m unittest discover -s aider-proxy -p 'test_server.py'` succeeded.
- `python3 aider-proxy/verify_offline.py` succeeded.
- `python3 aider-proxy/server.py --help` parsed cleanly.
- `bash -n aider-proxy/run_capture.sh` succeeded.
- The offline verification script proved the important non-network helper behavior without binding a listener:
  - `/v1` path normalization does not double-prefix already-versioned request paths
  - forwarded headers replace `Host`, force `Connection: close`, and default `Accept-Encoding` to `identity`
  - JSON body metadata capture, SHA-256 digesting, file-backed body logging, and sensitive-header redaction work as intended
- `run_capture.sh` now clears old capture artifacts (`proxy-traffic.jsonl`, `proxy-bodies/`, proxy stdout/stderr logs) before each run, which avoids mixing stale bodies from earlier attempts into a new RE session.
- `run_capture.sh` now also falls back to `python3 -m aider` when no standalone `aider` executable is present but the Python package is installed, which aligns better with Aider's documented install/launch pattern.
- `run_capture.sh` now also accepts multi-word command prefixes through `AIDER_CMD_PREFIX`, which makes the wrapper usable with module-style or package-manager launchers without local script edits.
- The proxy code is ready for out-of-sandbox use through `aider-proxy/run_capture.sh`.

Practical next step outside the sandbox:

1. Install `aider` on `PATH`.
2. Ensure `.env` contains `OPENAI_API_KEY`.
3. Run `aider-proxy/run_capture.sh "Say hello in one sentence."`
4. Inspect `targets/aider/proxy-traffic.jsonl` and `targets/aider/proxy-bodies/`
