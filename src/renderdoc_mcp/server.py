from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from renderdoc_mcp.service import RenderDocService


@lru_cache(maxsize=1)
def get_service() -> RenderDocService:
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
    description="Analyze a RenderDoc capture into top-level passes, hotspots, and a tail UI/present chain.",
    structured_output=True,
)
def renderdoc_analyze_frame(capture_path: str) -> dict[str, Any]:
    return get_service().analyze_frame(capture_path)


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
    description="List analyzed top-level frame passes with pagination and optional category or name filters.",
    structured_output=True,
)
def renderdoc_list_passes(
    capture_path: str,
    cursor: int | None = None,
    limit: int | None = None,
    category_filter: str | None = None,
    name_filter: str | None = None,
) -> dict[str, Any]:
    return get_service().list_passes(
        capture_path,
        cursor=cursor,
        limit=limit,
        category_filter=category_filter,
        name_filter=name_filter,
    )


@app.tool(
    name="renderdoc_get_pass_details",
    description="Fetch the full analyzed pass structure for a previously listed pass_id.",
    structured_output=True,
)
def renderdoc_get_pass_details(capture_path: str, pass_id: str) -> dict[str, Any]:
    return get_service().get_pass_details(capture_path, pass_id)


@app.tool(
    name="renderdoc_get_action_details",
    description="Fetch details for a specific RenderDoc event_id, including draw or dispatch metadata.",
    structured_output=True,
)
def renderdoc_get_action_details(capture_path: str, event_id: int) -> dict[str, Any]:
    return get_service().get_action_details(capture_path, event_id)


@app.tool(
    name="renderdoc_get_pipeline_state",
    description="Fetch the API-agnostic pipeline state at a specific RenderDoc event_id.",
    structured_output=True,
)
def renderdoc_get_pipeline_state(capture_path: str, event_id: int) -> dict[str, Any]:
    return get_service().get_pipeline_state(capture_path, event_id)


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
