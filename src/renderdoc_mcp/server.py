from __future__ import annotations

from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from renderdoc_mcp.application import RenderDocApplication
from renderdoc_mcp.application.registry import build_resource_registry, build_tool_registry
from renderdoc_mcp.bootstrap import prepare_runtime


@lru_cache(maxsize=1)
def get_application() -> RenderDocApplication:
    prepare_runtime()
    return RenderDocApplication()


app = FastMCP(
    name="renderdoc-mcp",
    instructions=(
        "Use renderdoc_open_capture first, then pass the returned capture_id to the other tools. "
        "Start with renderdoc_get_capture_overview or renderdoc_get_analysis_worklist, then drill down with paged list tools. "
        "The server launches qrenderdoc as needed and keeps each open capture session alive until closed or evicted."
    ),
)


def _register_registry() -> None:
    application = get_application()
    for tool in build_tool_registry(application):
        app.add_tool(
            tool.handler,
            name=tool.name,
            description=tool.description,
            structured_output=True,
        )

    for resource in build_resource_registry(application):
        app.resource(
            resource.uri,
            name=resource.name,
            description=resource.description,
            mime_type="application/json",
        )(resource.handler)


_register_registry()


def main() -> None:
    app.run(transport="stdio")
