from __future__ import annotations

import sys

from renderdoc_mcp.protocol import read_message, send_message


def main() -> int:
    send_message(
        sys.stdout,
        {
            "type": "hello",
            "backend": "native_python",
            "protocol_version": 1,
            "renderdoc_version": "",
        },
    )

    while True:
        try:
            request = read_message(sys.stdin)
        except ConnectionError:
            return 0

        request_id = request.get("id")
        method = str(request.get("method", ""))
        params = request.get("params", {}) or {}

        if method == "load_capture":
            payload = {"loaded": True, "filename": str(params.get("capture_path", ""))}
        else:
            payload = {"method": method, "params": params}

        send_message(sys.stdout, {"type": "response", "id": request_id, "result": payload})


if __name__ == "__main__":
    raise SystemExit(main())
