from __future__ import annotations

import os
from pathlib import Path

from renderdoc_mcp.errors import RenderDocNotInstalledError


def user_qrenderdoc_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set")
    return Path(appdata) / "qrenderdoc"


def extension_install_dir() -> Path:
    return user_qrenderdoc_dir() / "extensions" / "renderdoc_mcp_bridge"


def ui_config_path() -> Path:
    return user_qrenderdoc_dir() / "UI.config"


def resolve_qrenderdoc_path() -> Path:
    override = os.environ.get("RENDERDOC_QRENDERDOC_PATH")
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise RenderDocNotInstalledError(str(path))

    default_path = Path(r"C:\Program Files\RenderDoc\qrenderdoc.exe")
    if default_path.is_file():
        return default_path

    raise RenderDocNotInstalledError(str(default_path))
