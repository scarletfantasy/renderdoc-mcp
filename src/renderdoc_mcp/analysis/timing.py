try:
    from .models import (
        DEFAULT_PASS_PAGE_LIMIT,
        DEFAULT_TIMING_EVENT_PAGE_LIMIT,
        MAX_TIMING_EVENT_PAGE_LIMIT,
        PageInfo,
        TimingInfo,
        with_meta,
    )
    from .pass_classification import (
        copy_pass_entry,
        get_pass_summary,
        index_action_nodes,
        pass_list_entry,
        pass_summary,
    )
except Exception:
    from models import (
        DEFAULT_PASS_PAGE_LIMIT,
        DEFAULT_TIMING_EVENT_PAGE_LIMIT,
        MAX_TIMING_EVENT_PAGE_LIMIT,
        PageInfo,
        TimingInfo,
        with_meta,
    )
    from pass_classification import (
        copy_pass_entry,
        get_pass_summary,
        index_action_nodes,
        pass_list_entry,
        pass_summary,
    )


def build_analysis_result(
    analysis_cache,
    include_timing_summary=False,
    timing_payload=None,
):
    result = {
        "capture": dict(analysis_cache["capture"]),
        "api": analysis_cache["api"],
        "frame": dict(analysis_cache["frame"]),
        "statistics": dict(analysis_cache["statistics"]),
        "resource_counts": dict(analysis_cache["resource_counts"]),
        "pass_count": len(analysis_cache["passes"]),
        "passes": [pass_summary(item) for item in analysis_cache["passes"]],
        "top_draw_passes": [copy_pass_entry(item) for item in analysis_cache["analysis"]["top_draw_passes"]],
        "top_compute_passes": [copy_pass_entry(item) for item in analysis_cache["analysis"]["top_compute_passes"]],
        "tail_chain": [copy_pass_entry(item) for item in analysis_cache["analysis"]["tail_chain"]],
    }

    timing_info = timing_info_from_payload(None)
    if include_timing_summary:
        normalized_timing = normalize_timing_payload(timing_payload)
        timing_info = timing_info_from_payload(normalized_timing)
        result["passes"] = timed_pass_summaries(analysis_cache["passes"], normalized_timing)

    return with_meta(
        result,
        warnings=list(analysis_cache["analysis"]["warnings"]),
        timing=timing_info if include_timing_summary else None,
    )


def list_passes(
    analysis_cache,
    parent_pass_id=None,
    cursor=None,
    limit=None,
    category_filter=None,
    name_filter=None,
    sort_by="event_order",
    threshold_ms=None,
    timing_payload=None,
):
    parent_key = str(parent_pass_id or "")
    pass_ids = list(analysis_cache.get("pass_children_index", {}).get(parent_key, []))
    pass_index = analysis_cache.get("pass_index", {})
    passes = [pass_index[pass_id] for pass_id in pass_ids if pass_id in pass_index]
    name_filter_lower = lower(name_filter)
    filtered_passes = []

    for pass_payload in passes:
        if category_filter and pass_payload["category"] != category_filter:
            continue
        if name_filter_lower and name_filter_lower not in pass_payload["name"].lower():
            continue
        filtered_passes.append(pass_payload)

    warnings = []
    effective_sort_by = sort_by
    filtered = []
    timing_info = None

    if sort_by == "gpu_time":
        normalized_timing = normalize_timing_payload(timing_payload)
        timing_info = timing_info_from_payload(normalized_timing)
        filtered = timed_pass_summaries(filtered_passes, normalized_timing)
        if timing_info.timing_available:
            if threshold_ms is not None:
                filtered = [item for item in filtered if item["gpu_time_ms"] >= float(threshold_ms)]
            filtered = sorted(
                filtered,
                key=lambda item: (-item["gpu_time_ms"], item["event_range"]["start_event_id"]),
            )
        else:
            effective_sort_by = "event_order"
            warnings.append("GPU timing is unavailable, so sort_by='gpu_time' fell back to event_order.")
            if threshold_ms is not None:
                warnings.append("threshold_ms was ignored because GPU timing is unavailable.")
    else:
        filtered = [pass_list_entry(pass_payload) for pass_payload in filtered_passes]
        if sort_by == "draw_calls":
            filtered = sorted(
                filtered,
                key=lambda item: (
                    -item["stats"]["draw_calls"],
                    -item["stats"]["total_actions"],
                    item["event_range"]["start_event_id"],
                ),
            )
        elif sort_by == "dispatches":
            filtered = sorted(
                filtered,
                key=lambda item: (
                    -item["stats"]["dispatches"],
                    -item["stats"]["total_actions"],
                    item["event_range"]["start_event_id"],
                ),
            )
        elif sort_by == "name":
            filtered = sorted(
                filtered,
                key=lambda item: (item["name"].lower(), item["event_range"]["start_event_id"]),
            )

    page_limit = int(limit if limit is not None else DEFAULT_PASS_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = filtered[offset : offset + page_limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(filtered)

    return with_meta(
        {
            "parent_pass_id": parent_key,
            "passes": page,
            "sort_by": sort_by or "event_order",
            "effective_sort_by": effective_sort_by,
            "category_filter": category_filter or "",
            "name_filter": name_filter or "",
            "threshold_ms": float(threshold_ms) if sort_by == "gpu_time" and threshold_ms is not None else None,
        },
        warnings=warnings,
        page=PageInfo(
            cursor=str(offset),
            next_cursor=str(next_offset) if has_more else "",
            limit=page_limit,
            returned_count=len(page),
            total_count=len(pass_ids),
            matched_count=len(filtered),
            has_more=has_more,
        ),
        timing=timing_info if sort_by == "gpu_time" else None,
    )


def list_timing_events(
    analysis_cache,
    pass_id,
    timing_payload,
    cursor=None,
    limit=None,
    sort_by="event_order",
):
    pass_payload = analysis_cache["pass_index"].get(pass_id)
    if pass_payload is None:
        return None

    normalized_timing = normalize_timing_payload(timing_payload)
    timing_info = timing_info_from_payload(normalized_timing)
    result = {
        "pass": pass_list_entry(pass_payload),
        "basis": "gpu_timing" if timing_info.timing_available else "unavailable",
        "sort_by": sort_by or "event_order",
        "effective_sort_by": sort_by or "event_order",
        "total_gpu_time_ms": None,
        "timed_event_count": 0,
        "events": [],
    }

    if not timing_info.timing_available:
        result["effective_sort_by"] = "event_order"
        return with_meta(result, timing=timing_info)

    action_index = analysis_cache.get("action_index")
    if action_index is None:
        action_index = {}
        index_action_nodes(analysis_cache["action_tree"], action_index)
    start_event_id = int(pass_payload["event_range"]["start_event_id"])
    end_event_id = int(pass_payload["event_range"]["end_event_id"])
    events = []
    total_gpu_time_ms = 0.0

    for item in normalized_timing.get("rows", []):
        event_id = int(item["event_id"])
        if event_id < start_event_id or event_id > end_event_id:
            continue
        event_entry = timed_event_entry(item, action_index.get(event_id))
        events.append(event_entry)
        total_gpu_time_ms += event_entry["gpu_time_ms"]

    if sort_by == "gpu_time":
        events = sorted(events, key=lambda item: (-item["gpu_time_ms"], item["event_id"]))
    else:
        result["effective_sort_by"] = "event_order"
        events = sorted(events, key=lambda item: (item["event_id"], item["name"]))

    page_limit = int(limit if limit is not None else DEFAULT_TIMING_EVENT_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = events[offset : offset + page_limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(events)

    result["events"] = page
    result["timed_event_count"] = len(events)
    result["total_gpu_time_ms"] = round(total_gpu_time_ms, 6)
    return with_meta(
        result,
        page=PageInfo(
            cursor=str(offset),
            next_cursor=str(next_offset) if has_more else "",
            limit=page_limit,
            returned_count=len(page),
            total_count=len(events),
            matched_count=len(events),
            has_more=has_more,
        ),
        timing=timing_info,
    )


def build_timing_result(
    analysis_cache,
    pass_id,
    timing_payload,
):
    pass_payload = analysis_cache["pass_index"].get(pass_id)
    if pass_payload is None:
        return None

    normalized_timing = normalize_timing_payload(timing_payload)
    timing_info = timing_info_from_payload(normalized_timing)
    result = {
        "pass": pass_summary(pass_payload),
        "basis": "gpu_timing" if timing_info.timing_available else "unavailable",
        "total_gpu_time_ms": None,
        "timed_event_count": 0,
        "events": [],
    }

    if not timing_info.timing_available:
        return with_meta(result, timing=timing_info)

    action_index = {}
    index_action_nodes(analysis_cache["action_tree"], action_index)
    start_event_id = int(pass_payload["event_range"]["start_event_id"])
    end_event_id = int(pass_payload["event_range"]["end_event_id"])
    events = []
    total_gpu_time_ms = 0.0

    for item in normalized_timing.get("rows", []):
        event_id = int(item["event_id"])
        if event_id < start_event_id or event_id > end_event_id:
            continue
        event_entry = timed_event_entry(item, action_index.get(event_id))
        events.append(event_entry)
        total_gpu_time_ms += event_entry["gpu_time_ms"]

    events = sorted(events, key=lambda item: (item["event_id"], item["name"]))
    result["events"] = events
    result["timed_event_count"] = len(events)
    result["total_gpu_time_ms"] = round(total_gpu_time_ms, 6)
    return with_meta(result, timing=timing_info)


def normalize_timing_payload(timing_payload=None):
    payload = dict(timing_payload or {})
    payload.setdefault("timing_available", False)
    payload.setdefault("counter_name", "EventGPUDuration")
    payload.setdefault("rows", [])
    return payload


def timing_info_from_payload(timing_payload=None):
    payload = normalize_timing_payload(timing_payload)
    if payload.get("timing_available"):
        return TimingInfo(True, counter_name=payload.get("counter_name", "EventGPUDuration"))
    return TimingInfo(
        False,
        counter_name=payload.get("counter_name", "EventGPUDuration"),
        timing_unavailable_reason=payload.get(
            "reason",
            "GPU duration counters are unavailable for this capture or replay device.",
        ),
    )


def timed_pass_summaries(pass_payloads, timing_payload):
    rows = list(timing_payload.get("rows", []))
    available = bool(timing_payload.get("timing_available"))
    payload = []

    for pass_payload in pass_payloads:
        summary = pass_list_entry(pass_payload)
        if not available:
            summary["gpu_time_ms"] = None
            summary["timed_event_count"] = 0
            payload.append(summary)
            continue

        start_event_id = int(pass_payload["event_range"]["start_event_id"])
        end_event_id = int(pass_payload["event_range"]["end_event_id"])
        matched_rows = [
            item
            for item in rows
            if start_event_id <= int(item["event_id"]) <= end_event_id
        ]
        summary["gpu_time_ms"] = round(sum(float(item["gpu_time_ms"]) for item in matched_rows), 6)
        summary["timed_event_count"] = len(matched_rows)
        payload.append(summary)

    return payload


def timed_event_entry(item, node):
    return {
        "event_id": int(item["event_id"]),
        "name": node["name"] if node is not None else "Event {0}".format(int(item["event_id"])),
        "flags": list(node.get("flags", [])) if node is not None else [],
        "parent_event_id": node.get("parent_event_id") if node is not None else None,
        "depth": int(node.get("_analysis", {}).get("depth", node.get("depth", 0))) if node is not None else 0,
        "metric_name": "gpu_time_ms",
        "metric_value": round(float(item["gpu_time_ms"]), 6),
        "gpu_time_ms": round(float(item["gpu_time_ms"]), 6),
    }


def lower(value):
    if value is None:
        return None
    return str(value).strip().lower()
