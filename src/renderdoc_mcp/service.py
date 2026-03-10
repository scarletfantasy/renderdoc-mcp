from __future__ import annotations

from typing import Any

from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.errors import RenderDocMCPError
from renderdoc_mcp.services import ActionQueries, CaptureQueries, PassQueries, ResourceQueries, ServiceContext


class RenderDocService:
    def __init__(self, bridge: QRenderDocBridge | None = None) -> None:
        self._context = ServiceContext(bridge)
        self._captures = CaptureQueries(self._context)
        self._actions = ActionQueries(self._context)
        self._passes = PassQueries(self._context)
        self._resources = ResourceQueries(self._context)

    def get_capture_summary(self, capture_path: str) -> dict[str, Any]:
        return self._captures.get_capture_summary(capture_path)

    def analyze_frame(self, capture_path: str) -> dict[str, Any]:
        return self._captures.analyze_frame(capture_path)

    def list_actions(
        self,
        capture_path: str,
        max_depth: int | None = None,
        name_filter: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> dict[str, Any]:
        return self._actions.list_actions(
            capture_path,
            max_depth=max_depth,
            name_filter=name_filter,
            cursor=cursor,
            limit=limit,
        )

    def list_passes(
        self,
        capture_path: str,
        cursor: int | str | None = None,
        limit: int | str | None = None,
        category_filter: str | None = None,
        name_filter: str | None = None,
    ) -> dict[str, Any]:
        return self._passes.list_passes(
            capture_path,
            cursor=cursor,
            limit=limit,
            category_filter=category_filter,
            name_filter=name_filter,
        )

    def get_pass_details(self, capture_path: str, pass_id: str) -> dict[str, Any]:
        return self._passes.get_pass_details(capture_path, pass_id)

    def get_action_details(self, capture_path: str, event_id: int) -> dict[str, Any]:
        return self._actions.get_action_details(capture_path, event_id)

    def get_pipeline_state(self, capture_path: str, event_id: int) -> dict[str, Any]:
        return self._actions.get_pipeline_state(capture_path, event_id)

    def get_shader_code(
        self,
        capture_path: str,
        event_id: int,
        stage: str,
        target: str | None = None,
    ) -> dict[str, Any]:
        return self._actions.get_shader_code(capture_path, event_id, stage=stage, target=target)

    def list_resources(self, capture_path: str, kind: str = "all", name_filter: str | None = None) -> dict[str, Any]:
        return self._resources.list_resources(capture_path, kind=kind, name_filter=name_filter)

    def recent_captures_resource(self) -> dict[str, Any]:
        return self._captures.recent_captures_resource()

    def capture_summary_resource(self, encoded_path: str) -> dict[str, Any]:
        return self._captures.capture_summary_resource(encoded_path)

    def _error_response(self, capture_path: str, error: RenderDocMCPError, headline: str) -> dict[str, Any]:
        return self._context.error_response(capture_path, error, headline)
