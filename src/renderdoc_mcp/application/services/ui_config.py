from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from renderdoc_mcp.paths import ui_config_path


class UIConfigRepository:
    def read(self, path: Path | None = None) -> dict[str, Any]:
        path = path or ui_config_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload
