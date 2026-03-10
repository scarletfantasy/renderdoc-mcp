from __future__ import annotations

from types import SimpleNamespace

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


def test_bridge_client_pipeline_state_gracefully_handles_missing_descriptor_access() -> None:
    client = BridgeClient(FakeContext(FakeController()))

    response = client._get_pipeline_state(7)

    assert response["pipeline"]["available"] is True
    assert response["pipeline"]["descriptor_accesses"] == []
    assert response["pipeline"]["graphics_pipeline_object"] == ""


def test_bridge_client_api_pipeline_state_degrades_when_accessor_signature_changes() -> None:
    class BrokenController(FakeController):
        def GetD3D12PipelineState(self):
            raise TypeError("signature changed")

    client = BridgeClient(FakeContext(BrokenController(api_name="D3D12")))

    response = client._get_api_pipeline_state(7)

    assert response["api_pipeline"]["available"] is False
    assert "compatible D3D12 pipeline accessor" in response["api_pipeline"]["reason"]


def test_bridge_client_shader_code_returns_unavailable_when_disassembly_targets_missing(monkeypatch) -> None:
    client = BridgeClient(FakeContext(FakeController(state=FakeState(shader_bound=True))))
    monkeypatch.setattr(bridge_client_module, "_shader_stage_from_name", lambda stage_name: "Pixel")

    response = client._get_shader_code(7, "pixel", None)

    assert response["shader"]["stage"] == "Pixel"
    assert response["disassembly"]["available"] is False
    assert "did not report any shader disassembly targets" in response["disassembly"]["reason"]
