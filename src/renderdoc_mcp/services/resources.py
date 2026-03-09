from __future__ import annotations

from typing import Any

from renderdoc_mcp.errors import ReplayFailureError
from renderdoc_mcp.services.common import ServiceContext

SUPPORTED_RESOURCE_KINDS = {"all", "textures", "buffers"}


class ResourceQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def list_resources(self, capture_path: str, kind: str = "all", name_filter: str | None = None) -> dict[str, Any]:
        kind = self.context.normalize_optional_string(kind) or "all"
        name_filter = self.context.normalize_optional_string(name_filter)

        if kind not in SUPPORTED_RESOURCE_KINDS:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "kind must be one of 'all', 'textures', or 'buffers'.",
                    {"kind": kind},
                ),
                "Resource listing failed.",
            )

        params: dict[str, Any] = {"kind": kind}
        if name_filter:
            params["name_filter"] = name_filter

        return self.context.run_tool(
            capture_path,
            "Listed capture resources.",
            lambda normalized: self.context.capture_tool(normalized, "list_resources", params),
        )
