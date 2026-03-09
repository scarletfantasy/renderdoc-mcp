from __future__ import annotations

from typing import Any

from renderdoc_mcp.analysis.frame_analysis import MAX_PAGE_LIMIT
from renderdoc_mcp.errors import ReplayFailureError, RenderDocMCPError
from renderdoc_mcp.services.common import ServiceContext


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

    def get_pipeline_state(self, capture_path: str, event_id: int) -> dict[str, Any]:
        try:
            event_id = self.context.normalize_required_int(event_id, "event_id")
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Fetched pipeline state for the selected event.")

        return self.context.run_tool(
            capture_path,
            "Fetched pipeline state for the selected event.",
            lambda normalized: self.context.capture_tool(normalized, "get_pipeline_state", {"event_id": event_id}),
        )
