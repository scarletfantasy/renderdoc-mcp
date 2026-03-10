from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from renderdoc_mcp import bridge as bridge_module
from renderdoc_mcp.errors import BridgeHandshakeTimeoutError
from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge import client as bridge_client_module
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge.client import BridgeClient


class FakeMiniQt:
    def InvokeOntoUIThread(self, callback):
        callback()


class FakeExtensions:
    def GetMiniQtHelper(self):
        return FakeMiniQt()


class FakeReplay:
    def __init__(self, controller) -> None:
        self.controller = controller

    def BlockInvoke(self, callback):
        callback(self.controller)


class FakeAction:
    eventId = 7
    customName = ""
    flags = 0

    def GetName(self, structured_file):
        return "Draw"


class FakeContext:
    def __init__(self, controller) -> None:
        self.controller = controller

    def Extensions(self):
        return FakeExtensions()

    def Replay(self):
        return FakeReplay(self.controller)

    def IsCaptureLoaded(self):
        return True

    def GetAction(self, event_id):
        return FakeAction()

    def SetEventID(self, *args):
        return None

    def GetResourceName(self, resource_id):
        return str(resource_id)

    def GetTextures(self):
        return []

    def GetBuffers(self):
        return []


class FakeState:
    def __init__(self, *, shader_bound: bool = False) -> None:
        self.shader_bound = shader_bound

    def GetPrimitiveTopology(self):
        return "TriangleList"

    def GetShader(self, stage):
        if self.shader_bound:
            return "shader-1"
        return None

    def GetShaderReflection(self, stage):
        if not self.shader_bound:
            return None
        return SimpleNamespace(
            resourceId="shader-1",
            entryPoint="main",
            encoding="DXBC",
            inputSignature=[],
            outputSignature=[],
            constantBlocks=[],
        )

    def GetShaderEntryPoint(self, stage):
        if self.shader_bound:
            return "main"
        return ""


class FakeController:
    def __init__(self, *, api_name: str = "D3D12", state: FakeState | None = None) -> None:
        self.api_name = api_name
        self.state = state or FakeState()

    def GetStructuredFile(self):
        return object()

    def GetAPIProperties(self):
        return SimpleNamespace(pipelineType=self.api_name)

    def GetPipelineState(self):
        return self.state


def test_qrenderdoc_bridge_records_renderdoc_version_from_hello() -> None:
    bridge = QRenderDocBridge(timeout_seconds=1.0)

    bridge._accept_hello({"type": "hello", "token": "token", "renderdoc_version": "1.43"}, "token")

    assert bridge.renderdoc_version == "1.43"


def test_qrenderdoc_bridge_timeout_does_not_shell_out_to_kill_external_processes(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self._terminated = False

        def poll(self):
            return 0 if self._terminated else None

        def terminate(self) -> None:
            self._terminated = True

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            self._terminated = True

    class FakeListenSocket:
        def setsockopt(self, *args) -> None:
            return None

        def bind(self, address) -> None:
            return None

        def listen(self, backlog) -> None:
            return None

        def settimeout(self, value) -> None:
            return None

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def accept(self):
            raise TimeoutError()

        def close(self) -> None:
            return None

    monotonic_values = iter([0.0, 0.0, 1.0, 1.0, 1.0, 2.0])
    spawned: list[FakeProcess] = []
    subprocess_run_calls: list[list[str]] = []

    monkeypatch.setattr(bridge_module, "resolve_qrenderdoc_path", lambda: Path(r"C:\RenderDoc\qrenderdoc.exe"))
    monkeypatch.setattr(bridge_module.socket, "socket", lambda *args, **kwargs: FakeListenSocket())
    monkeypatch.setattr(bridge_module.subprocess, "Popen", lambda *args, **kwargs: spawned.append(FakeProcess()) or spawned[-1])
    monkeypatch.setattr(
        bridge_module.subprocess,
        "run",
        lambda args, **kwargs: subprocess_run_calls.append(list(args)) or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(bridge_module.time, "sleep", lambda seconds: None)

    bridge = QRenderDocBridge(timeout_seconds=1.0)

    with pytest.raises(BridgeHandshakeTimeoutError):
        bridge.ensure_started()

    assert len(spawned) == 2
    assert all(process.poll() is not None for process in spawned)
    assert subprocess_run_calls == []


def test_bridge_client_pipeline_overview_gracefully_handles_missing_descriptor_access() -> None:
    client = BridgeClient(FakeContext(FakeController()))

    response = client._get_pipeline_overview(7)

    assert response["pipeline"]["available"] is True
    assert response["pipeline"]["counts"]["descriptor_accesses"] == 0
    assert response["pipeline"]["graphics_pipeline_object"] == ""


def test_bridge_client_pipeline_bindings_degrades_when_accessor_signature_changes() -> None:
    class BrokenController(FakeController):
        def GetD3D12PipelineState(self):
            raise TypeError("signature changed")

    client = BridgeClient(FakeContext(BrokenController(api_name="D3D12")))

    response = client._list_pipeline_bindings(7, "api_details", 0, 50)

    assert response["items"][0]["available"] is False
    assert "compatible D3D12 pipeline accessor" in response["items"][0]["reason"]


def test_bridge_client_shader_summary_returns_unavailable_when_disassembly_targets_missing(monkeypatch) -> None:
    client = BridgeClient(FakeContext(FakeController(state=FakeState(shader_bound=True))))
    monkeypatch.setattr(bridge_client_module, "_shader_stage_from_name", lambda stage_name: "Pixel")
    monkeypatch.setattr(bridge_client_module, "_shader_stage_values", lambda: ["Pixel"])

    response = client._get_shader_summary(7, "pixel")

    assert response["shader"]["stage"] == "Pixel"
    assert response["disassembly"]["available"] is False
    assert "did not report any shader disassembly targets" in response["disassembly"]["reason"]


def test_bridge_client_shader_code_chunk_pages_cached_disassembly(monkeypatch) -> None:
    client = BridgeClient(FakeContext(FakeController(state=FakeState(shader_bound=True))))
    monkeypatch.setattr(
        client,
        "_get_shader_code",
        lambda event_id, stage_name, target: {
            "event_id": event_id,
            "api": "D3D12",
            "action": {"event_id": event_id},
            "shader": {"stage": "Pixel", "shader_id": "shader-1", "shader_name": "MainPS"},
            "disassembly": {
                "available": True,
                "reason": "",
                "target": "dxil",
                "available_targets": ["dxil"],
                "text": "line1\nline2\nline3",
            },
        },
    )

    response = client._get_shader_code_chunk(7, "Pixel", None, 2, 2)

    assert response["start_line"] == 2
    assert response["returned_line_count"] == 2
    assert response["has_more"] is False
    assert response["text"] == "line2\nline3"
