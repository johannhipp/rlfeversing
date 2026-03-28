# cursor-proxy

Minimal reverse proxy for reverse-engineering Cursor Agent network traffic.

It listens locally, forwards to the real Cursor backend, and logs sanitized HTTP exchanges plus raw request and response bodies under `../targets/cursor/`.

Usage:

```sh
python3 server.py
```

Cursor Agent resolves its backend from `CURSOR_API_ENDPOINT`, which falls back to `https://api2.cursor.sh` in the shipped bundle. The same bundle also uses `CURSOR_API_BASE_URL` for auth/login flows. Point the harness at the proxy by overriding both:

```sh
CURSOR_API_ENDPOINT="http://127.0.0.1:18457" \
CURSOR_API_BASE_URL="http://127.0.0.1:18457" \
  ~/.local/bin/cursor-agent models
```

For a reproducible capture run, use the wrapper:

```sh
./run_capture.sh
```

That script follows the repo convention of sourcing `../.env`, starts the proxy, exports `CURSOR_API_ENDPOINT`, and runs one of:

- `cursor-agent models` by default
- `cursor-agent status` when `CAPTURE_MODE=status`
- `cursor-agent -p --output-format json <prompt>` when `CAPTURE_MODE=prompt`

Artifacts:

- `../targets/cursor/proxy-exchanges.jsonl`
- `../targets/cursor/proxy-requests/`
- `../targets/cursor/proxy-responses/`
- `../targets/cursor/proxy-server.stdout.log`
- `../targets/cursor/proxy-server.stderr.log`
- `../targets/cursor/cursor-agent.stdout.log`
- `../targets/cursor/cursor-agent.stderr.log`

Offline validation:

```sh
cd cursor-proxy && python3 -m unittest test_server.py
```

Notes:

- The default upstream is `https://api2.cursor.sh`.
- The proxy is implemented as a reverse proxy, not a generic `HTTP_PROXY` tunnel, because Cursor exposes a direct base-URL override.
- `run_capture.sh` performs a direct bind preflight before starting the proxy, then polls `/health` before launching Cursor. That makes loopback policy failures explicit before you spend time debugging Cursor itself.
- `models` is the safest default probe, but it still requires valid Cursor auth. On this machine there is no `CURSOR_API_KEY` in `.env`, and direct unauthenticated probes fell back into a macOS keychain path.
- In this RE sandbox, local TCP binds are blocked. A direct `socket.bind(("127.0.0.1", 18459))` probe failed with `PermissionError: [Errno 1] Operation not permitted`, so live capture must be run outside the restricted harness even though the proxy repo is ready.
