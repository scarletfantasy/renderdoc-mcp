from __future__ import annotations

from typing import Any

from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.errors import RenderDocMCPError
from renderdoc_mcp.services import (
    ActionQueries,
    CaptureQueries,
    PerformanceQueries,
    PassQueries,
    PixelQueries,
    ResourceQueries,
    ServiceContext,
)


class RenderDocService:
    def __init__(self, bridge: QRenderDocBridge | None = None) -> None:
        self._context = ServiceContext(bridge)
        self._captures = CaptureQueries(self._context)
        self._actions = ActionQueries(self._context)
        self._passes = PassQueries(self._context)
        self._performance = PerformanceQueries(self._context)
        self._pixels = PixelQueries(self._context)
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

    def get_timing_data(self, capture_path: str, pass_id: str) -> dict[str, Any]:
        return self._performance.get_timing_data(capture_path, pass_id)

    def get_performance_hotspots(self, capture_path: str) -> dict[str, Any]:
        return self._performance.get_performance_hotspots(capture_path)

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
        return self._pixels.get_pixel_history(
            capture_path,
            texture_id,
            x,
            y,
            mip_level=mip_level,
            array_slice=array_slice,
            sample=sample,
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
        return self._pixels.debug_pixel(
            capture_path,
            texture_id,
            x,
            y,
            mip_level=mip_level,
            array_slice=array_slice,
            sample=sample,
        )

    def get_texture_data(
        self,
        capture_path: str,
        texture_id: str,
        mip_level: int,
        x: int,
        y: int,
        width: int,
        height: int,
        array_slice: int = 0,
        sample: int = 0,
    ) -> dict[str, Any]:
        return self._resources.get_texture_data(
            capture_path,
            texture_id,
            mip_level,
            x,
            y,
            width,
            height,
            array_slice=array_slice,
            sample=sample,
        )

    def get_buffer_data(self, capture_path: str, buffer_id: str, offset: int, size: int) -> dict[str, Any]:
        return self._resources.get_buffer_data(capture_path, buffer_id, offset, size)

    def save_texture_to_file(
        self,
        capture_path: str,
        texture_id: str,
        output_path: str,
        mip_level: int = 0,
        array_slice: int = 0,
    ) -> dict[str, Any]:
        return self._resources.save_texture_to_file(
            capture_path,
            texture_id,
            output_path,
            mip_level=mip_level,
            array_slice=array_slice,
        )

    def recent_captures_resource(self) -> dict[str, Any]:
        return self._captures.recent_captures_resource()

    def capture_summary_resource(self, encoded_path: str) -> dict[str, Any]:
        return self._captures.capture_summary_resource(encoded_path)

    def _error_response(self, capture_path: str, error: RenderDocMCPError, headline: str) -> dict[str, Any]:
        return self._context.error_response(capture_path, error, headline)
