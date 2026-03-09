from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from renderdoc_mcp.install import install_extension


@lru_cache(maxsize=1)
def prepare_runtime() -> Path:
    return install_extension()
