# Windsurf Hypotheses

## Confirmed

- The main Windsurf harness is not open-source.
- Cascade uses a hybrid architecture with both:
  - remote model-backed reasoning
  - local/on-device operations for some reads and integrations
- Windsurf includes at least one explicit internal specialized subagent:
  - Fast Context for code retrieval

## Strong Inferences

- The core product is likely implemented as a proprietary layer on top of a VS Code fork, with local tool adapters for terminal, file/context retrieval, and MCP client behavior.
- Planning is split between the user-selected model and a background planning agent.
- Tool calling is constrained by explicit platform limits:
  - up to 20 tool calls per prompt for Cascade
  - Fast Context retrieval worker executes up to 8 parallel tool calls per turn over at most 4 turns with a restricted tool set

## Unverified

- Exact binary packaging layout on macOS/Linux
- Whether there is an unofficial CLI-only headless mode beyond PATH launching the editor
- Whether a user-configurable backend URL exists comparable to `amp.url`
