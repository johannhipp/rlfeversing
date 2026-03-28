# aider-proxy

Minimal reverse proxy for capturing the OpenAI-compatible traffic that Aider sends to its model provider.

It logs each request/response exchange to `../targets/aider/proxy-traffic.jsonl` and stores raw bodies under `../targets/aider/proxy-bodies/`.
The JSONL log keeps compact metadata by default: headers, body paths, payload sizes, SHA-256 digests, and parsed JSON summaries. That makes real captures much easier to skim than duplicating every full body inline.

## Usage

Run the proxy:

```sh
python3 server.py --port 18457
```

Point Aider at it:

```sh
aider \
  --model openai/gpt-4o-mini \
  --openai-api-key "$OPENAI_API_KEY" \
  --openai-api-base http://127.0.0.1:18457/v1 \
  --message "Say hello in one sentence."
```

The proxy forwards to `https://api.openai.com/v1` by default. Override that with `--upstream` if you want to target another OpenAI-compatible backend.

By default the proxy forces `Accept-Encoding: identity` upstream so the response bodies it logs stay human-readable instead of arriving as compressed blobs. If you want exact header pass-through, start it with `--preserve-accept-encoding`.

If you explicitly want the JSONL log to embed base64 request/response bodies as well as writing them to disk, start the proxy with `--inline-bodies`.

For a full one-shot capture outside the RE sandbox, use the wrapper:

```sh
./run_capture.sh "Say hello in one sentence."
```

That script sources `../.env`, starts the proxy, runs a non-interactive `aider --message ...` invocation through `--openai-api-base`, and writes:

- `../targets/aider/proxy-traffic.jsonl`
- `../targets/aider/proxy-bodies/`
- `../targets/aider/proxy-server.stdout.log`
- `../targets/aider/proxy-server.stderr.log`

The wrapper clears any previous `proxy-traffic.jsonl`, `proxy-bodies/`, and proxy stdout/stderr logs first so each run leaves a clean capture set.

If `aider` is not the right binary name on your machine, set `AIDER_BIN`:

```sh
AIDER_BIN=aider ./run_capture.sh "Say hello in one sentence."
```

If the shell command is missing but you have the Python package installed, the wrapper now falls back automatically to `python3 -m aider`. You can also force any multi-word launcher prefix explicitly:

```sh
AIDER_CMD_PREFIX="python3 -m aider" ./run_capture.sh "Say hello in one sentence."
```

That same override also works for package-manager launchers:

```sh
AIDER_CMD_PREFIX="uvx --from aider-chat aider" ./run_capture.sh "Say hello in one sentence."
```

For offline verification in environments where loopback binds are blocked, run:

```sh
python3 verify_offline.py
```

That runs the local `unittest` suite plus `server.py --help` and `bash -n run_capture.sh`, so the full offline deliverable is checked without starting a listener.

You can also run the tests directly:

```sh
python3 -m unittest discover -s . -p 'test_server.py'
```

## HTTPS listener

If the client insists on HTTPS locally, provide a certificate and key:

```sh
python3 server.py \
  --port 18457 \
  --cert-file ./cert.pem \
  --key-file ./key.pem
```

Then point Aider at `https://127.0.0.1:18457/v1`.

## Notes

- This is a reverse proxy, not a generic `CONNECT` proxy. It is meant for clients like Aider that let you set a custom OpenAI-compatible base URL.
- Unlike the `amp-proxy` capture stub, this proxy forwards real upstream traffic. Aider needs valid provider responses to finish a one-shot run, so a pure fake-200 capture server is not sufficient here.
- Because Aider is open-source and provider-configurable, the right proxy seam is the model provider base URL rather than a harness-specific remote endpoint.
- Sensitive headers such as `Authorization` are redacted in the JSON log, and raw request/response bodies are stored on disk rather than duplicated inline by default.
- In this sandbox, loopback listeners are blocked and `aider` is not installed on `PATH`, so live capture has to be run outside the restricted harness with `./run_capture.sh`.
- The runner supports both the standalone `aider` executable and the Python-module form `python3 -m aider`, which matches Aider's documented installation/launch patterns.
