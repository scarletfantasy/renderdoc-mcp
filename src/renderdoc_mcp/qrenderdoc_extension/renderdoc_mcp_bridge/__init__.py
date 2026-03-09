import json
import os
import threading
import time
import traceback
import ctypes

try:
    import qrenderdoc as qrd
    import renderdoc as rd
except Exception:
    qrd = None
    rd = None

try:
    from . import frame_analysis as _frame_analysis
except Exception:
    import frame_analysis as _frame_analysis

PROTOCOL_VERSION = 1
CONNECT_RETRY_SECONDS = 20.0
SOCKET_POLL_TIMEOUT = 0.25
ACTION_LIST_NODE_LIMIT = 500

_bridge = None
_LOG_PATH = os.environ.get("RENDERDOC_MCP_BRIDGE_LOG")
if not _LOG_PATH:
    _LOG_PATH = os.path.join(os.environ.get("TEMP", os.environ.get("TMP", ".")), "renderdoc_mcp_bridge_default.log")


def _log(message):
    if not _LOG_PATH:
        return
    try:
        with open(_LOG_PATH, "a") as handle:
            handle.write("[{}] {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


class _WSADATA(ctypes.Structure):
    _fields_ = [
        ("wVersion", ctypes.c_ushort),
        ("wHighVersion", ctypes.c_ushort),
        ("szDescription", ctypes.c_char * 257),
        ("szSystemStatus", ctypes.c_char * 129),
        ("iMaxSockets", ctypes.c_ushort),
        ("iMaxUdpDg", ctypes.c_ushort),
        ("lpVendorInfo", ctypes.c_void_p),
    ]


class _SockAddrIn(ctypes.Structure):
    _fields_ = [
        ("sin_family", ctypes.c_short),
        ("sin_port", ctypes.c_ushort),
        ("sin_addr", ctypes.c_uint32),
        ("sin_zero", ctypes.c_char * 8),
    ]


class _WinSockClient(object):
    AF_INET = 2
    SOCK_STREAM = 1
    IPPROTO_TCP = 6
    SOL_SOCKET = 0xFFFF
    SO_RCVTIMEO = 0x1006
    SO_SNDTIMEO = 0x1005
    INVALID_SOCKET = ctypes.c_size_t(-1).value
    SOCKET_ERROR = -1
    WSAETIMEDOUT = 10060
    WSAEWOULDBLOCK = 10035

    _started = False
    _ws2_32 = ctypes.WinDLL("Ws2_32.dll")

    @classmethod
    def _startup(cls):
        if cls._started:
            return
        data = _WSADATA()
        result = cls._ws2_32.WSAStartup(0x0202, ctypes.byref(data))
        if result != 0:
            raise RuntimeError("WSAStartup failed: {}".format(result))
        cls._started = True

    @classmethod
    def _last_error(cls):
        return int(cls._ws2_32.WSAGetLastError())

    def __init__(self):
        self._startup()
        self.sock = ctypes.c_size_t(self.INVALID_SOCKET)
        self._buffer = b""

    def connect(self, host, port):
        self.sock = ctypes.c_size_t(self._ws2_32.socket(self.AF_INET, self.SOCK_STREAM, self.IPPROTO_TCP))
        if self.sock.value == self.INVALID_SOCKET:
            raise RuntimeError("socket() failed: {}".format(self._last_error()))

        timeout_ms = ctypes.c_int(250)
        timeout_size = ctypes.c_int(ctypes.sizeof(timeout_ms))
        self._ws2_32.setsockopt(self.sock, self.SOL_SOCKET, self.SO_RCVTIMEO, ctypes.byref(timeout_ms), timeout_size)
        self._ws2_32.setsockopt(self.sock, self.SOL_SOCKET, self.SO_SNDTIMEO, ctypes.byref(timeout_ms), timeout_size)

        addr = _SockAddrIn()
        addr.sin_family = self.AF_INET
        addr.sin_port = ((int(port) & 0xFF) << 8) | ((int(port) >> 8) & 0xFF)
        addr.sin_addr = self._ws2_32.inet_addr(host.encode("ascii"))
        addr.sin_zero = b"\0" * 8

        result = self._ws2_32.connect(self.sock, ctypes.byref(addr), ctypes.sizeof(addr))
        if result == self.SOCKET_ERROR:
            error = self._last_error()
            self.close()
            raise RuntimeError("connect() failed: {}".format(error))

    def send_text(self, text):
        payload = text.encode("utf-8")
        total = 0
        while total < len(payload):
            chunk = payload[total:]
            result = self._ws2_32.send(self.sock, chunk, len(chunk), 0)
            if result == self.SOCKET_ERROR:
                error = self._last_error()
                if error in (self.WSAETIMEDOUT, self.WSAEWOULDBLOCK):
                    raise TimeoutError("send() timed out")
                raise RuntimeError("send() failed: {}".format(error))
            total += int(result)

    def recv_line(self):
        while True:
            newline_index = self._buffer.find(b"\n")
            if newline_index >= 0:
                line = self._buffer[:newline_index]
                self._buffer = self._buffer[newline_index + 1 :]
                return line.decode("utf-8")

            chunk = ctypes.create_string_buffer(4096)
            result = self._ws2_32.recv(self.sock, chunk, len(chunk), 0)
            if result == 0:
                raise RuntimeError("recv() returned EOF")
            if result == self.SOCKET_ERROR:
                error = self._last_error()
                if error in (self.WSAETIMEDOUT, self.WSAEWOULDBLOCK):
                    raise TimeoutError("recv() timed out")
                raise RuntimeError("recv() failed: {}".format(error))
            self._buffer += chunk.raw[: int(result)]

    def close(self):
        if self.sock.value != self.INVALID_SOCKET:
            self._ws2_32.closesocket(self.sock)
            self.sock = ctypes.c_size_t(self.INVALID_SOCKET)


def _enum_name(value):
    return str(value).split(".")[-1]


def _resource_id(value):
    try:
        if value == rd.ResourceId.Null():
            return ""
    except Exception:
        pass
    return str(value)


def _resource_name(ctx, resource_id):
    if not _resource_id(resource_id):
        return ""
    try:
        return ctx.GetResourceName(resource_id) or str(resource_id)
    except Exception:
        return str(resource_id)


def _resource_format(fmt):
    return {
        "name": str(fmt),
        "comp_count": int(getattr(fmt, "compCount", 0)),
        "comp_byte_width": int(getattr(fmt, "compByteWidth", 0)),
        "comp_type": _enum_name(getattr(fmt, "compType", "Unknown")),
        "format_type": _enum_name(getattr(fmt, "type", "Unknown")),
    }


def _subresource(value):
    return {
        "mip": int(getattr(value, "mip", 0)),
        "slice": int(getattr(value, "slice", 0)),
        "sample": int(getattr(value, "sample", 0)),
    }


def _float_vector(value):
    return [
        float(getattr(value, "x", 0.0)),
        float(getattr(value, "y", 0.0)),
        float(getattr(value, "z", 0.0)),
        float(getattr(value, "w", 0.0)),
    ]


def _action_flags(action):
    flags = []
    enum = rd.ActionFlags
    known = [
        ("Drawcall", "draw"),
        ("Dispatch", "dispatch"),
        ("PushMarker", "push_marker"),
        ("SetMarker", "set_marker"),
        ("Copy", "copy"),
        ("Resolve", "resolve"),
        ("Clear", "clear"),
        ("Indexed", "indexed"),
        ("Instanced", "instanced"),
        ("Indirect", "indirect"),
        ("CommandBufferBoundary", "command_buffer_boundary"),
        ("BeginPass", "begin_pass"),
        ("EndPass", "end_pass"),
    ]
    for attr, name in known:
        if hasattr(enum, attr):
            try:
                if action.flags & getattr(enum, attr):
                    flags.append(name)
            except Exception:
                pass
    return flags


def _api_name(controller):
    return _enum_name(controller.GetAPIProperties().pipelineType)


def _serialize_event(api_event):
    payload = {"event_id": int(getattr(api_event, "eventId", 0))}
    if hasattr(api_event, "chunkIndex"):
        payload["chunk_index"] = int(getattr(api_event, "chunkIndex", 0))
    return payload


def _serialize_action_analysis_node(ctx, action, structured_file):
    name = action.GetName(structured_file) or action.customName or "Event {}".format(action.eventId)
    return {
        "event_id": int(action.eventId),
        "action_id": int(action.actionId),
        "name": name,
        "custom_name": str(action.customName or ""),
        "flags": _action_flags(action),
        "child_count": len(action.children),
        "is_fake_marker": bool(action.IsFakeMarker()),
        "num_indices": int(action.numIndices),
        "num_instances": int(action.numInstances),
        "dispatch_dimension": [int(x) for x in action.dispatchDimension],
        "dispatch_threads_dimension": [int(x) for x in action.dispatchThreadsDimension],
        "outputs": [
            {"resource_id": _resource_id(res_id), "resource_name": _resource_name(ctx, res_id)}
            for res_id in action.outputs
            if _resource_id(res_id)
        ],
        "depth_output": {
            "resource_id": _resource_id(action.depthOut),
            "resource_name": _resource_name(ctx, action.depthOut),
        },
        "parent_event_id": int(action.parent.eventId) if action.parent is not None else None,
        "children": [_serialize_action_analysis_node(ctx, child, structured_file) for child in action.children],
    }


def _serialize_action(ctx, action, structured_file, depth, max_depth, name_filter_lower):
    name = action.GetName(structured_file) or action.customName or "Event {}".format(action.eventId)
    children_payload = []

    if max_depth is None or depth < max_depth:
        for child in action.children:
            child_payload = _serialize_action(ctx, child, structured_file, depth + 1, max_depth, name_filter_lower)
            if child_payload is not None:
                children_payload.append(child_payload)

    if name_filter_lower and name_filter_lower not in name.lower() and not children_payload:
        return None

    return {
        "event_id": int(action.eventId),
        "action_id": int(action.actionId),
        "name": name,
        "custom_name": str(action.customName or ""),
        "flags": _action_flags(action),
        "is_fake_marker": bool(action.IsFakeMarker()),
        "marker_color": _float_vector(action.markerColor),
        "num_indices": int(action.numIndices),
        "num_instances": int(action.numInstances),
        "base_vertex": int(action.baseVertex),
        "index_offset": int(action.indexOffset),
        "vertex_offset": int(action.vertexOffset),
        "instance_offset": int(action.instanceOffset),
        "draw_index": int(action.drawIndex),
        "dispatch_dimension": [int(x) for x in action.dispatchDimension],
        "dispatch_threads_dimension": [int(x) for x in action.dispatchThreadsDimension],
        "dispatch_base": [int(x) for x in action.dispatchBase],
        "copy_source": {
            "resource_id": _resource_id(action.copySource),
            "resource_name": _resource_name(ctx, action.copySource),
            "subresource": _subresource(action.copySourceSubresource),
        },
        "copy_destination": {
            "resource_id": _resource_id(action.copyDestination),
            "resource_name": _resource_name(ctx, action.copyDestination),
            "subresource": _subresource(action.copyDestinationSubresource),
        },
        "outputs": [
            {"resource_id": _resource_id(res_id), "resource_name": _resource_name(ctx, res_id)}
            for res_id in action.outputs
            if _resource_id(res_id)
        ],
        "depth_output": {
            "resource_id": _resource_id(action.depthOut),
            "resource_name": _resource_name(ctx, action.depthOut),
        },
        "parent_event_id": int(action.parent.eventId) if action.parent is not None else None,
        "previous_event_id": int(action.previous.eventId) if action.previous is not None else None,
        "next_event_id": int(action.next.eventId) if action.next is not None else None,
        "events": [_serialize_event(api_event) for api_event in action.events],
        "children": children_payload,
    }


def _serialize_action_list_item(action, structured_file, depth, max_depth, name_filter_lower, budget):
    if budget["remaining"] <= 0:
        budget["truncated"] = True
        return None

    budget["remaining"] -= 1
    budget["returned"] += 1

    name = action.GetName(structured_file) or action.customName or "Event {}".format(action.eventId)
    children_payload = []

    if max_depth is None or depth < max_depth:
        for child in action.children:
            child_payload = _serialize_action_list_item(
                child, structured_file, depth + 1, max_depth, name_filter_lower, budget
            )
            if child_payload is not None:
                children_payload.append(child_payload)

    if name_filter_lower and name_filter_lower not in name.lower() and not children_payload:
        budget["remaining"] += 1
        budget["returned"] -= 1
        return None

    return {
        "event_id": int(action.eventId),
        "action_id": int(action.actionId),
        "name": name,
        "flags": _action_flags(action),
        "child_count": len(action.children),
        "children": children_payload,
    }


def _count_actions(actions):
    counts = {
        "total_actions": 0,
        "draw_calls": 0,
        "dispatches": 0,
        "copies": 0,
        "clears": 0,
    }

    for action in actions:
        counts["total_actions"] += 1
        flags = _action_flags(action)
        if "draw" in flags:
            counts["draw_calls"] += 1
        if "dispatch" in flags:
            counts["dispatches"] += 1
        if "copy" in flags:
            counts["copies"] += 1
        if "clear" in flags:
            counts["clears"] += 1

        child_counts = _count_actions(action.children)
        for key in counts:
            counts[key] += child_counts[key]

    return counts


def _serialize_bound_vbuffer(ctx, vb):
    return {
        "resource_id": _resource_id(vb.resourceId),
        "resource_name": _resource_name(ctx, vb.resourceId),
        "byte_offset": int(vb.byteOffset),
        "byte_stride": int(vb.byteStride),
        "byte_size": int(vb.byteSize),
    }


def _serialize_descriptor(ctx, descriptor):
    return {
        "type": _enum_name(descriptor.type),
        "resource_id": _resource_id(descriptor.resource),
        "resource_name": _resource_name(ctx, descriptor.resource),
        "secondary_resource_id": _resource_id(descriptor.secondary),
        "secondary_resource_name": _resource_name(ctx, descriptor.secondary),
        "view_id": _resource_id(descriptor.view),
        "view_name": _resource_name(ctx, descriptor.view),
        "byte_offset": int(descriptor.byteOffset),
        "byte_size": int(descriptor.byteSize),
        "element_byte_size": int(descriptor.elementByteSize),
        "first_mip": int(descriptor.firstMip),
        "num_mips": int(descriptor.numMips),
        "first_slice": int(descriptor.firstSlice),
        "num_slices": int(descriptor.numSlices),
        "format": _resource_format(descriptor.format),
    }


def _serialize_descriptor_access(value):
    return {
        "stage": _enum_name(value.stage),
        "type": _enum_name(value.type),
        "index": int(value.index),
        "array_element": int(value.arrayElement),
        "descriptor_store_id": _resource_id(value.descriptorStore),
        "byte_offset": int(value.byteOffset),
        "byte_size": int(value.byteSize),
        "statically_unused": bool(value.staticallyUnused),
    }


def _serialize_used_descriptor(ctx, used):
    return {
        "access": _serialize_descriptor_access(used.access),
        "descriptor": _serialize_descriptor(ctx, used.descriptor),
    }


def _serialize_vertex_input(attribute):
    return {
        "name": str(attribute.name),
        "vertex_buffer": int(attribute.vertexBuffer),
        "byte_offset": int(attribute.byteOffset),
        "per_instance": bool(attribute.perInstance),
        "instance_rate": int(attribute.instanceRate),
        "format": _resource_format(attribute.format),
        "generic_enabled": bool(attribute.genericEnabled),
        "used": bool(attribute.used),
    }


def _shader_stage_values():
    stage_names = [
        "Vertex",
        "Hull",
        "Domain",
        "Geometry",
        "Pixel",
        "Compute",
        "Task",
        "Mesh",
        "RayGen",
        "Intersection",
        "AnyHit",
        "ClosestHit",
        "Miss",
        "Callable",
    ]
    values = []
    for name in stage_names:
        if hasattr(rd.ShaderStage, name):
            values.append(getattr(rd.ShaderStage, name))
    return values


def _serialize_shader_stage(ctx, state, stage):
    shader_id = state.GetShader(stage)
    if _resource_id(shader_id) == "":
        return None

    reflection = state.GetShaderReflection(stage)
    payload = {
        "stage": _enum_name(stage),
        "shader_id": _resource_id(shader_id),
        "shader_name": _resource_name(ctx, shader_id),
        "entry_point": str(state.GetShaderEntryPoint(stage) or ""),
        "read_only_resources": [],
        "read_write_resources": [],
        "samplers": [],
        "constant_blocks": [],
    }

    if reflection is not None:
        payload["reflection"] = {
            "resource_id": _resource_id(reflection.resourceId),
            "entry_point": str(reflection.entryPoint or ""),
            "encoding": _enum_name(reflection.encoding),
            "input_signature_count": len(reflection.inputSignature),
            "output_signature_count": len(reflection.outputSignature),
            "constant_block_count": len(reflection.constantBlocks),
        }

    try:
        payload["read_only_resources"] = [_serialize_used_descriptor(ctx, item) for item in state.GetReadOnlyResources(stage, True)]
        payload["read_write_resources"] = [_serialize_used_descriptor(ctx, item) for item in state.GetReadWriteResources(stage, True)]
        payload["samplers"] = [_serialize_used_descriptor(ctx, item) for item in state.GetSamplers(stage, True)]
        payload["constant_blocks"] = [_serialize_used_descriptor(ctx, item) for item in state.GetConstantBlocks(stage, True)]
    except Exception:
        pass

    return payload


def _serialize_texture(ctx, texture):
    return {
        "kind": "texture",
        "resource_id": _resource_id(texture.resourceId),
        "name": _resource_name(ctx, texture.resourceId),
        "format": _resource_format(texture.format),
        "dimension": _enum_name(texture.dimension),
        "texture_type": _enum_name(texture.type),
        "width": int(texture.width),
        "height": int(texture.height),
        "depth": int(texture.depth),
        "mip_levels": int(texture.mips),
        "array_size": int(texture.arraysize),
        "sample_count": int(texture.msSamp),
        "byte_size": int(texture.byteSize),
        "creation_flags": _enum_name(texture.creationFlags),
    }


def _serialize_buffer(ctx, buffer_desc):
    return {
        "kind": "buffer",
        "resource_id": _resource_id(buffer_desc.resourceId),
        "name": _resource_name(ctx, buffer_desc.resourceId),
        "byte_size": int(buffer_desc.length),
        "gpu_address": int(buffer_desc.gpuAddress),
        "creation_flags": _enum_name(buffer_desc.creationFlags),
    }


class BridgeClient(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.mqt = ctx.Extensions().GetMiniQtHelper()
        self.sock = None
        self.stop_event = threading.Event()
        self.thread = None
        self.analysis_cache = _frame_analysis.AnalysisCache()

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
            payload["value"] = _frame_analysis.build_frame_analysis(
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
        return _frame_analysis.build_action_list_result(
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
        return _frame_analysis.list_passes(
            analysis,
            cursor=cursor,
            limit=limit,
            category_filter=category_filter,
            name_filter=name_filter,
        )

    def _get_pass_details(self, pass_id):
        analysis = self._ensure_frame_analysis()
        details = _frame_analysis.get_pass_details(analysis, pass_id)
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

    def _get_capture_summary_legacy(self):
        self._ensure_capture_loaded()
        summary = {
            "capture": self._capture_status(),
            "api": "Unknown",
            "frame": {},
            "statistics": {},
            "resource_counts": {
                "textures": len(self.ctx.GetTextures()),
                "buffers": len(self.ctx.GetBuffers()),
            },
        }

        def callback(controller):
            frame = controller.GetFrameInfo()
            actions = controller.GetRootActions()
            summary["api"] = _api_name(controller)
            summary["frame"] = {
                "frame_number": int(frame.frameNumber),
                "capture_time": int(frame.captureTime),
                "compressed_file_size": int(frame.compressedFileSize),
                "uncompressed_file_size": int(frame.uncompressedFileSize),
                "persistent_size": int(frame.persistentSize),
                "init_data_size": int(frame.initDataSize),
                "debug_message_count": len(frame.debugMessages),
            }
            summary["statistics"] = _count_actions(actions)

        self.ctx.Replay().BlockInvoke(callback)
        return summary

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
