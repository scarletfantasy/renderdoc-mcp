from __future__ import annotations

from pathlib import Path
from typing import Any

from renderdoc_mcp.analysis.frame_analysis import MAX_PAGE_LIMIT, MAX_TIMING_EVENT_PAGE_LIMIT, RESOURCE_USAGE_KINDS
from renderdoc_mcp.application.command_specs import GetResourceSummaryCommand
from renderdoc_mcp.application.context import ApplicationContext
from renderdoc_mcp.application.response import attach_capture, ensure_meta
from renderdoc_mcp.errors import ReplayFailureError

SUPPORTED_RESOURCE_KINDS = {"all", "textures", "buffers"}
SUPPORTED_RESOURCE_USAGE_KINDS = {"all", *RESOURCE_USAGE_KINDS}
SUPPORTED_RESOURCE_SORT_OPTIONS = {"name", "size"}
SUPPORTED_BUFFER_ENCODINGS = {"hex", "base64"}
DEFAULT_RESOURCE_PAGE_LIMIT = 50
DEFAULT_PIXEL_HISTORY_LIMIT = 100
DEFAULT_BUFFER_READ_SIZE = 256
MAX_BUFFER_READ_SIZE = 4096
MAX_TEXTURE_PREVIEW_DIMENSION = 64
MAX_TEXTURE_PREVIEW_PIXELS = 1024
DEFAULT_SHADER_DEBUG_STATE_LIMIT = 32
MAX_SHADER_DEBUG_STATE_LIMIT = 128
DEFAULT_SHADER_DEBUG_CHANGE_LIMIT = 64
MAX_SHADER_DEBUG_CHANGE_LIMIT = 256
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
        command = GetResourceSummaryCommand.from_raw(self.context.normalizer, capture_id, resource_id)
        session, result = self.context.sessions.capture_tool_normalized(
            command.capture_id,
            "get_resource_summary",
            {"resource_id": command.resource_id},
        )
        return attach_capture(ensure_meta(result), session)

    def renderdoc_list_resource_usages(
        self,
        capture_id: str,
        resource_id: str,
        usage_kind: str = "all",
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        normalized_resource_id = self.context.normalize_required_string(resource_id, "resource_id")
        normalized_usage_kind = (self.context.normalize_optional_string(usage_kind) or "all").lower()
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")

        if normalized_usage_kind not in SUPPORTED_RESOURCE_USAGE_KINDS:
            raise ReplayFailureError(
                "usage_kind must be one of {}.".format(", ".join(sorted(SUPPORTED_RESOURCE_USAGE_KINDS))),
                {"usage_kind": normalized_usage_kind},
            )
        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_PAGE_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                {"limit": normalized_limit},
            )

        params: dict[str, Any] = {
            "resource_id": normalized_resource_id,
            "usage_kind": normalized_usage_kind,
            "limit": normalized_limit or DEFAULT_RESOURCE_PAGE_LIMIT,
        }
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor

        session, result = self.context.capture_tool(capture_id, "list_resource_usages", params)
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

    def renderdoc_start_pixel_shader_debug(
        self,
        capture_id: str,
        event_id: int,
        x: int,
        y: int,
        texture_id: str | None = None,
        sample: int | str | None = None,
        primitive_id: int | str | None = None,
        view: int | str | None = None,
        state_limit: int | str | None = None,
    ) -> dict[str, Any]:
        params = {
            "event_id": self.context.normalize_required_int(event_id, "event_id"),
            "x": self.context.normalize_non_negative_int(x, "x"),
            "y": self.context.normalize_non_negative_int(y, "y"),
            "state_limit": self._normalize_state_limit(state_limit),
        }
        normalized_texture_id = self.context.normalize_optional_string(texture_id)
        if normalized_texture_id:
            params["texture_id"] = normalized_texture_id

        normalized_sample = self._normalize_optional_non_negative_int(sample, "sample")
        normalized_primitive_id = self._normalize_optional_non_negative_int(primitive_id, "primitive_id")
        normalized_view = self._normalize_optional_non_negative_int(view, "view")
        if normalized_sample is not None:
            params["sample"] = normalized_sample
        if normalized_primitive_id is not None:
            params["primitive_id"] = normalized_primitive_id
        if normalized_view is not None:
            params["view"] = normalized_view

        session, result = self.context.capture_tool(capture_id, "start_pixel_shader_debug", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_continue_shader_debug(
        self,
        capture_id: str,
        shader_debug_id: str,
        state_limit: int | str | None = None,
    ) -> dict[str, Any]:
        params = {
            "shader_debug_id": self.context.normalize_required_string(shader_debug_id, "shader_debug_id"),
            "state_limit": self._normalize_state_limit(state_limit),
        }
        session, result = self.context.capture_tool(capture_id, "continue_shader_debug", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_shader_debug_step(
        self,
        capture_id: str,
        shader_debug_id: str,
        step_index: int,
        change_limit: int | str | None = None,
    ) -> dict[str, Any]:
        params = {
            "shader_debug_id": self.context.normalize_required_string(shader_debug_id, "shader_debug_id"),
            "step_index": self.context.normalize_non_negative_int(step_index, "step_index"),
            "change_limit": self._normalize_change_limit(change_limit),
        }
        session, result = self.context.capture_tool(capture_id, "get_shader_debug_step", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_end_shader_debug(self, capture_id: str, shader_debug_id: str) -> dict[str, Any]:
        params = {"shader_debug_id": self.context.normalize_required_string(shader_debug_id, "shader_debug_id")}
        session, result = self.context.capture_tool(capture_id, "end_shader_debug", params)
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

    def _normalize_optional_non_negative_int(self, value: Any, field_name: str) -> int | None:
        normalized = self.context.normalize_optional_int(value, field_name)
        if normalized is None:
            return None
        if normalized < 0:
            raise ReplayFailureError(f"{field_name} must be greater than or equal to 0.", {field_name: normalized})
        return normalized

    def _normalize_state_limit(self, value: Any) -> int:
        normalized = self.context.normalize_optional_int(value, "state_limit") or DEFAULT_SHADER_DEBUG_STATE_LIMIT
        if normalized <= 0 or normalized > MAX_SHADER_DEBUG_STATE_LIMIT:
            raise ReplayFailureError(
                "state_limit must be between 1 and {}.".format(MAX_SHADER_DEBUG_STATE_LIMIT),
                {"state_limit": normalized},
            )
        return normalized

    def _normalize_change_limit(self, value: Any) -> int:
        normalized = self.context.normalize_optional_int(value, "change_limit") or DEFAULT_SHADER_DEBUG_CHANGE_LIMIT
        if normalized <= 0 or normalized > MAX_SHADER_DEBUG_CHANGE_LIMIT:
            raise ReplayFailureError(
                "change_limit must be between 1 and {}.".format(MAX_SHADER_DEBUG_CHANGE_LIMIT),
                {"change_limit": normalized},
            )
        return normalized
