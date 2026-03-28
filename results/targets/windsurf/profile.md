# Windsurf Profile

## Status

- Verdict: closed-source harness
- Local install found: no
- Local CLI found: no (`which windsurf` returned not found)
- Public distribution model: downloadable macOS, Windows, and Linux binaries from Windsurf release pages

## What Windsurf Appears To Be

- Windsurf Editor is a proprietary VS Code fork with an embedded agentic assistant called Cascade.
- Public docs describe:
  - Code/Chat modes
  - tool calling
  - terminal execution
  - MCP integration
  - web/docs search
  - planning/todo support
  - memories/rules
  - skills
  - workflows
  - a specialized retrieval subagent called Fast Context

## Important Public Paths

- `~/.codeium/windsurf/mcp_config.json`
- `~/.codeium/windsurf/memories/`
- workspace workflows in `.windsurf/workflows/`
- workspace skills in `.windsurf/skills/`

## Environment Constraints

- DNS/network resolution is unavailable in the shell, so direct artifact download from Windsurf hosts was not possible here.
- No local Windsurf binary or app bundle was present to inspect with `strings` or `--help`.
