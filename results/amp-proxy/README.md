# amp-proxy

Minimal local capture proxy for reverse-engineering the Amp CLI server protocol.

Usage:

```sh
python3 server.py
```

Requests are logged to `../targets/amp/proxy-requests.jsonl`, and raw bodies are written under `../targets/amp/proxy-bodies/`.
