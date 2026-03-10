from __future__ import annotations

from typing import Any

from renderdoc_mcp.analysis.frame_analysis import DEFAULT_ACTION_PAGE_LIMIT, MAX_PAGE_LIMIT
from renderdoc_mcp.application.context import ApplicationContext
from renderdoc_mcp.application.response import attach_capture, ensure_meta
from renderdoc_mcp.errors import ReplayFailureError

SUPPORTED_SHADER_STAGES = {
    "vertex": "Vertex",
    "vs": "Vertex",
    "hull": "Hull",
    "hs": "Hull",
    "domain": "Domain",
    "ds": "Domain",
    "geometry": "Geometry",
    "gs": "Geometry",
    "pixel": "Pixel",
    "fragment": "Pixel",
    "ps": "Pixel",
    "compute": "Compute",
    "cs": "Compute",
    "task": "Task",
    "amplification": "Task",
    "as": "Task",
    "mesh": "Mesh",
    "raygen": "RayGen",
    "raygeneration": "RayGen",
    "intersection": "Intersection",
    "anyhit": "AnyHit",
    "closesthit": "ClosestHit",
    "miss": "Miss",
    "callable": "Callable",
}
SUPPORTED_PIPELINE_BINDING_KINDS = {
    "descriptor_accesses",
    "vertex_buffers",
    "vertex_inputs",
    "output_targets",
    "shaders",
    "api_details",
}
DEFAULT_PIPELINE_BINDING_LIMIT = 50
DEFAULT_SHADER_LINE_COUNT = 200
MAX_SHADER_LINE_COUNT = 1000


def _normalize_shader_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    key = stage.strip().replace("_", "").replace("-", "").replace(" ", "").lower()
    return SUPPORTED_SHADER_STAGES.get(key)


class ActionHandlers:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def renderdoc_list_actions(
        self,
        capture_id: str,
        parent_event_id: int | str | None = None,
        name_filter: str | None = None,
        flags_filter: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        normalized_parent_event_id = self.context.normalize_optional_int(parent_event_id, "parent_event_id")
        normalized_name_filter = self.context.normalize_optional_string(name_filter)
        normalized_flags_filter = self.context.normalize_optional_string(flags_filter)
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")

        if normalized_parent_event_id is not None and normalized_parent_event_id <= 0:
            raise ReplayFailureError(
                "parent_event_id must be greater than 0 when provided.",
                {"parent_event_id": normalized_parent_event_id},
            )
        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_PAGE_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                {"limit": normalized_limit},
            )

        params: dict[str, Any] = {"limit": normalized_limit or DEFAULT_ACTION_PAGE_LIMIT}
        if normalized_parent_event_id is not None:
            params["parent_event_id"] = normalized_parent_event_id
        if normalized_name_filter:
            params["name_filter"] = normalized_name_filter
        if normalized_flags_filter:
            params["flags_filter"] = normalized_flags_filter
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor

        session, result = self.context.capture_tool(capture_id, "list_actions", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_action_summary(self, capture_id: str, event_id: int) -> dict[str, Any]:
        normalized_event_id = self.context.normalize_required_int(event_id, "event_id")
        session, result = self.context.capture_tool(capture_id, "get_action_summary", {"event_id": normalized_event_id})
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_pipeline_overview(self, capture_id: str, event_id: int) -> dict[str, Any]:
        normalized_event_id = self.context.normalize_required_int(event_id, "event_id")
        session, result = self.context.capture_tool(
            capture_id,
            "get_pipeline_overview",
            {"event_id": normalized_event_id},
        )
        return attach_capture(ensure_meta(result), session)

    def renderdoc_list_pipeline_bindings(
        self,
        capture_id: str,
        event_id: int,
        binding_kind: str,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        normalized_event_id = self.context.normalize_required_int(event_id, "event_id")
        normalized_binding_kind = (self.context.normalize_required_string(binding_kind, "binding_kind")).lower()
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")

        if normalized_binding_kind not in SUPPORTED_PIPELINE_BINDING_KINDS:
            raise ReplayFailureError(
                "binding_kind must be one of {}.".format(", ".join(sorted(SUPPORTED_PIPELINE_BINDING_KINDS))),
                {"binding_kind": normalized_binding_kind},
            )
        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_PAGE_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                {"limit": normalized_limit},
            )

        params: dict[str, Any] = {
            "event_id": normalized_event_id,
            "binding_kind": normalized_binding_kind,
            "limit": normalized_limit or DEFAULT_PIPELINE_BINDING_LIMIT,
        }
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor

        session, result = self.context.capture_tool(capture_id, "list_pipeline_bindings", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_shader_summary(
        self,
        capture_id: str,
        event_id: int,
        stage: str,
    ) -> dict[str, Any]:
        normalized_event_id = self.context.normalize_required_int(event_id, "event_id")
        normalized_stage = _normalize_shader_stage(self.context.normalize_optional_string(stage))

        if normalized_stage is None:
            raise ReplayFailureError(
                "stage must name a supported shader stage.",
                {"stage": stage, "supported_stages": sorted(set(SUPPORTED_SHADER_STAGES.values()))},
            )

        session, result = self.context.capture_tool(
            capture_id,
            "get_shader_summary",
            {"event_id": normalized_event_id, "stage": normalized_stage},
        )
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_shader_code_chunk(
        self,
        capture_id: str,
        event_id: int,
        stage: str,
        target: str | None = None,
        start_line: int | str | None = None,
        line_count: int | str | None = None,
    ) -> dict[str, Any]:
        normalized_event_id = self.context.normalize_required_int(event_id, "event_id")
        normalized_stage = _normalize_shader_stage(self.context.normalize_optional_string(stage))
        normalized_target = self.context.normalize_optional_string(target)
        normalized_start_line = self.context.normalize_optional_int(start_line, "start_line")
        normalized_line_count = self.context.normalize_optional_int(line_count, "line_count")

        if normalized_stage is None:
            raise ReplayFailureError(
                "stage must name a supported shader stage.",
                {"stage": stage, "supported_stages": sorted(set(SUPPORTED_SHADER_STAGES.values()))},
            )
        if normalized_start_line is not None and normalized_start_line <= 0:
            raise ReplayFailureError(
                "start_line must be greater than 0.",
                {"start_line": normalized_start_line},
            )
        if normalized_line_count is not None and (
            normalized_line_count <= 0 or normalized_line_count > MAX_SHADER_LINE_COUNT
        ):
            raise ReplayFailureError(
                "line_count must be between 1 and {}.".format(MAX_SHADER_LINE_COUNT),
                {"line_count": normalized_line_count},
            )

        params: dict[str, Any] = {
            "event_id": normalized_event_id,
            "stage": normalized_stage,
            "start_line": normalized_start_line or 1,
            "line_count": normalized_line_count or DEFAULT_SHADER_LINE_COUNT,
        }
        if normalized_target:
            params["target"] = normalized_target

        session, result = self.context.capture_tool(capture_id, "get_shader_code_chunk", params)
        return attach_capture(ensure_meta(result), session)
