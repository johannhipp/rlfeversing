# opencode-proxy

Minimal local capture proxy for reverse-engineering opencode provider traffic.

Usage:

```sh
python3 server.py
```

This listens on `http://127.0.0.1:18456` by default, logs exchanges to `../targets/opencode/proxy-requests.jsonl`, and writes raw request/response bodies under `../targets/opencode/proxy-bodies/`.

The useful redirect surface is Opencode's provider config. The local install on this machine uses `~/.config/opencode/opencode.json`, and the shipped SDK typings expose `provider.<name>.options.baseURL` and `apiKey`.

To point Opencode at the proxy without editing the user's real config, create a temporary `XDG_CONFIG_HOME` with an `opencode/opencode.json` that sets:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "permission": "allow",
  "provider": {
    "openai": {
      "options": {
        "apiKey": "dummy-or-real-key",
        "baseURL": "http://127.0.0.1:18456/v1"
      }
    }
  }
}
```

On this machine, the real config already uses `provider.openai.api = "codex"`. The capture wrapper preserves that existing provider block and only overlays `options.baseURL`, `options.apiKey`, and `permission`, which is safer than replacing the provider definition wholesale.

Then run a safe non-interactive command through that config:

```sh
XDG_CONFIG_HOME="$PWD/.tmp-opencode-proxy/config" \
perl -e 'alarm shift; exec @ARGV' 60 \
  ~/.opencode/bin/opencode run \
  --print-logs \
  --format json \
  --model openai/gpt-5.2 \
  'Say hello in one sentence.'
```

For a reproducible outside-sandbox capture run, use:

```sh
./run_capture.sh "Say hello in one sentence."
```

That wrapper:

- sources `../.env`
- creates an isolated temporary `XDG_CONFIG_HOME`
- reads the real `~/.config/opencode/opencode.json` first when present
- starts the proxy
- runs `opencode run --format json` through `provider.openai.options.baseURL`
- writes capture artifacts into `../targets/opencode/`

Artifacts:

- `../targets/opencode/proxy-requests.jsonl`
- `../targets/opencode/proxy-bodies/`
- `../targets/opencode/proxy-server.stdout.log`
- `../targets/opencode/proxy-server.stderr.log`
- `../targets/opencode/opencode-run.stdout.log`
- `../targets/opencode/opencode-run.stderr.log`

The proxy forwards upstream to `https://api.openai.com` by default and falls back to stub OpenAI-compatible responses when upstream access is blocked. Stub mode covers `/v1/models`, `/v1/responses`, and `/v1/chat/completions`, which is enough to confirm routing and request shapes even without a live upstream.

Forwarded upstream requests force `Accept-Encoding: identity` so the logged response bodies stay readable.

Notes:

- Several Opencode CLI subcommands still try to reach `models.dev` during startup, even for `--help`.
- In this RE sandbox, local TCP bind is blocked (`PermissionError: [Errno 1] Operation not permitted` on `127.0.0.1`), so the live capture step has to be run outside the restricted harness even though the proxy and wrapper are ready.
