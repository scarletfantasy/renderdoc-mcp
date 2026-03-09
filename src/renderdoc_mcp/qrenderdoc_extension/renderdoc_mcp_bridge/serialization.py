try:
    import renderdoc as rd
except Exception:
    rd = None


def _enum_name(value):
    return str(value).split(".")[-1]


def _resource_id(value):
    try:
        if rd is not None and value == rd.ResourceId.Null():
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
