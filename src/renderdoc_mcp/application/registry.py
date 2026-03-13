from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from renderdoc_mcp.application.app import RenderDocApplication
from renderdoc_mcp.application.command_specs import ResourceSpec, ToolSpec


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ResourceRegistration:
    uri: str
    name: str
    description: str
    handler: Callable[..., dict[str, Any]]


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "renderdoc_open_capture",
        "Open a RenderDoc capture and return a capture_id plus compact overview metadata.",
        "load_capture",
        lambda application: application.captures.renderdoc_open_capture,
    ),
    ToolSpec(
        "renderdoc_close_capture",
        "Close an open RenderDoc capture session by capture_id.",
        "close_capture",
        lambda application: application.captures.renderdoc_close_capture,
    ),
    ToolSpec(
        "renderdoc_get_capture_overview",
        "Return compact capture, frame, statistics, and capability overview data for an open capture.",
        "get_capture_overview",
        lambda application: application.captures.renderdoc_get_capture_overview,
    ),
    ToolSpec(
        "renderdoc_get_analysis_worklist",
        "Return a ranked AI-first worklist of the next passes, events, or resources worth investigating.",
        "get_analysis_worklist",
        lambda application: application.captures.renderdoc_get_analysis_worklist,
    ),
    ToolSpec(
        "renderdoc_list_passes",
        "List direct child passes for the root or a parent pass_id with pagination, filtering, and sorting.",
        "list_passes",
        lambda application: application.captures.renderdoc_list_passes,
    ),
    ToolSpec(
        "renderdoc_get_pass_summary",
        "Return a compact summary for a single analyzed pass_id.",
        "get_pass_summary",
        lambda application: application.captures.renderdoc_get_pass_summary,
    ),
    ToolSpec(
        "renderdoc_list_timing_events",
        "List paged GPU timing rows for a pass_id when timing is available.",
        "list_timing_events",
        lambda application: application.captures.renderdoc_list_timing_events,
    ),
    ToolSpec(
        "renderdoc_list_actions",
        "List direct child actions for the root or a parent event_id with pagination and compact rows.",
        "list_actions",
        lambda application: application.actions.renderdoc_list_actions,
    ),
    ToolSpec(
        "renderdoc_get_action_summary",
        "Return a compact summary for a single RenderDoc event_id.",
        "get_action_summary",
        lambda application: application.actions.renderdoc_get_action_summary,
    ),
    ToolSpec(
        "renderdoc_get_pipeline_overview",
        "Return a compact pipeline overview with counts and shader stage summaries for an event.",
        "get_pipeline_overview",
        lambda application: application.actions.renderdoc_get_pipeline_overview,
    ),
    ToolSpec(
        "renderdoc_list_pipeline_bindings",
        "List paged pipeline bindings, descriptors, buffers, outputs, shaders, or API details for an event.",
        "list_pipeline_bindings",
        lambda application: application.actions.renderdoc_list_pipeline_bindings,
    ),
    ToolSpec(
        "renderdoc_get_shader_summary",
        "Return compact shader metadata and binding counts for a stage at an event without disassembly text.",
        "get_shader_summary",
        lambda application: application.actions.renderdoc_get_shader_summary,
    ),
    ToolSpec(
        "renderdoc_get_shader_code_chunk",
        "Return a paged line chunk from shader disassembly for a stage at an event.",
        "get_shader_code_chunk",
        lambda application: application.actions.renderdoc_get_shader_code_chunk,
    ),
    ToolSpec(
        "renderdoc_list_resources",
        "List paged texture and buffer resources with compact rows and no duplicated arrays.",
        "list_resources",
        lambda application: application.resources.renderdoc_list_resources,
    ),
    ToolSpec(
        "renderdoc_get_resource_summary",
        "Return a compact summary and recommended follow-up calls for a single texture or buffer resource.",
        "get_resource_summary",
        lambda application: application.resources.renderdoc_get_resource_summary,
    ),
    ToolSpec(
        "renderdoc_list_resource_usages",
        "List paged direct draw or action events that use a texture as an RT, depth target, copy source, or copy destination.",
        "list_resource_usages",
        lambda application: application.resources.renderdoc_list_resource_usages,
    ),
    ToolSpec(
        "renderdoc_get_pixel_history",
        "List paged pixel history modifications for a single texture pixel and subresource.",
        "get_pixel_history",
        lambda application: application.resources.renderdoc_get_pixel_history,
    ),
    ToolSpec(
        "renderdoc_debug_pixel",
        "Summarize the draws or GPU events that affected a texture pixel.",
        "debug_pixel",
        lambda application: application.resources.renderdoc_debug_pixel,
    ),
    ToolSpec(
        "renderdoc_start_pixel_shader_debug",
        "Start a pixel shader debugging session for a draw event and pixel co-ordinate.",
        "start_pixel_shader_debug",
        lambda application: application.resources.renderdoc_start_pixel_shader_debug,
    ),
    ToolSpec(
        "renderdoc_continue_shader_debug",
        "Continue a shader debugging session and return the next compact batch of states.",
        "continue_shader_debug",
        lambda application: application.resources.renderdoc_continue_shader_debug,
    ),
    ToolSpec(
        "renderdoc_get_shader_debug_step",
        "Return the detailed variable changes for a previously fetched shader debug step.",
        "get_shader_debug_step",
        lambda application: application.resources.renderdoc_get_shader_debug_step,
    ),
    ToolSpec(
        "renderdoc_end_shader_debug",
        "Close a shader debugging session and release the underlying RenderDoc trace.",
        "end_shader_debug",
        lambda application: application.resources.renderdoc_end_shader_debug,
    ),
    ToolSpec(
        "renderdoc_get_texture_data",
        "Return a bounded JSON-friendly texture preview grid for a selected region and subresource.",
        "get_texture_data",
        lambda application: application.resources.renderdoc_get_texture_data,
    ),
    ToolSpec(
        "renderdoc_get_buffer_data",
        "Return a bounded hex or base64 buffer window with AI-friendly small defaults.",
        "get_buffer_data",
        lambda application: application.resources.renderdoc_get_buffer_data,
    ),
    ToolSpec(
        "renderdoc_save_texture_to_file",
        "Save a texture resource to disk, inferring the export type from the output extension.",
        "save_texture_to_file",
        lambda application: application.resources.renderdoc_save_texture_to_file,
    ),
)

RESOURCE_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        "renderdoc://recent-captures",
        "renderdoc_recent_captures",
        "Recent RenderDoc capture files from the local qrenderdoc UI config.",
        lambda application: application.captures.renderdoc_recent_captures,
    ),
    ResourceSpec(
        "renderdoc://capture/{capture_id}/overview",
        "renderdoc_capture_overview",
        "A compact overview for an already-open RenderDoc capture session.",
        lambda application: application.captures.renderdoc_capture_overview_resource,
    ),
)


def build_tool_registry(application: RenderDocApplication) -> list[ToolRegistration]:
    return [
        ToolRegistration(
            name=spec.name,
            description=spec.description,
            handler=spec.handler(application),
        )
        for spec in TOOL_SPECS
    ]


def build_resource_registry(application: RenderDocApplication) -> list[ResourceRegistration]:
    return [
        ResourceRegistration(
            uri=spec.uri,
            name=spec.name,
            description=spec.description,
            handler=spec.handler(application),
        )
        for spec in RESOURCE_SPECS
    ]
