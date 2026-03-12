try:
    import renderdoc as rd
except Exception:
    rd = None


def _enum_name(value):
    if value is None:
        return ""

    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name

    repr_text = repr(value)
    if repr_text.startswith("<") and repr_text.endswith(">") and ":" in repr_text:
        enum_path = repr_text[1:-1].split(":", 1)[0].strip()
        if "." in enum_path:
            candidate = enum_path.split(".", 1)[1].strip()
        else:
            candidate = enum_path
        if candidate:
            return candidate

    text = str(value)
    if "." in text:
        return text.split(".")[-1]
    return text


def _resource_id(value):
    if value is None:
        return ""
    try:
        if rd is not None and value == rd.ResourceId.Null():
            return ""
    except Exception:
        pass
    return str(value)


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


def _safe_list(value):
    try:
        return list(value or [])
    except Exception:
        return []


def _resource_ref(ctx, resource_id):
    return {
        "resource_id": _resource_id(resource_id),
        "resource_name": _resource_name(ctx, resource_id),
    }


def _action_flags(action):
    if rd is None:
        return []

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
    try:
        return _enum_name(controller.GetAPIProperties().pipelineType)
    except Exception:
        return "Unknown"


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
        "resource_id": _resource_id(getattr(vb, "resourceId", None)),
        "resource_name": _resource_name(ctx, getattr(vb, "resourceId", None)),
        "byte_offset": int(getattr(vb, "byteOffset", 0)),
        "byte_stride": int(getattr(vb, "byteStride", 0)),
        "byte_size": int(getattr(vb, "byteSize", 0)),
    }


def _serialize_descriptor(ctx, descriptor):
    return {
        "type": _enum_name(getattr(descriptor, "type", "")),
        "resource_id": _resource_id(getattr(descriptor, "resource", None)),
        "resource_name": _resource_name(ctx, getattr(descriptor, "resource", None)),
        "secondary_resource_id": _resource_id(getattr(descriptor, "secondary", None)),
        "secondary_resource_name": _resource_name(ctx, getattr(descriptor, "secondary", None)),
        "view_id": _resource_id(getattr(descriptor, "view", None)),
        "view_name": _resource_name(ctx, getattr(descriptor, "view", None)),
        "byte_offset": int(getattr(descriptor, "byteOffset", 0)),
        "byte_size": int(getattr(descriptor, "byteSize", 0)),
        "element_byte_size": int(getattr(descriptor, "elementByteSize", 0)),
        "first_mip": int(getattr(descriptor, "firstMip", 0)),
        "num_mips": int(getattr(descriptor, "numMips", 0)),
        "first_slice": int(getattr(descriptor, "firstSlice", 0)),
        "num_slices": int(getattr(descriptor, "numSlices", 0)),
        "format": _resource_format(getattr(descriptor, "format", None)),
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


def _serialize_sampler_descriptor(value):
    return {
        "filter": _enum_name(getattr(value, "filter", "")),
        "address_u": _enum_name(getattr(value, "addressU", "")),
        "address_v": _enum_name(getattr(value, "addressV", "")),
        "address_w": _enum_name(getattr(value, "addressW", "")),
        "compare_function": _enum_name(getattr(value, "compareFunction", "")),
        "max_anisotropy": int(getattr(value, "maxAnisotropy", 0)),
        "mip_lod_bias": float(getattr(value, "mipLODBias", 0.0)),
        "min_lod": float(getattr(value, "minLOD", 0.0)),
        "max_lod": float(getattr(value, "maxLOD", 0.0)),
        "border_color": _float_vector(getattr(value, "borderColor", None)),
        "unnormalized": bool(getattr(value, "unnormalized", False)),
    }


def _serialize_used_descriptor(ctx, used):
    return {
        "access": _serialize_descriptor_access(used.access),
        "descriptor": _serialize_descriptor(ctx, used.descriptor),
    }


def _serialize_vertex_input(attribute):
    return {
        "name": str(getattr(attribute, "name", "")),
        "vertex_buffer": int(getattr(attribute, "vertexBuffer", 0)),
        "byte_offset": int(getattr(attribute, "byteOffset", 0)),
        "per_instance": bool(getattr(attribute, "perInstance", False)),
        "instance_rate": int(getattr(attribute, "instanceRate", 0)),
        "format": _resource_format(getattr(attribute, "format", None)),
        "generic_enabled": bool(getattr(attribute, "genericEnabled", False)),
        "used": bool(getattr(attribute, "used", False)),
    }


def _descriptor_has_contents(descriptor):
    return bool(
        _resource_id(getattr(descriptor, "resource", None))
        or _resource_id(getattr(descriptor, "secondary", None))
        or _resource_id(getattr(descriptor, "view", None))
        or int(getattr(descriptor, "byteSize", 0)) > 0
    )


def _serialize_d3d12_root_table_range(value):
    return {
        "category": _enum_name(getattr(value, "category", "")),
        "space": int(getattr(value, "space", 0)),
        "base_register": int(getattr(value, "baseRegister", 0)),
        "count": int(getattr(value, "count", 0)),
        "table_byte_offset": int(getattr(value, "tableByteOffset", 0)),
        "appended": bool(getattr(value, "appended", False)),
    }


def _serialize_d3d12_root_param(ctx, index, value):
    table_ranges = [_serialize_d3d12_root_table_range(item) for item in _safe_list(getattr(value, "tableRanges", []))]
    descriptor = getattr(value, "descriptor", None)
    constants = bytes(getattr(value, "constants", b"") or b"")
    heap = getattr(value, "heap", None)
    heap_resource_id = _resource_id(heap)

    kind = "unknown"
    if table_ranges or heap_resource_id:
        kind = "descriptor_table"
    elif len(constants) > 0:
        kind = "constants"
    elif descriptor is not None and _descriptor_has_contents(descriptor):
        kind = "descriptor"

    payload = {
        "index": int(index),
        "kind": kind,
        "visibility": _enum_name(getattr(value, "visibility", "")),
        "space": int(getattr(value, "space", 0)),
        "register": int(getattr(value, "reg", 0)),
        "constants_byte_count": len(constants),
        "heap": _resource_ref(ctx, heap),
        "heap_byte_offset": int(getattr(value, "heapByteOffset", 0)),
        "table_range_count": len(table_ranges),
        "table_ranges": table_ranges,
    }
    if descriptor is not None and _descriptor_has_contents(descriptor):
        payload["descriptor"] = _serialize_descriptor(ctx, descriptor)
    return payload


def _serialize_d3d12_static_sampler(index, value):
    return {
        "index": int(index),
        "visibility": _enum_name(getattr(value, "visibility", "")),
        "space": int(getattr(value, "space", 0)),
        "register": int(getattr(value, "reg", 0)),
        "descriptor": _serialize_sampler_descriptor(getattr(value, "descriptor", None)),
    }


def _serialize_d3d12_root_signature(ctx, value):
    parameters = [_serialize_d3d12_root_param(ctx, index, item) for index, item in enumerate(_safe_list(getattr(value, "parameters", [])))]
    static_samplers = [
        _serialize_d3d12_static_sampler(index, item)
        for index, item in enumerate(_safe_list(getattr(value, "staticSamplers", [])))
    ]
    return {
        "resource_id": _resource_id(getattr(value, "resourceId", None)),
        "parameter_count": len(parameters),
        "parameters": parameters,
        "static_sampler_count": len(static_samplers),
        "static_samplers": static_samplers,
    }


def _serialize_vk_dynamic_offset(value):
    return {
        "descriptor_byte_offset": int(getattr(value, "descriptorByteOffset", 0)),
        "dynamic_buffer_byte_offset": int(getattr(value, "dynamicBufferByteOffset", 0)),
    }


def _serialize_vk_descriptor_set(value):
    dynamic_offsets = [_serialize_vk_dynamic_offset(item) for item in _safe_list(getattr(value, "dynamicOffsets", []))]
    return {
        "layout_resource_id": _resource_id(getattr(value, "layoutResourceId", None)),
        "descriptor_set_resource_id": _resource_id(getattr(value, "descriptorSetResourceId", None)),
        "push_descriptor": bool(getattr(value, "pushDescriptor", False)),
        "dynamic_offset_count": len(dynamic_offsets),
        "dynamic_offsets": dynamic_offsets,
        "descriptor_buffer_index": int(getattr(value, "descriptorBufferIndex", -1)),
        "descriptor_buffer_byte_offset": int(getattr(value, "descriptorBufferByteOffset", 0)),
        "descriptor_buffer_embedded_samplers": bool(getattr(value, "descriptorBufferEmbeddedSamplers", False)),
    }


def _serialize_vk_descriptor_buffer(ctx, value):
    return {
        "buffer": _resource_ref(ctx, getattr(value, "buffer", None)),
        "offset": int(getattr(value, "offset", 0)),
        "push_descriptor": bool(getattr(value, "pushDescriptor", False)),
        "push_buffer": _resource_ref(ctx, getattr(value, "pushBuffer", None)),
        "resource_buffer": bool(getattr(value, "resourceBuffer", False)),
        "sampler_buffer": bool(getattr(value, "samplerBuffer", False)),
    }


def _serialize_vk_pipeline(ctx, value):
    return {
        "pipeline_resource_id": _resource_id(getattr(value, "pipelineResourceId", None)),
        "pipeline_compute_layout_resource_id": _resource_id(getattr(value, "pipelineComputeLayoutResourceId", None)),
        "pipeline_pre_rast_layout_resource_id": _resource_id(getattr(value, "pipelinePreRastLayoutResourceId", None)),
        "pipeline_fragment_layout_resource_id": _resource_id(getattr(value, "pipelineFragmentLayoutResourceId", None)),
        "flags": int(getattr(value, "flags", 0)),
    }


def _serialize_vk_renderpass(value):
    return {
        "resource_id": _resource_id(getattr(value, "resourceId", None)),
        "dynamic": bool(getattr(value, "dynamic", False)),
        "suspended": bool(getattr(value, "suspended", False)),
        "feedback_loop": bool(getattr(value, "feedbackLoop", False)),
        "subpass": int(getattr(value, "subpass", 0)),
        "input_attachments": [int(item) for item in _safe_list(getattr(value, "inputAttachments", []))],
        "color_attachments": [int(item) for item in _safe_list(getattr(value, "colorAttachments", []))],
        "resolve_attachments": [int(item) for item in _safe_list(getattr(value, "resolveAttachments", []))],
        "depthstencil_attachment": int(getattr(value, "depthstencilAttachment", -1)),
        "depthstencil_resolve_attachment": int(getattr(value, "depthstencilResolveAttachment", -1)),
        "fragment_density_attachment": int(getattr(value, "fragmentDensityAttachment", -1)),
        "shading_rate_attachment": int(getattr(value, "shadingRateAttachment", -1)),
        "multiviews": [int(item) for item in _safe_list(getattr(value, "multiviews", []))],
        "tile_only_msaa_sample_count": int(getattr(value, "tileOnlyMSAASampleCount", 0)),
        "color_attachment_locations": [int(item) for item in _safe_list(getattr(value, "colorAttachmentLocations", []))],
        "color_attachment_input_indices": [int(item) for item in _safe_list(getattr(value, "colorAttachmentInputIndices", []))],
        "is_depth_input_attachment_index_implicit": bool(getattr(value, "isDepthInputAttachmentIndexImplicit", True)),
        "is_stencil_input_attachment_index_implicit": bool(getattr(value, "isStencilInputAttachmentIndexImplicit", True)),
        "depth_input_attachment_index": int(getattr(value, "depthInputAttachmentIndex", 0)),
        "stencil_input_attachment_index": int(getattr(value, "stencilInputAttachmentIndex", 0)),
    }


def _serialize_vk_framebuffer(ctx, value):
    attachments = [_serialize_descriptor(ctx, item) for item in _safe_list(getattr(value, "attachments", []))]
    return {
        "resource_id": _resource_id(getattr(value, "resourceId", None)),
        "attachment_count": len(attachments),
        "attachments": attachments,
        "width": int(getattr(value, "width", 0)),
        "height": int(getattr(value, "height", 0)),
        "layers": int(getattr(value, "layers", 0)),
    }


def _serialize_vk_render_area(value):
    return {
        "x": int(getattr(value, "x", 0)),
        "y": int(getattr(value, "y", 0)),
        "width": int(getattr(value, "width", 0)),
        "height": int(getattr(value, "height", 0)),
    }


def _serialize_vk_current_pass(ctx, value):
    return {
        "renderpass": _serialize_vk_renderpass(getattr(value, "renderpass", None)),
        "framebuffer": _serialize_vk_framebuffer(ctx, getattr(value, "framebuffer", None)),
        "render_area": _serialize_vk_render_area(getattr(value, "renderArea", None)),
        "color_feedback_allowed": bool(getattr(value, "colorFeedbackAllowed", False)),
        "depth_feedback_allowed": bool(getattr(value, "depthFeedbackAllowed", False)),
        "stencil_feedback_allowed": bool(getattr(value, "stencilFeedbackAllowed", False)),
    }


def _serialize_d3d12_pipeline_state(ctx, value):
    return {
        "api": "D3D12",
        "available": True,
        "pipeline_resource_id": _resource_id(getattr(value, "pipelineResourceId", None)),
        "descriptor_heaps": [_resource_ref(ctx, item) for item in _safe_list(getattr(value, "descriptorHeaps", []))],
        "root_signature": _serialize_d3d12_root_signature(ctx, getattr(value, "rootSignature", None)),
    }


def _serialize_vulkan_pipeline_state(ctx, value):
    pipeline = getattr(value, "pipeline", None)
    return {
        "api": "Vulkan",
        "available": True,
        "pipeline": _serialize_vk_pipeline(ctx, pipeline),
        "descriptor_sets": [_serialize_vk_descriptor_set(item) for item in _safe_list(getattr(pipeline, "descriptorSets", []))],
        "descriptor_buffers": [
            _serialize_vk_descriptor_buffer(ctx, item)
            for item in _safe_list(getattr(pipeline, "descriptorBuffers", []))
        ],
        "current_pass": _serialize_vk_current_pass(ctx, getattr(value, "currentPass", None)),
    }


def _shader_stage_values():
    if rd is None:
        return []

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
    shader_id = _call_method_variants(state, "GetShader", [(stage,)], default=None)
    if _resource_id(shader_id) == "":
        return None

    reflection = _call_method_variants(state, "GetShaderReflection", [(stage,)], default=None)
    payload = {
        "stage": _enum_name(stage),
        "shader_id": _resource_id(shader_id),
        "shader_name": _resource_name(ctx, shader_id),
        "entry_point": str(_call_method_variants(state, "GetShaderEntryPoint", [(stage,)], default="") or ""),
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

    payload["read_only_resources"] = [
        _serialize_used_descriptor(ctx, item)
        for item in _safe_list(_call_method_variants(state, "GetReadOnlyResources", [(stage, True), (stage,)], default=[]))
    ]
    payload["read_write_resources"] = [
        _serialize_used_descriptor(ctx, item)
        for item in _safe_list(_call_method_variants(state, "GetReadWriteResources", [(stage, True), (stage,)], default=[]))
    ]
    payload["samplers"] = [
        _serialize_used_descriptor(ctx, item)
        for item in _safe_list(_call_method_variants(state, "GetSamplers", [(stage, True), (stage,)], default=[]))
    ]
    payload["constant_blocks"] = [
        _serialize_used_descriptor(ctx, item)
        for item in _safe_list(_call_method_variants(state, "GetConstantBlocks", [(stage, True), (stage,)], default=[]))
    ]

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
