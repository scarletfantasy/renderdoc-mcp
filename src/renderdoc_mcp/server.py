from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from renderdoc_mcp.bootstrap import prepare_runtime
from renderdoc_mcp.service import RenderDocService


@lru_cache(maxsize=1)
def get_service() -> RenderDocService:
    prepare_runtime()
    return RenderDocService()


app = FastMCP(
    name="renderdoc-mcp",
    instructions=(
        "Use these tools to inspect existing RenderDoc .rdc captures on the local Windows machine. "
        "Always pass an explicit capture_path. The server will launch qrenderdoc as needed."
    ),
)


@app.tool(
    name="renderdoc_get_capture_summary",
    description="Load a RenderDoc capture and return frame, API, action-count, and resource-count summary data.",
    structured_output=True,
)
def renderdoc_get_capture_summary(capture_path: str) -> dict[str, Any]:
    return get_service().get_capture_summary(capture_path)


@app.tool(
    name="renderdoc_analyze_frame",
    description="Analyze a RenderDoc capture into top-level passes, hotspots, and a tail UI/present chain, with optional top-level pass GPU timing summary.",
    structured_output=True,
)
def renderdoc_analyze_frame(capture_path: str, include_timing_summary: bool = False) -> dict[str, Any]:
    return get_service().analyze_frame(capture_path, include_timing_summary=include_timing_summary)


@app.tool(
    name="renderdoc_list_actions",
    description="List the action tree in a RenderDoc capture, optionally filtered by depth or action name, with optional flat pagination.",
    structured_output=True,
)
def renderdoc_list_actions(
    capture_path: str,
    max_depth: int | None = None,
    name_filter: str | None = None,
    cursor: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    return get_service().list_actions(
        capture_path,
        max_depth=max_depth,
        name_filter=name_filter,
        cursor=cursor,
        limit=limit,
    )


@app.tool(
    name="renderdoc_list_passes",
    description="List analyzed top-level frame passes with pagination, optional filtering, and optional sorting including GPU time when available.",
    structured_output=True,
)
def renderdoc_list_passes(
    capture_path: str,
    cursor: int | None = None,
    limit: int | None = None,
    category_filter: str | None = None,
    name_filter: str | None = None,
    sort_by: str = "event_order",
    threshold_ms: float | None = None,
) -> dict[str, Any]:
    return get_service().list_passes(
        capture_path,
        cursor=cursor,
        limit=limit,
        category_filter=category_filter,
        name_filter=name_filter,
        sort_by=sort_by,
        threshold_ms=threshold_ms,
    )


@app.tool(
    name="renderdoc_get_pass_details",
    description="Fetch the full analyzed pass structure for a previously listed pass_id.",
    structured_output=True,
)
def renderdoc_get_pass_details(capture_path: str, pass_id: str) -> dict[str, Any]:
    return get_service().get_pass_details(capture_path, pass_id)


@app.tool(
    name="renderdoc_get_timing_data",
    description="Fetch per-event GPU timing data for a previously listed pass_id when the capture supports GPU duration counters.",
    structured_output=True,
)
def renderdoc_get_timing_data(capture_path: str, pass_id: str) -> dict[str, Any]:
    return get_service().get_timing_data(capture_path, pass_id)


@app.tool(
    name="renderdoc_get_performance_hotspots",
    description="Rank top-level passes and individual events by GPU timing, or fall back to heuristic hotspots when timing is unavailable.",
    structured_output=True,
)
def renderdoc_get_performance_hotspots(capture_path: str) -> dict[str, Any]:
    return get_service().get_performance_hotspots(capture_path)


@app.tool(
    name="renderdoc_get_action_details",
    description="Fetch details for a specific RenderDoc event_id, including draw or dispatch metadata.",
    structured_output=True,
)
def renderdoc_get_action_details(capture_path: str, event_id: int) -> dict[str, Any]:
    return get_service().get_action_details(capture_path, event_id)


@app.tool(
    name="renderdoc_get_pipeline_state",
    description="Fetch the API-agnostic pipeline state at a specific RenderDoc event_id, with optional API-specific detail.",
    structured_output=True,
)
def renderdoc_get_pipeline_state(
    capture_path: str,
    event_id: int,
    detail_level: str = "portable",
) -> dict[str, Any]:
    return get_service().get_pipeline_state(capture_path, event_id, detail_level=detail_level)


@app.tool(
    name="renderdoc_get_shader_code",
    description="Fetch shader disassembly text for a specific shader stage at a RenderDoc event_id.",
    structured_output=True,
)
def renderdoc_get_shader_code(
    capture_path: str,
    event_id: int,
    stage: str,
    target: str | None = None,
) -> dict[str, Any]:
    return get_service().get_shader_code(capture_path, event_id, stage=stage, target=target)


@app.tool(
    name="renderdoc_list_resources",
    description="List texture and buffer resources in a RenderDoc capture, with optional kind and name filtering.",
    structured_output=True,
)
def renderdoc_list_resources(
    capture_path: str,
    kind: str = "all",
    name_filter: str | None = None,
) -> dict[str, Any]:
    return get_service().list_resources(capture_path, kind=kind, name_filter=name_filter)


@app.tool(
    name="renderdoc_get_pixel_history",
    description="Inspect the ordered pixel history for a texture pixel and subresource in the active capture.",
    structured_output=True,
)
def renderdoc_get_pixel_history(
    capture_path: str,
    texture_id: str,
    x: int,
    y: int,
    mip_level: int = 0,
    array_slice: int = 0,
    sample: int = 0,
) -> dict[str, Any]:
    return get_service().get_pixel_history(
        capture_path,
        texture_id,
        x,
        y,
        mip_level=mip_level,
        array_slice=array_slice,
        sample=sample,
    )


@app.tool(
    name="renderdoc_debug_pixel",
    description="Summarize the draw or GPU events that affected a texture pixel, derived from RenderDoc pixel history.",
    structured_output=True,
)
def renderdoc_debug_pixel(
    capture_path: str,
    texture_id: str,
    x: int,
    y: int,
    mip_level: int = 0,
    array_slice: int = 0,
    sample: int = 0,
) -> dict[str, Any]:
    return get_service().debug_pixel(
        capture_path,
        texture_id,
        x,
        y,
        mip_level=mip_level,
        array_slice=array_slice,
        sample=sample,
    )


@app.tool(
    name="renderdoc_get_texture_data",
    description="Return a JSON-friendly pixel preview grid for a selected texture region and subresource.",
    structured_output=True,
)
def renderdoc_get_texture_data(
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
    return get_service().get_texture_data(
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


@app.tool(
    name="renderdoc_get_buffer_data",
    description="Return a bounded raw byte window from a buffer resource, with metadata and encoded contents.",
    structured_output=True,
)
def renderdoc_get_buffer_data(capture_path: str, buffer_id: str, offset: int, size: int) -> dict[str, Any]:
    return get_service().get_buffer_data(capture_path, buffer_id, offset, size)


@app.tool(
    name="renderdoc_save_texture_to_file",
    description="Save a texture resource to disk, inferring the export file type from the output path extension.",
    structured_output=True,
)
def renderdoc_save_texture_to_file(
    capture_path: str,
    texture_id: str,
    output_path: str,
    mip_level: int = 0,
    array_slice: int = 0,
) -> dict[str, Any]:
    return get_service().save_texture_to_file(
        capture_path,
        texture_id,
        output_path,
        mip_level=mip_level,
        array_slice=array_slice,
    )


@app.resource(
    "renderdoc://recent-captures",
    name="renderdoc_recent_captures",
    description="Recent RenderDoc capture files from the local qrenderdoc UI config.",
    mime_type="application/json",
)
def renderdoc_recent_captures() -> dict[str, Any]:
    return get_service().recent_captures_resource()


@app.resource(
    "renderdoc://capture/{encoded_path}/summary",
    name="renderdoc_capture_summary",
    description="A JSON capture summary for the supplied base64url-encoded RenderDoc capture path.",
    mime_type="application/json",
)
def renderdoc_capture_summary(encoded_path: str) -> dict[str, Any]:
    return get_service().capture_summary_resource(encoded_path)


def main() -> None:
    app.run(transport="stdio")
