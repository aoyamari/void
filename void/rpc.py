"""Minimal NEAR JSON-RPC client for read-only contract view calls."""
from __future__ import annotations

import base64
import json
import os
import time

import requests

DEFAULT_RPC = os.environ.get("NEAR_RPC_URL", "https://rpc.mainnet.fastnear.com")


class ViewError(RuntimeError):
    pass


class Rpc:
    def __init__(self, url: str = DEFAULT_RPC, retries: int = 5, timeout: int = 30):
        self.url = url
        self.retries = retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "void-near-thesis/0.1"

    def view(self, account_id: str, method: str, args: dict | None = None):
        payload = {
            "jsonrpc": "2.0", "id": "void", "method": "query",
            "params": {
                "request_type": "call_function", "finality": "final",
                "account_id": account_id, "method_name": method,
                "args_base64": base64.b64encode(json.dumps(args or {}).encode()).decode(),
            },
        }
        delay = 1.0
        for attempt in range(self.retries):
            try:
                r = self.session.post(self.url, json=payload, timeout=self.timeout)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code == 200:
                body = r.json()
                if "error" in body:
                    raise ViewError(json.dumps(body["error"])[:300])
                result = body.get("result", {})
                if "error" in result:  # contract panicked / method missing
                    raise ViewError(str(result["error"])[:300])
                return json.loads(bytes(result["result"]).decode() or "null")
            if r is not None and r.status_code not in (408, 429, 500, 502, 503, 504):
                raise ViewError(f"HTTP {r.status_code}: {r.text[:200]}")
            time.sleep(delay)
            delay = min(delay * 2, 30)
        raise ViewError(f"gave up after {self.retries} attempts: {account_id}.{method}")
