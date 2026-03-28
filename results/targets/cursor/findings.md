# Cursor Findings

## Verdict

Cursor is closed-source for the actual harness.

The public `cursor/cursor` repo is not the harness source, and the installed CLI package is a private bundled runtime rather than a public source tree.

## Open-Source Check

- Public repo: `https://github.com/cursor/cursor`
- Result: public-facing repository, not the editor/agent source
- Evidence:
  - The repo contents are effectively README, security policy, and issue templates.
  - The README directs users to `cursor.com` to download Cursor rather than to build from source.

## Local Package Evidence

- Local symlinks:
  - `~/.local/bin/cursor-agent`
  - `~/.local/bin/agent`
- Both point to:
  - `~/.local/share/cursor-agent/versions/2026.01.23-916f423/cursor-agent`
- The installed `cursor-agent` entrypoint is a shell launcher that execs:
  - bundled `node`
  - bundled `index.js`
- Local `package.json`:
  - `"name": "@anysphere/agent-cli-runtime"`
  - `"private": true`

This is strong evidence that the shipped harness is proprietary. It is locally inspectable after install, but not distributed as an open-source harness repository.

## Binary / Distribution Evidence

- Cursor publishes an installer script at `https://cursor.com/install`.
- As observed on March 28, 2026, the script downloads a prebuilt tarball:
  - `https://downloads.cursor.com/lab/2026.03.25-933d5a6/${OS}/${ARCH}/agent-cli-package.tar.gz`
- The installer places the package under:
  - `~/.local/share/cursor-agent/versions/2026.03.25-933d5a6`
- It creates symlinks:
  - `~/.local/bin/agent`
  - `~/.local/bin/cursor-agent`

This matches the older local install already present on this machine:

- installed version found locally:
  - `2026.01.23-916f423`

So the distribution model is consistent: Cursor ships a prebuilt, versioned agent package.

## Local RE Attempt

- I found an existing local Cursor installation:
  - `/Applications/Cursor.app`
  - `~/.local/bin/cursor-agent`
  - `~/.local/share/cursor-agent/versions/2026.01.23-916f423/`
- The package contents are not a native single binary. They include:
  - `cursor-agent` shell launcher
  - bundled `node`
  - bundled `rg`
  - `cursorsandbox`
  - webpack bundle `index.js`
  - many numbered `*.index.js` chunk files
- Safe timeout-wrapped `--help` completed successfully.
- Other timeout-wrapped probes such as `about`, `mcp --help`, `--version`, `create-chat`, and `help create-chat` did not complete within 10 seconds on this machine.

That means the local RE surface is real, but some subcommands appear to block on auth, network, or slow startup paths.

## Harness Architecture From Local Evidence

### Tool calls

The shipped bundle contains dedicated modules/UI for all of these tool families:

- read files
- list directories
- glob files
- grep/search files
- semantic search / merged read+search views
- edit files
- delete files
- run terminal commands
- write to terminal stdin
- search the web
- fetch webpages
- use MCP servers
- list MCP resources
- fetch MCP resources
- update todos
- create plans
- run task/subagent calls

Concrete local evidence:

- `./src/components/read-tool-ui.tsx`
- `./src/components/ls-tool-ui.tsx`
- `./src/components/glob-tool-ui.tsx`
- `./src/components/grep-tool-ui.tsx`
- `./src/components/edit-tool-ui.tsx`
- `./src/components/delete-tool-ui.tsx`
- `./src/components/shell-tool-ui.tsx`
- `./src/components/write-shell-stdin-tool-ui.tsx`
- `./src/components/web-search-tool-ui.tsx`
- `./src/components/web-fetch-tool-ui.tsx`
- `./src/components/mcp-tool-ui.tsx`
- `./src/components/list-mcp-resources-tool-ui.tsx`
- `./src/components/fetch-mcp-resource-tool-ui.tsx`
- `./src/components/update-todos-tool-ui.tsx`
- `./src/components/create-plan-tool-ui.tsx`
- `./src/components/task-tool-ui.tsx`

### CLI / headless mode

The local CLI help and bundle confirm:

- `cursor-agent` supports a non-interactive print mode (`-p` / `--print`)
- `--output-format` supports `text`, `json`, and `stream-json`
- non-interactive mode has full write access
- `--approve-mcps` exists for headless mode
- `--browser` exists for browser automation support
- the CLI exposes `help [command]`, `resume`, and listing flows
- the bundle contains a dedicated `./src/headless.ts`

Concrete help text from the local bundle:

- `--print`: "Has access to all tools, including write and bash."
- `--approve-mcps`: "Automatically approve all MCP servers (only works with --print/headless mode)"
- `--cloud`: opens the composer picker on launch

That is enough to conclude Cursor has a real headless harness surface rather than just a UI-only editor feature.

### Subagents

Local bundle evidence for subagents is strong:

- `./src/utils/task-tool.ts` renders a tool titled `Subagent task`
- it reads `args.description` and `args.subagentType`
- it tracks `additionalData.subagentState`
- it distinguishes normal completion, error, and `isBackground`
- `./src/components/running-agents-ui.tsx` shows per-subagent status labels like:
  - `Reading ...`
  - `Editing ...`
  - `Deleting ...`
  - `Listing ...`
  - `Searching ...`
  - shell execution states
- the bundle includes `./src/components/task-tool-ui.tsx`
- the bundle includes `./src/components/running-agents-ui.tsx`

Conclusion:

- Cursor has first-class subagent support in the shipped harness.
- This is not just product copy. The local package has an actual task-tool/subagent state model and dedicated UI for running agents.
- I did not recover the exact scheduler/orchestrator implementation, so I cannot prove from local code alone how aggressively it parallelizes them.

### Background / cloud agents

Local bundle and local state both show a separate background-agent path:

- bundle modules:
  - `./src/background.tsx`
  - `./src/components/background-composer-conversation.tsx`
  - `./src/components/background-composer-list.tsx`
  - `./src/components/background-composer-selection.tsx`
  - `./src/hooks/use-send-to-background.ts`
  - `./src/hooks/use-attach-background-composer.ts`
- local `storage.json` contains remote workspace entries under:
  - `vscode-remote://background-composer+.../workspace`
- the local bundle defines:
  - `--cloud`
  - hidden `--background` alias

This looks like a separate remote-execution harness alongside the local foreground agent.

### Worker / protocol architecture

The local package exposes at least two more execution surfaces:

- hidden `worker-server` command in the main bundle
- `./src/worker-manager.ts`, which spawns `worker-server` with:
  - `AGENT_CLI_SOCKET_PATH`
  - `AGENT_CLI_LOG_PATH`
  - `AGENT_CLI_WORKER_OPTIONS`
- a separate ACP stack:
  - `./src/acp/agent-session.ts`
  - `./src/acp/agent-store.ts`
  - `./src/acp/cursor-acp-agent.ts`
  - `./src/acp/run.ts`

So Cursor is not just a monolithic chat loop. It has at least:

- the main interactive/headless CLI
- local worker-server infrastructure
- background-composer flows
- an ACP agent/protocol layer

## Proxy / Redirectability

`cursor-proxy/` now exists at the repo root as a dedicated reverse-proxy repo, with its own `.git/`, following the same general capture pattern as `amp-proxy` but adapted to Cursor's backend override surface.

What the local bundle proves:

- `./src/utils/api-endpoint.ts` resolves agent traffic from:
  - `process.env.CURSOR_API_ENDPOINT`
  - fallback: `https://api2.cursor.sh`
- the auth/login flow resolves from:
  - `process.env.CURSOR_API_BASE_URL`
  - fallback: `https://api2.cursor.sh`
- the login poll path is built as:
  - `${CURSOR_API_BASE_URL}/auth/poll`

That means Cursor is redirectable without binary patching. To proxy it faithfully, set both:

- `CURSOR_API_ENDPOINT=http://127.0.0.1:<port>`
- `CURSOR_API_BASE_URL=http://127.0.0.1:<port>`

## cursor-proxy Repo

Current repo-root proxy deliverable:

- `cursor-proxy/server.py`
  - simple HTTP reverse proxy
  - optional HTTPS listener support
  - logs request/response metadata to JSONL
  - stores raw request and response bodies under `targets/cursor/`
  - redacts sensitive headers/query params by default
- `cursor-proxy/run_capture.sh`
  - sources `../.env`
  - starts the proxy
  - polls `/health` before launching Cursor
  - preserves the current `HOME` by default so existing Cursor auth state still works
  - drives one safe non-interactive command through the redirected base URL
- `cursor-proxy/test_server.py`
  - offline unit coverage for path joining and redaction helpers

Artifacts written by the proxy/capture wrapper:

- `targets/cursor/proxy-exchanges.jsonl`
- `targets/cursor/proxy-requests/`
- `targets/cursor/proxy-responses/`
- `targets/cursor/proxy-server.stdout.log`
- `targets/cursor/proxy-server.stderr.log`

## Capture Status On This Machine

Offline validation succeeded:

- `python3 -m unittest cursor-proxy/test_server.py` passed
- `sh -n cursor-proxy/run_capture.sh` passed
- `bash -n cursor-proxy/run_capture.sh` passed

Live capture did not succeed in this sandbox, but the blocker is environmental rather than architectural:

- starting `cursor-proxy/server.py` failed at `socket.bind(...)`
- the concrete error was:
  - `PermissionError: [Errno 1] Operation not permitted`
- no request or response artifacts were captured here because the proxy listener could not bind locally

So the current state is:

- redirect seam identified from local shipped code
- proxy repo built
- runner built
- offline validation done
- live request capture still requires running `cursor-proxy/run_capture.sh` outside this restricted sandbox

## Are These Useful In The Harness?

Yes.

Why:

- The tool surface is the standard useful set for autonomous coding work.
- Headless CLI mode plus structured output formats make the harness automatable.
- The task/subagent path is useful for decomposing search, implementation, and validation work.
- Background agents are useful for longer-running tasks and PR-oriented workflows.

Limits:

- Task/subagents only help when work can be decomposed cleanly.
- Poor coordination can turn them into duplicated effort and extra latency.
- Auto-running commands in remote/background environments increases prompt-injection and exfiltration risk.

## Who Would Be A Good Judge?

This is an inference, not something Cursor states directly.

A good judge would be:

- maintainers of coding-agent benchmarks such as SWE-bench-style or terminal-agent evals
- engineers running agents against real repositories, CI, and PR queues
- people measuring task success rate, wall-clock time, edit quality, and review burden

What they would likely say:

- The tool set is useful, but also table stakes.
- The real question is whether task/subagents improve end-to-end completion and latency on real tasks.
- They are valuable when they parallelize independent exploration/build/test work.
- Background agents are valuable for long-running or remote setup-heavy tasks, but they require stronger trust and security controls.

## Sources

- GitHub repo: https://github.com/cursor/cursor
- Installer script: https://cursor.com/install
- Product page: https://cursor.com/product
- CLI announcement, August 7, 2025: https://cursor.com/blog/cli
- Background agents docs: https://docs.cursor.com/en/background-agents
- Cursor 2.5 changelog, February 17, 2026: https://cursor.com/changelog/2-5
- Cloud agents / computer use blog, February 24, 2026: https://cursor.com/blog/agent-computer-use
- Local package:
  - `~/.local/share/cursor-agent/versions/2026.01.23-916f423/`
- Local proxy repo:
  - `cursor-proxy/`
- Local user state:
  - `~/Library/Application Support/Cursor/User/globalStorage/storage.json`
