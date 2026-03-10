from __future__ import annotations

from pathlib import Path

from renderdoc_mcp.errors import ReplayFailureError
from renderdoc_mcp.service import RenderDocService


class DummyBridge:
    def __init__(self) -> None:
        self.loaded = []
        self.calls = []

    def ensure_capture_loaded(self, capture_path: str):
        self.loaded.append(capture_path)
        return {"loaded": True}

    def call(self, method: str, params=None):
        self.calls.append((method, params or {}))
        if method == "get_capture_summary":
            return {"api": "D3D12"}
        if method == "analyze_frame":
            return {"passes": [], "pass_count": 0}
        if method == "list_passes":
            return {"passes": [], "count": 0, "matched_count": 0, "returned_count": 0, "limit": 100}
        if method == "get_pass_details":
            return {"pass_id": "pass:1-2"}
        if method == "get_buffer_data":
            return {"returned_size": 4, "data_base64": "AAAAAA=="}
        return {"ok": True}


def test_summary_response_envelope(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_capture_summary(str(capture_path))

    assert response["error"] is None
    assert response["result"]["api"] == "D3D12"
    assert bridge.loaded == [str(capture_path.resolve())]
    assert bridge.calls == [("get_capture_summary", {})]


def test_invalid_resource_kind_returns_structured_error(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.list_resources(str(capture_path), kind="bogus")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_list_actions_normalizes_string_inputs(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.list_actions(str(capture_path), max_depth="2", name_filter="null")

    assert response["error"] is None
    assert bridge.calls == [("list_actions", {"max_depth": 2})]


def test_list_actions_accepts_pagination_inputs(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.list_actions(str(capture_path), cursor="10", limit="25")

    assert response["error"] is None
    assert bridge.calls == [("list_actions", {"cursor": 10, "limit": 25})]


def test_list_actions_rejects_large_limit(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.list_actions(str(capture_path), limit="2000")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_analyze_frame_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.analyze_frame(str(capture_path))

    assert response["error"] is None
    assert bridge.calls == [("analyze_frame", {})]


def test_list_passes_validates_category_filter(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.list_passes(str(capture_path), category_filter="bogus")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_list_passes_uses_default_limit(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.list_passes(str(capture_path), cursor="5", category_filter="geometry")

    assert response["error"] is None
    assert bridge.calls == [("list_passes", {"limit": 100, "cursor": 5, "category_filter": "geometry"})]


def test_get_pass_details_requires_non_empty_pass_id(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_pass_details(str(capture_path), "null")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_invalid_event_id_string_returns_structured_error(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_action_details(str(capture_path), event_id="not-an-int")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_get_shader_code_normalizes_stage_and_target(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_shader_code(str(capture_path), event_id="42", stage=" ps ", target=" DXBC ")

    assert response["error"] is None
    assert bridge.calls == [("get_shader_code", {"event_id": 42, "stage": "Pixel", "target": "DXBC"})]


def test_get_shader_code_rejects_unknown_stage(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_shader_code(str(capture_path), event_id=7, stage="bogus")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_tool_wraps_domain_errors(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service._error_response(str(capture_path), ReplayFailureError("boom"), "failed")

    assert response["error"]["message"] == "boom"


def test_get_timing_data_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_timing_data(str(capture_path), " pass:1-2 ")

    assert response["error"] is None
    assert bridge.calls == [("get_timing_data", {"pass_id": "pass:1-2"})]


def test_get_timing_data_requires_non_empty_pass_id(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_timing_data(str(capture_path), "null")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_get_performance_hotspots_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_performance_hotspots(str(capture_path))

    assert response["error"] is None
    assert bridge.calls == [("get_performance_hotspots", {})]


def test_get_pixel_history_normalizes_default_subresource_inputs(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_pixel_history(str(capture_path), texture_id=" tex123 ", x="10", y="20")

    assert response["error"] is None
    assert bridge.calls == [
        (
            "get_pixel_history",
            {"texture_id": "tex123", "x": 10, "y": 20, "mip_level": 0, "array_slice": 0, "sample": 0},
        )
    ]


def test_debug_pixel_rejects_negative_coordinates(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.debug_pixel(str(capture_path), texture_id="tex123", x=-1, y=4)

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_get_texture_data_validates_preview_limits(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_texture_data(
        str(capture_path),
        texture_id="tex123",
        mip_level=0,
        x=0,
        y=0,
        width=65,
        height=1,
    )

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_get_texture_data_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_texture_data(
        str(capture_path),
        texture_id="tex123",
        mip_level="1",
        x="2",
        y="3",
        width="4",
        height="5",
        array_slice="6",
        sample="7",
    )

    assert response["error"] is None
    assert bridge.calls == [
        (
            "get_texture_data",
            {
                "texture_id": "tex123",
                "mip_level": 1,
                "x": 2,
                "y": 3,
                "width": 4,
                "height": 5,
                "array_slice": 6,
                "sample": 7,
            },
        )
    ]


def test_get_buffer_data_rejects_large_reads(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_buffer_data(str(capture_path), buffer_id="buf123", offset=0, size=70000)

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_get_buffer_data_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.get_buffer_data(str(capture_path), buffer_id=" buf123 ", offset="16", size="32")

    assert response["error"] is None
    assert bridge.calls == [("get_buffer_data", {"buffer_id": "buf123", "offset": 16, "size": 32})]
    assert response["result"]["data_hex_preview"] == "00 00 00 00"


def test_save_texture_to_file_rejects_unknown_extension(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.save_texture_to_file(str(capture_path), texture_id="tex123", output_path="out.bmp")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_save_texture_to_file_uses_bridge(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    bridge = DummyBridge()
    service = RenderDocService(bridge=bridge)
    response = service.save_texture_to_file(
        str(capture_path),
        texture_id=" tex123 ",
        output_path=" render.png ",
        mip_level="2",
        array_slice="3",
    )

    assert response["error"] is None
    assert bridge.calls == [
        (
            "save_texture_to_file",
            {"texture_id": "tex123", "output_path": "render.png", "mip_level": 2, "array_slice": 3},
        )
    ]
