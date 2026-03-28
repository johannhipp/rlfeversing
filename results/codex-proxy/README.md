# codex-proxy

Minimal reverse proxy for reverse-engineering Codex network traffic.

It listens locally, forwards to the real upstream API, and logs sanitized HTTP exchanges plus WebSocket handshakes and frame payloads under `../targets/codex/`.

Usage:

```sh
python3 server.py
```

Then point Codex at the proxy:

```sh
codex exec \
  -c 'openai_base_url="http://127.0.0.1:18456/v1"' \
  --skip-git-repo-check \
  --sandbox read-only \
  --json \
  'Say hello in one sentence.'
```

For a reproducible outside-sandbox capture run, use the wrapper:

```sh
./run_capture.sh "Say hello in one sentence."
```

That script sources `../.env`, starts the proxy, runs `codex exec` through `openai_base_url`, and writes:

- `../targets/codex/proxy-requests.jsonl`
- `../targets/codex/proxy-bodies/`
- `../targets/codex/proxy-server.stdout.log`
- `../targets/codex/proxy-server.stderr.log`

The proxy normalizes the forwarded path so this default setup works correctly when Codex sends requests like `/v1/responses` to the local listener. Without that normalization, forwarding to the default upstream `https://api.openai.com/v1` would incorrectly duplicate the prefix as `/v1/v1/responses`.

This matters for Codex specifically because current builds do not just send plain HTTP to `/v1/responses`; they attempt a WebSocket connection on the same base URL. The proxy therefore captures:

- normal HTTP request/response bodies
- WebSocket handshake metadata
- best-effort decoded WebSocket message payloads in both directions

HTTPS listener mode is optional:

```sh
python3 server.py --cert-file cert.pem --key-file key.pem
```

Offline validation:

```sh
python3 -m unittest test_server.py
```

Artifacts:

- `../targets/codex/proxy-requests.jsonl`
- `../targets/codex/proxy-bodies/`

Notes:

- In the current Codex CLI, `-c 'openai_base_url="http://127.0.0.1:18456/v1"'` is enough to redirect the upstream.
- The sandbox used for this RE project blocks local TCP binds. A direct Python `socket.bind(("127.0.0.1", ...))` probe failed with `PermissionError: [Errno 1] Operation not permitted`, so live capture must be run outside that restricted harness even though the proxy itself is ready.
