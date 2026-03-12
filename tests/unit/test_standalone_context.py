from __future__ import annotations

from types import SimpleNamespace

from renderdoc_mcp.standalone_context import StandaloneRenderDocContext


class FakeReplayOptions:
    pass


class FakeController:
    def __init__(self, *, label: str) -> None:
        self.label = label
        self.shutdown_called = 0
        self.frame_events: list[tuple[int, bool]] = []
        self.child_action = SimpleNamespace(eventId=2, children=[])
        self.root_action = SimpleNamespace(eventId=1, children=[self.child_action])
        self.resources = [
            SimpleNamespace(resourceId="tex-1", name="ColorTex"),
            SimpleNamespace(resourceId="buf-1", name="VertexBuffer"),
        ]
        self.textures = [SimpleNamespace(resourceId="tex-1")]
        self.buffers = [SimpleNamespace(resourceId="buf-1")]

    def GetRootActions(self):
        return [self.root_action]

    def GetResources(self):
        return list(self.resources)

    def GetTextures(self):
        return list(self.textures)

    def GetBuffers(self):
        return list(self.buffers)

    def SetFrameEvent(self, event_id: int, force: bool) -> None:
        self.frame_events.append((event_id, force))

    def Shutdown(self) -> None:
        self.shutdown_called += 1


class FakeCaptureFile:
    def __init__(self, controller: FakeController) -> None:
        self.controller = controller
        self.shutdown_called = 0
        self.opened_paths: list[str] = []

    def OpenFile(self, capture_path: str, _driver: str, _importer) -> str:
        self.opened_paths.append(capture_path)
        return "Succeeded"

    def LocalReplaySupport(self) -> bool:
        return True

    def OpenCapture(self, _options: FakeReplayOptions, _progress) -> tuple[str, FakeController]:
        return ("Succeeded", self.controller)

    def Shutdown(self) -> None:
        self.shutdown_called += 1


class FakeRD:
    ResultCode = SimpleNamespace(Succeeded="Succeeded")
    ReplayOptions = FakeReplayOptions

    def __init__(self) -> None:
        self.capture_files: list[FakeCaptureFile] = []

    def OpenCaptureFile(self) -> FakeCaptureFile:
        return self.capture_files.pop(0)


def test_standalone_context_loads_capture_and_indexes_actions_and_resources() -> None:
    rd = FakeRD()
    controller = FakeController(label="first")
    rd.capture_files.append(FakeCaptureFile(controller))
    context = StandaloneRenderDocContext(rd)

    loaded = context.LoadCapture("sample.rdc", rd.ReplayOptions())

    assert loaded is True
    assert context.IsCaptureLoaded() is True
    assert context.GetCaptureFilename() == "sample.rdc"
    assert context.GetAction(1) is controller.root_action
    assert context.GetAction(2) is controller.child_action
    assert context.GetResourceName("tex-1") == "ColorTex"
    assert len(context.GetTextures()) == 1
    assert len(context.GetBuffers()) == 1

    context.SetEventID([], 7, 7, True)
    assert controller.frame_events == [(7, True)]


def test_standalone_context_reloads_and_closes_previous_capture() -> None:
    rd = FakeRD()
    first_controller = FakeController(label="first")
    second_controller = FakeController(label="second")
    first_capture = FakeCaptureFile(first_controller)
    second_capture = FakeCaptureFile(second_controller)
    rd.capture_files.extend([first_capture, second_capture])
    context = StandaloneRenderDocContext(rd)

    context.LoadCapture("first.rdc", rd.ReplayOptions())
    context.LoadCapture("second.rdc", rd.ReplayOptions())

    assert first_controller.shutdown_called == 1
    assert first_capture.shutdown_called == 1
    assert context.GetCaptureFilename() == "second.rdc"

    context.CloseCapture()

    assert second_controller.shutdown_called == 1
    assert second_capture.shutdown_called == 1
    assert context.IsCaptureLoaded() is False
    assert context.GetCaptureFilename() == ""
