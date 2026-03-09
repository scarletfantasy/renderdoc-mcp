from __future__ import annotations

import base64
from pathlib import Path


def encode_capture_path(path: str | Path) -> str:
    raw = str(Path(path)).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_capture_path(encoded_path: str) -> str:
    padding = "=" * (-len(encoded_path) % 4)
    raw = base64.urlsafe_b64decode((encoded_path + padding).encode("ascii"))
    return raw.decode("utf-8")
