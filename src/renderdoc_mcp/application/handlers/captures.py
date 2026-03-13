from __future__ import annotations

from pathlib import Path
from typing import Any

from renderdoc_mcp.analysis.frame_analysis import (
    DEFAULT_PASS_PAGE_LIMIT,
    DEFAULT_TIMING_EVENT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_TIMING_EVENT_PAGE_LIMIT,
    PASS_CATEGORIES,
    PASS_SORT_OPTIONS,
)
from renderdoc_mcp.application.command_specs import OpenCaptureCommand
from renderdoc_mcp.application.context import ApplicationContext
from renderdoc_mcp.application.response import attach_capture, bridge_meta, ensure_meta, runtime_meta
from renderdoc_mcp.errors import ReplayFailureError

SUPPORTED_PASS_CATEGORIES = set(PASS_CATEGORIES)
SUPPORTED_PASS_SORT_OPTIONS = set(PASS_SORT_OPTIONS)
SUPPORTED_WORKLIST_FOCI = {"performance", "structure", "resources"}
DEFAULT_WORKLIST_LIMIT = 10
MAX_WORKLIST_LIMIT = 50


class CaptureHandlers:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    def renderdoc_open_capture(self, capture_path: str) -> dict[str, Any]:
        command = OpenCaptureCommand.from_raw(self.context.normalizer, capture_path)
        session = self.context.sessions.open_normalized_capture(command.capture_path)
        try:
            session.bridge.ensure_capture_loaded(session.capture_path)
            overview = ensure_meta(session.bridge.call("get_capture_overview"))
        except Exception:
            self.context.sessions.close_normalized_capture(session.capture_id)
            raise
        return attach_capture(overview, session)

    def renderdoc_close_capture(self, capture_id: str) -> dict[str, Any]:
        session = self.context.get_session(capture_id)
        self.context.close_capture(capture_id)
        return {
            "capture_id": session.capture_id,
            "capture_path": session.capture_path,
            "closed": True,
            "meta": bridge_meta(session),
        }

    def renderdoc_get_capture_overview(self, capture_id: str) -> dict[str, Any]:
        session, result = self.context.capture_tool(capture_id, "get_capture_overview")
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_analysis_worklist(
        self,
        capture_id: str,
        focus: str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        normalized_focus = (self.context.normalize_optional_string(focus) or "performance").lower()
        normalized_limit = self.context.normalize_optional_int(limit, "limit")

        if normalized_focus not in SUPPORTED_WORKLIST_FOCI:
            raise ReplayFailureError(
                "focus must be one of performance, structure, or resources.",
                {"focus": normalized_focus},
            )
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_WORKLIST_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_WORKLIST_LIMIT),
                {"limit": normalized_limit},
            )

        params = {"focus": normalized_focus, "limit": normalized_limit or DEFAULT_WORKLIST_LIMIT}
        session, result = self.context.capture_tool(capture_id, "get_analysis_worklist", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_list_passes(
        self,
        capture_id: str,
        parent_pass_id: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
        category_filter: str | None = None,
        name_filter: str | None = None,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        normalized_parent_pass_id = self.context.normalize_optional_string(parent_pass_id)
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")
        normalized_category_filter = self.context.normalize_optional_string(category_filter)
        normalized_name_filter = self.context.normalize_optional_string(name_filter)
        normalized_sort_by = (self.context.normalize_optional_string(sort_by) or "event_order").lower()

        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (normalized_limit <= 0 or normalized_limit > MAX_PAGE_LIMIT):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                {"limit": normalized_limit},
            )
        if normalized_category_filter and normalized_category_filter not in SUPPORTED_PASS_CATEGORIES:
            raise ReplayFailureError(
                "category_filter must be one of {}.".format(", ".join(sorted(SUPPORTED_PASS_CATEGORIES))),
                {"category_filter": normalized_category_filter},
            )
        if normalized_sort_by not in SUPPORTED_PASS_SORT_OPTIONS:
            raise ReplayFailureError(
                "sort_by must be one of {}.".format(", ".join(sorted(SUPPORTED_PASS_SORT_OPTIONS))),
                {"sort_by": normalized_sort_by},
            )

        params: dict[str, Any] = {"limit": normalized_limit or DEFAULT_PASS_PAGE_LIMIT, "sort_by": normalized_sort_by}
        if normalized_parent_pass_id:
            params["parent_pass_id"] = normalized_parent_pass_id
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor
        if normalized_category_filter:
            params["category_filter"] = normalized_category_filter
        if normalized_name_filter:
            params["name_filter"] = normalized_name_filter

        session, result = self.context.capture_tool(capture_id, "list_passes", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_get_pass_summary(self, capture_id: str, pass_id: str) -> dict[str, Any]:
        normalized_pass_id = self.context.normalize_required_string(pass_id, "pass_id")
        session, result = self.context.capture_tool(capture_id, "get_pass_summary", {"pass_id": normalized_pass_id})
        return attach_capture(ensure_meta(result), session)

    def renderdoc_list_timing_events(
        self,
        capture_id: str,
        pass_id: str,
        cursor: int | str | None = None,
        limit: int | str | None = None,
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        normalized_pass_id = self.context.normalize_required_string(pass_id, "pass_id")
        normalized_cursor = self.context.normalize_optional_int(cursor, "cursor")
        normalized_limit = self.context.normalize_optional_int(limit, "limit")
        normalized_sort_by = (self.context.normalize_optional_string(sort_by) or "event_order").lower()

        if normalized_cursor is not None and normalized_cursor < 0:
            raise ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": normalized_cursor})
        if normalized_limit is not None and (
            normalized_limit <= 0 or normalized_limit > MAX_TIMING_EVENT_PAGE_LIMIT
        ):
            raise ReplayFailureError(
                "limit must be between 1 and {}.".format(MAX_TIMING_EVENT_PAGE_LIMIT),
                {"limit": normalized_limit},
            )
        if normalized_sort_by not in {"event_order", "gpu_time"}:
            raise ReplayFailureError(
                "sort_by must be one of event_order or gpu_time.",
                {"sort_by": normalized_sort_by},
            )

        params: dict[str, Any] = {
            "pass_id": normalized_pass_id,
            "limit": normalized_limit or DEFAULT_TIMING_EVENT_PAGE_LIMIT,
            "sort_by": normalized_sort_by,
        }
        if normalized_cursor is not None:
            params["cursor"] = normalized_cursor

        session, result = self.context.capture_tool(capture_id, "list_timing_events", params)
        return attach_capture(ensure_meta(result), session)

    def renderdoc_recent_captures(self) -> dict[str, Any]:
        config = self.context.read_ui_config()
        recent_paths = list(config.get("RecentCaptureFiles", []))
        captures = []

        for raw_path in recent_paths:
            path = Path(raw_path)
            captures.append({"path": str(path), "exists": path.is_file()})

        return {"recent_captures": captures, "count": len(captures), "meta": runtime_meta()}

    def renderdoc_capture_overview_resource(self, capture_id: str) -> dict[str, Any]:
        return self.renderdoc_get_capture_overview(capture_id)
