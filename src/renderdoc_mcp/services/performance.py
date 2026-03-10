from __future__ import annotations

from typing import Any

from renderdoc_mcp.errors import RenderDocMCPError
from renderdoc_mcp.services.common import ServiceContext


class PerformanceQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def get_timing_data(self, capture_path: str, pass_id: str) -> dict[str, Any]:
        try:
            pass_id = self.context.normalize_required_string(pass_id, "pass_id")
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched GPU timing data for the selected pass.")

        return self.context.run_tool(
            capture_path,
            "Fetched GPU timing data for the selected pass.",
            lambda normalized: self.context.capture_tool(normalized, "get_timing_data", {"pass_id": pass_id}),
        )

    def get_performance_hotspots(self, capture_path: str) -> dict[str, Any]:
        return self.context.run_tool(
            capture_path,
            "Fetched performance hotspots for the active capture.",
            lambda normalized: self.context.capture_tool(normalized, "get_performance_hotspots"),
        )
