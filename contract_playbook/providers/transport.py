"""Fixed-purpose HTTP worker; no tool execution, redirects, proxies, or child processes."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from ..common import ReviewError, canonical, parse_json
from .contract import validate_endpoint


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise urllib.error.HTTPError(request.full_url, code, "Redirect denied", headers, response)


def main():
    try:
        data = parse_json(sys.stdin.buffer.read(128 * 1024 + 1), 128 * 1024)
        endpoint = validate_endpoint(data["endpoint"])
        raw = canonical(data["request"])
        if len(raw) > 96 * 1024:
            raise ValueError("Request exceeds byte limit.")
        timeout = data["socket_timeout"]
        if type(timeout) not in (int, float) or not 0 < timeout <= 15:
            raise ValueError("Invalid socket timeout.")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        request = urllib.request.Request(endpoint, data=raw,
                    headers={"Content-Type": "application/json"}, method="POST")
        with opener.open(request, timeout=timeout) as response:
            body = response.read(64 * 1024 + 1)
        result = {"ok": True, "response": parse_json(body, 64 * 1024)}
    except urllib.error.HTTPError as exc:
        result = {"ok": False, "error": f"HTTP {exc.code}", "retryable": exc.code in (502, 503, 504)}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        result = {"ok": False, "error": type(exc).__name__, "retryable": True}
    except ReviewError as exc:
        result = {"ok": False, "error": str(exc)[:400], "retryable": False, "protocol": True}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:400], "retryable": False}
    sys.stdout.buffer.write(canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

