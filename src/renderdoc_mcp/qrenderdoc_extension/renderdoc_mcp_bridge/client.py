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
_METHOD_UNAVAILABLE = object()


class BridgeError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_payload(self):
        payload = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    @classmethod
    def from_payload(cls, payload):
        return cls(payload.get("code", "replay_failure"), payload.get("message", "RenderDoc request failed."), payload.get("details"))


def _shader_stage_from_name(stage_name):
    normalized = str(stage_name or "").strip().lower()
    for stage in _shader_stage_values():
        if _enum_name(stage).lower() == normalized:
            return stage
    return None


def _select_pipeline_object(state, stage_name):
    graphics = _call_method_variants(state, "GetGraphicsPipelineObject", [()], default=None)
    compute = _call_method_variants(state, "GetComputePipelineObject", [()], default=None)

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


def _call_method_variants(obj, method_name, arg_variants, default=None):
    method = getattr(obj, method_name, None)
    if method is None:
        return default

    for args in arg_variants:
        try:
            return method(*args)
        except TypeError:
            continue
        except AttributeError:
            return default

    return default


def _safe_list(value):
    try:
        return list(value or [])
    except Exception:
        return []


def _load_capture_with_fallback(ctx, capture_path):
    if rd is None:
        return _METHOD_UNAVAILABLE

    replay_options = rd.ReplayOptions()
    signatures = [
        (capture_path, replay_options, capture_path, False, True),
        (capture_path, replay_options, capture_path, False),
        (capture_path, replay_options, capture_path),
        (capture_path, replay_options),
        (capture_path,),
    ]

    return _call_method_variants(ctx, "LoadCapture", signatures, default=_METHOD_UNAVAILABLE)


def _get_disassembly_targets(controller):
    targets = _call_method_variants(controller, "GetDisassemblyTargets", [(True,), ()], default=[])
    return [str(item) for item in _safe_list(targets)]


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
    def __init__(self, ctx, renderdoc_version=""):
        self.ctx = ctx
        self.renderdoc_version = str(renderdoc_version or "")
        self.mqt = ctx.Extensions().GetMiniQtHelper()
        self.sock = None
        self.stop_event = threading.Event()
        self.thread = None
        self.analysis_cache = frame_analysis.AnalysisCache()
        self.timing_cache = frame_analysis.AnalysisCache()
        self.shader_code_cache = {}
        self.handlers = self._build_handlers()

    def _build_handlers(self):
        return {
            "load_capture": lambda params: self._load_capture(params.get("capture_path", "")),
            "get_capture_status": lambda params: self._capture_status(),
            "get_capture_overview": lambda params: self._get_capture_overview(),
            "get_analysis_worklist": lambda params: self._get_analysis_worklist(
                params.get("focus", "performance"),
                params.get("limit", 10),
            ),
            "list_actions": lambda params: self._list_actions(
                params.get("parent_event_id"),
                params.get("name_filter"),
                params.get("flags_filter"),
                params.get("cursor"),
                params.get("limit"),
            ),
            "list_passes": lambda params: self._list_passes(
                params.get("parent_pass_id"),
                params.get("cursor"),
                params.get("limit"),
                params.get("category_filter"),
                params.get("name_filter"),
                params.get("sort_by", "event_order"),
            ),
            "get_pass_summary": lambda params: self._get_pass_summary(params.get("pass_id", "")),
            "list_timing_events": lambda params: self._list_timing_events(
                params.get("pass_id", ""),
                params.get("cursor"),
                params.get("limit"),
                params.get("sort_by", "event_order"),
            ),
            "get_action_summary": lambda params: self._get_action_summary(int(params.get("event_id", 0))),
            "get_pipeline_overview": lambda params: self._get_pipeline_overview(int(params.get("event_id", 0))),
            "list_pipeline_bindings": lambda params: self._list_pipeline_bindings(
                int(params.get("event_id", 0)),
                params.get("binding_kind", ""),
                params.get("cursor"),
                params.get("limit"),
            ),
            "get_shader_summary": lambda params: self._get_shader_summary(
                int(params.get("event_id", 0)),
                params.get("stage", ""),
            ),
            "get_shader_code_chunk": lambda params: self._get_shader_code_chunk(
                int(params.get("event_id", 0)),
                params.get("stage", ""),
                params.get("target"),
                params.get("start_line", 1),
                params.get("line_count", 200),
            ),
            "list_resources": lambda params: self._list_resources(
                params.get("kind", "all"),
                params.get("cursor"),
                params.get("limit"),
                params.get("name_filter"),
                params.get("sort_by", "name"),
            ),
            "get_resource_summary": lambda params: self._get_resource_summary(params.get("resource_id", "")),
            "get_pixel_history": lambda params: self._get_pixel_history(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
                params.get("cursor"),
                params.get("limit"),
            ),
            "debug_pixel": lambda params: self._debug_pixel(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            ),
            "get_texture_data": lambda params: self._get_texture_data(
                params.get("texture_id", ""),
                int(params.get("mip_level", 0)),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("width", 0)),
                int(params.get("height", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            ),
            "get_buffer_data": lambda params: self._get_buffer_data(
                params.get("buffer_id", ""),
                int(params.get("offset", 0)),
                int(params.get("size", 0)),
                params.get("encoding", "hex"),
            ),
            "save_texture_to_file": lambda params: self._save_texture_to_file(
                params.get("texture_id", ""),
                params.get("output_path", ""),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
            ),
            "close_capture": lambda params: self._close_capture(),
        }

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
                        "renderdoc_version": self.renderdoc_version or os.environ.get("RENDERDOC_VERSION", ""),
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
        self.shader_code_cache.clear()

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
            except BridgeError as exc:
                result["error"] = exc.to_payload()
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
            raise BridgeError.from_payload(result["error"])

        return result.get("value", {})

    def _ensure_capture_loaded(self):
        if not self.ctx.IsCaptureLoaded():
            raise BridgeError("replay_failure", "No capture is currently loaded in qrenderdoc.")

    def _set_event(self, event_id):
        action = self.ctx.GetAction(event_id)
        if action is None:
            raise BridgeError(
                "invalid_event_id",
                "The supplied event_id does not exist in the current capture.",
                {"event_id": int(event_id)},
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
        self.shader_code_cache.clear()

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

    def _compact_texture(self, texture):
        payload = _serialize_texture(self.ctx, texture)
        return {
            "kind": "texture",
            "resource_id": payload["resource_id"],
            "name": payload["name"],
            "format": {
                "comp_count": int(payload["format"]["comp_count"]),
                "comp_byte_width": int(payload["format"]["comp_byte_width"]),
                "comp_type": payload["format"]["comp_type"],
                "format_type": payload["format"]["format_type"],
            },
            "dimension": payload["dimension"],
            "width": int(payload["width"]),
            "height": int(payload["height"]),
            "mips": int(payload["mip_levels"]),
            "sample_count": int(payload["sample_count"]),
            "byte_size": int(payload["byte_size"]),
        }

    def _compact_buffer(self, buffer_desc):
        payload = _serialize_buffer(self.ctx, buffer_desc)
        return {
            "kind": "buffer",
            "resource_id": payload["resource_id"],
            "name": payload["name"],
            "byte_size": int(payload["byte_size"]),
            "usage_flags": payload["creation_flags"],
        }

    def _resource_sort_key(self, item, sort_by):
        if sort_by == "size":
            return (-int(item.get("byte_size", 0)), item.get("name", "").lower(), item.get("resource_id", ""))
        return (item.get("name", "").lower(), -int(item.get("byte_size", 0)), item.get("resource_id", ""))

    def _resource_recommendations(self, item):
        if item["kind"] == "texture":
            return [
                {"tool": "renderdoc_get_texture_data", "arguments": {"texture_id": item["resource_id"]}},
                {"tool": "renderdoc_get_pixel_history", "arguments": {"texture_id": item["resource_id"], "x": 0, "y": 0}},
                {"tool": "renderdoc_debug_pixel", "arguments": {"texture_id": item["resource_id"], "x": 0, "y": 0}},
                {"tool": "renderdoc_save_texture_to_file", "arguments": {"texture_id": item["resource_id"]}},
            ]
        return [
            {"tool": "renderdoc_get_buffer_data", "arguments": {"buffer_id": item["resource_id"], "offset": 0}},
        ]

    def _list_resource_items(self, kind, name_filter, sort_by):
        self._ensure_capture_loaded()
        name_filter_lower = (str(name_filter or "").strip().lower()) or None

        def matches(item_name):
            return not name_filter_lower or name_filter_lower in item_name.lower()

        items = []
        if kind in ("all", "textures"):
            items.extend([self._compact_texture(tex) for tex in self.ctx.GetTextures()])
        if kind in ("all", "buffers"):
            items.extend([self._compact_buffer(buf) for buf in self.ctx.GetBuffers()])
        items = [item for item in items if matches(item["name"])]
        items.sort(key=lambda item: self._resource_sort_key(item, sort_by))
        return items

    def _compact_shader_binding(self, shader_payload):
        return {
            "stage": shader_payload["stage"],
            "shader_id": shader_payload["shader_id"],
            "shader_name": shader_payload["shader_name"],
            "entry_point": shader_payload["entry_point"],
            "read_only_resource_count": len(shader_payload.get("read_only_resources", [])),
            "read_write_resource_count": len(shader_payload.get("read_write_resources", [])),
            "sampler_count": len(shader_payload.get("samplers", [])),
            "constant_block_count": len(shader_payload.get("constant_blocks", [])),
        }

    def _page_items(self, items, cursor, limit):
        offset = int(cursor or 0)
        page_limit = int(limit or 0)
        page = items[offset : offset + page_limit]
        next_offset = offset + len(page)
        return {
            "items": page,
            "page": {
                "cursor": str(offset),
                "next_cursor": str(next_offset) if next_offset < len(items) else "",
                "limit": page_limit,
                "returned_count": len(page),
                "total_count": len(items),
                "matched_count": len(items),
                "has_more": next_offset < len(items),
            },
        }

    def _get_output_target_items(self, pipeline):
        items = []
        for index, descriptor in enumerate(pipeline.get("output_targets", [])):
            entry = dict(descriptor)
            entry["slot_kind"] = "color"
            entry["slot_index"] = index
            items.append(entry)
        depth_target = pipeline.get("depth_target")
        if depth_target and depth_target.get("resource_id"):
            entry = dict(depth_target)
            entry["slot_kind"] = "depth"
            entry["slot_index"] = -1
            items.append(entry)
        depth_resolve_target = pipeline.get("depth_resolve_target")
        if depth_resolve_target and depth_resolve_target.get("resource_id"):
            entry = dict(depth_resolve_target)
            entry["slot_kind"] = "depth_resolve"
            entry["slot_index"] = -1
            items.append(entry)
        return items

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
        result = _load_capture_with_fallback(self.ctx, capture_path)
        if result is _METHOD_UNAVAILABLE:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "replay_failure",
                        "message": "RenderDoc did not expose a compatible LoadCapture signature.",
                        "details": {"capture_path": capture_path},
                    }
                )
            )
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

    def _get_capture_overview(self):
        overview = self._get_capture_summary()
        analysis = self._ensure_frame_analysis()
        timing_payload = self._ensure_timing_data()
        overview["root_pass_count"] = len(analysis.get("root_pass_ids", []))
        overview["action_root_count"] = len(analysis.get("root_action_ids", []))
        overview["capabilities"] = {
            "timing_data": bool(timing_payload.get("timing_available")),
            "pixel_history": True,
            "shader_disassembly": True,
        }
        return overview

    def _get_analysis_worklist(self, focus, limit):
        analysis = self._ensure_frame_analysis()
        limit = max(1, int(limit or 10))
        focus = str(focus or "performance").strip().lower() or "performance"

        items = []
        if focus == "performance":
            hotspots = frame_analysis.build_performance_hotspots(analysis, self._ensure_timing_data(), limit=limit)
            for entry in hotspots.get("top_passes", []):
                items.append(
                    {
                        "kind": "pass",
                        "id": entry["pass_id"],
                        "label": entry["name"],
                        "reason": "High-impact pass ranked by {}.".format(entry["metric_name"]),
                        "recommended_call": {
                            "tool": "renderdoc_get_pass_summary",
                            "arguments": {"pass_id": entry["pass_id"]},
                        },
                    }
                )
            for entry in hotspots.get("top_events", []):
                if len(items) >= limit:
                    break
                items.append(
                    {
                        "kind": "event",
                        "id": int(entry["event_id"]),
                        "label": entry["name"],
                        "reason": "High-impact event ranked by {}.".format(entry["metric_name"]),
                        "recommended_call": {
                            "tool": "renderdoc_get_pipeline_overview",
                            "arguments": {"event_id": int(entry["event_id"])},
                        },
                    }
                )
        elif focus == "structure":
            for pass_id in analysis.get("root_pass_ids", [])[:limit]:
                entry = frame_analysis.get_pass_summary(analysis, pass_id)
                if entry is None:
                    continue
                next_tool = "renderdoc_get_pass_summary"
                next_args = {"pass_id": entry["pass_id"]}
                if int(entry.get("child_pass_count", 0)) > 0:
                    next_tool = "renderdoc_list_passes"
                    next_args = {"parent_pass_id": entry["pass_id"]}
                items.append(
                    {
                        "kind": "pass",
                        "id": entry["pass_id"],
                        "label": entry["name"],
                        "reason": "Root-level structural pass with {} child pass(es).".format(entry["child_pass_count"]),
                        "recommended_call": {"tool": next_tool, "arguments": next_args},
                    }
                )
        else:
            for item in self._list_resource_items("all", None, "size")[:limit]:
                items.append(
                    {
                        "kind": "resource",
                        "id": item["resource_id"],
                        "label": item["name"],
                        "reason": "Large {} resource by byte size.".format(item["kind"]),
                        "recommended_call": {
                            "tool": "renderdoc_get_resource_summary",
                            "arguments": {"resource_id": item["resource_id"]},
                        },
                    }
                )

        return {"focus": focus, "count": len(items), "items": items}

    def _get_action_tree(self, max_depth, name_filter, limit):
        analysis = self._ensure_frame_analysis()
        return frame_analysis.build_action_tree_result(
            analysis["action_tree"],
            analysis["total_actions"],
            max_depth=max_depth,
            name_filter=name_filter,
            limit=limit,
        )

    def _list_actions(self, parent_event_id, name_filter, flags_filter, cursor, limit):
        analysis = self._ensure_frame_analysis()
        if parent_event_id not in (None, "") and int(parent_event_id) not in analysis.get("action_index", {}):
            raise BridgeError(
                "invalid_event_id",
                "The supplied event_id does not exist in the current capture.",
                {"event_id": int(parent_event_id)},
            )
        return frame_analysis.build_action_children_result(
            analysis,
            parent_event_id=parent_event_id,
            name_filter=name_filter,
            flags_filter=flags_filter,
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

    def _list_passes(self, parent_pass_id, cursor, limit, category_filter, name_filter, sort_by):
        analysis = self._ensure_frame_analysis()
        if parent_pass_id not in (None, "") and parent_pass_id not in analysis.get("pass_index", {}):
            raise BridgeError(
                "invalid_pass_id",
                "The supplied pass_id does not exist in the active frame analysis.",
                {"pass_id": parent_pass_id},
            )
        timing_payload = self._ensure_timing_data() if sort_by == "gpu_time" else None
        return frame_analysis.list_passes(
            analysis,
            parent_pass_id=parent_pass_id,
            cursor=cursor,
            limit=limit,
            category_filter=category_filter,
            name_filter=name_filter,
            sort_by=sort_by,
            timing_payload=timing_payload,
        )

    def _get_pass_details(self, pass_id):
        analysis = self._ensure_frame_analysis()
        details = frame_analysis.get_pass_details(analysis, pass_id)
        if details is None:
            raise BridgeError(
                "invalid_pass_id",
                "The supplied pass_id does not exist in the active frame analysis.",
                {"pass_id": pass_id},
            )
        return details

    def _get_pass_summary(self, pass_id):
        analysis = self._ensure_frame_analysis()
        summary = frame_analysis.get_pass_summary(analysis, pass_id)
        if summary is None:
            raise BridgeError(
                "invalid_pass_id",
                "The supplied pass_id does not exist in the active frame analysis.",
                {"pass_id": pass_id},
            )
        return summary

    def _get_timing_data(self, pass_id):
        analysis = self._ensure_frame_analysis()
        if frame_analysis.get_pass_details(analysis, pass_id) is None:
            raise BridgeError(
                "invalid_pass_id",
                "The supplied pass_id does not exist in the active frame analysis.",
                {"pass_id": pass_id},
            )
        return frame_analysis.build_timing_result(analysis, pass_id, self._ensure_timing_data())

    def _list_timing_events(self, pass_id, cursor, limit, sort_by):
        analysis = self._ensure_frame_analysis()
        if frame_analysis.get_pass_summary(analysis, pass_id) is None:
            raise BridgeError(
                "invalid_pass_id",
                "The supplied pass_id does not exist in the active frame analysis.",
                {"pass_id": pass_id},
            )
        return frame_analysis.list_timing_events(
            analysis,
            pass_id,
            self._ensure_timing_data(),
            cursor=cursor,
            limit=limit,
            sort_by=sort_by,
        )

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

    def _get_action_summary(self, event_id):
        analysis = self._ensure_frame_analysis()
        summary = frame_analysis.build_action_summary_result(analysis, event_id)
        if summary is None:
            raise BridgeError(
                "invalid_event_id",
                "The supplied event_id does not exist in the current capture.",
                {"event_id": int(event_id)},
            )
        return summary

    def _get_pipeline_overview(self, event_id):
        pipeline_payload = self._get_pipeline_state(event_id)
        api_pipeline_payload = self._get_api_pipeline_state(event_id)
        pipeline = pipeline_payload.get("pipeline", {})
        shaders = [self._compact_shader_binding(item) for item in pipeline.get("shaders", [])]
        overview = {
            "event_id": int(event_id),
            "api": pipeline_payload.get("api", api_pipeline_payload.get("api", "")),
            "action": pipeline_payload.get("action", api_pipeline_payload.get("action", {})),
            "pipeline": {
                "available": bool(pipeline.get("available", False)),
                "reason": pipeline.get("reason", ""),
                "topology": pipeline.get("topology", "Unknown"),
                "graphics_pipeline_object": pipeline.get("graphics_pipeline_object", ""),
                "compute_pipeline_object": pipeline.get("compute_pipeline_object", ""),
                "counts": {
                    "descriptor_accesses": len(pipeline.get("descriptor_accesses", [])),
                    "vertex_buffers": len(pipeline.get("vertex_buffers", [])),
                    "vertex_inputs": len(pipeline.get("vertex_inputs", [])),
                    "output_targets": len(self._get_output_target_items(pipeline)),
                    "shaders": len(shaders),
                },
                "shaders": shaders,
                "api_details_available": bool((api_pipeline_payload.get("api_pipeline") or {}).get("available", False)),
                "api_details_api": (api_pipeline_payload.get("api_pipeline") or {}).get(
                    "api",
                    api_pipeline_payload.get("api", ""),
                ),
            },
        }
        return overview

    def _list_pipeline_bindings(self, event_id, binding_kind, cursor, limit):
        pipeline_payload = self._get_pipeline_state(event_id)
        api_pipeline_payload = self._get_api_pipeline_state(event_id)
        pipeline = pipeline_payload.get("pipeline", {})

        if binding_kind == "descriptor_accesses":
            items = list(pipeline.get("descriptor_accesses", []))
        elif binding_kind == "vertex_buffers":
            items = list(pipeline.get("vertex_buffers", []))
        elif binding_kind == "vertex_inputs":
            items = list(pipeline.get("vertex_inputs", []))
        elif binding_kind == "output_targets":
            items = self._get_output_target_items(pipeline)
        elif binding_kind == "shaders":
            items = [self._compact_shader_binding(item) for item in pipeline.get("shaders", [])]
        else:
            api_details = api_pipeline_payload.get("api_pipeline")
            items = [api_details] if api_details is not None else []

        paging = self._page_items(items, cursor or 0, limit or 50)
        return {
            "event_id": int(event_id),
            "api": pipeline_payload.get("api", api_pipeline_payload.get("api", "")),
            "action": pipeline_payload.get("action", api_pipeline_payload.get("action", {})),
            "binding_kind": binding_kind,
            "available": bool(pipeline.get("available", False)) if binding_kind != "api_details" else True,
            "items": paging["items"],
            "meta": {"page": paging["page"]},
        }

    def _get_shader_summary(self, event_id, stage_name):
        pipeline_payload = self._get_pipeline_state(event_id)
        pipeline = pipeline_payload.get("pipeline", {})
        shader_payload = next(
            (item for item in pipeline.get("shaders", []) if str(item.get("stage", "")).lower() == str(stage_name).lower()),
            None,
        )
        if shader_payload is None:
            raise BridgeError(
                "shader_not_bound",
                "No shader is bound at the supplied stage for the selected event.",
                {"event_id": int(event_id), "stage": stage_name},
            )

        targets_payload = self._get_shader_disassembly_targets(event_id)
        return {
            "event_id": int(event_id),
            "api": pipeline_payload.get("api", ""),
            "action": pipeline_payload.get("action", {}),
            "shader": {
                "stage": shader_payload["stage"],
                "shader_id": shader_payload["shader_id"],
                "shader_name": shader_payload["shader_name"],
                "entry_point": shader_payload["entry_point"],
                "reflection": dict(shader_payload.get("reflection", {})),
                "counts": {
                    "read_only_resources": len(shader_payload.get("read_only_resources", [])),
                    "read_write_resources": len(shader_payload.get("read_write_resources", [])),
                    "samplers": len(shader_payload.get("samplers", [])),
                    "constant_blocks": len(shader_payload.get("constant_blocks", [])),
                },
            },
            "disassembly": targets_payload,
        }

    def _get_shader_code_chunk(self, event_id, stage_name, target, start_line, line_count):
        start_line = max(1, int(start_line or 1))
        line_count = max(1, int(line_count or 200))
        cache_key = (int(event_id), str(stage_name), str(target or "").lower())
        cached = self.shader_code_cache.get(cache_key)

        if cached is None:
            shader_payload = self._get_shader_code(event_id, stage_name, target)
            disassembly = shader_payload.get("disassembly", {})
            selected_target = str(disassembly.get("target", "") or "")
            actual_key = (int(event_id), str(stage_name), selected_target.lower())
            text = str(disassembly.get("text", "") or "")
            cached = {
                "event_id": int(event_id),
                "api": shader_payload.get("api", ""),
                "action": shader_payload.get("action", {}),
                "shader": {
                    "stage": shader_payload.get("shader", {}).get("stage", stage_name),
                    "shader_id": shader_payload.get("shader", {}).get("shader_id", ""),
                    "shader_name": shader_payload.get("shader", {}).get("shader_name", ""),
                },
                "available": bool(disassembly.get("available", False)),
                "reason": disassembly.get("reason", ""),
                "target": selected_target,
                "available_targets": list(disassembly.get("available_targets", [])),
                "lines": text.splitlines(),
            }
            self.shader_code_cache[actual_key] = cached
            self.shader_code_cache[cache_key] = cached

        if not cached["available"]:
            return {
                "event_id": cached["event_id"],
                "api": cached["api"],
                "action": cached["action"],
                "shader": dict(cached["shader"]),
                "target": cached["target"],
                "available_targets": list(cached["available_targets"]),
                "available": False,
                "reason": cached["reason"],
                "start_line": start_line,
                "returned_line_count": 0,
                "total_lines": 0,
                "has_more": False,
                "text": "",
            }

        lines = cached["lines"]
        offset = start_line - 1
        chunk = lines[offset : offset + line_count]
        returned_line_count = len(chunk)
        total_lines = len(lines)
        return {
            "event_id": cached["event_id"],
            "api": cached["api"],
            "action": cached["action"],
            "shader": dict(cached["shader"]),
            "target": cached["target"],
            "available_targets": list(cached["available_targets"]),
            "available": True,
            "reason": "",
            "start_line": start_line,
            "returned_line_count": returned_line_count,
            "total_lines": total_lines,
            "has_more": (offset + returned_line_count) < total_lines,
            "text": "\n".join(chunk),
        }

    def _get_pipeline_state(self, event_id):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        response = {"event_id": int(event_id)}

        def callback(controller):
            response["api"] = _api_name(controller)
            response["action"] = {
                "event_id": int(action.eventId),
                "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                "flags": _action_flags(action),
            }
            state = _call_method_variants(controller, "GetPipelineState", [()], default=None)
            if state is None:
                response["pipeline"] = {
                    "available": False,
                    "reason": "RenderDoc did not expose GetPipelineState in this build.",
                    "topology": "Unknown",
                    "graphics_pipeline_object": "",
                    "compute_pipeline_object": "",
                    "index_buffer": _serialize_bound_vbuffer(self.ctx, None),
                    "vertex_buffers": [],
                    "vertex_inputs": [],
                    "output_targets": [],
                    "depth_target": _serialize_descriptor(self.ctx, None),
                    "depth_resolve_target": _serialize_descriptor(self.ctx, None),
                    "descriptor_accesses": [],
                    "shaders": [],
                }
                return

            descriptor_accesses = _call_method_variants(state, "GetDescriptorAccess", [()], default=[])
            response["pipeline"] = {
                "available": True,
                "topology": _enum_name(_call_method_variants(state, "GetPrimitiveTopology", [()], default="Unknown")),
                "graphics_pipeline_object": _resource_id(
                    _call_method_variants(state, "GetGraphicsPipelineObject", [()], default=None)
                ),
                "compute_pipeline_object": _resource_id(
                    _call_method_variants(state, "GetComputePipelineObject", [()], default=None)
                ),
                "index_buffer": _serialize_bound_vbuffer(
                    self.ctx,
                    _call_method_variants(state, "GetIBuffer", [()], default=None),
                ),
                "vertex_buffers": [
                    _serialize_bound_vbuffer(self.ctx, vb)
                    for vb in _safe_list(_call_method_variants(state, "GetVBuffers", [()], default=[]))
                ],
                "vertex_inputs": [
                    _serialize_vertex_input(attr)
                    for attr in _safe_list(_call_method_variants(state, "GetVertexInputs", [()], default=[]))
                ],
                "output_targets": [
                    _serialize_descriptor(self.ctx, desc)
                    for desc in _safe_list(_call_method_variants(state, "GetOutputTargets", [()], default=[]))
                ],
                "depth_target": _serialize_descriptor(
                    self.ctx,
                    _call_method_variants(state, "GetDepthTarget", [()], default=None),
                ),
                "depth_resolve_target": _serialize_descriptor(
                    self.ctx,
                    _call_method_variants(state, "GetDepthResolveTarget", [()], default=None),
                ),
                "descriptor_accesses": [_serialize_descriptor_access(item) for item in _safe_list(descriptor_accesses)],
                "shaders": [],
            }

            for stage in _shader_stage_values():
                serialized = _serialize_shader_stage(self.ctx, state, stage)
                if serialized is not None:
                    response["pipeline"]["shaders"].append(serialized)

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _get_api_pipeline_state(self, event_id):
        self._ensure_capture_loaded()
        action = self._set_event(event_id)
        response = {"event_id": int(event_id)}

        def callback(controller):
            api_name = _api_name(controller)
            response["api"] = api_name
            response["action"] = {
                "event_id": int(action.eventId),
                "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                "flags": _action_flags(action),
            }
            if api_name == "D3D12" and hasattr(controller, "GetD3D12PipelineState"):
                value = _call_method_variants(controller, "GetD3D12PipelineState", [()], default=None)
                if value is None:
                    response["api_pipeline"] = {
                        "api": api_name,
                        "available": False,
                        "reason": "RenderDoc did not expose a compatible D3D12 pipeline accessor in this build.",
                    }
                else:
                    response["api_pipeline"] = _serialize_d3d12_pipeline_state(self.ctx, value)
            elif api_name == "Vulkan" and hasattr(controller, "GetVulkanPipelineState"):
                value = _call_method_variants(controller, "GetVulkanPipelineState", [()], default=None)
                if value is None:
                    response["api_pipeline"] = {
                        "api": api_name,
                        "available": False,
                        "reason": "RenderDoc did not expose a compatible Vulkan pipeline accessor in this build.",
                    }
                else:
                    response["api_pipeline"] = _serialize_vulkan_pipeline_state(self.ctx, value)
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

            state = _call_method_variants(controller, "GetPipelineState", [()], default=None)
            if state is None:
                response["api"] = _api_name(controller)
                response["action"] = {
                    "event_id": int(action.eventId),
                    "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                    "flags": _action_flags(action),
                }
                response["shader"] = {
                    "stage": _enum_name(stage),
                    "shader_id": "",
                    "shader_name": "",
                    "entry_point": "",
                    "read_only_resources": [],
                    "read_write_resources": [],
                    "samplers": [],
                    "constant_blocks": [],
                }
                response["disassembly"] = {
                    "available": False,
                    "reason": "RenderDoc did not expose GetPipelineState in this build.",
                    "target": "",
                    "available_targets": [],
                    "pipeline_object_kind": "",
                    "pipeline_object_id": "",
                    "text": "",
                }
                return

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

            response["api"] = _api_name(controller)
            response["action"] = {
                "event_id": int(action.eventId),
                "name": action.GetName(controller.GetStructuredFile()) or action.customName or "Event {}".format(action.eventId),
                "flags": _action_flags(action),
            }
            response["shader"] = shader_payload

            targets = _get_disassembly_targets(controller)
            if not targets:
                response["disassembly"] = {
                    "available": False,
                    "reason": "RenderDoc did not report any shader disassembly targets.",
                    "target": "",
                    "available_targets": [],
                    "pipeline_object_kind": "",
                    "pipeline_object_id": "",
                    "text": "",
                }
                return

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

            reflection = _call_method_variants(state, "GetShaderReflection", [(stage,)], default=None)
            if reflection is None:
                pipeline_object_kind, pipeline_object = _select_pipeline_object(state, shader_payload["stage"])
                response["disassembly"] = {
                    "available": False,
                    "reason": "RenderDoc did not return shader reflection for the selected stage.",
                    "target": selected_target,
                    "available_targets": targets,
                    "pipeline_object_kind": pipeline_object_kind,
                    "pipeline_object_id": _resource_id(pipeline_object),
                    "text": "",
                }
                return

            pipeline_object_kind, pipeline_object = _select_pipeline_object(state, shader_payload["stage"])
            disassembly_text = ""
            disassembly_available = False
            disassembly_reason = ""
            try:
                disassembly_text = str(controller.DisassembleShader(pipeline_object, reflection, selected_target) or "")
                disassembly_available = True
            except TypeError:
                disassembly_reason = "RenderDoc did not expose a compatible DisassembleShader signature."
            except AttributeError:
                disassembly_reason = "RenderDoc did not expose DisassembleShader in this build."

            response["disassembly"] = {
                "available": disassembly_available,
                "reason": disassembly_reason,
                "target": selected_target,
                "available_targets": targets,
                "pipeline_object_kind": pipeline_object_kind,
                "pipeline_object_id": _resource_id(pipeline_object),
                "text": disassembly_text,
            }

        self.ctx.Replay().BlockInvoke(callback)
        return response

    def _get_shader_disassembly_targets(self, event_id):
        self._ensure_capture_loaded()
        self._set_event(event_id)
        payload = {
            "available": False,
            "reason": "",
            "default_target": "",
            "available_targets": [],
        }

        def callback(controller):
            targets = _get_disassembly_targets(controller)
            payload["available_targets"] = targets
            payload["default_target"] = targets[0] if targets else ""
            payload["available"] = bool(targets)
            if not targets:
                payload["reason"] = "RenderDoc did not report any shader disassembly targets."

        self.ctx.Replay().BlockInvoke(callback)
        return payload

    def _get_pixel_history(self, texture_id, x, y, mip_level, array_slice, sample, cursor, limit):
        payload = self._pixel_history_payload(texture_id, x, y, mip_level, array_slice, sample)
        modifications = list(payload.get("modifications", []))
        paging = self._page_items(modifications, cursor or 0, limit or 100)
        payload["modifications"] = paging["items"]
        payload["total_modification_count"] = len(modifications)
        payload["modification_count"] = len(paging["items"])
        payload["meta"] = {"page": paging["page"]}
        return payload

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

    def _get_buffer_data(self, buffer_id, offset, size, encoding):
        self._ensure_capture_loaded()
        self._ensure_final_event()
        response = {
            "buffer_id": buffer_id,
            "offset": int(offset),
            "size": int(size),
            "encoding": str(encoding or "hex"),
        }

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
            response["buffer"] = self._compact_buffer(buffer_desc)
            response["requested_range"] = {"offset": int(offset), "size": int(size)}
            response["returned_size"] = len(data)
            if str(encoding or "hex").lower() == "base64":
                response["data"] = base64.b64encode(data).decode("ascii")
            else:
                response["data"] = data.hex(" ")

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

    def _list_resources(self, kind, cursor, limit, name_filter, sort_by):
        items = self._list_resource_items(kind, name_filter, sort_by)
        paging = self._page_items(items, cursor or 0, limit or 50)
        return {
            "kind": kind,
            "sort_by": sort_by,
            "name_filter": str(name_filter or ""),
            "items": paging["items"],
            "meta": {"page": paging["page"]},
        }

    def _get_resource_summary(self, resource_id):
        self._ensure_capture_loaded()

        for texture in self.ctx.GetTextures():
            if _resource_id_matches(texture.resourceId, resource_id):
                item = self._compact_texture(texture)
                return {"resource": item, "recommended_calls": self._resource_recommendations(item), "meta": {}}

        for buffer_desc in self.ctx.GetBuffers():
            if _resource_id_matches(buffer_desc.resourceId, resource_id):
                item = self._compact_buffer(buffer_desc)
                return {"resource": item, "recommended_calls": self._resource_recommendations(item), "meta": {}}

        raise BridgeError(
            "invalid_resource_id",
            "The supplied resource_id does not exist in the active capture.",
            {"resource_id": resource_id},
        )

    def _close_capture(self):
        if self.ctx.IsCaptureLoaded():
            self._clear_analysis_cache()
            self.ctx.CloseCapture()
        return {"closed": True, "meta": {}}

    def _dispatch(self, method, params):
        handler = self.handlers.get(method)
        if handler is None:
            raise BridgeError("replay_failure", "Unknown bridge method.", {"method": method})
        return handler(params or {})

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
        if isinstance(exc, BridgeError):
            return exc.to_payload()
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
        bridge = BridgeClient(ctx, renderdoc_version=version)
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
