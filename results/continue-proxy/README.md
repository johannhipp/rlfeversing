# continue-proxy

Minimal capture proxy for reverse-engineering Continue CLI model traffic.

It listens locally, forwards requests to an upstream OpenAI-compatible API, and writes one JSONL exchange record plus raw request/response bodies for every call.

For RE convenience, forwarded requests force `Accept-Encoding: identity` so upstream JSON and SSE bodies are logged uncompressed by default.

## Usage

```sh
python3 server.py
```

Default paths:

- exchange log: `../targets/continue/proxy-exchanges.jsonl`
- request bodies: `../targets/continue/proxy-requests/`
- response bodies: `../targets/continue/proxy-responses/`
- Continue stdout: `../targets/continue/continue.stdout.log`
- Continue stderr: `../targets/continue/continue.stderr.log`
- server stdout/stderr can be redirected by the runner into `../targets/continue/`

## Continue Wiring

Continue CLI can be pointed at an OpenAI-compatible endpoint via model `apiBase`. A minimal config looks like:

```yaml
models:
  - name: local-proxy
    provider: openai
    model: gpt-4o-mini
    apiKey: dummy
    apiBase: http://127.0.0.1:18431/v1
```

Then run Continue headlessly against that config:

```sh
cn --config /absolute/path/to/config.yaml -p "say hello"
```

This repo also includes a project runner that follows the RE harness convention:

```sh
./run_capture.sh "say hello"
```

`run_capture.sh`:

- sources `../.env`
- writes `../targets/continue/proxy-config.yaml`
- starts the proxy
- polls `http://127.0.0.1:18431/health` before launching Continue
- clears prior request/response artifacts for a clean run
- runs `cn --config ... -p ...` through a hard timeout
- writes proxy and Continue logs into `../targets/continue/`

If Continue is not installed as a plain `cn` binary, the runner also accepts multi-word launchers:

```sh
CONTINUE_CMD='npx -y @continuedev/cli' ./run_capture.sh "say hello"
```

You can append fixed extra arguments with `CONTINUE_CMD_ARGS`.

Use `--upstream` if you want to forward to a real provider:

```sh
python3 server.py --upstream https://api.openai.com
```

Optional HTTPS listener:

```sh
python3 server.py --https-port 18432 --cert cert.pem --key key.pem
```

## Notes

- Default upstream is `https://api.openai.com`; override it with `UPSTREAM=... ./run_capture.sh`.
- `run_capture.sh` uses `CONTINUE_API_KEY` if set, otherwise `OPENAI_API_KEY`, otherwise `dummy`.
- `run_capture.sh` parses `CONTINUE_CMD` and `CONTINUE_CMD_ARGS` with shell-style quoting, so launchers such as `npx -y @continuedev/cli` work without editing the script.
- Offline verification is available with `python3 -m unittest discover -s . -p 'test_server.py'`.
- In the restricted RE sandbox used for this project, local TCP binds are blocked (`bind('127.0.0.1', ...) -> PermissionError: [Errno 1] Operation not permitted`), so live capture must be run outside the sandbox even though the proxy repo is ready.
