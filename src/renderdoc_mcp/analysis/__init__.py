"""Shared analysis logic used by both the MCP server and the qrenderdoc extension."""

from renderdoc_mcp.analysis.frame_analysis import (
    DEFAULT_ACTION_PAGE_LIMIT,
    DEFAULT_PASS_PAGE_LIMIT,
    HOTSPOT_LIMIT,
    LEGACY_ACTION_LIST_NODE_LIMIT,
    MAX_PAGE_LIMIT,
    PASS_CATEGORIES,
    TOP_PASS_RANKING_LIMIT,
    AnalysisCache,
    build_action_list_result,
    build_frame_analysis,
    build_performance_hotspots,
    build_timing_result,
    get_pass_details,
    list_passes,
    pass_id_from_range,
)

__all__ = [
    "AnalysisCache",
    "PASS_CATEGORIES",
    "LEGACY_ACTION_LIST_NODE_LIMIT",
    "DEFAULT_ACTION_PAGE_LIMIT",
    "DEFAULT_PASS_PAGE_LIMIT",
    "HOTSPOT_LIMIT",
    "MAX_PAGE_LIMIT",
    "TOP_PASS_RANKING_LIMIT",
    "build_action_list_result",
    "build_frame_analysis",
    "build_performance_hotspots",
    "build_timing_result",
    "list_passes",
    "get_pass_details",
    "pass_id_from_range",
]
