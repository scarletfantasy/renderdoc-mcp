from __future__ import annotations

from pathlib import Path
from typing import Any

from renderdoc_mcp.analysis.frame_analysis import MAX_PAGE_LIMIT, MAX_TIMING_EVENT_PAGE_LIMIT
from renderdoc_mcp.application.context import ApplicationContext
from renderdoc_mcp.application.response import attach_capture, ensure_meta
from renderdoc_mcp.errors import ReplayFailureError

SUPPORTED_RESOURCE_KINDS = {"all", "textures", "buffers"}
SUPPORTED_RESOURCE_SORT_OPTIONS = {"name", "size"}
SUPPORTED_BUFFER_ENCODINGS = {"hex", "base64"}
DEFAULT_RESOURCE_PAGE_LIMIT = 50
DEFAULT_PIXEL_HISTORY_LIMIT = 100
DEFAULT_BUFFER_READ_SIZE = 256
MAX_BUFFER_READ_SIZE = 4096
MAX_TEXTURE_PREVIEW_DIMENSION = 64
MAX_TEXTURE_PREVIEW_PIXELS = 1024
SUPPORTED_TEXTURE_EXPORT_TYPES = {
    ".dds": "DDS",
    ".hdr": "HDR",
    ".jpeg": "JPG",
    ".jpg": "JPG",
    ".png": "PNG",
}


class ResourceHandlers:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def renderdoc_list_resources(
        self,
        capture_id: str,
        kind: str = "all",
        cursor: int | str | None = None,
        limit: int | str | None = None,
        name_filter: str | None = None,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        normalized_kind = self.context.normalize_optional_string(kind) or "all"
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")
        normalized_name_filter = self.context.normalize_optional_string(name_filter)
        normalized_sort_by = (self.context.normalize_optional_string(sort_by) or "name").lower()

        if normalized_kind not in SUPPORTED_RESOURCE_KINDS:
            raise ReplayFailureError(
                "kind must be one of 'all', 'textures', or 'buffers'.",
                {"kind": normalized_kind},
            )
        if normalized_sort_by not in SUPPORTED_RESOURCE_SORT_OPTIONS:
            raise ReplayFailureError(
                "sort_by must be one of name or size.",
                {"sort_by": normalized_sort_by},
            )
        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_PAGE_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                {"limit": normalized_limit},
            )

        params: dict[str, Any] = {
            "kind": normalized_kind,
            "limit": normalized_limit or DEFAULT_RESOURCE_PAGE_LIMIT,
            "sort_by": normalized_sort_by,
        }
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor
        if normalized_name_filter:
            params["name_filter"] = normalized_name_filter

        session, result = self.context.capture_tool(capture_id, "list_resources", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_resource_summary(self, capture_id: str, resource_id: str) -> dict[str, Any]:
        normalized_resource_id = self.context.normalize_required_string(resource_id, "resource_id")
        session, result = self.context.capture_tool(
            capture_id,
            "get_resource_summary",
            {"resource_id": normalized_resource_id},
        )
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_pixel_history(
        self,
        capture_id: str,
        texture_id: str,
        x: int,
        y: int,
        mip_level: int | None = 0,
        array_slice: int | None = 0,
        sample: int | None = 0,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        params = self._normalize_pixel_params(texture_id, x, y, mip_level, array_slice, sample)
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")
        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (
            normalized_limit <= 0 or normalized_limit > MAX_TIMING_EVENT_PAGE_LIMIT
        ):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_TIMING_EVENT_PAGE_LIMIT),
                {"limit": normalized_limit},
            )
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor
        params["limit"] = normalized_limit or DEFAULT_PIXEL_HISTORY_LIMIT
        session, result = self.context.capture_tool(capture_id, "get_pixel_history", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_debug_pixel(
        self,
        capture_id: str,
        texture_id: str,
        x: int,
        y: int,
        mip_level: int | None = 0,
        array_slice: int | None = 0,
        sample: int | None = 0,
    ) -> dict[str, Any]:
        params = self._normalize_pixel_params(texture_id, x, y, mip_level, array_slice, sample)
        session, result = self.context.capture_tool(capture_id, "debug_pixel", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_texture_data(
        self,
        capture_id: str,
        texture_id: str,
        mip_level: int,
        x: int,
        y: int,
        width: int,
        height: int,
        array_slice: int = 0,
        sample: int = 0,
    ) -> dict[str, Any]:
        params = {
            "texture_id": self.context.normalize_required_string(texture_id, "texture_id"),
            "mip_level": self.context.normalize_non_negative_int(mip_level, "mip_level"),
            "x": self.context.normalize_non_negative_int(x, "x"),
            "y": self.context.normalize_non_negative_int(y, "y"),
            "width": self.context.normalize_positive_int(width, "width"),
            "height": self.context.normalize_positive_int(height, "height"),
            "array_slice": self.context.normalize_non_negative_int(array_slice, "array_slice"),
            "sample": self.context.normalize_non_negative_int(sample, "sample"),
        }

        if params["width"] > MAX_TEXTURE_PREVIEW_DIMENSION:
            raise ReplayFailureError(
                f"width must be less than or equal to {MAX_TEXTURE_PREVIEW_DIMENSION}.",
                {"width": params["width"]},
            )
        if params["height"] > MAX_TEXTURE_PREVIEW_DIMENSION:
            raise ReplayFailureError(
                f"height must be less than or equal to {MAX_TEXTURE_PREVIEW_DIMENSION}.",
                {"height": params["height"]},
            )
        if params["width"] * params["height"] > MAX_TEXTURE_PREVIEW_PIXELS:
            raise ReplayFailureError(
                f"width * height must be less than or equal to {MAX_TEXTURE_PREVIEW_PIXELS}.",
                {"width": params["width"], "height": params["height"]},
            )

        session, result = self.context.capture_tool(capture_id, "get_texture_data", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_buffer_data(
        self,
        capture_id: str,
        buffer_id: str,
        offset: int | str | None = 0,
        size: int | str | None = None,
        encoding: str | None = None,
    ) -> dict[str, Any]:
        normalized_size = self.context.normalize_optional_int(size, "size")
        normalized_encoding = (self.context.normalize_optional_string(encoding) or "hex").lower()
        params = {
            "buffer_id": self.context.normalize_required_string(buffer_id, "buffer_id"),
            "offset": self.context.normalize_non_negative_int(offset, "offset"),
            "size": normalized_size or DEFAULT_BUFFER_READ_SIZE,
            "encoding": normalized_encoding,
        }

        if params["size"] > MAX_BUFFER_READ_SIZE:
            raise ReplayFailureError(
                f"size must be less than or equal to {MAX_BUFFER_READ_SIZE}.",
                {"size": params["size"]},
            )
        if normalized_encoding not in SUPPORTED_BUFFER_ENCODINGS:
            raise ReplayFailureError(
                "encoding must be one of hex or base64.",
                {"encoding": normalized_encoding},
            )

        session, result = self.context.capture_tool(capture_id, "get_buffer_data", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_save_texture_to_file(
        self,
        capture_id: str,
        texture_id: str,
        output_path: str,
        mip_level: int = 0,
        array_slice: int = 0,
    ) -> dict[str, Any]:
        normalized_output_path = self.context.normalize_required_string(output_path, "output_path")
        params = {
            "texture_id": self.context.normalize_required_string(texture_id, "texture_id"),
            "output_path": normalized_output_path,
            "mip_level": self.context.normalize_non_negative_int(mip_level, "mip_level"),
            "array_slice": self.context.normalize_non_negative_int(array_slice, "array_slice"),
        }

        extension = Path(normalized_output_path).suffix.lower()
        if extension not in SUPPORTED_TEXTURE_EXPORT_TYPES:
            raise ReplayFailureError(
                "output_path must end in one of: .dds, .hdr, .jpeg, .jpg, .png.",
                {"output_path": normalized_output_path},
            )

        session, result = self.context.capture_tool(capture_id, "save_texture_to_file", params)
        return attach_capture(ensure_meta(result), session)

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
