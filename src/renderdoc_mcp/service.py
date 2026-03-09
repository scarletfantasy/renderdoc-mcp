from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.errors import CapturePathError, ReplayFailureError, RenderDocMCPError
from renderdoc_mcp.paths import ui_config_path
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge.frame_analysis import (
    DEFAULT_PASS_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    PASS_CATEGORIES,
)
from renderdoc_mcp.uri import decode_capture_path, encode_capture_path

SUPPORTED_RESOURCE_KINDS = {"all", "textures", "buffers"}
SUPPORTED_PASS_CATEGORIES = set(PASS_CATEGORIES)
NULL_LIKE_VALUES = {"", "null", "none", "undefined"}


class RenderDocService:
    def __init__(self, bridge: QRenderDocBridge | None = None) -> None:
        self.bridge = bridge or QRenderDocBridge()

    def get_capture_summary(self, capture_path: str) -> dict[str, Any]:
        return self._run_tool(
            capture_path,
            "Loaded capture summary from RenderDoc.",
            lambda normalized: self._capture_tool(normalized, "get_capture_summary"),
        )

    def analyze_frame(self, capture_path: str) -> dict[str, Any]:
        return self._run_tool(
            capture_path,
            "Analyzed the frame pass structure from RenderDoc.",
            lambda normalized: self._capture_tool(normalized, "analyze_frame"),
        )

    def list_actions(
        self,
        capture_path: str,
        max_depth: int | None = None,
        name_filter: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        try:
            max_depth = self._normalize_optional_int(max_depth, "max_depth")
            name_filter = self._normalize_optional_string(name_filter)
            cursor = self._normalize_optional_int(cursor, "cursor")
            limit = self._normalize_optional_int(limit, "limit")
        except RenderDocMCPError as exc:
            return self._error_response(capture_path, exc, "Action listing failed.")

        if max_depth is not None and max_depth < 0:
            return self._error_response(
                capture_path,
                ReplayFailureError("max_depth must be greater than or equal to 0."),
                "Action listing failed.",
            )

        if cursor is not None and cursor < 0:
            return self._error_response(
                capture_path,
                ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": cursor}),
                "Action listing failed.",
            )

        if limit is not None and (limit <= 0 or limit > MAX_PAGE_LIMIT):
            return self._error_response(
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

        return self._run_tool(
            capture_path,
            "Listed capture actions.",
            lambda normalized: self._capture_tool(normalized, "list_actions", params),
        )

    def list_passes(
        self,
        capture_path: str,
        cursor: int | str | None = None,
        limit: int | str | None = None,
        category_filter: str | None = None,
        name_filter: str | None = None,
    ) -> dict[str, Any]:
        try:
            cursor = self._normalize_optional_int(cursor, "cursor")
            limit = self._normalize_optional_int(limit, "limit")
            category_filter = self._normalize_optional_string(category_filter)
            name_filter = self._normalize_optional_string(name_filter)
        except RenderDocMCPError as exc:
            return self._error_response(capture_path, exc, "Pass listing failed.")

        if cursor is not None and cursor < 0:
            return self._error_response(
                capture_path,
                ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": cursor}),
                "Pass listing failed.",
            )

        if limit is not None and (limit <= 0 or limit > MAX_PAGE_LIMIT):
            return self._error_response(
                capture_path,
                ReplayFailureError(
                    "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                    {"limit": limit},
                ),
                "Pass listing failed.",
            )

        if category_filter and category_filter not in SUPPORTED_PASS_CATEGORIES:
            return self._error_response(
                capture_path,
                ReplayFailureError(
                    "category_filter must be one of {}.".format(", ".join(sorted(SUPPORTED_PASS_CATEGORIES))),
                    {"category_filter": category_filter},
                ),
                "Pass listing failed.",
            )

        params: dict[str, Any] = {"limit": limit or DEFAULT_PASS_PAGE_LIMIT}
        if cursor is not None:
            params["cursor"] = cursor
        if category_filter:
            params["category_filter"] = category_filter
        if name_filter:
            params["name_filter"] = name_filter

        return self._run_tool(
            capture_path,
            "Listed analyzed frame passes.",
            lambda normalized: self._capture_tool(normalized, "list_passes", params),
        )

    def get_pass_details(self, capture_path: str, pass_id: str) -> dict[str, Any]:
        pass_id = self._normalize_optional_string(pass_id)
        if not pass_id:
            return self._error_response(
                capture_path,
                ReplayFailureError("pass_id must be a non-empty string."),
                "Fetched pass details.",
            )

        return self._run_tool(
            capture_path,
            "Fetched pass details.",
            lambda normalized: self._capture_tool(normalized, "get_pass_details", {"pass_id": pass_id}),
        )

    def get_action_details(self, capture_path: str, event_id: int) -> dict[str, Any]:
        try:
            event_id = self._normalize_required_int(event_id, "event_id")
        except RenderDocMCPError as exc:
            return self._error_response(capture_path, exc, "Fetched action details.")

        return self._run_tool(
            capture_path,
            "Fetched action details.",
            lambda normalized: self._capture_tool(normalized, "get_action_details", {"event_id": event_id}),
        )

    def get_pipeline_state(self, capture_path: str, event_id: int) -> dict[str, Any]:
        try:
            event_id = self._normalize_required_int(event_id, "event_id")
        except RenderDocMCPError as exc:
            return self._error_response(capture_path, exc, "Fetched pipeline state for the selected event.")

        return self._run_tool(
            capture_path,
            "Fetched pipeline state for the selected event.",
            lambda normalized: self._capture_tool(normalized, "get_pipeline_state", {"event_id": event_id}),
        )

    def list_resources(self, capture_path: str, kind: str = "all", name_filter: str | None = None) -> dict[str, Any]:
        kind = self._normalize_optional_string(kind) or "all"
        name_filter = self._normalize_optional_string(name_filter)

        if kind not in SUPPORTED_RESOURCE_KINDS:
            return self._error_response(
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

        return self._run_tool(
            capture_path,
            "Listed capture resources.",
            lambda normalized: self._capture_tool(normalized, "list_resources", params),
        )

    def recent_captures_resource(self) -> dict[str, Any]:
        config = self._read_ui_config()
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

    def _capture_tool(self, normalized_path: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.bridge.ensure_capture_loaded(normalized_path)
        return self.bridge.call(method, params or {})

    def _run_tool(self, capture_path: str, headline: str, callback: Any) -> dict[str, Any]:
        try:
            normalized = self._normalize_capture_path(capture_path)
            result = callback(normalized)
            return self._success_response(normalized, result, headline)
        except RenderDocMCPError as exc:
            return self._error_response(capture_path, exc, headline)
        except Exception as exc:  # pragma: no cover
            return self._error_response(
                capture_path,
                ReplayFailureError(
                    "Unexpected server error while talking to RenderDoc.",
                    {"exception_type": type(exc).__name__, "message": str(exc)},
                ),
                headline,
            )

    def _success_response(self, capture_path: str, result: dict[str, Any], headline: str) -> dict[str, Any]:
        warnings: list[str] = []
        if result.get("truncated"):
            returned_count = result.get("returned_count")
            limit = result.get("limit")
            warnings.append(
                "Result was truncated to {} action nodes{}.".format(
                    limit,
                    " (returned {})".format(returned_count) if returned_count is not None else "",
                )
            )

        return {
            "capture": {"path": capture_path, "encoded_path": encode_capture_path(capture_path)},
            "result": result,
            "summary": {"headline": headline},
            "warnings": warnings,
            "error": None,
        }

    def _error_response(self, capture_path: str, error: RenderDocMCPError, headline: str) -> dict[str, Any]:
        normalized = str(Path(capture_path)) if capture_path else ""
        return {
            "capture": {
                "path": normalized,
                "encoded_path": encode_capture_path(normalized) if normalized else "",
            },
            "result": None,
            "summary": {"headline": headline},
            "warnings": [],
            "error": error.to_payload(),
        }

    def _normalize_capture_path(self, capture_path: str) -> str:
        path = Path(capture_path).expanduser()
        if not path.is_file():
            raise CapturePathError(str(path))
        return str(path.resolve())

    def _read_ui_config(self) -> dict[str, Any]:
        path = ui_config_path()
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _normalize_optional_string(self, value: Any) -> str | None:
        if value is None:
            return None

        if isinstance(value, str):
            normalized = value.strip()
        else:
            normalized = str(value).strip()

        if normalized.lower() in NULL_LIKE_VALUES:
            return None

        return normalized

    def _normalize_optional_int(self, value: Any, field_name: str) -> int | None:
        if value is None:
            return None

        if isinstance(value, str) and value.strip().lower() in NULL_LIKE_VALUES:
            return None

        return self._normalize_required_int(value, field_name)

    def _normalize_required_int(self, value: Any, field_name: str) -> int:
        if isinstance(value, bool):
            raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value})

        if isinstance(value, int):
            return value

        if isinstance(value, float) and value.is_integer():
            return int(value)

        if isinstance(value, str):
            stripped = value.strip()
            try:
                return int(stripped)
            except ValueError as exc:
                raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value}) from exc

        raise ReplayFailureError(f"{field_name} must be an integer.", {field_name: value})
