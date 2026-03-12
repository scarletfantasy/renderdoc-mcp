from __future__ import annotations

import sys

from renderdoc_mcp.protocol import send_message


def main() -> int:
    send_message(
        sys.stdout,
        {
            "type": "fatal",
            "error": {
                "code": "native_python_import_failed",
                "message": "boom",
                "details": {"reason": "synthetic"},
            },
        },
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
