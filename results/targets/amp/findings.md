# Amp Findings

## Verdict

Amp is closed-source/publicly distributed, not open-source.

## Why This Looks Closed-Source

- The public npm package `@sourcegraph/amp` is published on npm, but npm lists its license as `none` rather than an OSS license.
- Web search did not surface a public repository for the Amp CLI itself. What is public is the manual, news posts, npm package, SDK, plugin API, and integrations.
- The locally installed CLI is a standalone Mach-O binary at `/Users/johann/.amp/bin/amp` (about 70 MB), symlinked from `/Users/johann/.local/bin/amp`.
- `strings` on that binary shows Bun compile markers such as `bun build --compile`, which is consistent with a bundled Bun executable rather than shipping readable TS/JS source.
- `otool -L` shows only system dylibs, again consistent with a self-contained compiled binary.
- Local probing did not reveal a readable source tree or shipped TS/JS runtime files alongside the executable. The practical artifact is the compiled binary plus local app-state JSON.
- The shipped CLI reports version `0.0.1774713864-g12539b (released 2026-03-28T16:08:27.304Z)` via `amp version`, but that version is surfaced by the compiled binary itself, not by a readable local source checkout.

## Local Artifact Notes

- Installed binary: `/Users/johann/.amp/bin/amp`
- Symlink: `/Users/johann/.local/bin/amp`
- Config path: `~/.config/amp/settings.json`
- Local state path: `~/.local/share/amp/`
- In this environment, `~/.config/amp/settings.json` contains:
  - `amp.url: http://localhost:18317`
  - `amp.dangerouslyAllowAll: true`

That confirms the project hint: Amp can be pointed at a custom backend/proxy through `amp.url`.

## Harness Architecture From Public Docs + Local CLI

### Subagents

- Generic subagents are exposed through the `Task` tool.
- The manual says each subagent gets its own context window and can edit files and run terminal commands.
- Limits: subagents are isolated, cannot talk to each other, cannot be steered mid-task, and the main agent only gets their final summary.
- Amp also has specialized subagents/tools:
  - `oracle`: a second-opinion reasoning/review agent, currently documented as GPT-5.4 with high reasoning.
  - `Librarian`: a remote-code-search subagent for public GitHub, selected private GitHub repos, and Bitbucket Enterprise.
  - Code review checks: `amp review` spawns a separate subagent for each configured review check.

### Tools / extensibility

- Built-in tools exist and are listed by `amp tools list` according to the manual, though that command timed out in this environment.
- Tool extensibility surfaces are strong:
  - Toolboxes: executable files exposed as tools via `AMP_TOOLBOX`
  - MCP servers: configured directly or bundled inside skills
  - Skills: project/user/global instruction bundles with optional resources and MCP configs
  - Plugins: Bun-run TypeScript/JavaScript code that can intercept tool calls (`tool.call`), register tools, and register commands
  - Painter: image generation/editing tool
- The plugin API is especially revealing: docs show `amp.on('tool.call', ...)`, `amp.registerTool(...)`, and `amp.registerCommand(...)`.

### CLI / modes / permissions

- `amp --help` succeeds under a hard timeout wrapper and exposes a lot of the harness surface directly:
  - commands: `threads`, `tools`, `review`, `skill`, `permissions`, `mcp`, `usage`, `update`
  - modes: `deep`, `free`, `large`, `rush`, `smart`
  - execute/programmatic flags: `--execute`/`-x`, `--stream-json`, `--stream-json-thinking`, `--stream-json-input`, `--archive`, `--label`
  - control/config flags: `--settings-file`, `--mcp-config`, `--dangerously-allow-all`
- `amp version` also succeeds under the same wrapper.
- `strings` on the binary independently exposes the same family of mode and flag names, which is useful corroboration when interactive probes are flaky.
- `amp permissions list --builtin`, `amp tools list`, `amp permissions --help`, `amp review --help`, and `amp skill --help` still did not complete within the same 10-second wrapper here, so the CLI is probeable but uneven.

## Are The Subagents / Tool Calls Useful?

Yes, in the context of Amp's harness, they look genuinely useful rather than decorative.

- Generic `Task` subagents are useful because Amp explicitly optimizes for preserving the main thread's context window while offloading bounded work.
- `oracle` is useful because it separates "coding" from "analysis/review/architecture" and uses a different model/system prompt for that second opinion.
- `Librarian` is useful because it turns cross-repo and external-library research into a first-class tool instead of forcing brittle shell/web-search improvisation.
- Per-check review subagents are useful because they parallelize review criteria and allow scoped tool access per check.
- Toolboxes, MCP, skills, and plugins are useful because they let teams add deterministic local capabilities and policy hooks without changing Amp's core.

The strongest negative is that these features are not free:

- Amp's own docs repeatedly note that `oracle` is slower and more expensive.
- The subagent note says specialized subagents previously failed when the distinction from search was unclear or when the main model simply refused to delegate.
- The manual says you may need to explicitly ask Amp to use `oracle` or `Librarian`, which implies imperfect automatic invocation.

My read: the mechanism is useful when the harness gives each agent/tool a crisp role, and less useful when role boundaries blur.

## Directly Observed Local Evidence

The docs are not the only evidence. Amp's local thread/state files expose real harness behavior:

- `~/.local/share/amp/threads/*.json` records tool-use events and usage metadata per message.
- In one local thread, assistant usage metadata explicitly records model `gpt-5.3-codex` for the main agent.
- The same thread corpus shows first-class tool names such as:
  - `Task`
  - `oracle`
  - `find_thread`
  - `read_thread`
  - `shell_command`
  - `Read`
  - `Bash`
  - `Grep`
  - `glob`
  - `skill`
  - `read_github`
  - `search_github`
  - `list_directory_github`
  - `web_search`
  - `read_web_page`
- A quick count over local thread JSON found `Task` 70 times, `oracle` 27 times, `find_thread` 18 times, and `read_thread` 16 times. That is strong evidence these are real harness tools, not just documented concepts.
- The local corpus also shows concrete delegated/research patterns. For example, `read_thread` and `find_thread` are used to recover prior context across threads, and `Task` appears in active transcripts rather than only in docs.
- The thread corpus shows Amp using skills as an explicit mechanism (`skill` tool present in transcripts), which lines up with the manual's skill-loading model.

Some representative transcript examples from local thread JSON:

- In `~/.local/share/amp/threads/T-019d17a5-8282-76ef-a543-3c5f0ea8726b.json`, Amp issued two `Task` tool calls with long-form delegated edit prompts, including:
  - `description: "Remove fake agents and steps 4-6 from onboarding modal"`
  - `description: "Update onboarding wrapper and layout to create real session"`
- In `~/.local/share/amp/threads/T-019d18ad-971a-71be-85f5-1f26d129ed2a.json`, Amp issued an `oracle` tool call with a long architecture/reasoning task about conversation history in a Daytona sandbox runner.
- In `~/.local/share/amp/threads/T-019d1c54-b7c6-711f-8483-7008a4f8a1b3.json`, Amp used `read_thread` with a structured goal to inspect the end of a previous session for crash causes.
- In `~/.local/share/amp/threads/T-019d1e3c-8096-7326-b666-9e9de72fceb5.json`, Amp used `find_thread`, `read_thread`, `web_search`, and `read_web_page` together in one workflow to recover prior context and fetch external docs.

That combination makes the harness shape much clearer:

- `Task` is not just a marketing term; it carries detailed delegated work items.
- `oracle` is not just branding; it is invoked as a specialized reasoning/review tool with its own task payload.
- `find_thread` / `read_thread` are real thread-memory primitives, not just UI search affordances.
- `web_search` / `read_web_page` appear as first-class tool calls in the same transcript format as local tools.

## Directly Observed Tool Surface From Local Transcripts

Across the local thread corpus, the most common recorded tool names were:

- `Read`
- `Grep`
- `edit_file`
- `glob`
- `Bash`
- `read_github`
- `list_directory_github`
- `create_file`
- `search_github`
- `list_repositories`
- `web_search`
- `read_web_page`
- `finder`
- `skill`

That makes Amp look like a serious multi-tool harness with local FS tools, shell execution, repo-hosted code search, thread memory tools, skills, and specialist delegation.

## Persisted Edit Artifacts

Amp also persists a second high-value local artifact surface under `~/.amp/file-changes/`.

- The directory currently contains hundreds of JSON files organized by thread ID and keyed by tool-use IDs.
- These files are not opaque blobs; they are readable JSON containing fields such as:
  - `uri`
  - `before`
  - `after`
  - `diff`
  - `isNewFile`
  - `reverted`
  - `timestamp`
- For example, `~/.amp/file-changes/T-019d17a5-8282-76ef-a543-3c5f0ea8726b/toolu_01CHAhcvjs4d9R8qhuQtyMFU.72595378-f6f7-4b3d-ad64-84fa9680e9c9` stores a concrete before/after/diff record for an edit to `apps/dashboard/app/(dashboard)/layout.tsx`.

This is useful for RE because it lets you map transcript tool-use IDs to concrete file modifications even though the core runtime is closed-source.

## Who Would Be Good Judges?

- Power users doing long multi-file tasks in real repos. They can judge whether subagents actually reduce context blowups and unblock complex work.
- Team leads / repo owners writing review checks. They can judge whether per-check review subagents find issues that linters and ordinary reviews miss.
- Toolsmiths building MCP servers, toolbox scripts, or plugins. They can judge whether Amp's extensibility surfaces are practical and predictable.
- Competing harness builders / evaluator authors. They are good judges of whether these are real harness advantages or mostly prompt-layer marketing.

## What Would Those Judges Likely Say?

- Power users would probably say the subagents are useful when work decomposes cleanly and the harness keeps the main thread focused.
- Review-focused engineers would probably say `oracle` and per-check review agents are useful because code review is exactly where second-opinion and read-only analysis models pay off.
- Toolsmiths would likely rate Amp highly on extensibility. Toolboxes, skills, MCP, and plugins give several distinct ways to add capability or policy.
- Harness/evals people would likely say Amp has a serious orchestration layer, not just a single-agent shell wrapper. The evidence is the documented `Task` tool, specialist agents, per-check review fan-out, and the plugin/tool policy surfaces.
- Skeptics would still point out that the core is proprietary and hard to audit. We can see documented behavior and some local policy/config surfaces, but not the actual source for orchestration, prompts, or server-side tool routing.

## Best RE Techniques For Amp So Far

- Use a hard timeout wrapper on every probe. On this machine, `perl -e 'alarm shift; exec @ARGV' 10 amp --help` and `amp version` worked, while `amp tools list` and `amp permissions list --builtin` still hung.
- Don’t skip top-level help entirely. Contrary to the first pass, `amp --help` turned out to be one of the highest-signal local artifacts because it exposes commands, modes, execute flags, MCP wiring, and settings paths in one shot.
- Read the manual and news posts; Amp documents its harness surprisingly openly.
- Inspect `~/.config/amp/settings.json` for `amp.url`.
- Treat the local binary as a Bun-compiled executable first; `strings` yields more than trying to force the TUI.
- Mine `~/.local/share/amp/threads/*.json` before deeper binary reversing. Those transcripts expose actual tool names, model metadata, thread-reading tools, and evidence that `Task`/`oracle` are used in practice.
- Mine `~/.amp/file-changes/` as a second evidence source. It confirms that Amp persists per-tool artifacts locally even though the runtime itself is closed, and the JSON includes exact `before`/`after`/`diff` content keyed by tool-use IDs.

## Additional Direct CLI Evidence

- `amp --help` confirms first-class support for:
  - thread management (`new`, `continue`, `list`, `search`, `share`, `handoff`, `markdown`)
  - tool management (`list`, `show`, `make`, `use`)
  - skills, permissions, and MCP server configuration
  - execute mode with Claude Code-compatible `--stream-json`
- The settings reference embedded in `amp --help` confirms:
  - `amp.mcpServers`
  - `amp.permissions`
  - `amp.tools.disable`
  - `amp.tools.enable`
  - `amp.toolbox.path`
  - `amp.skills.path`
  - `amp.proxy`
  - `amp.network.timeout`
  - `amp.experimental.modes`
- That is useful RE evidence because it shows the harness has real policy/config plumbing for tools and extensions even though the runtime is closed-source.

## Sources

- Amp manual: https://ampcode.com/manual
- Appendix: https://ampcode.com/manual/appendix
- Plugin API: https://ampcode.com/manual/plugin-api
- SDK: https://ampcode.com/manual/sdk
- Agents for the Agent: https://ampcode.com/notes/agents-for-the-agent
- Oracle: https://ampcode.com/news/oracle
- GPT-5.4, The New Oracle: https://ampcode.com/news/gpt-5.4-the-new-oracle
- Rush Mode: https://ampcode.com/news/rush-mode
- 50% Faster Search Agent: https://ampcode.com/news/faster-search-agent
- npm package metadata: https://www.npmjs.com/package/%40sourcegraph/amp
