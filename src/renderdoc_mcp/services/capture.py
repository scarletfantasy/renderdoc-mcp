from __future__ import annotations

from pathlib import Path
from typing import Any

from renderdoc_mcp.services.common import ServiceContext
from renderdoc_mcp.uri import decode_capture_path, encode_capture_path


class CaptureQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def get_capture_summary(self, capture_path: str) -> dict[str, Any]:
        return self.context.run_tool(
            capture_path,
            "Loaded capture summary from RenderDoc.",
            lambda normalized: self.context.capture_tool(normalized, "get_capture_summary"),
        )

    def analyze_frame(self, capture_path: str) -> dict[str, Any]:
        return self.context.run_tool(
            capture_path,
            "Analyzed the frame pass structure from RenderDoc.",
            lambda normalized: self.context.capture_tool(normalized, "analyze_frame"),
        )

    def recent_captures_resource(self) -> dict[str, Any]:
        config = self.context.read_ui_config()
        recent_paths = list(config.get("RecentCaptureFiles", []))
        captures = []

        for raw_path in recent_paths:
            path = Path(raw_path)
            captures.append(
                {
                    "path": str(path),
                    "exists": path.is_file(),
                    "encoded_path": encode_capture_path(path),
                }
            )

        return {"recent_captures": captures, "count": len(captures)}

    def capture_summary_resource(self, encoded_path: str) -> dict[str, Any]:
        return self.get_capture_summary(decode_capture_path(encoded_path))
