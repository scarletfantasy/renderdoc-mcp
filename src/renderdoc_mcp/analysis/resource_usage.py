from .models import DEFAULT_ACTION_PAGE_LIMIT, PageInfo, with_meta


RESOURCE_USAGE_KINDS = (
    "color_output",
    "depth_output",
    "copy_source",
    "copy_destination",
    "resolve_source",
    "resolve_destination",
)


def build_resource_usage_index(nodes):
    indexed = {}
    for node in nodes:
        _index_resource_usage_node(node, indexed)

    payload = {}
    for resource_id, rows_by_event in indexed.items():
        payload[str(resource_id)] = [
            _finalize_resource_usage_row(rows_by_event[event_id])
            for event_id in sorted(rows_by_event)
        ]
    return payload


def build_resource_usage_overview(analysis_cache, resource_id):
    rows = list(analysis_cache.get("resource_usage_index", {}).get(str(resource_id), []))
    counts_by_kind = {kind: 0 for kind in RESOURCE_USAGE_KINDS}

    for row in rows:
        for usage_kind in row.get("matched_usage_kinds", []):
            if usage_kind in counts_by_kind:
                counts_by_kind[usage_kind] += 1

    return {
        "available": True,
        "supported_scope": "rt_texture_v1",
        "total_matching_events": len(rows),
        "counts_by_kind": counts_by_kind,
        "first_event_id": rows[0]["event_id"] if rows else None,
        "last_event_id": rows[-1]["event_id"] if rows else None,
        "representative_events": [_representative_event(row) for row in rows[:5]],
    }


def list_resource_usages(analysis_cache, resource_id, usage_kind="all", cursor=None, limit=None):
    rows = list(analysis_cache.get("resource_usage_index", {}).get(str(resource_id), []))
    normalized_usage_kind = str(usage_kind or "all")

    if normalized_usage_kind == "all":
        filtered = rows
    else:
        filtered = [
            row
            for row in rows
            if normalized_usage_kind in set(row.get("matched_usage_kinds", []))
        ]

    page_limit = int(limit if limit is not None else DEFAULT_ACTION_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = [_copy_resource_usage_row(row) for row in filtered[offset : offset + page_limit]]
    next_offset = offset + len(page)
    has_more = next_offset < len(filtered)

    return with_meta(
        {
            "resource_id": str(resource_id),
            "usage_kind": normalized_usage_kind,
            "events": page,
        },
        page=PageInfo(
            cursor=str(offset),
            next_cursor=str(next_offset) if has_more else "",
            limit=page_limit,
            returned_count=len(page),
            total_count=len(rows),
            matched_count=len(filtered),
            has_more=has_more,
        ),
    )


def _index_resource_usage_node(node, output):
    for resource_id, binding in _resource_usage_bindings(node):
        rows_by_event = output.setdefault(str(resource_id), {})
        event_id = int(node.get("event_id", 0))
        row = rows_by_event.get(event_id)
        if row is None:
            row = {
                "event_id": event_id,
                "name": node.get("name", "Event {0}".format(event_id)),
                "flags": list(node.get("flags", [])),
                "parent_event_id": node.get("parent_event_id"),
                "matched_usage_kinds": [],
                "bindings": [],
                "_usage_seen": set(),
                "_binding_seen": set(),
            }
            rows_by_event[event_id] = row

        usage_kind = binding["usage_kind"]
        if usage_kind not in row["_usage_seen"]:
            row["matched_usage_kinds"].append(usage_kind)
            row["_usage_seen"].add(usage_kind)

        binding_key = _binding_key(binding)
        if binding_key not in row["_binding_seen"]:
            row["bindings"].append(_copy_binding(binding))
            row["_binding_seen"].add(binding_key)

    for child in node.get("children", []):
        _index_resource_usage_node(child, output)


def _resource_usage_bindings(node):
    bindings = []

    for index, item in enumerate(node.get("outputs", [])):
        resource_id = str((item or {}).get("resource_id", "") or "")
        if resource_id:
            bindings.append(
                (
                    resource_id,
                    {
                        "usage_kind": "color_output",
                        "slot_kind": "color",
                        "slot_index": int(index),
                    },
                )
            )

    depth_output = node.get("depth_output") or {}
    depth_resource_id = str(depth_output.get("resource_id", "") or "")
    if depth_resource_id:
        bindings.append(
            (
                depth_resource_id,
                {
                    "usage_kind": "depth_output",
                    "slot_kind": "depth",
                    "slot_index": -1,
                },
            )
        )

    prefix = "resolve" if "resolve" in set(node.get("flags", [])) else "copy"
    copy_source = node.get("copy_source") or {}
    copy_source_id = str(copy_source.get("resource_id", "") or "")
    if copy_source_id:
        bindings.append(
            (
                copy_source_id,
                {
                    "usage_kind": "{0}_source".format(prefix),
                    "subresource": _copy_subresource(copy_source.get("subresource")),
                },
            )
        )

    copy_destination = node.get("copy_destination") or {}
    copy_destination_id = str(copy_destination.get("resource_id", "") or "")
    if copy_destination_id:
        bindings.append(
            (
                copy_destination_id,
                {
                    "usage_kind": "{0}_destination".format(prefix),
                    "subresource": _copy_subresource(copy_destination.get("subresource")),
                },
            )
        )

    return bindings


def _binding_key(binding):
    subresource = binding.get("subresource") or {}
    return (
        str(binding.get("usage_kind", "")),
        str(binding.get("slot_kind", "")),
        int(binding.get("slot_index", -999999)),
        int(subresource.get("mip", 0)),
        int(subresource.get("slice", 0)),
        int(subresource.get("sample", 0)),
    )


def _finalize_resource_usage_row(row):
    return {
        "event_id": int(row["event_id"]),
        "name": row["name"],
        "flags": list(row.get("flags", [])),
        "parent_event_id": row.get("parent_event_id"),
        "matched_usage_kinds": list(row.get("matched_usage_kinds", [])),
        "bindings": [_copy_binding(binding) for binding in row.get("bindings", [])],
    }


def _copy_resource_usage_row(row):
    return {
        "event_id": int(row["event_id"]),
        "name": row["name"],
        "flags": list(row.get("flags", [])),
        "parent_event_id": row.get("parent_event_id"),
        "matched_usage_kinds": list(row.get("matched_usage_kinds", [])),
        "bindings": [_copy_binding(binding) for binding in row.get("bindings", [])],
    }


def _copy_binding(binding):
    payload = {"usage_kind": str(binding.get("usage_kind", ""))}
    slot_kind = str(binding.get("slot_kind", "") or "")
    if slot_kind:
        payload["slot_kind"] = slot_kind
        payload["slot_index"] = int(binding.get("slot_index", -1))
    if "subresource" in binding and binding.get("subresource") is not None:
        payload["subresource"] = _copy_subresource(binding.get("subresource"))
    return payload


def _copy_subresource(subresource):
    value = dict(subresource or {})
    return {
        "mip": int(value.get("mip", 0)),
        "slice": int(value.get("slice", 0)),
        "sample": int(value.get("sample", 0)),
    }


def _representative_event(row):
    return {
        "event_id": int(row["event_id"]),
        "name": row["name"],
        "flags": list(row.get("flags", [])),
    }
