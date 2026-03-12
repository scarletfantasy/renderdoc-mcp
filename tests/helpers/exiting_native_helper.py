from __future__ import annotations

import sys

from renderdoc_mcp.protocol import send_message


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
