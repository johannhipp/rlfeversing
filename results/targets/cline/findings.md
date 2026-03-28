# Cline Findings

## Verdict

Cline's harness is open-source.

Primary evidence:

- Public GitHub repo: <https://github.com/cline/cline>
- License: Apache-2.0
- Public package metadata points `repository.url` at `https://github.com/cline/cline`, declares `license: Apache-2.0`, and ships both the extension and `cli` workspace from the same repo.

## What the Harness Is

Cline is an IDE/CLI coding-agent harness with a tool-driven loop. The public repo contains:

- VS Code extension source
- CLI source
- Prompt/tool registration code
- Docs describing subagents, tools, approvals, and headless mode

The package metadata identifies the extension entrypoint as `./dist/extension.js`, declares a `cli` workspace, and points `repository.url` at `https://github.com/cline/cline`.

## Tool Calling Architecture

The clearest source path is:

- `src/core/prompts/system-prompt/tools/`

This directory contains one file per built-in tool plus a registry/index. The repo's own README for that directory says each tool exports a `{toolName}_variants` array and that the registration system collects all variants into `ClineToolSet`.

Built-in tools visible from the source and docs include:

- `read_file`
- `write_to_file`
- `replace_in_file`
- `search_files`
- `list_files`
- `list_code_definition_names`
- `execute_command`
- `apply_patch`
- `browser_action`
- `use_mcp_tool`
- `access_mcp_resource`
- `web_fetch`
- `web_search`
- `use_skill`
- `new_task`
- `use_subagents`
- interaction/meta tools such as `ask_followup_question`, `attempt_completion`, `plan_mode_respond`, `act_mode_respond`, `focus_chain`, and `load_mcp_documentation`

This means the harness is not hiding its agent loop behind a closed binary. The control surface is mostly defined as prompt-visible tools, then wired into the runtime through the tool registry.

One useful nuance from the public docs: Cline's tool layer is at least partly prompt-driven rather than purely API-native function calling. The tools reference shows examples in XML-like tags such as `<write_to_file>...</write_to_file>` and `<execute_command>...</execute_command>`, which indicates the default harness contract is "tool schemas described to the model in prompt space, then parsed/executed by the runtime." Cline also documents a separate "Native Tool Call (Experimental)" setting for some providers/models, so native tool calling exists, but it is not the whole story of how the harness works today.

## Subagents

Subagents are real and first-class in the public harness.

Evidence:

- Docs page: <https://docs.cline.bot/features/subagents>
- Tool source: `src/core/prompts/system-prompt/tools/subagent.ts`

What the source/docs show:

- Tool name is `use_subagents`
- The tool can launch up to five subagents in parallel
- The tool description calls them "in-process subagents", so this is harness-level parallel delegation inside the same runtime, not an external worker protocol
- The source gates the tool behind `context.subagentsEnabled === true && !context.isSubagentRun`
- The source-level parameter surface is five prompt slots: `prompt_1` through `prompt_5`
- Each subagent gets its own prompt, context window, and token budget
- The public docs say each subagent returns a detailed report plus per-subagent tool, token, and cost stats in the UI
- Subagents are read-only research workers
- They can:
  - read files
  - list files
  - search files
  - list code definition names
  - run read-only shell commands
  - use skills
- They cannot:
  - edit files
  - apply patches
  - use the browser
  - access MCP servers
  - perform web searches
  - spawn nested subagents

Important behavioral note: Cline does not automatically choose subagents. The user must enable the feature and ask for them explicitly.

Approval note from the public docs: subagent launches follow the same "Read project files" auto-approve path. If that auto-approve permission is on, launches are auto-approved; otherwise Cline asks for approval before launching them.

## How It Gets Things Done

At a harness level, Cline gets work done through a relatively standard but capable tool loop:

1. The model is prompted with a tool schema derived from registered tool variants.
2. The model emits tool calls such as `read_file`, `replace_in_file`, or `execute_command`.
3. The harness executes the tool, often behind approval gates.
4. Results are returned to the model and the loop continues until `attempt_completion`.

Notable implementation/behavior details exposed by the public source/docs:

- `execute_command` includes an explicit `requires_approval` parameter.
- `execute_command` also has model-family-specific variants, which is evidence that Cline adapts the tool contract per provider/model family instead of exposing one universal schema.
- Tool descriptions vary by model family, so the same logical tool can have model-specific prompt text.
- `new_task` exists as a context-reset/handoff mechanism.
- MCP support is built in through `use_mcp_tool` and `access_mcp_resource`.
- Browser automation is built in through `browser_action`.
- Web fetch/search are also first-class tools in the registry.

## Are the Subagents Useful?

Yes, but narrowly.

Best use:

- parallel codebase reconnaissance
- onboarding to unfamiliar repos
- tracing cross-cutting concerns before editing
- reducing pressure on the main context window

Less useful for:

- implementation-heavy tasks
- end-to-end autonomous execution
- anything requiring edits, browser work, MCP, or nested delegation

My assessment: in this harness, subagents are useful as bounded research workers, not as fully capable worker agents. They look closer to "parallel read-only scouts" than to the stronger execution/delegation model used by more capable coding-agent harnesses.

## Who Would Be a Good Judge?

Best judges:

- maintainers or power users working in large, unfamiliar repositories
- people evaluating code-understanding throughput rather than raw task completion
- benchmark/evals authors studying multi-file discovery or context-efficiency

Likely weak judges:

- users expecting subagents to implement features independently
- anyone comparing them to full-capability delegated workers with write access

Inference from the sources: a strong judge here would be someone evaluating codebase-exploration quality rather than raw autonomous task completion. They would probably say Cline's subagents are legitimately useful for map-the-codebase work, but limited as "real delegation" because the harness intentionally strips them down to read-only investigation.

## What They Would Likely Say

Reasonable judge summary:

- Positive: "This is a sensible way to parallelize discovery without blowing the main context window."
- Negative: "These are not general-purpose worker agents; they are constrained research helpers."
- Context-specific: "Inside Cline's harness they fit the safety model well, but they do not materially increase execution autonomy."

## Practical Limitations Observed

The primary-source limitations are mostly deliberate design limits rather than accidental gaps:

- subagents are only available when the feature is enabled and the current run is not already a subagent run
- subagents are intentionally read-only and cannot recurse
- the docs explicitly say subagents are best for broad exploration and add unnecessary overhead on small, focused tasks

These do not make the harness weak. They do mean Cline's delegation model is optimized for safe parallel discovery, not for recursive autonomous execution.

## Closed-Source Path

Not needed for this target.

The main harness is already public, with source, docs, license, and tool definitions available. Reverse-engineering a packaged binary would add little value compared with reading the public implementation.

## Sources

- GitHub repo: <https://github.com/cline/cline>
- Raw package metadata: <https://raw.githubusercontent.com/cline/cline/main/package.json>
- Tools docs: <https://docs.cline.bot/tools-reference/all-cline-tools>
- Tools docs source: <https://raw.githubusercontent.com/cline/cline/main/docs/tools-reference/all-cline-tools.mdx>
- Subagents docs: <https://docs.cline.bot/features/subagents>
- Subagents docs source: <https://raw.githubusercontent.com/cline/cline/main/docs/features/subagents.mdx>
- Tool registry source: <https://raw.githubusercontent.com/cline/cline/main/src/core/prompts/system-prompt/tools/index.ts>
- Tool registry directory: <https://github.com/cline/cline/tree/main/src/core/prompts/system-prompt/tools>
- Subagent tool source: <https://raw.githubusercontent.com/cline/cline/main/src/core/prompts/system-prompt/tools/subagent.ts>
- Execute command tool source: <https://raw.githubusercontent.com/cline/cline/main/src/core/prompts/system-prompt/tools/execute_command.ts>
- Baseten provider docs mentioning Native Tool Call (Experimental): <https://docs.cline.bot/provider-config/baseten>
