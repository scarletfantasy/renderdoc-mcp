from __future__ import annotations

from pathlib import Path

import pytest

from renderdoc_mcp.application import RenderDocApplication
from renderdoc_mcp.application.registry import build_resource_registry, build_tool_registry
from renderdoc_mcp.errors import InvalidCaptureIDError, ReplayFailureError
from renderdoc_mcp.session_pool import CaptureSessionPool


class DummyBridge:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.calls: list[tuple[str, dict]] = []
        self.closed = 0
        self.renderdoc_version = "1.43"

    def ensure_capture_loaded(self, capture_path: str):
        self.loaded.append(capture_path)
        return {"loaded": True, "filename": capture_path}

    def call(self, method: str, params=None):
        payload = params or {}
        self.calls.append((method, payload))

        if method == "get_capture_overview":
            return {
                "capture": {"loaded": True, "filename": "sample.rdc"},
                "api": "D3D12",
                "frame": {"frame_number": 1},
                "statistics": {"total_actions": 2},
                "resource_counts": {"textures": 1, "buffers": 1},
                "root_pass_count": 1,
                "action_root_count": 1,
                "capabilities": {"timing_data": True, "pixel_history": True, "shader_disassembly": True},
                "meta": {},
            }
        if method == "get_analysis_worklist":
            return {
                "focus": payload.get("focus", "performance"),
                "count": 1,
                "items": [
                    {
                        "kind": "pass",
                        "id": "pass:1-10",
                        "label": "BasePass",
                        "reason": "Hot path",
                        "recommended_call": {"tool": "renderdoc_get_pass_summary", "arguments": {"pass_id": "pass:1-10"}},
                    }
                ],
                "meta": {},
            }
        if method == "list_actions":
            return {
                "parent_event_id": str(payload.get("parent_event_id", "")),
                "name_filter": payload.get("name_filter", ""),
                "flags_filter": payload.get("flags_filter", ""),
                "actions": [],
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 50)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    }
                },
            }
        if method == "list_passes":
            return {
                "parent_pass_id": payload.get("parent_pass_id", ""),
                "passes": [],
                "sort_by": payload.get("sort_by", "event_order"),
                "effective_sort_by": payload.get("sort_by", "event_order"),
                "category_filter": payload.get("category_filter", ""),
                "name_filter": payload.get("name_filter", ""),
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 50)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    }
                },
            }
        if method == "get_pass_summary":
            return {"pass_id": payload["pass_id"], "parent_pass_id": "", "child_pass_count": 0, "meta": {}}
        if method == "list_timing_events":
            return {
                "pass": {"pass_id": payload["pass_id"]},
                "basis": "gpu_timing",
                "sort_by": payload.get("sort_by", "event_order"),
                "effective_sort_by": payload.get("sort_by", "event_order"),
                "total_gpu_time_ms": 0.0,
                "timed_event_count": 0,
                "events": [],
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 100)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    },
                    "timing": {"timing_available": True, "counter_name": "EventGPUDuration"},
                },
            }
        if method == "get_action_summary":
            return {
                "action": {
                    "event_id": payload["event_id"],
                    "name": "Draw",
                    "flags": ["draw"],
                    "depth": 2,
                    "child_count": 0,
                    "parent_event_id": 1,
                    "resource_usage_summary": {"output_count": 1, "has_depth_output": True},
                },
                "meta": {},
            }
        if method == "get_pipeline_overview":
            return {
                "event_id": payload["event_id"],
                "api": "D3D12",
                "action": {"event_id": payload["event_id"], "name": "Draw", "flags": ["draw"]},
                "pipeline": {
                    "available": True,
                    "topology": "TriangleList",
                    "graphics_pipeline_object": "pipe",
                    "compute_pipeline_object": "",
                    "counts": {
                        "descriptor_accesses": 2,
                        "vertex_buffers": 1,
                        "vertex_inputs": 1,
                        "output_targets": 1,
                        "shaders": 2,
                    },
                    "shaders": [],
                    "api_details_available": True,
                    "api_details_api": "D3D12",
                },
                "meta": {},
            }
        if method == "list_pipeline_bindings":
            return {
                "event_id": payload["event_id"],
                "binding_kind": payload["binding_kind"],
                "items": [],
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 50)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    }
                },
            }
        if method == "get_shader_summary":
            return {
                "event_id": payload["event_id"],
                "shader": {"stage": payload["stage"], "counts": {}},
                "disassembly": {"available": True, "available_targets": ["dxil"], "default_target": "dxil"},
                "meta": {},
            }
        if method == "get_shader_code_chunk":
            return {
                "event_id": payload["event_id"],
                "shader": {"stage": payload["stage"]},
                "target": payload.get("target", ""),
                "start_line": int(payload.get("start_line", 1)),
                "returned_line_count": 1,
                "total_lines": 1,
                "has_more": False,
                "available": True,
                "reason": "",
                "text": "shader",
                "meta": {},
            }
        if method == "list_resources":
            return {
                "kind": payload["kind"],
                "sort_by": payload.get("sort_by", "name"),
                "name_filter": payload.get("name_filter", ""),
                "items": [],
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 50)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    }
                },
            }
        if method == "get_resource_summary":
            return {
                "resource": {"resource_id": payload["resource_id"], "kind": "texture"},
                "recommended_calls": [],
                "meta": {},
            }
        if method == "get_pixel_history":
            return {
                "texture": {"resource_id": payload["texture_id"]},
                "query": {"x": payload["x"], "y": payload["y"]},
                "modifications": [],
                "total_modification_count": 0,
                "meta": {
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 100)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    }
                },
            }
        if method == "debug_pixel":
            return {"texture": {"resource_id": payload["texture_id"]}, "draws": [], "meta": {}}
        if method == "get_texture_data":
            return {"texture": {"resource_id": payload["texture_id"]}, "pixels": [], "meta": {}}
        if method == "get_buffer_data":
            return {
                "buffer": {"resource_id": payload["buffer_id"]},
                "returned_size": 4,
                "encoding": payload.get("encoding", "hex"),
                "data": "00 00 00 00",
                "meta": {},
            }
        if method == "save_texture_to_file":
            return {"saved": True, "output_path": payload["output_path"], "meta": {}}
        return {"ok": True, "meta": {}}

    def close(self) -> None:
        self.closed += 1


def _capture(tmp_path: Path, name: str = "sample.rdc") -> str:
    capture_path = tmp_path / name
    capture_path.write_text("x", encoding="utf-8")
    return str(capture_path.resolve())


def _application() -> tuple[RenderDocApplication, list[DummyBridge]]:
    created: list[DummyBridge] = []
    pool = CaptureSessionPool(bridge_factory=lambda: created.append(DummyBridge()) or created[-1])
    return RenderDocApplication(session_pool=pool), created


def test_open_capture_returns_capture_id_and_overview(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)

    response = application.captures.renderdoc_open_capture(capture_path)

    assert response["capture_id"]
    assert response["capture_path"] == capture_path
    assert response["api"] == "D3D12"
    assert response["root_pass_count"] == 1
    assert response["meta"] == {"renderdoc_version": "1.43"}
    assert created[0].loaded == [capture_path]
    assert created[0].calls == [("get_capture_overview", {})]


def test_handlers_reuse_capture_id_session_and_attach_meta(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    actions = application.actions.renderdoc_list_actions(opened["capture_id"], cursor="10", limit="25")
    passes = application.captures.renderdoc_list_passes(opened["capture_id"], limit=5, sort_by="gpu_time")
    pipeline = application.actions.renderdoc_get_pipeline_overview(opened["capture_id"], event_id="42")

    assert actions["capture_id"] == opened["capture_id"]
    assert actions["meta"]["renderdoc_version"] == "1.43"
    assert actions["meta"]["page"]["cursor"] == "10"
    assert passes["meta"]["page"]["limit"] == 5
    assert passes["sort_by"] == "gpu_time"
    assert pipeline["pipeline"]["api_details_available"] is True
    assert [call[0] for call in created[0].calls] == [
        "get_capture_overview",
        "list_actions",
        "list_passes",
        "get_pipeline_overview",
    ]


def test_close_capture_invalidates_session(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    closed = application.captures.renderdoc_close_capture(opened["capture_id"])

    assert closed["closed"] is True
    assert created[0].closed == 1
    with pytest.raises(InvalidCaptureIDError):
        application.captures.renderdoc_get_capture_overview(opened["capture_id"])


def test_analysis_worklist_uses_distinct_bridge_method(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    response = application.captures.renderdoc_get_analysis_worklist(opened["capture_id"], focus="structure", limit=5)

    assert response["focus"] == "structure"
    assert created[0].calls[-1] == ("get_analysis_worklist", {"focus": "structure", "limit": 5})


def test_buffer_reads_default_to_hex(tmp_path: Path) -> None:
    application, _ = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    response = application.resources.renderdoc_get_buffer_data(opened["capture_id"], " buf123 ", "16", "32")

    assert response["encoding"] == "hex"
    assert response["data"] == "00 00 00 00"


def test_validation_errors_raise_domain_exceptions(tmp_path: Path) -> None:
    application, _ = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    with pytest.raises(ReplayFailureError):
        application.actions.renderdoc_list_actions(opened["capture_id"], limit="2000")
    with pytest.raises(ReplayFailureError):
        application.resources.renderdoc_list_resources(opened["capture_id"], kind="bogus")
    with pytest.raises(ReplayFailureError):
        application.actions.renderdoc_list_pipeline_bindings(opened["capture_id"], event_id=7, binding_kind="bogus")


def test_registry_contains_new_breaking_api_surface() -> None:
    application, _ = _application()
    tool_names = {tool.name for tool in build_tool_registry(application)}
    resource_uris = {resource.uri for resource in build_resource_registry(application)}

    assert {
        "renderdoc_open_capture",
        "renderdoc_get_capture_overview",
        "renderdoc_get_analysis_worklist",
        "renderdoc_get_pipeline_overview",
        "renderdoc_get_shader_code_chunk",
    }.issubset(tool_names)
    assert "renderdoc://capture/{capture_id}/overview" in resource_uris
