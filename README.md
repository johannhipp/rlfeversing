# rlfeversing

Reverse engineering project for coding agent harnesses, built during Ralphthon SF on March 28th 2026. 

Burned through all $100 of OpenAI API credits in the process, therefore these are the results as of 14:13 PT.

My take: findings are sound but way too much of the usual AI gibberish language. I'd have to rewrite all of the `*.md` files to actually make these usefull :(

## Results

All output lives in [`results/`](results/):

- [`results/skill.md`](results/skill.md) — 194 cycles on this
- [`results/knowledgebase.md`](results/knowledgebase.md) — cross-agent findings, patterns, and dead ends
- [`results/targets/<name>/findings.md`](results/targets/) — per-agent detailed analysis
- [`results/<name>-proxy/`](results/) — proxy repos for intercepting agent traffic

### Targets analyzed

| Agent | Type | Proxy | Findings |
|-------|------|-------|----------|
| Claude Code | closed-source | ✅ | [findings](results/targets/claude-code/findings.md) |
| Codex | open-source | ✅ | [findings](results/targets/codex/findings.md) |
| Amp | closed-source | ✅ | [findings](results/targets/amp/findings.md) |
| Factory | closed-source | — | [findings](results/targets/factory/findings.md) |
| OpenCode | open-source | ✅ | [findings](results/targets/opencode/findings.md) |
| Cursor | closed-source | ✅ | [findings](results/targets/cursor/findings.md) |
| Windsurf | closed-source | — | [findings](results/targets/windsurf/findings.md) |
| Aider | open-source | ✅ | [findings](results/targets/aider/findings.md) |
| Cline | open-source | ✅ | [findings](results/targets/cline/findings.md) |
| Continue | open-source | ✅ | [findings](results/targets/continue/findings.md) |

## Architecture

```
┌─────────────────────────────────────────────────┐
│  YOU (Telegram)                                  │
│  - Send commands, receive status updates         │
│  - Kick off / stop / steer reverse engineering   │
└──────────────┬──────────────────────────────────┘
               │ Telegram Bot API
               ▼
┌─────────────────────────────────────────────────┐
│  OpenClaw                                        │
│  - Telegram bot remote interface                 │
│  - Orchestrator: reads targets.txt, assigns 1:1  │
│  - Spawns exactly 1 Codex per target (max 10)    │
│  - Creates targets/<name>/ + LOCK file per agent │
│  - Aggregates findings back to you               │
└──────────────┬──────────────────────────────────┘
               │ spawns
               ▼
┌─────────────────────────────────────────────────┐
│  Codex (×N, max 10)                              │
│  Each instance runs a RALF loop:                 │
│                                                  │
│   1. OBSERVE  – gather public info about target  │
│                 agent (docs, GitHub, npm, APIs,   │
│                 blog posts, changelogs)           │
│   2. HYPOTHESIZE – form theory about internals   │
│                    (system prompt, tool set,      │
│                     routing, guardrails)          │
│   3. PROBE    – craft inputs to test hypothesis  │
│                 (if interactive access exists)    │
│   4. ANALYZE  – compare expected vs actual        │
│   5. DOCUMENT – write findings to /targets/<name>│
│   6. LOOP     – refine or move to next aspect    │
│                                                  │
│  Follows instructions in prompt.md               │
└─────────────────────────────────────────────────┘
               │ writes
               ▼
┌─────────────────────────────────────────────────┐
│  /targets/<agent-name>/                          │
│  - LOCK             (created by OpenClaw on spawn│
│                      removed when worker exits)  │
│  - profile.md      (what we know)                │
│  - hypotheses.md   (current theories)            │
│  - probes.log      (inputs tried & results)      │
│  - findings.md     (confirmed findings)          │
└──────────────┬──────────────────────────────────┘
               │ feeds into
               ▼
┌─────────────────────────────────────────────────┐
│  Shared Knowledge Layer (all agents read+write)  │
│                                                  │
│  knowledgebase.md                                │
│  - Cross-agent patterns & commonalities          │
│  - Techniques that work / don't work             │
│  - Index of all findings across targets          │
│                                                  │
│  skill.md  (starts near-empty)                   │
│  - The evolving reverse-engineering playbook     │
│  - Agents READ this before each RALF cycle       │
│  - Agents WRITE to it when a technique proves    │
│    effective across ≥2 targets                   │
│  - Becomes the distilled "how to RE an agent"    │
└─────────────────────────────────────────────────┘
```

## Feedback Loops

### Skill Evolution
1. Each Codex worker **reads `skill.md`** at the start of every RALF cycle
2. When a technique consistently works (confirmed on ≥2 targets), the agent **appends it to `skill.md`**
3. When a technique fails repeatedly, the agent **notes it in `knowledgebase.md` → Techniques That Don't Work**
4. Over time, `skill.md` grows from empty into a battle-tested RE playbook

### Knowledge Aggregation
1. After each RALF cycle, the agent **updates `knowledgebase.md`** with new findings
2. Before starting a cycle, agents **check `knowledgebase.md`** to avoid duplicate work and learn from others
3. Cross-agent patterns (e.g., "all agents use markdown tool output") get promoted to the top

## Setup

### 1. OpenClaw + Telegram

```bash
# Install openclaw (assumes it's available)
# Configure with your Telegram bot token
export OPENCLAW_TELEGRAM_TOKEN=<your-token>
openclaw init --remote telegram
```

### 2. Codex as the worker

OpenClaw assigns targets centrally — **one Codex per target, no overlap**:

1. Reads `targets.txt`, iterates line by line
2. For each target: `mkdir -p targets/<name>`, writes `targets/<name>/LOCK`
3. Spawns a Codex instance scoped to that folder
4. On worker exit: removes `LOCK`

Each Codex gets:
- A target agent name via `--target` arg
- Access to `prompt.md` (the RALF loop instructions)
- A working directory scoped to `targets/<target>/`
- Read/write access to `skill.md` and `knowledgebase.md`

```bash
# OpenClaw spawns one worker per target like this:
./launch.sh claude-code
# launch.sh handles: mkdir, LOCK, {{TARGET}} substitution in prompt, cleanup
```

### 3. Target list

Edit `targets.txt` — one agent per line, max 10:

```
claude-code
codex
amp
factory
opencode
cursor
windsurf
aider
cline
continue
```

## File Structure

```
rlfeversing/
├── README.md
├── prompt.md            # RALF loop instructions
├── targets.txt          # agents to reverse engineer
├── openclaw.config.json # openclaw configuration
├── launch.sh            # per-target worker launcher
├── run.sh               # orchestrator (spawns all workers)
├── AGENTS.md            # openclaw agent instructions
└── results/             # all output from the RALF loops
    ├── skill.md          # evolving RE playbook
    ├── knowledgebase.md  # shared findings
    ├── targets/          # per-agent findings
    │   ├── claude-code/findings.md
    │   ├── codex/findings.md
    │   └── ...
    └── *-proxy/          # proxy repos for traffic interception
        ├── codex-proxy/
        ├── continue-proxy/
        └── ...
```
