# r(lf)ersing

You have been assigned to reverse-engineer **{{TARGET}}**. Your working directory is `targets/{{TARGET}}/` — all output files go there.

Figure out if the harness is open-source or not.

## 1) Open-source

Fetch the source and figure out how it uses subagents, tool calls to get things done. Are these useful? Who would be a good judge of these? What would they say about their usefulness in the context of the harness?

## 2) Closed-source

Fetch the binary and try reverse-engineering it. If it's a bun/TS app (or adjacent), try starting out with `strings`. Try iteratively running the binary in non-interactive mode (figure out how to do that with `timeout 10 <binary> --help`). NEVER try just running it, since you might get lost in an interactive session. ALWAYS wrap possibly interactive commands with `timeout`, e.g. `timeout 10 <cmd>`.

Most proprietary apps allow you to set your own remote url (for amp, it's `amp.url` in the settings json), which means all traffic goes through there. If helpful, write your own proxy for the tool with its own git repo inside this root in the form `{{TARGET}}-proxy`. Use this one as a reference for `amp`, which is already fully reverse-engineered: https://github.com/johannhipp/amp-proxy

## Shared knowledge

As you progress, iterate on the reverse-engineering agent skill in `skill.md` — add techniques that helped you considerably, even dead ends. Furthermore, maintain `knowledgebase.md` with all knowledge you gained about your target (subagents, tools, architecture, etc.).

For both shared files: **read the file first** before writing. Other agents are editing them too. Maintain the existing structure, DONT break it for them.
