# cline-proxy

Minimal local reverse proxy for capturing Cline's OpenAI-compatible HTTP traffic.

The proxy:

- listens locally on HTTP by default
- forwards traffic to a configurable HTTP or HTTPS upstream
- logs each request/response exchange to `../targets/cline/proxy-exchanges.jsonl`
- stores raw request and response bodies under `../targets/cline/proxy-bodies/`
- preserves streaming responses such as `text/event-stream`
- redacts sensitive headers in logs by default

## Usage

Point the proxy at the real upstream you want to observe:

```sh
python3 server.py --upstream-base-url https://api.openai.com/v1
```

Then configure Cline to use the proxy as its Base URL:

```text
http://127.0.0.1:18421/v1
```

Examples:

```sh
python3 server.py --upstream-base-url https://api.openai.com/v1
python3 server.py --upstream-base-url https://openrouter.ai/api/v1
python3 server.py --upstream-base-url http://127.0.0.1:18555/v1
```

## Useful Flags

```sh
python3 server.py --help
```

Important options:

- `--mount-path /v1`: local path prefix the harness calls
- `--log ../targets/cline/proxy-exchanges.jsonl`: JSONL exchange log
- `--bodies-dir ../targets/cline/proxy-bodies`: directory for raw bodies
- `--upstream-api-key-env OPENAI_API_KEY`: replace the inbound `Authorization` header with a local env var
- `--insecure`: disable TLS verification for HTTPS upstreams
- `--cert-file` and `--key-file`: serve the proxy itself over HTTPS
- `--log-secrets`: disable header redaction in the JSONL log

## Wiring Cline

Use one of Cline's OpenAI-style providers:

- In the VS Code extension, choose `OpenAI` or `OpenAI Compatible`, then set `Base URL` to `http://127.0.0.1:18421/v1`.
- In the CLI, use the auth flow and pass `-b/--baseurl` with the same local URL.

If you already have a provider configured, only the Base URL needs to change. The proxy will forward the original request headers upstream unless `--upstream-api-key-env` is set.
