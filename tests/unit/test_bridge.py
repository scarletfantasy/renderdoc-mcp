from __future__ import annotations

from enum import Enum
from pathlib import Path
from types import SimpleNamespace

import pytest

from renderdoc_mcp import bridge as bridge_module
from renderdoc_mcp.errors import BridgeHandshakeTimeoutError
from renderdoc_mcp.bridge import QRenderDocBridge
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge import client as bridge_client_module
from renderdoc_mcp.qrenderdoc_extension.renderdoc_mcp_bridge import serialization as serialization_module
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
    outputs = ["tex-1"]
    depthOut = None

    def GetName(self, structured_file):
        return "Draw"


class FakeContext:
    def __init__(self, controller) -> None:
        self.controller = controller
        self.loaded = True

    def Extensions(self):
        return FakeExtensions()

    def Replay(self):
        return FakeReplay(self.controller)

    def IsCaptureLoaded(self):
        return self.loaded

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

    def CloseCapture(self):
        self.loaded = False

    def GetCaptureFilename(self):
        return str(Path(__file__).resolve())


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
    def __init__(self, *, api_name: str = "D3D12", state: FakeState | None = None, shader_debugging: bool = False) -> None:
        self.api_name = api_name
        self.state = state or FakeState()
        self.shader_debugging = shader_debugging
        self.debug_pixel_calls: list[tuple[int, int, object]] = []
        self.continue_debug_batches: list[list[object]] = []
        self.freed_traces: list[object] = []

    def GetStructuredFile(self):
        return object()

    def GetAPIProperties(self):
        return SimpleNamespace(pipelineType=self.api_name, shaderDebugging=self.shader_debugging)

    def GetPipelineState(self):
        return self.state

    def DebugPixel(self, x, y, inputs):
        self.debug_pixel_calls.append((x, y, inputs))
        return getattr(self, "trace", None)

    def ContinueDebug(self, debugger):
        if self.continue_debug_batches:
            return self.continue_debug_batches.pop(0)
        return []

    def FreeTrace(self, trace):
        self.freed_traces.append(trace)


class FakeDebugPixelInputs:
    def __init__(self) -> None:
        self.sample = None
        self.primitive = None
        self.view = None


class FakeUInt32DebugPixelInputs:
    def __init__(self) -> None:
        self._sample = None
        self._primitive = None
        self._view = None

    @property
    def sample(self):
        return self._sample

    @sample.setter
    def sample(self, value):
        if int(value) < 0:
            raise OverflowError("sample must be uint32")
        self._sample = int(value)

    @property
    def primitive(self):
        return self._primitive

    @primitive.setter
    def primitive(self, value):
        if int(value) < 0:
            raise OverflowError("primitive must be uint32")
        self._primitive = int(value)

    @property
    def view(self):
        return self._view

    @view.setter
    def view(self, value):
        if int(value) < 0:
            raise OverflowError("view must be uint32")
        self._view = int(value)


class _EnumGraphicsAPI(Enum):
    D3D12 = 1


class _EnumTopology(Enum):
    Unknown = 0


def _shader_variable(name: str, values: list[float], type_name: str = "Float") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        type=type_name,
        rows=1,
        columns=len(values),
        members=[],
        value=SimpleNamespace(
            f16v=list(values),
            f32v=list(values),
            f64v=list(values),
            s8v=[int(item) for item in values],
            s16v=[int(item) for item in values],
            s32v=[int(item) for item in values],
            s64v=[int(item) for item in values],
            u8v=[int(item) for item in values],
            u16v=[int(item) for item in values],
            u32v=[int(item) for item in values],
            u64v=[int(item) for item in values],
        ),
    )


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


def test_enum_name_uses_python_enum_names_for_native_renderdoc_bindings() -> None:
    assert serialization_module._enum_name(_EnumGraphicsAPI.D3D12) == "D3D12"
    assert serialization_module._enum_name(_EnumTopology.Unknown) == "Unknown"


def test_bridge_client_pipeline_overview_uses_enum_names_for_api_and_topology() -> None:
    class EnumState(FakeState):
        def GetPrimitiveTopology(self):
            return _EnumTopology.Unknown

    class EnumController(FakeController):
        def __init__(self) -> None:
            super().__init__(api_name=_EnumGraphicsAPI.D3D12, state=EnumState())

        def GetD3D12PipelineState(self):
            return SimpleNamespace(
                pipelineResourceId="pipe-1",
                descriptorHeaps=[],
                rootSignature=SimpleNamespace(resourceId=None, parameters=[], staticSamplers=[]),
            )

    client = BridgeClient(FakeContext(EnumController()))

    response = client._get_pipeline_overview(7)

    assert response["api"] == "D3D12"
    assert response["pipeline"]["topology"] == "Unknown"
    assert response["pipeline"]["api_details_available"] is True
    assert response["pipeline"]["api_details_api"] == "D3D12"


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


def test_bridge_client_detects_shader_debugging_support() -> None:
    client = BridgeClient(FakeContext(FakeController(shader_debugging=True)))

    assert client._controller_shader_debugging_supported(client.ctx.controller) is True


def test_bridge_client_start_pixel_shader_debug_requires_draw_event(monkeypatch) -> None:
    controller = FakeController(state=FakeState(shader_bound=True), shader_debugging=True)
    client = BridgeClient(FakeContext(controller))

    monkeypatch.setattr(bridge_client_module, "rd", SimpleNamespace(DebugPixelInputs=FakeDebugPixelInputs, NoPreference=-1))
    monkeypatch.setattr(bridge_client_module, "_shader_stage_from_name", lambda stage_name: "Pixel")
    monkeypatch.setattr(bridge_client_module, "_action_flags", lambda action: ["dispatch"])

    with pytest.raises(bridge_client_module.BridgeError) as exc_info:
        client._start_pixel_shader_debug(7, 4, 5, None, None, None, None, 2)

    assert exc_info.value.code == "shader_debug_requires_draw_event"


def test_bridge_client_pixel_shader_debug_sessions_buffer_continue_states(monkeypatch) -> None:
    controller = FakeController(state=FakeState(shader_bound=True), shader_debugging=True)
    trace = SimpleNamespace(
        debugger=object(),
        stage="Pixel",
        inputs=[_shader_variable("input0", [1.0])],
        constantBlocks=[],
        readOnlyResources=[],
        readWriteResources=[],
        samplers=[],
        sourceVars=[SimpleNamespace(name="color")],
        instInfo=[
            SimpleNamespace(
                instruction=0,
                lineInfo=SimpleNamespace(fileIndex=0, lineStart=12, lineEnd=12, colStart=1, colEnd=8, disassemblyLine=1),
                sourceVars=[SimpleNamespace(name="color")],
            ),
            SimpleNamespace(
                instruction=1,
                lineInfo=SimpleNamespace(fileIndex=0, lineStart=13, lineEnd=13, colStart=1, colEnd=8, disassemblyLine=2),
                sourceVars=[SimpleNamespace(name="outputColor")],
            ),
            SimpleNamespace(
                instruction=2,
                lineInfo=SimpleNamespace(fileIndex=0, lineStart=14, lineEnd=14, colStart=1, colEnd=8, disassemblyLine=3),
                sourceVars=[SimpleNamespace(name="outputColor")],
            ),
        ],
    )
    state0 = SimpleNamespace(
        stepIndex=0,
        nextInstruction=0,
        flags="ShaderEvents.None",
        changes=[SimpleNamespace(before=_shader_variable("color", [0.0, 0.0, 0.0, 1.0]), after=_shader_variable("color", [1.0, 0.0, 0.0, 1.0]))],
        callstack=["main"],
    )
    state1 = SimpleNamespace(
        stepIndex=1,
        nextInstruction=1,
        flags="ShaderEvents.SampleLoadGather",
        changes=[],
        callstack=[],
    )
    state2 = SimpleNamespace(
        stepIndex=2,
        nextInstruction=2,
        flags="ShaderEvents.None",
        changes=[],
        callstack=[],
    )
    controller.trace = trace
    controller.continue_debug_batches = [[state0, state1], [state2], []]

    client = BridgeClient(FakeContext(controller))
    monkeypatch.setattr(bridge_client_module, "rd", SimpleNamespace(DebugPixelInputs=FakeDebugPixelInputs, NoPreference=-1))
    monkeypatch.setattr(bridge_client_module, "_shader_stage_from_name", lambda stage_name: "Pixel")
    monkeypatch.setattr(bridge_client_module, "_action_flags", lambda action: ["draw"])

    started = client._start_pixel_shader_debug(7, 4, 5, "tex-1", None, None, None, 1)

    assert started["shader"]["stage"] == "Pixel"
    assert started["target"]["validated"] is True
    assert started["returned_state_count"] == 1
    assert started["states"][0]["step_index"] == 0
    assert started["meta"]["completed"] is False
    assert started["meta"]["has_more"] is True
    assert controller.debug_pixel_calls[0][0:2] == (4, 5)
    assert controller.debug_pixel_calls[0][2].sample == 0xFFFFFFFF

    continued = client._continue_shader_debug(started["shader_debug_id"], 1)
    assert continued["returned_state_count"] == 1
    assert continued["states"][0]["step_index"] == 1
    assert continued["meta"]["has_more"] is True

    continued_again = client._continue_shader_debug(started["shader_debug_id"], 2)
    assert continued_again["returned_state_count"] == 1
    assert continued_again["states"][0]["step_index"] == 2
    assert continued_again["meta"]["completed"] is True
    assert continued_again["meta"]["has_more"] is False

    step = client._get_shader_debug_step(started["shader_debug_id"], 0, 10)
    assert step["step_index"] == 0
    assert step["returned_change_count"] == 1
    assert step["changes"][0]["name"] == "color"
    assert step["changes"][0]["before_value"] == [0.0, 0.0, 0.0, 1.0]
    assert step["changes"][0]["after_value"] == [1.0, 0.0, 0.0, 1.0]

    closed = client._end_shader_debug(started["shader_debug_id"])
    assert closed["closed"] is True
    assert controller.freed_traces == [trace]


def test_bridge_client_pixel_shader_debug_converts_no_preference_to_uint32(monkeypatch) -> None:
    controller = FakeController(state=FakeState(shader_bound=True), shader_debugging=True)
    controller.trace = SimpleNamespace(
        debugger=object(),
        stage="Pixel",
        inputs=[],
        constantBlocks=[],
        readOnlyResources=[],
        readWriteResources=[],
        samplers=[],
        sourceVars=[],
        instInfo=[],
    )
    controller.continue_debug_batches = [[]]

    client = BridgeClient(FakeContext(controller))
    monkeypatch.setattr(bridge_client_module, "rd", SimpleNamespace(DebugPixelInputs=FakeUInt32DebugPixelInputs, NoPreference=-1))
    monkeypatch.setattr(bridge_client_module, "_shader_stage_from_name", lambda stage_name: "Pixel")
    monkeypatch.setattr(bridge_client_module, "_action_flags", lambda action: ["draw"])

    started = client._start_pixel_shader_debug(7, 4, 5, "tex-1", None, None, None, 1)

    assert started["returned_state_count"] == 0
    assert started["meta"]["completed"] is True
    assert controller.debug_pixel_calls[0][2].sample == 0xFFFFFFFF
    assert controller.debug_pixel_calls[0][2].primitive == 0xFFFFFFFF
    assert controller.debug_pixel_calls[0][2].view == 0xFFFFFFFF


def test_bridge_client_shader_debug_step_requires_cached_history(monkeypatch) -> None:
    controller = FakeController(state=FakeState(shader_bound=True), shader_debugging=True)
    client = BridgeClient(FakeContext(controller))
    client.shader_debug_sessions["debug-1"] = {
        "shader_debug_id": "debug-1",
        "event_id": 7,
        "api": "D3D12",
        "action": {"event_id": 7},
        "shader": {"stage": "Pixel"},
        "target": {"texture_id": "", "validated": False, "slot_kind": "", "slot_index": -1},
        "trace": SimpleNamespace(instInfo=[]),
        "history": [],
        "history_by_step": {},
        "pending_states": [],
        "completed": False,
    }

    with pytest.raises(bridge_client_module.BridgeError) as exc_info:
        client._get_shader_debug_step("debug-1", 3, 10)

    assert exc_info.value.code == "shader_debug_trace_unavailable"


def test_bridge_client_clear_analysis_cache_releases_shader_debug_sessions() -> None:
    controller = FakeController(shader_debugging=True)
    trace = object()
    client = BridgeClient(FakeContext(controller))
    client.shader_debug_sessions["debug-1"] = {
        "shader_debug_id": "debug-1",
        "trace": trace,
        "pending_states": [],
        "history": [],
        "history_by_step": {},
        "completed": True,
    }

    client._clear_analysis_cache()

    assert client.shader_debug_sessions == {}
    assert controller.freed_traces == [trace]
