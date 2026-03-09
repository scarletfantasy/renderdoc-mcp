from __future__ import annotations

from typing import Any

from renderdoc_mcp.analysis.frame_analysis import DEFAULT_PASS_PAGE_LIMIT, MAX_PAGE_LIMIT, PASS_CATEGORIES
from renderdoc_mcp.errors import ReplayFailureError, RenderDocMCPError
from renderdoc_mcp.services.common import ServiceContext

SUPPORTED_PASS_CATEGORIES = set(PASS_CATEGORIES)


class PassQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def list_passes(
        self,
        capture_path: str,
        cursor: int | str | None = None,
        limit: int | str | None = None,
        category_filter: str | None = None,
        name_filter: str | None = None,
    ) -> dict[str, Any]:
        try:
            cursor = self.context.normalize_optional_int(cursor, "cursor")
            limit = self.context.normalize_optional_int(limit, "limit")
            category_filter = self.context.normalize_optional_string(category_filter)
            name_filter = self.context.normalize_optional_string(name_filter)
        except RenderDocMCPError as exc:
            return self.context.error_response(capture_path, exc, "Pass listing failed.")

        if cursor is not None and cursor < 0:
            return self.context.error_response(
                capture_path,
                ReplayFailureError("cursor must be greater than or equal to 0.", {"cursor": cursor}),
                "Pass listing failed.",
            )

        if limit is not None and (limit <= 0 or limit > MAX_PAGE_LIMIT):
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "limit must be between 1 and {}.".format(MAX_PAGE_LIMIT),
                    {"limit": limit},
                ),
                "Pass listing failed.",
            )

        if category_filter and category_filter not in SUPPORTED_PASS_CATEGORIES:
            return self.context.error_response(
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

        return self.context.run_tool(
            capture_path,
            "Listed analyzed frame passes.",
            lambda normalized: self.context.capture_tool(normalized, "list_passes", params),
        )

    def get_pass_details(self, capture_path: str, pass_id: str) -> dict[str, Any]:
        pass_id = self.context.normalize_optional_string(pass_id)
        if not pass_id:
            return self.context.error_response(
                capture_path,
                ReplayFailureError("pass_id must be a non-empty string."),
                "Fetched pass details.",
            )

        return self.context.run_tool(
            capture_path,
            "Fetched pass details.",
            lambda normalized: self.context.capture_tool(normalized, "get_pass_details", {"pass_id": pass_id}),
        )
