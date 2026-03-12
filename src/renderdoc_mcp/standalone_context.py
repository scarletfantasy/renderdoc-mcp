from __future__ import annotations

import json
from typing import Any


class _InlineMiniQtHelper:
    def InvokeOntoUIThread(self, callback) -> None:
        callback()


class _ExtensionsFacade:
    def __init__(self) -> None:
        self._mini_qt = _InlineMiniQtHelper()

    def GetMiniQtHelper(self) -> _InlineMiniQtHelper:
        return self._mini_qt


class _ReplayFacade:
    def __init__(self, context: "StandaloneRenderDocContext") -> None:
        self._context = context

    def BlockInvoke(self, callback) -> None:
        controller = self._context._controller
        if controller is None:
            return
        callback(controller)


class StandaloneRenderDocContext:
    def __init__(self, rd_module: Any) -> None:
        self._rd = rd_module
        self._capture_file = None
        self._controller = None
        self._capture_path = ""
        self._action_index: dict[int, Any] = {}
        self._resource_names: dict[str, str] = {}
        self._extensions = _ExtensionsFacade()
        self._replay = _ReplayFacade(self)

    def Extensions(self) -> _ExtensionsFacade:
        return self._extensions

    def Replay(self) -> _ReplayFacade:
        return self._replay

    def LoadCapture(self, *args) -> bool:
        capture_path = str(args[0] if args else "" or "")
        replay_options = next((value for value in args if isinstance(value, self._rd.ReplayOptions)), None)
        if replay_options is None:
            replay_options = self._rd.ReplayOptions()

        self.CloseCapture()

        capture_file = self._rd.OpenCaptureFile()
        result = capture_file.OpenFile(capture_path, "", None)
        if result != self._rd.ResultCode.Succeeded:
            capture_file.Shutdown()
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "capture_path_not_found",
                        "message": "capture_path does not exist or could not be opened.",
                        "details": {"capture_path": capture_path, "result": str(result)},
                    }
                )
            )

        if not capture_file.LocalReplaySupport():
            capture_file.Shutdown()
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "replay_failure",
                        "message": "The capture cannot be replayed locally by this RenderDoc build.",
                        "details": {"capture_path": capture_path},
                    }
                )
            )

        result, controller = capture_file.OpenCapture(replay_options, None)
        if result != self._rd.ResultCode.Succeeded or controller is None:
            capture_file.Shutdown()
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "replay_failure",
                        "message": "RenderDoc could not initialise replay for the requested capture.",
                        "details": {"capture_path": capture_path, "result": str(result)},
                    }
                )
            )

        self._capture_file = capture_file
        self._controller = controller
        self._capture_path = capture_path
        self._refresh_indices()
        return True

    def CloseCapture(self) -> None:
        controller = self._controller
        capture_file = self._capture_file
        self._controller = None
        self._capture_file = None
        self._capture_path = ""
        self._action_index = {}
        self._resource_names = {}

        if controller is not None:
            try:
                controller.Shutdown()
            except Exception:
                pass

        if capture_file is not None:
            try:
                capture_file.Shutdown()
            except Exception:
                pass

    def IsCaptureLoaded(self) -> bool:
        return self._controller is not None

    def GetCaptureFilename(self) -> str:
        return self._capture_path

    def GetTextures(self) -> list[Any]:
        controller = self._controller
        if controller is None:
            return []
        return list(controller.GetTextures() or [])

    def GetBuffers(self) -> list[Any]:
        controller = self._controller
        if controller is None:
            return []
        return list(controller.GetBuffers() or [])

    def GetAction(self, event_id: int) -> Any | None:
        return self._action_index.get(int(event_id))

    def SetEventID(self, *args) -> None:
        controller = self._controller
        if controller is None:
            return

        event_id = 0
        if len(args) >= 2:
            event_id = int(args[1])
        elif args:
            event_id = int(args[0])

        force = bool(args[-1]) if args and isinstance(args[-1], bool) else False
        controller.SetFrameEvent(event_id, force)

    def GetResourceName(self, resource_id: Any) -> str:
        key = str(resource_id)
        if not key:
            return ""
        name = self._resource_names.get(key)
        if isinstance(name, str) and name:
            return name
        return key

    def _refresh_indices(self) -> None:
        controller = self._controller
        if controller is None:
            self._action_index = {}
            self._resource_names = {}
            return

        self._action_index = {}
        for action in list(controller.GetRootActions() or []):
            self._index_action(action)

        resource_names: dict[str, str] = {}
        for resource in list(controller.GetResources() or []):
            key = str(getattr(resource, "resourceId", "") or "")
            if not key:
                continue
            name = str(getattr(resource, "name", "") or "")
            resource_names[key] = name or key
        self._resource_names = resource_names

    def _index_action(self, action: Any) -> None:
        event_id = int(getattr(action, "eventId", 0))
        if event_id > 0:
            self._action_index[event_id] = action
        for child in list(getattr(action, "children", []) or []):
            self._index_action(child)
