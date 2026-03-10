from __future__ import annotations

from typing import Any

from renderdoc_mcp.analysis.frame_analysis import MAX_PAGE_LIMIT
from renderdoc_mcp.errors import ReplayFailureError, RenderDocMCPError
from renderdoc_mcp.services.common import ServiceContext

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
SUPPORTED_PIPELINE_DETAIL_LEVELS = {"portable", "api_specific"}


def _normalize_shader_stage(stage: str | None) -> str | None:
    if stage is None:
        return None

    key = stage.strip().replace("_", "").replace("-", "").replace(" ", "").lower()
    return SUPPORTED_SHADER_STAGES.get(key)


class ActionQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def list_actions(
        self,
        capture_path: str,
        max_depth: int | None = None,
        name_filter: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        try:
            max_depth = self.context.normalize_optional_int(max_depth, "max_depth")
            name_filter = self.context.normalize_optional_string(name_filter)
            cursor = self.context.normalize_optional_int(cursor, "cursor")
            limit = self.context.normalize_optional_int(limit, "limit")
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Action listing failed.")

        if max_depth is not None and max_depth < 0:
            return self.context.error_response(
                capture_path,
                ReplayFailureError("max_depth must be greater than or equal to 0."),
                "Action listing failed.",
            )

        if cursor is not None and cursor < 0:
            return self.context.error_response(
                capture_path,
                ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": cursor}),
                "Action listing failed.",
            )

        if limit is not None and (limit <= 0 or limit > MAX_PAGE_LIMIT):
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                    {"limit": limit},
                ),
                "Action listing failed.",
            )

        params: dict[str, Any] = {}
        if max_depth is not None:
            params["max_depth"] = max_depth
        if name_filter:
            params["name_filter"] = name_filter
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit

        return self.context.run_tool(
            capture_path,
            "Listed capture actions.",
            lambda normalized: self.context.capture_tool(normalized, "list_actions", params),
        )

    def get_action_details(self, capture_path: str, event_id: int) -> dict[str, Any]:
        try:
            event_id = self.context.normalize_required_int(event_id, "event_id")
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched action details.")

        return self.context.run_tool(
            capture_path,
            "Fetched action details.",
            lambda normalized: self.context.capture_tool(normalized, "get_action_details", {"event_id": event_id}),
        )

    def get_pipeline_state(
        self,
        capture_path: str,
        event_id: int,
        detail_level: str | None = None,
    ) -> dict[str, Any]:
        try:
            event_id = self.context.normalize_required_int(event_id, "event_id")
            detail_level = (self.context.normalize_optional_string(detail_level) or "portable").lower()
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched pipeline state for the selected event.")

        if detail_level not in SUPPORTED_PIPELINE_DETAIL_LEVELS:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "detail_level must be one of {}.".format(", ".join(sorted(SUPPORTED_PIPELINE_DETAIL_LEVELS))),
                    {"detail_level": detail_level},
                ),
                "Fetched pipeline state for the selected event.",
            )

        return self.context.run_tool(
            capture_path,
            "Fetched pipeline state for the selected event.",
            lambda normalized: self.context.capture_tool(
                normalized,
                "get_pipeline_state",
                {"event_id": event_id, "detail_level": detail_level},
            ),
        )

    def get_shader_code(
        self,
        capture_path: str,
        event_id: int,
        stage: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        try:
            event_id = self.context.normalize_required_int(event_id, "event_id")
            normalized_stage = _normalize_shader_stage(self.context.normalize_optional_string(stage))
            normalized_target = self.context.normalize_optional_string(target)
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched shader code for the selected stage.")

        if normalized_stage is None:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "stage must name a supported shader stage.",
                    {"stage": stage, "supported_stages": sorted(set(SUPPORTED_SHADER_STAGES.values()))},
                ),
                "Fetched shader code for the selected stage.",
            )

        params = {"event_id": event_id, "stage": normalized_stage}
        if normalized_target:
            params["target"] = normalized_target

        return self.context.run_tool(
            capture_path,
            "Fetched shader code for the selected stage.",
            lambda normalized: self.context.capture_tool(normalized, "get_shader_code", params),
        )
