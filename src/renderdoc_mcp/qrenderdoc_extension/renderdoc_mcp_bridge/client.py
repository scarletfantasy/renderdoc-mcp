import base64
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
        _float_vector,
        _resource_id,
        _serialize_action,
        _serialize_action_analysis_node,
        _serialize_bound_vbuffer,
        _serialize_buffer,
        _serialize_descriptor,
        _serialize_descriptor_access,
        _serialize_d3d12_pipeline_state,
        _serialize_shader_stage,
        _serialize_texture,
        _serialize_vertex_input,
        _serialize_vulkan_pipeline_state,
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
        _float_vector,
        _resource_id,
        _serialize_action,
        _serialize_action_analysis_node,
        _serialize_bound_vbuffer,
        _serialize_buffer,
        _serialize_descriptor,
        _serialize_descriptor_access,
        _serialize_d3d12_pipeline_state,
        _serialize_shader_stage,
        _serialize_texture,
        _serialize_vertex_input,
        _serialize_vulkan_pipeline_state,
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


def _subresource(mip_level, array_slice, sample):
    sub = rd.Subresource()
    sub.mip = int(mip_level)
    sub.slice = int(array_slice)
    sub.sample = int(sample)
    return sub


def _resource_id_matches(value, expected):
    return _resource_id(value) == str(expected)


def _safe_float(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def _counter_value_as_float(value, result_type_name, byte_width):
    type_name = str(result_type_name or "").lower()
    if "float" in type_name or "double" in type_name:
        if int(byte_width or 0) >= 8 and hasattr(value, "d"):
            return float(value.d)
        if hasattr(value, "f"):
            return float(value.f)

    if "unsigned" in type_name or "uint" in type_name:
        if int(byte_width or 0) >= 8 and hasattr(value, "u64"):
            return float(value.u64)
        if hasattr(value, "u32"):
            return float(value.u32)

    if "signed" in type_name or "sint" in type_name:
        if int(byte_width or 0) >= 8 and hasattr(value, "s64"):
            return float(value.s64)
        if hasattr(value, "s32"):
            return float(value.s32)

    for attr in ("d", "f", "u64", "u32", "s64", "s32"):
        if hasattr(value, attr):
            return float(getattr(value, attr))
    return None


def _serialize_pixel_value(value):
    if value is None:
        return None

    if all(hasattr(value, item) for item in ("x", "y", "z", "w")):
        return [float(value.x), float(value.y), float(value.z), float(value.w)]

    for attr in ("floatValue", "floatVec", "value"):
        nested = getattr(value, attr, None)
        if nested is not None and nested is not value:
            serialized = _serialize_pixel_value(nested)
            if serialized is not None:
                return serialized

    components = []
    for attr in ("r", "g", "b", "a"):
        if hasattr(value, attr):
            components.append(_safe_float(getattr(value, attr)))
    if components:
        while len(components) < 4:
            components.append(0.0)
        return components[:4]

    if isinstance(value, (list, tuple)):
        return [_safe_float(item) for item in list(value)[:4]]

    for attr in ("d", "f", "u64", "u32", "s64", "s32"):
        if hasattr(value, attr):
            return _safe_float(getattr(value, attr))

    return str(value)


class BridgeClient(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.mqt = ctx.Extensions().GetMiniQtHelper()
        self.sock = None
        self.stop_event = threading.Event()
        self.thread = None
        self.analysis_cache = frame_analysis.AnalysisCache()
        self.timing_cache = frame_analysis.AnalysisCache()

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
        self.timing_cache.clear()

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
        self.timing_cache.clear()

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

    def _analysis_max_event_id(self, nodes):
        maximum = 0
        for node in nodes:
            maximum = max(maximum, int(node.get("event_id", 0)), self._analysis_max_event_id(node.get("children", [])))
        return maximum

    def _ensure_final_event(self):
        analysis = self._ensure_frame_analysis()
        event_id = self._analysis_max_event_id(analysis.get("action_tree", []))
        if event_id > 0:
            self._set_event(event_id)
        return analysis

    def _find_texture_by_id(self, texture_id):
        for texture in self.ctx.GetTextures():
            if _resource_id_matches(texture.resourceId, texture_id):
                return texture
        raise RuntimeError(
            json.dumps(
                {
                    "code": "invalid_resource_id",
                    "message": "The supplied texture_id does not exist in the active capture.",
                    "details": {"texture_id": texture_id},
                }
            )
        )

    def _find_buffer_by_id(self, buffer_id):
        for buffer_desc in self.ctx.GetBuffers():
            if _resource_id_matches(buffer_desc.resourceId, buffer_id):
                return buffer_desc
        raise RuntimeError(
            json.dumps(
                {
                    "code": "invalid_resource_id",
                    "message": "The supplied buffer_id does not exist in the active capture.",
                    "details": {"buffer_id": buffer_id},
                }
            )
        )

    def _texture_slice_count(self, texture, mip_level):
        if int(getattr(texture, "arraysize", 0)) > 1:
            return int(texture.arraysize)
        return max(1, int(getattr(texture, "depth", 1)) >> int(mip_level))

    def _texture_dimensions(self, texture, mip_level):
        mip = int(mip_level)
        width = max(1, int(getattr(texture, "width", 1)) >> mip)
        height = max(1, int(getattr(texture, "height", 1)) >> mip)
        depth = max(1, int(getattr(texture, "depth", 1)) >> mip)
        return width, height, depth

    def _validate_texture_request(self, texture, mip_level, array_slice, sample, x=None, y=None, width=None, height=None):
        mip_level = int(mip_level)
        array_slice = int(array_slice)
        sample = int(sample)
        mip_levels = max(1, int(getattr(texture, "mips", 1)))
        if mip_level >= mip_levels:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_subresource",
                        "message": "mip_level is out of bounds for the selected texture.",
                        "details": {"mip_level": mip_level, "mip_levels": mip_levels},
                    }
                )
            )

        slice_count = self._texture_slice_count(texture, mip_level)
        if array_slice >= slice_count:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_subresource",
                        "message": "array_slice is out of bounds for the selected texture.",
                        "details": {"array_slice": array_slice, "slice_count": slice_count},
                    }
                )
            )

        sample_count = max(1, int(getattr(texture, "msSamp", 1)))
        if sample >= sample_count:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_subresource",
                        "message": "sample is out of bounds for the selected texture.",
                        "details": {"sample": sample, "sample_count": sample_count},
                    }
                )
            )

        mip_width, mip_height, mip_depth = self._texture_dimensions(texture, mip_level)
        if x is not None and int(x) >= mip_width:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_texture_region",
                        "message": "x is out of bounds for the selected texture mip.",
                        "details": {"x": int(x), "mip_width": mip_width},
                    }
                )
            )
        if y is not None and int(y) >= mip_height:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_texture_region",
                        "message": "y is out of bounds for the selected texture mip.",
                        "details": {"y": int(y), "mip_height": mip_height},
                    }
                )
            )
        if width is not None and int(x or 0) + int(width) > mip_width:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_texture_region",
                        "message": "The requested width extends past the selected texture mip.",
                        "details": {"x": int(x or 0), "width": int(width), "mip_width": mip_width},
                    }
                )
            )
        if height is not None and int(y or 0) + int(height) > mip_height:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_texture_region",
                        "message": "The requested height extends past the selected texture mip.",
                        "details": {"y": int(y or 0), "height": int(height), "mip_height": mip_height},
                    }
                )
            )
        return {"mip_width": mip_width, "mip_height": mip_height, "mip_depth": mip_depth, "slice_count": slice_count, "sample_count": sample_count}

    def _default_comp_type(self, texture):
        comp_type = getattr(getattr(texture, "format", None), "compType", None)
        if comp_type is not None:
            return comp_type
        if rd is not None and hasattr(rd, "CompType") and hasattr(rd.CompType, "Typeless"):
            return rd.CompType.Typeless
        return 0

    def _action_brief(self, action, structured_file, event_id):
        if action is None:
            return {"event_id": int(event_id), "name": "Event {}".format(int(event_id)), "flags": []}
        return {
            "event_id": int(action.eventId),
            "name": action.GetName(structured_file) or action.customName or "Event {}".format(action.eventId),
            "flags": _action_flags(action),
        }

    def _ensure_timing_data(self):
        self._ensure_capture_loaded()
        cache_key = self._capture_cache_key()
        cached = self.timing_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = {}

        def callback(controller):
            event_counter = None
            if rd is not None and hasattr(rd, "GPUCounter") and hasattr(rd.GPUCounter, "EventGPUDuration"):
                event_counter = rd.GPUCounter.EventGPUDuration

            if event_counter is None:
                payload["value"] = {
                    "timing_available": False,
                    "counter_name": "EventGPUDuration",
                    "rows": [],
                    "reason": "This RenderDoc build does not expose GPUCounter.EventGPUDuration.",
                }
                return

            counters = list(controller.EnumerateCounters() or [])
            if event_counter not in counters:
                payload["value"] = {
                    "timing_available": False,
                    "counter_name": _enum_name(event_counter),
                    "rows": [],
                    "reason": "The active replay device does not support the EventGPUDuration counter.",
                }
                return

            counter_desc = controller.DescribeCounter(event_counter)
            result_type_name = _enum_name(getattr(counter_desc, "resultType", ""))
            byte_width = int(getattr(counter_desc, "resultByteWidth", 0))
            rows = []
            for item in controller.FetchCounters([event_counter]) or []:
                seconds = _counter_value_as_float(getattr(item, "value", None), result_type_name, byte_width)
                if seconds is None:
                    continue
                rows.append(
                    {
                        "event_id": int(getattr(item, "eventId", 0)),
                        "gpu_time_ms": round(float(seconds) * 1000.0, 6),
                    }
                )
            payload["value"] = {
                "timing_available": True,
                "counter_name": _enum_name(event_counter),
                "rows": sorted(rows, key=lambda row: row["event_id"]),
            }

        self.ctx.Replay().BlockInvoke(callback)
        return self.timing_cache.store(cache_key, payload["value"])

    def _serialize_pixel_modification(self, modification, structured_file):
        event_id = int(getattr(modification, "eventId", 0))
        action = self.ctx.GetAction(event_id)
        failed_fields = [
            ("sampleMasked", "sample_masked"),
            ("backfaceCulled", "backface_culled"),
            ("depthClipped", "depth_clipped"),
            ("viewClipped", "view_clipped"),
            ("scissorClipped", "scissor_clipped"),
            ("shaderDiscarded", "shader_discarded"),
            ("depthBoundsFailed", "depth_bounds_failed"),
            ("depthTestFailed", "depth_test_failed"),
            ("stencilTestFailed", "stencil_test_failed"),
        ]
        failed_tests = [name for attr, name in failed_fields if bool(getattr(modification, attr, False))]
        payload = {
            "event_id": event_id,
            "action": self._action_brief(action, structured_file, event_id),
            "primitive_id": _safe_int(getattr(modification, "primitiveID", 0)),
            "fragment_index": _safe_int(getattr(modification, "fragIndex", 0)),
            "passed": not failed_tests and not bool(getattr(modification, "unboundPS", False)),
            "failed_tests": failed_tests,
            "direct_shader_write": bool(getattr(modification, "directShaderWrite", False)),
            "unbound_pixel_shader": bool(getattr(modification, "unboundPS", False)),
        }

        for attr, name in failed_fields:
            payload[name] = bool(getattr(modification, attr, False))

        pre_mod = _serialize_pixel_value(getattr(modification, "preMod", None))
        shader_out = _serialize_pixel_value(getattr(modification, "shaderOut", None))
        post_mod = _serialize_pixel_value(getattr(modification, "postMod", None))
        if pre_mod is not None:
            payload["pre_mod"] = pre_mod
        if shader_out is not None:
            payload["shader_output"] = shader_out
        if post_mod is not None:
            payload["post_mod"] = post_mod
        return payload

    def _pixel_history_payload(self, texture_id, x, y, mip_level, array_slice, sample):
        self._ensure_capture_loaded()
        self._ensure_final_event()
        response = {
            "query": {
                "texture_id": texture_id,
                "x": int(x),
                "y": int(y),
                "mip_level": int(mip_level),
                "array_slice": int(array_slice),
                "sample": int(sample),
            }
        }

        def callback(controller):
            texture = self._find_texture_by_id(texture_id)
            validation = self._validate_texture_request(texture, mip_level, array_slice, sample, x=x, y=y, width=1, height=1)
            comp_type = self._default_comp_type(texture)
            subresource = _subresource(mip_level, array_slice, sample)
            usage = list(controller.GetUsage(texture.resourceId) or [])
            try:
                modifications = list(controller.PixelHistory(usage, texture.resourceId, int(x), int(y), subresource, comp_type) or [])
            except TypeError:
                modifications = list(controller.PixelHistory(texture.resourceId, int(x), int(y), subresource, comp_type) or [])
            structured_file = controller.GetStructuredFile()
            response["texture"] = _serialize_texture(self.ctx, texture)
            response["query"]["mip_dimensions"] = {
                "width": validation["mip_width"],
                "height": validation["mip_height"],
                "depth": validation["mip_depth"],
            }
            response["usage_event_count"] = len(usage)
            response["modifications"] = [self._serialize_pixel_modification(item, structured_file) for item in modifications]
            response["modification_count"] = len(response["modifications"])

        self.ctx.Replay().BlockInvoke(callback)
        return response

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

    def _analyze_frame(self, include_timing_summary=False):
        analysis = self._ensure_frame_analysis()
        timing_payload = self._ensure_timing_data() if include_timing_summary else None
        return frame_analysis.build_analysis_result(
            analysis,
            include_timing_summary=bool(include_timing_summary),
            timing_payload=timing_payload,
        )

    def _list_passes(self, cursor, limit, category_filter, name_filter, sort_by, threshold_ms):
        analysis = self._ensure_frame_analysis()
        timing_payload = self._ensure_timing_data() if sort_by == "gpu_time" else None
        return frame_analysis.list_passes(
            analysis,
            cursor=cursor,
            limit=limit,
            category_filter=category_filter,
            name_filter=name_filter,
            sort_by=sort_by,
            threshold_ms=threshold_ms,
            timing_payload=timing_payload,
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

    def _get_timing_data(self, pass_id):
        analysis = self._ensure_frame_analysis()
        if frame_analysis.get_pass_details(analysis, pass_id) is None:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "invalid_pass_id",
                        "message": "The supplied pass_id does not exist in the active frame analysis.",
                        "details": {"pass_id": pass_id},
                    }
                )
            )
        return frame_analysis.build_timing_result(analysis, pass_id, self._ensure_timing_data())

    def _get_performance_hotspots(self):
        analysis = self._ensure_frame_analysis()
        return frame_analysis.build_performance_hotspots(analysis, self._ensure_timing_data())

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

    def _get_pipeline_state(self, event_id, detail_level):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        response = {"event_id": int(event_id), "detail_level": str(detail_level or "portable")}

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

            if detail_level == "api_specific":
                api_name = response["api"]
                if api_name == "D3D12" and hasattr(controller, "GetD3D12PipelineState"):
                    response["api_pipeline"] = _serialize_d3d12_pipeline_state(
                        self.ctx,
                        controller.GetD3D12PipelineState(),
                    )
                elif api_name == "Vulkan" and hasattr(controller, "GetVulkanPipelineState"):
                    response["api_pipeline"] = _serialize_vulkan_pipeline_state(
                        self.ctx,
                        controller.GetVulkanPipelineState(),
                    )
                else:
                    response["api_pipeline"] = {
                        "api": api_name,
                        "available": False,
                        "reason": "No API-specific pipeline serializer is implemented for this capture API.",
                    }

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

    def _get_pixel_history(self, texture_id, x, y, mip_level, array_slice, sample):
        return self._pixel_history_payload(texture_id, x, y, mip_level, array_slice, sample)

    def _debug_pixel(self, texture_id, x, y, mip_level, array_slice, sample):
        payload = self._pixel_history_payload(texture_id, x, y, mip_level, array_slice, sample)
        grouped = {}
        ordered = []

        for modification in payload.get("modifications", []):
            event_id = int(modification["event_id"])
            entry = grouped.get(event_id)
            if entry is None:
                entry = {
                    "event_id": event_id,
                    "action": dict(modification["action"]),
                    "modification_count": 0,
                    "passed_modification_count": 0,
                    "failed_modification_count": 0,
                    "failed_tests": [],
                    "primitive_ids": [],
                }
                grouped[event_id] = entry
                ordered.append(entry)

            entry["modification_count"] += 1
            if modification["passed"]:
                entry["passed_modification_count"] += 1
            else:
                entry["failed_modification_count"] += 1
            for failed_test in modification.get("failed_tests", []):
                if failed_test not in entry["failed_tests"]:
                    entry["failed_tests"].append(failed_test)
            primitive_id = modification.get("primitive_id")
            if primitive_id not in entry["primitive_ids"]:
                entry["primitive_ids"].append(primitive_id)
            if "pre_mod" in modification and "first_pre_mod" not in entry:
                entry["first_pre_mod"] = modification["pre_mod"]
            if "post_mod" in modification:
                entry["last_post_mod"] = modification["post_mod"]

        return {
            "texture": payload.get("texture"),
            "query": payload.get("query"),
            "usage_event_count": payload.get("usage_event_count", 0),
            "draw_count": len(ordered),
            "draws": ordered,
        }

    def _get_texture_data(self, texture_id, mip_level, x, y, width, height, array_slice, sample):
        self._ensure_capture_loaded()
        self._ensure_final_event()
        response = {
            "query": {
                "texture_id": texture_id,
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
                "mip_level": int(mip_level),
                "array_slice": int(array_slice),
                "sample": int(sample),
            }
        }

        def callback(controller):
            texture = self._find_texture_by_id(texture_id)
            validation = self._validate_texture_request(texture, mip_level, array_slice, sample, x=x, y=y, width=width, height=height)
            comp_type = self._default_comp_type(texture)
            subresource = _subresource(mip_level, array_slice, sample)
            pixels = []
            for row_index in range(int(height)):
                row = []
                for column_index in range(int(width)):
                    pixel = controller.PickPixel(texture.resourceId, int(x) + column_index, int(y) + row_index, subresource, comp_type)
                    row.append(_float_vector(pixel))
                pixels.append(row)
            response["texture"] = _serialize_texture(self.ctx, texture)
            response["query"]["mip_dimensions"] = {
                "width": validation["mip_width"],
                "height": validation["mip_height"],
                "depth": validation["mip_depth"],
            }
            response["row_count"] = len(pixels)
            response["column_count"] = len(pixels[0]) if pixels else 0
            response["pixels"] = pixels

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _get_buffer_data(self, buffer_id, offset, size):
        self._ensure_capture_loaded()
        self._ensure_final_event()
        response = {"buffer_id": buffer_id, "offset": int(offset), "size": int(size)}

        def callback(controller):
            buffer_desc = self._find_buffer_by_id(buffer_id)
            byte_size = int(getattr(buffer_desc, "length", 0))
            if int(offset) + int(size) > byte_size:
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "invalid_buffer_range",
                            "message": "The requested buffer range extends past the end of the selected buffer.",
                            "details": {"offset": int(offset), "size": int(size), "buffer_size": byte_size},
                        }
                    )
                )
            raw = controller.GetBufferData(buffer_desc.resourceId, int(offset), int(size))
            data = bytes(raw or b"")
            response["buffer"] = _serialize_buffer(self.ctx, buffer_desc)
            response["requested_range"] = {"offset": int(offset), "size": int(size)}
            response["returned_size"] = len(data)
            response["data_base64"] = base64.b64encode(data).decode("ascii")
            response["data_hex_preview"] = data[:64].hex(" ")

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _save_texture_to_file(self, texture_id, output_path, mip_level, array_slice):
        self._ensure_capture_loaded()
        self._ensure_final_event()
        response = {
            "texture_id": texture_id,
            "output_path": os.path.abspath(output_path),
            "mip_level": int(mip_level),
            "array_slice": int(array_slice),
        }

        def callback(controller):
            texture = self._find_texture_by_id(texture_id)
            self._validate_texture_request(texture, mip_level, array_slice, 0)
            extension = os.path.splitext(output_path)[1].lower()
            file_type_map = {
                ".dds": "DDS",
                ".hdr": "HDR",
                ".jpeg": "JPG",
                ".jpg": "JPG",
                ".png": "PNG",
            }
            file_type_name = file_type_map.get(extension, "")
            if not file_type_name or rd is None or not hasattr(rd.FileType, file_type_name):
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "unsupported_export_type",
                            "message": "The requested output_path extension is not supported for texture export.",
                            "details": {"output_path": output_path},
                        }
                    )
                )
            directory = os.path.dirname(os.path.abspath(output_path))
            if directory:
                os.makedirs(directory, exist_ok=True)

            texsave = rd.TextureSave()
            texsave.resourceId = texture.resourceId
            texsave.mip = int(mip_level)
            texsave.slice.sliceIndex = int(array_slice)
            texsave.destType = getattr(rd.FileType, file_type_name)
            controller.SaveTexture(texsave, os.path.abspath(output_path))

            if not os.path.isfile(os.path.abspath(output_path)):
                raise RuntimeError(
                    json.dumps(
                        {
                            "code": "replay_failure",
                            "message": "RenderDoc did not create the requested texture export file.",
                            "details": {"output_path": os.path.abspath(output_path)},
                        }
                    )
                )

            response["texture"] = _serialize_texture(self.ctx, texture)
            response["saved"] = True
            response["file_type"] = file_type_name
            response["file_size"] = int(os.path.getsize(os.path.abspath(output_path)))

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
            return self._analyze_frame(bool(params.get("include_timing_summary", False)))
        if method == "list_passes":
            return self._list_passes(
                params.get("cursor"),
                params.get("limit"),
                params.get("category_filter"),
                params.get("name_filter"),
                params.get("sort_by", "event_order"),
                params.get("threshold_ms"),
            )
        if method == "get_pass_details":
            return self._get_pass_details(params.get("pass_id", ""))
        if method == "get_timing_data":
            return self._get_timing_data(params.get("pass_id", ""))
        if method == "get_performance_hotspots":
            return self._get_performance_hotspots()
        if method == "get_action_details":
            return self._get_action_details(int(params.get("event_id", 0)))
        if method == "get_pipeline_state":
            return self._get_pipeline_state(
                int(params.get("event_id", 0)),
                params.get("detail_level", "portable"),
            )
        if method == "get_shader_code":
            return self._get_shader_code(
                int(params.get("event_id", 0)),
                params.get("stage", ""),
                params.get("target"),
            )
        if method == "list_resources":
            return self._list_resources(params.get("kind", "all"), params.get("name_filter"))
        if method == "get_pixel_history":
            return self._get_pixel_history(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            )
        if method == "debug_pixel":
            return self._debug_pixel(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            )
        if method == "get_texture_data":
            return self._get_texture_data(
                params.get("texture_id", ""),
                int(params.get("mip_level", 0)),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("width", 0)),
                int(params.get("height", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            )
        if method == "get_buffer_data":
            return self._get_buffer_data(
                params.get("buffer_id", ""),
                int(params.get("offset", 0)),
                int(params.get("size", 0)),
            )
        if method == "save_texture_to_file":
            return self._save_texture_to_file(
                params.get("texture_id", ""),
                params.get("output_path", ""),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
            )
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
