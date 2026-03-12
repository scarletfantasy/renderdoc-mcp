from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from renderdoc_mcp.backend import DEFAULT_BACKEND, current_backend_name
from renderdoc_mcp.install import install_extension


@lru_cache(maxsize=1)
def prepare_runtime() -> Path | None:
    if current_backend_name() == DEFAULT_BACKEND:
        return install_extension()
    return None
