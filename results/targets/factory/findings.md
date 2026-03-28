# Factory Findings

## Verdict

Factory is **not meaningfully open-source as a harness**.

- There is a public repo at `Factory-AI/factory`, but the public repo appears to be documentation/packaging/community surface, not the actual CLI/runtime source.
- The public repo root only exposes `.github`, `docs`, `.gitignore`, and `README.md` in the top-level tree when inspected on 2026-03-28.
- The install script published at `https://app.factory.ai/cli` downloads a prebuilt `droid` binary from `https://downloads.factory.ai/factory-cli/releases/0.89.0/.../droid`.
- The installed CLI on this machine is a closed distributed binary: `~/.local/bin/droid` is a `Mach-O 64-bit executable arm64`.
- The public GitHub README says `npm -g install droid`, but the public repo does not expose obvious harness source directories; the README footer also says `Copyright © 2025-2026 Factory AI. All rights reserved.`

## Open vs Closed Evidence

### Public surface

- Public repo: `https://github.com/Factory-AI/factory`
- Repo README describes the product and install flow, but the rendered tree only showed `.github`, `docs`, and `README.md` on the landing page when inspected on 2026-03-28.
- Docs are extensive and public. Important pages:
  - `droid exec` headless mode
  - custom droids / subagents
  - skills
  - plugins
  - auto-run

### Closed harness surface

- Installer script hardcodes:
  - `VER="0.89.0"`
  - `BASE_URL="https://downloads.factory.ai"`
  - download target `.../factory-cli/releases/$VER/$platform/$droid_architecture/droid`
  - a separately downloaded ripgrep helper into `~/.factory/bin/rg`
- Local binary inspection:
  - `file ~/.local/bin/droid` -> `Mach-O 64-bit executable arm64`
  - binary size on this machine: `108095840` bytes
  - `strings ~/.local/bin/droid` strongly suggests a Bun-compiled bundle rather than a native-from-scratch binary
- Safe non-interactive probes with a 10s Python timeout:
  - `droid --help` timed out with no output
  - `droid -v` did not return within the timeout
  - `droid exec --help` timed out
  - `droid exec -f /dev/null` timed out
  - `droid exec --list-tools --output-format json` also timed out

Interpretation: the practical harness is a proprietary shipped binary with public docs around it.

## Reverse-Engineered Architecture

## Distribution / runtime

- The distributed CLI is called `droid`.
- It installs into `~/.local/bin/droid`.
- Factory also installs its own ripgrep copy into `~/.factory/bin/rg`.
- The binary appears Bun-based:
  - `strings` output contains extensive Bun runtime strings and CLI internals.
  - `strings` also leaks harness-level enums and protocol fragments including:
    - permission/autonomy actions like `proceed_auto_run_high`, `mcp_tool`, `apply_patch`
    - roles/states like `orchestrator`, `worker`, `awaiting_input`, `orchestrator_turn`, `completed`
    - session update types like `user_message_chunk`, `agent_message_chunk`, `agent_thought_chunk`, `tool_call_update`, `available_commands_update`, `current_mode_update`

## Local state

Factory persists substantial state under `~/.factory/`, including:

- `settings.json`
- `history.json`
- `sessions/.../*.jsonl`
- `artifacts/tool-outputs/*.log`
- `snapshots/manifests/*.snapshots.json`
- `droids/*.md`
- `plugins/...`
- `mcp.json`

This is useful for RE because it exposes:

- session transcripts
- tool result artifacts
- custom subagent definitions
- plugin marketplace metadata
- snapshot manifests keyed by tool call ids
- raw tool call and tool result traffic in JSONL form

## Models / provider locking

Observed local config:

- `sessionDefaultSettings.model`: `claude-opus-4-5-20251101`
- `sessionDefaultSettings.reasoningEffort`: `low`
- `sessionDefaultSettings.autonomyMode`: `auto-high`

Observed session metadata:

- `providerLock: "anthropic"`

Docs also show BYOK/custom model support through `~/.factory/settings.json` using `baseUrl`, `apiKey`, `provider`, and a `custom:` model prefix.

## Tools

Docs for custom droids map tool categories to concrete tools:

- `read-only` -> `Read`, `LS`, `Grep`, `Glob`
- `edit` -> `Create`, `Edit`, `ApplyPatch`
- `execute` -> `Execute`
- `web` -> `WebSearch`, `FetchUrl`
- `mcp` -> dynamically populated MCP tools
- `TodoWrite` is auto-included for all droids

Observed from local transcripts/artifacts:

- `Execute`
- `FetchUrl` / `fetch_url`
- `grep_tool_cli`
- `Read`
- `Glob`
- `Grep`
- file snapshotting keyed by `toolu_*` ids

Observed from local session JSONL:

- assistant turns persist `tool_use` records with names such as `Glob`, `Grep`, and `Read`
- tool responses are written back as `tool_result` content on subsequent user-role messages
- the stored transcript format is rich enough to reconstruct real tool usage patterns without successfully driving the live CLI

Observed from docs:

- tool filtering on `droid exec --enabled-tools` / `--disabled-tools`
- MCP integration exists, but `~/.factory/mcp.json` is empty on this machine

## Subagents / delegation

Factory calls subagents **custom droids**.

Key behavior from docs:

- droids are markdown files under:
  - project: `<repo>/.factory/droids/`
  - personal: `~/.factory/droids/`
- droid definitions are exposed as `subagent_type` targets for the **Task tool**
- each droid has YAML frontmatter controlling:
  - `name`
  - `description`
  - `model`
  - `reasoningEffort`
  - `tools`

Observed local droids:

- `worker.md`
- `scrutiny-feature-reviewer.md`
- `user-testing-flow-validator.md`

These are not toy examples. They show actual delegation patterns:

- `worker`: generic parallel execution / research / analysis helper
- `scrutiny-feature-reviewer`: focused code-review subagent used during “missions”
- `user-testing-flow-validator`: isolated user-flow validation subagent with evidence requirements

This suggests the harness supports:

- parent-agent orchestration
- fresh-context subagents
- restricted toolsets per subagent
- specialized prompts encoded on disk
- parallel validation/review patterns
- import compatibility with Claude Code agents

## Safety / autonomy model

Docs and local settings show a built-in autonomy system:

- `auto-low`
- `auto-medium`
- `auto-high`

Docs state:

- file tools auto-run at low risk
- execute commands carry explicit risk ratings and justifications
- dangerous patterns still force confirmation

Observed local settings also include:

- command allowlist
- command denylist
- `enableDroidShield: true`

## Plugin architecture

Factory has a public plugin marketplace repo:

- `Factory-AI/factory-plugins`

Observed locally:

- installed plugin source is `factory-plugins`
- preinstalled plugin: `core@factory-plugins`
- marketplace metadata points to GitHub repo `Factory-AI/factory-plugins`

Marketplace README says plugins can contain:

- skills
- droids
- commands
- `mcp.json`
- hooks

This makes the harness reasonably extensible even though the core runtime is closed.

## Usefulness Assessment

## Are the subagents useful?

Yes, but mostly in a **workflow-engineering** sense rather than as a novel agent architecture.

What looks genuinely useful:

- markdown-defined subagents are easy to author, version, and share
- per-droid tool restrictions are a clean safety boundary
- “fresh context” delegation helps keep parent sessions smaller
- the mission/review/test-validator examples show a credible pattern for enterprise QA and code review
- compatibility/import from Claude Code subagents lowers switching cost
- headless `droid exec` plus machine-readable output formats make the harness scriptable in CI and automation contexts

What looks less impressive:

- the subagent mechanism appears prompt-and-tooling orchestration, not a deeper planner/executor research contribution
- much of the value comes from packaging, policy, and UX rather than a unique harness primitive
- if the Task tool is just a standard spawn/delegate wrapper, the innovation is operational polish more than capability

## Who would be a good judge?

Best judges:

- staff/principal engineers running large internal codebases
- developer productivity / platform teams
- CI/review workflow owners
- benchmarkers who care about long-horizon engineering automation rather than toy coding tasks

Less ideal judges:

- people looking only for “can it solve a LeetCode-style codegen task?”
- people evaluating only model quality independent of harness ergonomics

## What would they likely say?

A strong internal-tools or devprod judge would probably say:

- Factory’s custom droids are useful because they turn repeatable org workflows into versioned reusable helpers.
- The value is highest for review, validation, rollout, and bounded parallel work.
- The usefulness depends heavily on whether the parent agent chooses good delegation boundaries.
- In harness terms, this is a solid enterprise orchestration feature, not evidence that the underlying agent is fundamentally smarter.

A benchmark-oriented judge would probably say:

- The subagent system is directionally good and likely helps on longer tasks.
- The important question is not “does it have subagents?” but “how reliably does the parent invoke them, with the right tool budget and the right isolation?”
- Without access to the harness source, it is hard to evaluate how much of the performance comes from prompting vs orchestration logic vs model choice.

## Practical RE Notes

- Treat Factory as a closed-source Bun/TS-adjacent binary with public docs.
- High-value RE surfaces are:
  - installer script
  - `strings` on `droid`
  - `~/.factory/settings.json`
  - `~/.factory/droids/*.md`
  - `~/.factory/sessions/**/*.jsonl`
  - `~/.factory/artifacts/tool-outputs/*.log`
  - `~/.factory/plugins/*`
- Safe CLI probing should be wrapped with a timeout equivalent; `timeout` was not installed on this machine, so a Python `subprocess.run(..., timeout=10)` wrapper was used instead.

## Sources

- `https://app.factory.ai/cli`
- `https://github.com/Factory-AI/factory`
- `https://raw.githubusercontent.com/Factory-AI/factory/main/README.md`
- `https://github.com/Factory-AI/factory-plugins`
- `https://docs.factory.ai/cli/configuration/custom-droids`
- `https://docs.factory.ai/cli/configuration/skills`
- `https://docs.factory.ai/cli/droid-exec/overview`
- `https://docs.factory.ai/cli/user-guides/auto-run`
- local install: `~/.local/bin/droid`
- local state: `~/.factory/`
