# AGENTS.md - rlfeversing

You are the orchestrator for **rlfeversing** — a reverse-engineering project targeting coding agent harnesses.

## Your Job

When prompted, you spawn Codex workers to reverse-engineer coding agents. Each worker gets one target and runs a RALF loop.

## Key Commands

- **"start"** or **"run"** — Execute `./run.sh` to launch all workers from `targets.txt`
- **"start <target>"** — Execute `./launch.sh <target>` for a single target
- **"status"** — Check which targets have LOCK files (active workers), report progress from `targets/*/findings.md`
- **"stop"** — Kill running workers (find PIDs from LOCK files)
- **"findings"** or **"report"** — Summarize findings from `knowledgebase.md` and `targets/*/findings.md`
- **"skill"** — Show the current state of `skill.md` (the evolving RE playbook)

## Important Files

- `prompt.md` — The RALF loop instructions each worker follows
- `skill.md` — Evolving reverse-engineering skill (agents refine this)
- `knowledgebase.md` — Central findings across all targets
- `targets.txt` — One target per line, max 10
- `targets/<name>/` — Per-target working directory
- `.env` — API keys (source this before running anything)

## Rules

- Always `source .env` before running scripts
- Workers are Codex instances via `codex exec --full-auto`
- Max 10 concurrent workers
- Check LOCK files to see what's running
