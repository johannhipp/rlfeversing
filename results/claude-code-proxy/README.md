# claude-code-proxy

Minimal local capture proxy for reverse-engineering Claude Code's Anthropic API traffic.

Usage:

```sh
python3 server.py
```

Point Claude Code at the proxy with `ANTHROPIC_BASE_URL=http://127.0.0.1:18441`.

For a reproducible capture run outside this sandbox:

```sh
./run_capture.sh
```

Offline verification in this sandbox:

```sh
python3 -m unittest discover -s tests -v
python3 server.py --help
```

Requests are logged to `../targets/claude-code/proxy-requests.jsonl`, responses to
`../targets/claude-code/proxy-responses.jsonl`, and raw bodies under
`../targets/claude-code/proxy-bodies/`.

Notes:

- The proxy forwards to `https://api.anthropic.com` by default and now supports optional HTTPS listener mode via `--https-port`, `--cert`, and `--key`.
- Upstream requests force `Accept-Encoding: identity` by default so captured response bodies stay readable. Pass `--preserve-accept-encoding` if you need the original compression behavior.
- Claude Code disables optimistic Tool Search on non-first-party `ANTHROPIC_BASE_URL` hosts. If your proxy forwards `tool_reference` blocks, set `ENABLE_TOOL_SEARCH=true`.
- `run_capture.sh` sources the repo `.env`, waits for the local `/health` endpoint, and runs a safe non-interactive `claude -p` probe through the proxy. By default it keeps your current `HOME` so existing Claude auth can be reused; set `CLAUDE_HOME=/path/to/home` if you want an isolated state directory.
- In this Codex sandbox, binding a local listener on `127.0.0.1` is blocked by policy, so real capture has to be run on a less restricted host.
