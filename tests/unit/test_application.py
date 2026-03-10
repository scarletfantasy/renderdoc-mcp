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

        if method == "get_capture_summary":
            return {
                "capture": {"loaded": True, "filename": "sample.rdc"},
                "api": "D3D12",
                "frame": {"frame_number": 1},
                "statistics": {"total_actions": 2},
                "resource_counts": {"textures": 1, "buffers": 1},
                "meta": {},
            }
        if method == "analyze_frame":
            return {
                "capture": {"loaded": True, "filename": "sample.rdc"},
                "api": "D3D12",
                "frame": {"frame_number": 1},
                "statistics": {"total_actions": 2},
                "resource_counts": {"textures": 1, "buffers": 1},
                "pass_count": 0,
                "passes": [],
                "top_draw_passes": [],
                "top_compute_passes": [],
                "tail_chain": [],
                "meta": {"warnings": []},
            }
        if method == "get_action_tree":
            return {
                "actions": [],
                "meta": {
                    "page_mode": "tree_preview",
                    "page": {
                        "cursor": "0",
                        "next_cursor": "",
                        "limit": 500,
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    },
                },
            }
        if method == "list_actions":
            return {
                "actions": [],
                "meta": {
                    "page_mode": "flat_preorder",
                    "page": {
                        "cursor": str(payload.get("cursor", 0)),
                        "next_cursor": "",
                        "limit": int(payload.get("limit", 100)),
                        "returned_count": 0,
                        "total_count": 0,
                        "matched_count": 0,
                        "has_more": False,
                    },
                },
            }
        if method == "list_passes":
            return {
                "passes": [],
                "sort_by": payload.get("sort_by", "event_order"),
                "effective_sort_by": payload.get("sort_by", "event_order"),
                "category_filter": payload.get("category_filter", ""),
                "name_filter": payload.get("name_filter", ""),
                "threshold_ms": payload.get("threshold_ms"),
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
        if method == "get_pass_details":
            return {"pass_id": payload["pass_id"], "meta": {}}
        if method == "get_timing_data":
            return {
                "pass": {"pass_id": payload["pass_id"]},
                "basis": "gpu_timing",
                "total_gpu_time_ms": 0.0,
                "timed_event_count": 0,
                "events": [],
                "meta": {"timing": {"timing_available": True, "counter_name": "EventGPUDuration"}},
            }
        if method == "get_performance_hotspots":
            return {
                "basis": "heuristic",
                "top_passes": [],
                "top_events": [],
                "fallback_explanation": "unsupported",
                "meta": {
                    "timing": {
                        "timing_available": False,
                        "counter_name": "EventGPUDuration",
                        "timing_unavailable_reason": "unsupported",
                    }
                },
            }
        if method == "get_action_details":
            return {"event_id": payload["event_id"], "action": {"event_id": payload["event_id"]}, "meta": {}}
        if method == "get_pipeline_state":
            return {"event_id": payload["event_id"], "pipeline": {"shaders": []}, "meta": {}}
        if method == "get_api_pipeline_state":
            return {
                "event_id": payload["event_id"],
                "api": "D3D12",
                "api_pipeline": {"api": "D3D12", "available": True},
                "meta": {},
            }
        if method == "get_shader_code":
            return {
                "event_id": payload["event_id"],
                "shader": {"stage": payload["stage"]},
                "disassembly": {"text": "shader"},
                "meta": {},
            }
        if method == "list_resources":
            return {"kind": payload["kind"], "count": 0, "textures": [], "buffers": [], "items": [], "meta": {}}
        if method == "get_pixel_history":
            return {"texture": {"resource_id": payload["texture_id"]}, "query": {"x": payload["x"], "y": payload["y"]}, "meta": {}}
        if method == "debug_pixel":
            return {"texture": {"resource_id": payload["texture_id"]}, "draws": [], "meta": {}}
        if method == "get_texture_data":
            return {"texture": {"resource_id": payload["texture_id"]}, "pixels": [], "meta": {}}
        if method == "get_buffer_data":
            return {
                "buffer": {"resource_id": payload["buffer_id"]},
                "returned_size": 4,
                "data_base64": "AAAAAA==",
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


def test_open_capture_returns_capture_id_and_summary(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)

    response = application.captures.renderdoc_open_capture(capture_path)

    assert response["capture_id"]
    assert response["capture_path"] == capture_path
    assert response["api"] == "D3D12"
    assert response["meta"] == {"renderdoc_version": "1.43"}
    assert created[0].loaded == [capture_path]
    assert created[0].calls == [("get_capture_summary", {})]


def test_handlers_reuse_capture_id_session_and_attach_meta(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    actions = application.actions.renderdoc_list_actions(opened["capture_id"], cursor="10", limit="25")
    passes = application.captures.renderdoc_list_passes(opened["capture_id"], limit=5, sort_by="gpu_time", threshold_ms="0.5")
    pipeline = application.actions.renderdoc_get_api_pipeline_state(opened["capture_id"], event_id="42")

    assert actions["capture_id"] == opened["capture_id"]
    assert actions["meta"]["renderdoc_version"] == "1.43"
    assert actions["meta"]["page"]["cursor"] == "10"
    assert passes["meta"]["page"]["limit"] == 5
    assert passes["sort_by"] == "gpu_time"
    assert pipeline["api_pipeline"]["available"] is True
    assert [call[0] for call in created[0].calls] == [
        "get_capture_summary",
        "list_actions",
        "list_passes",
        "get_api_pipeline_state",
    ]


def test_close_capture_invalidates_session(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    closed = application.captures.renderdoc_close_capture(opened["capture_id"])

    assert closed["closed"] is True
    assert created[0].closed == 1
    with pytest.raises(InvalidCaptureIDError):
        application.captures.renderdoc_get_capture_summary(opened["capture_id"])


def test_get_action_tree_uses_distinct_bridge_method(tmp_path: Path) -> None:
    application, created = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    response = application.actions.renderdoc_get_action_tree(opened["capture_id"], max_depth=2)

    assert response["meta"]["page_mode"] == "tree_preview"
    assert created[0].calls[-1] == ("get_action_tree", {"max_depth": 2})


def test_buffer_reads_add_hex_preview(tmp_path: Path) -> None:
    application, _ = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    response = application.resources.renderdoc_get_buffer_data(opened["capture_id"], " buf123 ", "16", "32")

    assert response["data_hex_preview"] == "00 00 00 00"


def test_validation_errors_raise_domain_exceptions(tmp_path: Path) -> None:
    application, _ = _application()
    capture_path = _capture(tmp_path)
    opened = application.captures.renderdoc_open_capture(capture_path)

    with pytest.raises(ReplayFailureError):
        application.actions.renderdoc_list_actions(opened["capture_id"], limit="2000")
    with pytest.raises(ReplayFailureError):
        application.resources.renderdoc_list_resources(opened["capture_id"], kind="bogus")
    with pytest.raises(ReplayFailureError):
        application.resources.renderdoc_debug_pixel(opened["capture_id"], "tex123", -1, 4)


def test_registry_contains_new_breaking_api_surface() -> None:
    application, _ = _application()
    tool_names = {tool.name for tool in build_tool_registry(application)}
    resource_uris = {resource.uri for resource in build_resource_registry(application)}

    assert {
        "renderdoc_open_capture",
        "renderdoc_close_capture",
        "renderdoc_get_action_tree",
        "renderdoc_get_api_pipeline_state",
    }.issubset(tool_names)
    assert "renderdoc://capture/{capture_id}/summary" in resource_uris
