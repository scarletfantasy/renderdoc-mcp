from __future__ import annotations

from typing import Any

from renderdoc_mcp.errors import RenderDocMCPError
from renderdoc_mcp.services.common import ServiceContext


class PixelQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def get_pixel_history(
        self,
        capture_path: str,
        texture_id: str,
        x: int,
        y: int,
        mip_level: int | None = 0,
        array_slice: int | None = 0,
        sample: int | None = 0,
    ) -> dict[str, Any]:
        try:
            params = self._normalize_pixel_params(texture_id, x, y, mip_level, array_slice, sample)
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched pixel history for the selected texture.")

        return self.context.run_tool(
            capture_path,
            "Fetched pixel history for the selected texture.",
            lambda normalized: self.context.capture_tool(normalized, "get_pixel_history", params),
        )

    def debug_pixel(
        self,
        capture_path: str,
        texture_id: str,
        x: int,
        y: int,
        mip_level: int | None = 0,
        array_slice: int | None = 0,
        sample: int | None = 0,
    ) -> dict[str, Any]:
        try:
            params = self._normalize_pixel_params(texture_id, x, y, mip_level, array_slice, sample)
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Debugged the selected pixel.")

        return self.context.run_tool(
            capture_path,
            "Debugged the selected pixel.",
            lambda normalized: self.context.capture_tool(normalized, "debug_pixel", params),
        )

    def _normalize_pixel_params(
        self,
        texture_id: str,
        x: int,
        y: int,
        mip_level: int | None,
        array_slice: int | None,
        sample: int | None,
    ) -> dict[str, Any]:
        return {
            "texture_id": self.context.normalize_required_string(texture_id, "texture_id"),
            "x": self.context.normalize_non_negative_int(x, "x"),
            "y": self.context.normalize_non_negative_int(y, "y"),
            "mip_level": self.context.normalize_non_negative_int(mip_level, "mip_level"),
            "array_slice": self.context.normalize_non_negative_int(array_slice, "array_slice"),
            "sample": self.context.normalize_non_negative_int(sample, "sample"),
        }
