# r(lf)ersing

You have been assigned to reverse-engineer **{{TARGET}}**. Your working directory is `targets/{{TARGET}}/` — all output files go there.

**Before doing anything else**, read `targets/{{TARGET}}/findings.md` if it exists. If surface-level work (classification, docs, `strings`, tool listing) is already done, **do not repeat it**. Your job now is to build a `{{TARGET}}-proxy` repo — see the progression below.

## 1) Open-source

Fetch the source and figure out how it uses subagents, tool calls to get things done. Are these useful? Who would be a good judge of these? What would they say about their usefulness in the context of the harness?

## 2) Closed-source

Fetch the binary and try reverse-engineering it. If it's a bun/TS app (or adjacent), try starting out with `strings`. Try iteratively running the binary in non-interactive mode (figure out how to do that with `timeout 10 <binary> --help`). NEVER try just running it, since you might get lost in an interactive session. ALWAYS wrap possibly interactive commands with `timeout`, e.g. `timeout 10 <cmd>`.

Most proprietary apps allow you to set your own remote url (for amp, it's `amp.url` in the settings json), which means all traffic goes through there.

## 3) Build a proxy (DO THIS if findings.md already exists)

If `targets/{{TARGET}}/findings.md` already has classification and surface analysis, your primary task is now to **build `{{TARGET}}-proxy`**. This is not optional — it's the whole point of the project.

1. Create a new directory `{{TARGET}}-proxy/` at the repo root (NOT inside targets/)
2. `git init` inside it
3. Use https://github.com/johannhipp/amp-proxy as your reference implementation
4. Build a simple HTTP/HTTPS proxy that logs all requests and responses the harness makes
5. Configure the target harness to route through your proxy (find the config setting for custom URLs/endpoints)
6. Run the harness through the proxy and capture real traffic
7. Document what you learn in `targets/{{TARGET}}/findings.md`

If the target is open-source and doesn't have a redirectable URL setting, build a proxy that wraps its API calls to the LLM provider instead.

## Shared knowledge

As you progress, iterate on the reverse-engineering agent skill in `skill.md` — add techniques that helped you considerably, even dead ends. Furthermore, maintain `knowledgebase.md` with all knowledge you gained about your target (subagents, tools, architecture, etc.).

For both shared files: **read the file first** before writing. Other agents are editing them too. Maintain the existing structure, DONT break it for them.
