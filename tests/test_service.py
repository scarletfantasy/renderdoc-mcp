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


def test_invalid_event_id_string_returns_structured_error(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service.get_action_details(str(capture_path), event_id="not-an-int")

    assert response["result"] is None
    assert response["error"]["code"] == "replay_failure"


def test_tool_wraps_domain_errors(tmp_path: Path) -> None:
    capture_path = tmp_path / "sample.rdc"
    capture_path.write_text("x", encoding="utf-8")

    service = RenderDocService(bridge=DummyBridge())
    response = service._error_response(str(capture_path), ReplayFailureError("boom"), "failed")

    assert response["error"]["message"] == "boom"
