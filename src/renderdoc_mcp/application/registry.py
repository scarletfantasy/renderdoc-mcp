from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from renderdoc_mcp.application.app import RenderDocApplication


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


def build_tool_registry(application: RenderDocApplication) -> list[ToolRegistration]:
    return [
        ToolRegistration(
            "renderdoc_open_capture",
            "Open a RenderDoc capture and return a capture_id plus compact overview metadata.",
            application.captures.renderdoc_open_capture,
        ),
        ToolRegistration(
            "renderdoc_close_capture",
            "Close an open RenderDoc capture session by capture_id.",
            application.captures.renderdoc_close_capture,
        ),
        ToolRegistration(
            "renderdoc_get_capture_overview",
            "Return compact capture, frame, statistics, and capability overview data for an open capture.",
            application.captures.renderdoc_get_capture_overview,
        ),
        ToolRegistration(
            "renderdoc_get_analysis_worklist",
            "Return a ranked AI-first worklist of the next passes, events, or resources worth investigating.",
            application.captures.renderdoc_get_analysis_worklist,
        ),
        ToolRegistration(
            "renderdoc_list_passes",
            "List direct child passes for the root or a parent pass_id with pagination, filtering, and sorting.",
            application.captures.renderdoc_list_passes,
        ),
        ToolRegistration(
            "renderdoc_get_pass_summary",
            "Return a compact summary for a single analyzed pass_id.",
            application.captures.renderdoc_get_pass_summary,
        ),
        ToolRegistration(
            "renderdoc_list_timing_events",
            "List paged GPU timing rows for a pass_id when timing is available.",
            application.captures.renderdoc_list_timing_events,
        ),
        ToolRegistration(
            "renderdoc_list_actions",
            "List direct child actions for the root or a parent event_id with pagination and compact rows.",
            application.actions.renderdoc_list_actions,
        ),
        ToolRegistration(
            "renderdoc_get_action_summary",
            "Return a compact summary for a single RenderDoc event_id.",
            application.actions.renderdoc_get_action_summary,
        ),
        ToolRegistration(
            "renderdoc_get_pipeline_overview",
            "Return a compact pipeline overview with counts and shader stage summaries for an event.",
            application.actions.renderdoc_get_pipeline_overview,
        ),
        ToolRegistration(
            "renderdoc_list_pipeline_bindings",
            "List paged pipeline bindings, descriptors, buffers, outputs, shaders, or API details for an event.",
            application.actions.renderdoc_list_pipeline_bindings,
        ),
        ToolRegistration(
            "renderdoc_get_shader_summary",
            "Return compact shader metadata and binding counts for a stage at an event without disassembly text.",
            application.actions.renderdoc_get_shader_summary,
        ),
        ToolRegistration(
            "renderdoc_get_shader_code_chunk",
            "Return a paged line chunk from shader disassembly for a stage at an event.",
            application.actions.renderdoc_get_shader_code_chunk,
        ),
        ToolRegistration(
            "renderdoc_list_resources",
            "List paged texture and buffer resources with compact rows and no duplicated arrays.",
            application.resources.renderdoc_list_resources,
        ),
        ToolRegistration(
            "renderdoc_get_resource_summary",
            "Return a compact summary and recommended follow-up calls for a single texture or buffer resource.",
            application.resources.renderdoc_get_resource_summary,
        ),
        ToolRegistration(
            "renderdoc_get_pixel_history",
            "List paged pixel history modifications for a single texture pixel and subresource.",
            application.resources.renderdoc_get_pixel_history,
        ),
        ToolRegistration(
            "renderdoc_debug_pixel",
            "Summarize the draws or GPU events that affected a texture pixel.",
            application.resources.renderdoc_debug_pixel,
        ),
        ToolRegistration(
            "renderdoc_start_pixel_shader_debug",
            "Start a pixel shader debugging session for a draw event and pixel co-ordinate.",
            application.resources.renderdoc_start_pixel_shader_debug,
        ),
        ToolRegistration(
            "renderdoc_continue_shader_debug",
            "Continue a shader debugging session and return the next compact batch of states.",
            application.resources.renderdoc_continue_shader_debug,
        ),
        ToolRegistration(
            "renderdoc_get_shader_debug_step",
            "Return the detailed variable changes for a previously fetched shader debug step.",
            application.resources.renderdoc_get_shader_debug_step,
        ),
        ToolRegistration(
            "renderdoc_end_shader_debug",
            "Close a shader debugging session and release the underlying RenderDoc trace.",
            application.resources.renderdoc_end_shader_debug,
        ),
        ToolRegistration(
            "renderdoc_get_texture_data",
            "Return a bounded JSON-friendly texture preview grid for a selected region and subresource.",
            application.resources.renderdoc_get_texture_data,
        ),
        ToolRegistration(
            "renderdoc_get_buffer_data",
            "Return a bounded hex or base64 buffer window with AI-friendly small defaults.",
            application.resources.renderdoc_get_buffer_data,
        ),
        ToolRegistration(
            "renderdoc_save_texture_to_file",
            "Save a texture resource to disk, inferring the export type from the output extension.",
            application.resources.renderdoc_save_texture_to_file,
        ),
    ]


def build_resource_registry(application: RenderDocApplication) -> list[ResourceRegistration]:
    return [
        ResourceRegistration(
            "renderdoc://recent-captures",
            "renderdoc_recent_captures",
            "Recent RenderDoc capture files from the local qrenderdoc UI config.",
            application.captures.renderdoc_recent_captures,
        ),
        ResourceRegistration(
            "renderdoc://capture/{capture_id}/overview",
            "renderdoc_capture_overview",
            "A compact overview for an already-open RenderDoc capture session.",
            application.captures.renderdoc_capture_overview_resource,
        ),
    ]
