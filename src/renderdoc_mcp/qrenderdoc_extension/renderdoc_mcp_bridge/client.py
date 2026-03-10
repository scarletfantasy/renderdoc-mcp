import json
import os
import threading
import time
import traceback

try:
    import renderdoc as rd
except Exception:
    rd = None

try:
    from . import frame_analysis
    from .serialization import (
        _action_flags,
        _api_name,
        _count_actions,
        _enum_name,
        _resource_id,
        _serialize_action,
        _serialize_action_analysis_node,
        _serialize_bound_vbuffer,
        _serialize_buffer,
        _serialize_descriptor,
        _serialize_descriptor_access,
        _serialize_shader_stage,
        _serialize_texture,
        _serialize_vertex_input,
        _shader_stage_values,
    )
    from .transport import _WinSockClient, _log
except Exception:
    import frame_analysis
    from serialization import (
        _action_flags,
        _api_name,
        _count_actions,
        _enum_name,
        _resource_id,
        _serialize_action,
        _serialize_action_analysis_node,
        _serialize_bound_vbuffer,
        _serialize_buffer,
        _serialize_descriptor,
        _serialize_descriptor_access,
        _serialize_shader_stage,
        _serialize_texture,
        _serialize_vertex_input,
        _shader_stage_values,
    )
    from transport import _WinSockClient, _log

PROTOCOL_VERSION = 1
CONNECT_RETRY_SECONDS = 20.0

_bridge = None


def _shader_stage_from_name(stage_name):
    normalized = str(stage_name or "").strip().lower()
    for stage in _shader_stage_values():
        if _enum_name(stage).lower() == normalized:
            return stage
    return None


def _select_pipeline_object(state, stage_name):
    graphics = state.GetGraphicsPipelineObject()
    compute = state.GetComputePipelineObject()

    if stage_name == "Compute" and _resource_id(compute):
        return ("compute_pipeline_object", compute)

    if _resource_id(graphics):
        return ("graphics_pipeline_object", graphics)

    if _resource_id(compute):
        return ("compute_pipeline_object", compute)

    return ("compute_pipeline_object" if stage_name == "Compute" else "graphics_pipeline_object", graphics)


class BridgeClient(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.mqt = ctx.Extensions().GetMiniQtHelper()
        self.sock = None
        self.stop_event = threading.Event()
        self.thread = None
        self.analysis_cache = frame_analysis.AnalysisCache()

    def start(self):
        host = os.environ.get("RENDERDOC_MCP_BRIDGE_HOST")
        port = os.environ.get("RENDERDOC_MCP_BRIDGE_PORT")
        token = os.environ.get("RENDERDOC_MCP_BRIDGE_TOKEN")
        protocol = os.environ.get("RENDERDOC_MCP_BRIDGE_PROTOCOL")
        _log("Bridge start requested host={} port={} protocol={}".format(host, port, protocol))

        if not host or not port or not token:
            _log("Bridge env vars missing, not connecting.")
            return False

        if protocol and int(protocol) != PROTOCOL_VERSION:
            _log("Protocol mismatch: expected {}, got {}".format(PROTOCOL_VERSION, protocol))
            return False

        deadline = time.time() + CONNECT_RETRY_SECONDS

        while time.time() < deadline and not self.stop_event.is_set():
            try:
                sock = _WinSockClient()
                sock.connect(host, int(port))
                self.sock = sock
                self._send(
                    {
                        "type": "hello",
                        "token": token,
                        "protocol_version": PROTOCOL_VERSION,
                        "renderdoc_version": os.environ.get("RENDERDOC_VERSION", ""),
                    }
                )
                _log("Bridge connected and hello sent.")
                self.thread = threading.Thread(target=self._run, name="renderdoc_mcp_bridge", daemon=True)
                self.thread.start()
                return True
            except Exception:
                _log("Bridge connection attempt failed:\n{}".format(traceback.format_exc()))
                time.sleep(0.25)

        _log("Bridge failed to connect before timeout.")
        return False

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=2.0)
            self.thread = None
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.analysis_cache.clear()

    def _send(self, message):
        self.sock.send_text(json.dumps(message, separators=(",", ":")) + "\n")

    def _read(self):
        return json.loads(self.sock.recv_line())

    def _invoke_on_ui_thread(self, callback):
        done = threading.Event()
        result = {}

        def runner():
            try:
                result["value"] = callback()
            except Exception:
                result["error"] = {
                    "code": "replay_failure",
                    "message": "RenderDoc request failed.",
                    "details": {"traceback": traceback.format_exc()},
                }
            finally:
                done.set()

        self.mqt.InvokeOntoUIThread(runner)
        done.wait()

        if "error" in result:
            raise RuntimeError(json.dumps(result["error"]))

        return result.get("value", {})

    def _ensure_capture_loaded(self):
        if not self.ctx.IsCaptureLoaded():
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "replay_failure",
                        "message": "No capture is currently loaded in qrenderdoc.",
                    }
                )
            )

    def _set_event(self, event_id):
        action = self.ctx.GetAction(event_id)
        if action is None:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_event_id",
                        "message": "The supplied event_id does not exist in the current capture.",
                        "details": {"event_id": int(event_id)},
                    }
                )
            )
        try:
            self.ctx.SetEventID([], event_id, event_id, True)
        except TypeError:
            self.ctx.SetEventID([], event_id, event_id)
        return action

    def _capture_status(self):
        loaded = bool(self.ctx.IsCaptureLoaded())
        return {
            "loaded": loaded,
            "filename": self.ctx.GetCaptureFilename() if loaded else "",
        }

    def _clear_analysis_cache(self):
        self.analysis_cache.clear()

    def _capture_cache_key(self):
        capture_path = self.ctx.GetCaptureFilename()
        stat_result = os.stat(capture_path)
        return {
            "capture_path": os.path.abspath(capture_path),
            "file_size": int(stat_result.st_size),
            "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1000000000))),
        }

    def _build_frame_metadata(self, controller):
        frame = controller.GetFrameInfo()
        actions = controller.GetRootActions()
        return {
            "capture": self._capture_status(),
            "api": _api_name(controller),
            "frame": {
                "frame_number": int(frame.frameNumber),
                "capture_time": int(frame.captureTime),
                "compressed_file_size": int(frame.compressedFileSize),
                "uncompressed_file_size": int(frame.uncompressedFileSize),
                "persistent_size": int(frame.persistentSize),
                "init_data_size": int(frame.initDataSize),
                "debug_message_count": len(frame.debugMessages),
            },
            "statistics": _count_actions(actions),
            "resource_counts": {
                "textures": len(self.ctx.GetTextures()),
                "buffers": len(self.ctx.GetBuffers()),
            },
        }

    def _ensure_frame_analysis(self):
        self._ensure_capture_loaded()
        cache_key = self._capture_cache_key()
        cached = self.analysis_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = {}

        def callback(controller):
            structured_file = controller.GetStructuredFile()
            root_actions = controller.GetRootActions()
            metadata = self._build_frame_metadata(controller)
            payload["value"] = frame_analysis.build_frame_analysis(
                [_serialize_action_analysis_node(self.ctx, action, structured_file) for action in root_actions],
                metadata,
            )

        self.ctx.Replay().BlockInvoke(callback)
        return self.analysis_cache.store(cache_key, payload["value"])

    def _load_capture(self, capture_path):
        if not os.path.isfile(capture_path):
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "capture_path_not_found",
                        "message": "capture_path does not exist.",
                        "details": {"capture_path": capture_path},
                    }
                )
            )

        self._clear_analysis_cache()
        self.ctx.LoadCapture(capture_path, rd.ReplayOptions(), capture_path, False, True)
        if not self.ctx.IsCaptureLoaded():
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "replay_failure",
                        "message": "RenderDoc failed to load the requested capture.",
                        "details": {"capture_path": capture_path},
                    }
                )
            )
        self._clear_analysis_cache()
        return self._capture_status()

    def _get_capture_summary(self):
        self._ensure_capture_loaded()
        analysis = self._ensure_frame_analysis()
        return {
            "capture": analysis["capture"],
            "api": analysis["api"],
            "frame": analysis["frame"],
            "statistics": analysis["statistics"],
            "resource_counts": analysis["resource_counts"],
        }

    def _list_actions(self, max_depth, name_filter, cursor, limit):
        analysis = self._ensure_frame_analysis()
        return frame_analysis.build_action_list_result(
            analysis["action_tree"],
            analysis["total_actions"],
            max_depth=max_depth,
            name_filter=name_filter,
            cursor=cursor,
            limit=limit,
        )

    def _analyze_frame(self):
        analysis = self._ensure_frame_analysis()
        return dict(analysis["analysis"])

    def _list_passes(self, cursor, limit, category_filter, name_filter):
        analysis = self._ensure_frame_analysis()
        return frame_analysis.list_passes(
            analysis,
            cursor=cursor,
            limit=limit,
            category_filter=category_filter,
            name_filter=name_filter,
        )

    def _get_pass_details(self, pass_id):
        analysis = self._ensure_frame_analysis()
        details = frame_analysis.get_pass_details(analysis, pass_id)
        if details is None:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_pass_id",
                        "message": "The supplied pass_id does not exist in the active frame analysis.",
                        "details": {"pass_id": pass_id},
                    }
                )
            )
        return details

    def _get_action_details(self, event_id):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        details = {"event_id": int(event_id)}

        def callback(controller):
            structured_file = controller.GetStructuredFile()
            payload = _serialize_action(self.ctx, action, structured_file, 0, 0, None)
            payload["api"] = _api_name(controller)
            payload["resource_usage_summary"] = {
                "output_count": len(payload["outputs"]),
                "has_depth_output": bool(payload["depth_output"]["resource_id"]),
            }
            details["action"] = payload

        self.ctx.Replay().BlockInvoke(callback)
        return details

    def _get_pipeline_state(self, event_id):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        response = {"event_id": int(event_id)}

        def callback(controller):
            state = controller.GetPipelineState()
            response["api"] = _api_name(controller)
            response["action"] = {
                "event_id": int(action.eventId),
                "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                "flags": _action_flags(action),
            }
            response["pipeline"] = {
                "topology": _enum_name(state.GetPrimitiveTopology()),
                "graphics_pipeline_object": _resource_id(state.GetGraphicsPipelineObject()),
                "compute_pipeline_object": _resource_id(state.GetComputePipelineObject()),
                "index_buffer": _serialize_bound_vbuffer(self.ctx, state.GetIBuffer()),
                "vertex_buffers": [_serialize_bound_vbuffer(self.ctx, vb) for vb in state.GetVBuffers()],
                "vertex_inputs": [_serialize_vertex_input(attr) for attr in state.GetVertexInputs()],
                "output_targets": [_serialize_descriptor(self.ctx, desc) for desc in state.GetOutputTargets()],
                "depth_target": _serialize_descriptor(self.ctx, state.GetDepthTarget()),
                "depth_resolve_target": _serialize_descriptor(self.ctx, state.GetDepthResolveTarget()),
                "descriptor_accesses": [_serialize_descriptor_access(item) for item in state.GetDescriptorAccess()],
                "shaders": [],
            }

            for stage in _shader_stage_values():
                serialized = _serialize_shader_stage(self.ctx, state, stage)
                if serialized is not None:
                    response["pipeline"]["shaders"].append(serialized)

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _get_shader_code(self, event_id, stage_name, target):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        response = {"event_id": int(event_id)}

        def callback(controller):
            stage = _shader_stage_from_name(stage_name)
            if stage is None:
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "invalid_shader_stage",
                            "message": "The supplied shader stage is not supported by this RenderDoc build.",
                            "details": {
                                "stage": stage_name,
                                "supported_stages": [_enum_name(item) for item in _shader_stage_values()],
                            },
                        }
                    )
                )

            state = controller.GetPipelineState()
            shader_payload = _serialize_shader_stage(self.ctx, state, stage)
            if shader_payload is None:
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "shader_not_bound",
                            "message": "No shader is bound at the supplied stage for the selected event.",
                            "details": {"event_id": int(event_id), "stage": _enum_name(stage)},
                        }
                    )
                )

            targets = [str(item) for item in controller.GetDisassemblyTargets(True)]
            if not targets:
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "replay_failure",
                            "message": "RenderDoc did not report any shader disassembly targets.",
                            "details": {"event_id": int(event_id), "stage": shader_payload["stage"]},
                        }
                    )
                )

            selected_target = targets[0]
            if target:
                selected_target = next((item for item in targets if item.lower() == str(target).lower()), "")
                if not selected_target:
                    raise RuntimeError(
                        json.dumps(
                            {
                                "code": "invalid_disassembly_target",
                                "message": "The supplied disassembly target is not available for this capture.",
                                "details": {
                                    "target": target,
                                    "available_targets": targets,
                                    "event_id": int(event_id),
                                    "stage": shader_payload["stage"],
                                },
                            }
                        )
                    )

            reflection = state.GetShaderReflection(stage)
            if reflection is None:
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "replay_failure",
                            "message": "RenderDoc did not return shader reflection for the selected stage.",
                            "details": {"event_id": int(event_id), "stage": shader_payload["stage"]},
                        }
                    )
                )

            pipeline_object_kind, pipeline_object = _select_pipeline_object(state, shader_payload["stage"])
            disassembly_text = str(controller.DisassembleShader(pipeline_object, reflection, selected_target) or "")

            response["api"] = _api_name(controller)
            response["action"] = {
                "event_id": int(action.eventId),
                "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                "flags": _action_flags(action),
            }
            response["shader"] = shader_payload
            response["disassembly"] = {
                "target": selected_target,
                "available_targets": targets,
                "pipeline_object_kind": pipeline_object_kind,
                "pipeline_object_id": _resource_id(pipeline_object),
                "text": disassembly_text,
            }

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _list_resources(self, kind, name_filter):
        self._ensure_capture_loaded()
        name_filter_lower = name_filter.lower() if name_filter else None

        def matches(item_name):
            return not name_filter_lower or name_filter_lower in item_name.lower()

        textures = [_serialize_texture(self.ctx, tex) for tex in self.ctx.GetTextures()]
        textures = [item for item in textures if matches(item["name"])]
        buffers = [_serialize_buffer(self.ctx, buf) for buf in self.ctx.GetBuffers()]
        buffers = [item for item in buffers if matches(item["name"])]

        if kind == "textures":
            items = textures
        elif kind == "buffers":
            items = buffers
        else:
            items = textures + buffers

        return {
            "kind": kind,
            "count": len(items),
            "textures": textures if kind in ("textures", "all") else [],
            "buffers": buffers if kind in ("buffers", "all") else [],
            "items": items,
        }

    def _dispatch(self, method, params):
        if method == "load_capture":
            return self._load_capture(params.get("capture_path", ""))
        if method == "get_capture_status":
            return self._capture_status()
        if method == "get_capture_summary":
            return self._get_capture_summary()
        if method == "list_actions":
            return self._list_actions(
                params.get("max_depth"),
                params.get("name_filter"),
                params.get("cursor"),
                params.get("limit"),
            )
        if method == "analyze_frame":
            return self._analyze_frame()
        if method == "list_passes":
            return self._list_passes(
                params.get("cursor"),
                params.get("limit"),
                params.get("category_filter"),
                params.get("name_filter"),
            )
        if method == "get_pass_details":
            return self._get_pass_details(params.get("pass_id", ""))
        if method == "get_action_details":
            return self._get_action_details(int(params.get("event_id", 0)))
        if method == "get_pipeline_state":
            return self._get_pipeline_state(int(params.get("event_id", 0)))
        if method == "get_shader_code":
            return self._get_shader_code(
                int(params.get("event_id", 0)),
                params.get("stage", ""),
                params.get("target"),
            )
        if method == "list_resources":
            return self._list_resources(params.get("kind", "all"), params.get("name_filter"))
        if method == "close_capture":
            if self.ctx.IsCaptureLoaded():
                self._clear_analysis_cache()
                self.ctx.CloseCapture()
            return {"closed": True}
        raise RuntimeError(
            json.dumps(
                {
                    "code": "replay_failure",
                    "message": "Unknown bridge method.",
                    "details": {"method": method},
                }
            )
        )

    def _run(self):
        while not self.stop_event.is_set():
            try:
                request = self._read()
            except TimeoutError:
                continue
            except Exception:
                _log("Bridge read failed, stopping loop:\n{}".format(traceback.format_exc()))
                break

            request_id = request.get("id")
            try:
                result = self._invoke_on_ui_thread(lambda: self._dispatch(request.get("method", ""), request.get("params", {})))
                response = {"type": "response", "id": request_id, "result": result}
            except Exception as exc:
                response = {"type": "response", "id": request_id, "error": self._parse_exception(exc)}

            try:
                self._send(response)
            except Exception:
                _log("Bridge write failed, stopping loop:\n{}".format(traceback.format_exc()))
                break

        self.stop()

    def _parse_exception(self, exc):
        try:
            payload = json.loads(str(exc))
            if isinstance(payload, dict) and "message" in payload:
                return payload
        except Exception:
            pass

        return {
            "code": "replay_failure",
            "message": str(exc),
            "details": {"traceback": traceback.format_exc()},
        }


def register(version, ctx):
    global _bridge
    _log("register() called for version {}".format(version))
    if _bridge is None:
        bridge = BridgeClient(ctx)
        if bridge.start():
            _bridge = bridge
            _log("Bridge registered successfully.")
        else:
            _log("Bridge did not start during register().")


def unregister():
    global _bridge
    _log("unregister() called")
    if _bridge is not None:
        _bridge.stop()
        _bridge = None
