PASS_CATEGORIES = (
    "setup",
    "copy_resolve",
    "shadow_depth",
    "depth_prepass",
    "geometry",
    "lighting",
    "transparency",
    "post_process",
    "ui_overlay",
    "presentation",
    "compute",
    "unknown",
)
PASS_SORT_OPTIONS = (
    "event_order",
    "gpu_time",
    "draw_calls",
    "dispatches",
    "name",
)

LEGACY_ACTION_LIST_NODE_LIMIT = 500
DEFAULT_ACTION_PAGE_LIMIT = 100
DEFAULT_PASS_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1000
TOP_PASS_RANKING_LIMIT = 5
HOTSPOT_LIMIT = 10

_TAIL_CATEGORIES = set(["setup", "copy_resolve", "ui_overlay", "presentation"])
_GPU_WORK_FLAGS = set(["draw", "dispatch", "copy", "resolve", "clear"])
_MARKER_FLAGS = set(["push_marker", "set_marker"])
_PRESENT_HINTS = ["present", "swapchain", "backbuffer"]
_UI_HINTS = ["hud", "overlay", "imgui", "slate", "canvas", "widget", "debug canvas", "debug ui"]
_POST_PROCESS_HINTS = [
    "post",
    "tonemap",
    "bloom",
    "temporalsuperresolution",
    "temporal super resolution",
    "taa",
    "tsr",
    "fxaa",
    "motionblur",
    "motion blur",
    "depth of field",
    "depthoffield",
    "upscale",
    "outline",
    "composite",
    "color grading",
]
_TRANSPARENCY_HINTS = ["transluc", "transparen", "particle", "afterdof", "separate translucency", "glass"]
_LIGHTING_HINTS = [
    "light",
    "lighting",
    "ambient occlusion",
    "ambientocclusion",
    "gtao",
    "reflection",
    "ssr",
    "irradiance",
    "shadow projection",
    "subsurface",
    "indirect",
    "fog",
    "volumetric",
    "deferred",
]
_SHADOW_HINTS = ["shadow", "csm", "vsm"]
_DEPTH_HINTS = ["prepass", "depth", "z pre", "hzb", "occlusion"]


class AnalysisCache(object):
    def __init__(self):
        self._cache_key = None
        self._value = None

    def clear(self):
        self._cache_key = None
        self._value = None

    def get(self, cache_key):
        if self._cache_key == cache_key:
            return self._value
        return None

    def store(self, cache_key, value):
        self._cache_key = cache_key
        self._value = value
        return value


def build_action_list_result(nodes, total_count, max_depth=None, name_filter=None, cursor=None, limit=None):
    name_filter_lower = _lower(name_filter)
    filtered = _filter_action_tree(nodes, max_depth, name_filter_lower, 0)
    flat = []
    _flatten_action_tree(filtered, flat)

    if cursor is None and limit is None:
        preview_budget = {"remaining": LEGACY_ACTION_LIST_NODE_LIMIT, "returned": 0}
        preview = _take_action_tree_preview(filtered, preview_budget)
        has_more = len(flat) > preview_budget["returned"]
        return {
            "actions": preview,
            "count": int(total_count),
            "matched_count": len(flat),
            "returned_count": preview_budget["returned"],
            "truncated": has_more,
            "limit": LEGACY_ACTION_LIST_NODE_LIMIT,
            "has_more": has_more,
            "next_cursor": str(preview_budget["returned"]) if has_more else "",
            "cursor": "",
            "page_mode": "tree_preview",
        }

    page_limit = int(limit if limit is not None else DEFAULT_ACTION_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = flat[offset : offset + page_limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(flat)
    return {
        "actions": page,
        "count": int(total_count),
        "matched_count": len(flat),
        "returned_count": len(page),
        "truncated": False,
        "limit": page_limit,
        "has_more": has_more,
        "next_cursor": str(next_offset) if has_more else "",
        "cursor": str(offset),
        "page_mode": "flat_preorder",
    }


def build_frame_analysis(nodes, metadata):
    annotated_nodes = []
    for node in nodes:
        annotated_nodes.append(_annotate_action_node(node, 0))

    top_level_passes = []
    pass_index = {}
    for node in annotated_nodes:
        pass_payload = _build_pass_payload(node, 0, True, pass_index)
        if pass_payload is not None:
            top_level_passes.append(pass_payload)

    top_level_summaries = [_pass_summary(pass_payload) for pass_payload in top_level_passes]
    all_passes = _flatten_pass_tree(top_level_passes)
    warnings = _build_analysis_warnings(all_passes)

    draw_rankings = sorted(
        [item for item in all_passes if item["stats"]["draw_calls"] > 0],
        key=lambda item: (-item["stats"]["draw_calls"], -item["stats"]["total_actions"], item["event_range"]["start_event_id"]),
    )[:TOP_PASS_RANKING_LIMIT]
    compute_rankings = sorted(
        [item for item in all_passes if item["stats"]["dispatches"] > 0],
        key=lambda item: (-item["stats"]["dispatches"], -item["stats"]["total_actions"], item["event_range"]["start_event_id"]),
    )[:TOP_PASS_RANKING_LIMIT]

    public_analysis = {
        "capture": metadata["capture"],
        "api": metadata["api"],
        "frame": metadata["frame"],
        "statistics": metadata["statistics"],
        "resource_counts": metadata["resource_counts"],
        "pass_count": len(top_level_summaries),
        "passes": top_level_summaries,
        "top_draw_passes": [_pass_summary(item) for item in draw_rankings],
        "top_compute_passes": [_pass_summary(item) for item in compute_rankings],
        "tail_chain": _build_tail_chain(top_level_summaries),
        "warnings": warnings,
    }

    return {
        "analysis": public_analysis,
        "action_tree": annotated_nodes,
        "passes": top_level_passes,
        "pass_index": pass_index,
        "statistics": metadata["statistics"],
        "resource_counts": metadata["resource_counts"],
        "frame": metadata["frame"],
        "api": metadata["api"],
        "capture": metadata["capture"],
        "total_actions": metadata["statistics"]["total_actions"],
    }


def build_analysis_result(analysis_cache, include_timing_summary=False, timing_payload=None):
    result = {
        "capture": dict(analysis_cache["capture"]),
        "api": analysis_cache["api"],
        "frame": dict(analysis_cache["frame"]),
        "statistics": dict(analysis_cache["statistics"]),
        "resource_counts": dict(analysis_cache["resource_counts"]),
        "pass_count": len(analysis_cache["passes"]),
        "passes": [_pass_summary(item) for item in analysis_cache["passes"]],
        "top_draw_passes": [_copy_pass_entry(item) for item in analysis_cache["analysis"]["top_draw_passes"]],
        "top_compute_passes": [_copy_pass_entry(item) for item in analysis_cache["analysis"]["top_compute_passes"]],
        "tail_chain": [_copy_pass_entry(item) for item in analysis_cache["analysis"]["tail_chain"]],
        "warnings": list(analysis_cache["analysis"]["warnings"]),
    }

    if include_timing_summary:
        normalized_timing = _normalize_timing_payload(timing_payload)
        result.update(_timing_metadata(normalized_timing))
        result["passes"] = _timed_pass_summaries(analysis_cache["passes"], normalized_timing)

    return result


def list_passes(
    analysis_cache,
    cursor=None,
    limit=None,
    category_filter=None,
    name_filter=None,
    sort_by="event_order",
    threshold_ms=None,
    timing_payload=None,
):
    passes = analysis_cache["passes"]
    name_filter_lower = _lower(name_filter)
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
    timing_fields = {}

    if sort_by == "gpu_time":
        normalized_timing = _normalize_timing_payload(timing_payload)
        timing_fields = _timing_metadata(normalized_timing)
        filtered = _timed_pass_summaries(filtered_passes, normalized_timing)
        if timing_fields["timing_available"]:
            if threshold_ms is not None:
                filtered = [item for item in filtered if item["gpu_time_ms"] >= float(threshold_ms)]
            filtered = sorted(
                filtered,
                key=lambda item: (-item["gpu_time_ms"], item["event_range"]["start_event_id"]),
            )
        else:
            effective_sort_by = "event_order"
            warnings.append(
                "GPU timing is unavailable, so sort_by='gpu_time' fell back to event_order."
            )
            if threshold_ms is not None:
                warnings.append("threshold_ms was ignored because GPU timing is unavailable.")
    else:
        filtered = [_pass_summary(pass_payload) for pass_payload in filtered_passes]
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
    result = {
        "passes": page,
        "count": len(passes),
        "matched_count": len(filtered),
        "returned_count": len(page),
        "limit": page_limit,
        "cursor": str(offset),
        "has_more": has_more,
        "next_cursor": str(next_offset) if has_more else "",
        "category_filter": category_filter or "",
        "name_filter": name_filter or "",
        "sort_by": sort_by or "event_order",
        "effective_sort_by": effective_sort_by,
        "threshold_ms": float(threshold_ms) if sort_by == "gpu_time" and threshold_ms is not None else None,
        "warnings": warnings,
    }
    if sort_by == "gpu_time":
        result.update(timing_fields)
    return result


def get_pass_details(analysis_cache, pass_id):
    return analysis_cache["pass_index"].get(pass_id)


def build_timing_result(analysis_cache, pass_id, timing_payload):
    pass_payload = get_pass_details(analysis_cache, pass_id)
    if pass_payload is None:
        return None

    timing_payload = _normalize_timing_payload(timing_payload)
    available = bool(timing_payload.get("timing_available"))
    counter_name = timing_payload.get("counter_name", "EventGPUDuration")
    result = {
        "pass": _pass_summary(pass_payload),
        "timing_available": available,
        "basis": "gpu_timing" if available else "unavailable",
        "counter_name": counter_name,
        "total_gpu_time_ms": None,
        "timed_event_count": 0,
        "events": [],
    }

    if not available:
        result["timing_unavailable_reason"] = timing_payload.get(
            "reason",
            "GPU duration counters are unavailable for this capture or replay device.",
        )
        return result

    action_index = {}
    _index_action_nodes(analysis_cache["action_tree"], action_index)
    start_event_id = int(pass_payload["event_range"]["start_event_id"])
    end_event_id = int(pass_payload["event_range"]["end_event_id"])
    events = []
    total_gpu_time_ms = 0.0

    for item in timing_payload.get("rows", []):
        event_id = int(item["event_id"])
        if event_id < start_event_id or event_id > end_event_id:
            continue
        event_entry = _timed_event_entry(item, action_index.get(event_id))
        events.append(event_entry)
        total_gpu_time_ms += event_entry["gpu_time_ms"]

    events = sorted(events, key=lambda item: (item["event_id"], item["name"]))
    result["events"] = events
    result["timed_event_count"] = len(events)
    result["total_gpu_time_ms"] = round(total_gpu_time_ms, 6)
    return result


def build_performance_hotspots(analysis_cache, timing_payload, limit=HOTSPOT_LIMIT):
    limit = int(limit or HOTSPOT_LIMIT)
    action_index = {}
    _index_action_nodes(analysis_cache["action_tree"], action_index)
    timing_payload = _normalize_timing_payload(timing_payload)

    available = bool(timing_payload.get("timing_available"))
    result = {
        "timing_available": available,
        "basis": "gpu_timing" if available else "heuristic",
        "counter_name": timing_payload.get("counter_name", "EventGPUDuration"),
        "top_passes": [],
        "top_events": [],
    }

    if available:
        pass_rankings = []
        for pass_payload in analysis_cache["passes"]:
            start_event_id = int(pass_payload["event_range"]["start_event_id"])
            end_event_id = int(pass_payload["event_range"]["end_event_id"])
            rows = [
                item
                for item in timing_payload.get("rows", [])
                if start_event_id <= int(item["event_id"]) <= end_event_id
            ]
            if not rows:
                continue

            total_gpu_time_ms = round(sum(float(item["gpu_time_ms"]) for item in rows), 6)
            pass_rankings.append(
                {
                    "metric_name": "gpu_time_ms",
                    "metric_value": total_gpu_time_ms,
                    "gpu_time_ms": total_gpu_time_ms,
                    "timed_event_count": len(rows),
                    **_pass_summary(pass_payload),
                }
            )

        result["top_passes"] = sorted(
            pass_rankings,
            key=lambda item: (-item["gpu_time_ms"], item["event_range"]["start_event_id"]),
        )[:limit]

        event_rankings = [_timed_event_entry(item, action_index.get(int(item["event_id"]))) for item in timing_payload.get("rows", [])]
        result["top_events"] = sorted(
            event_rankings,
            key=lambda item: (-item["gpu_time_ms"], item["event_id"]),
        )[:limit]
        return result

    result["fallback_explanation"] = timing_payload.get(
        "reason",
        "GPU duration counters are unavailable, so hotspots were ranked with draw, dispatch, copy, and clear heuristics.",
    )
    result["top_passes"] = sorted(
        [_heuristic_pass_entry(item) for item in analysis_cache["passes"]],
        key=lambda item: (-item["heuristic_score"], item["event_range"]["start_event_id"]),
    )[:limit]
    result["top_events"] = sorted(
        _heuristic_event_entries(analysis_cache["action_tree"]),
        key=lambda item: (-item["heuristic_score"], item["event_id"]),
    )[:limit]
    return result


def pass_id_from_range(start_event_id, end_event_id):
    return "pass:{0}-{1}".format(int(start_event_id), int(end_event_id))


def _filter_action_tree(nodes, max_depth, name_filter_lower, depth):
    payload = []
    for node in nodes:
        children = []
        if max_depth is None or depth < max_depth:
            children = _filter_action_tree(node["children"], max_depth, name_filter_lower, depth + 1)

        if name_filter_lower and name_filter_lower not in node["name"].lower() and not children:
            continue

        payload.append(
            {
                "event_id": node["event_id"],
                "action_id": node["action_id"],
                "name": node["name"],
                "flags": list(node["flags"]),
                "child_count": int(node["child_count"]),
                "parent_event_id": node.get("parent_event_id"),
                "depth": depth,
                "children": children,
            }
        )
    return payload


def _flatten_action_tree(nodes, output):
    for node in nodes:
        output.append(
            {
                "event_id": node["event_id"],
                "action_id": node["action_id"],
                "name": node["name"],
                "flags": list(node["flags"]),
                "child_count": int(node["child_count"]),
                "parent_event_id": node.get("parent_event_id"),
                "depth": int(node.get("depth", 0)),
                "children": [],
            }
        )
        _flatten_action_tree(node["children"], output)


def _take_action_tree_preview(nodes, budget):
    payload = []
    for node in nodes:
        if budget["remaining"] <= 0:
            break

        budget["remaining"] -= 1
        budget["returned"] += 1
        children = _take_action_tree_preview(node["children"], budget)
        payload.append(
            {
                "event_id": node["event_id"],
                "action_id": node["action_id"],
                "name": node["name"],
                "flags": list(node["flags"]),
                "child_count": int(node["child_count"]),
                "parent_event_id": node.get("parent_event_id"),
                "depth": int(node.get("depth", 0)),
                "children": children,
            }
        )
    return payload


def _annotate_action_node(node, depth):
    children = []
    for child in node["children"]:
        children.append(_annotate_action_node(child, depth + 1))

    flags = list(node.get("flags", []))
    stats = {
        "total_actions": 1,
        "draw_calls": 1 if "draw" in flags else 0,
        "dispatches": 1 if "dispatch" in flags else 0,
        "copies": 1 if "copy" in flags else 0,
        "clears": 1 if "clear" in flags else 0,
        "resolves": 1 if "resolve" in flags else 0,
        "marker_actions": 1 if _is_marker_like(node) else 0,
    }

    start_event_id = int(node["event_id"])
    end_event_id = int(node["event_id"])
    color_targets = _collect_resource_names(node.get("outputs", []))
    depth_targets = _collect_resource_names([node.get("depth_output", {})])
    color_target_count_max = len(color_targets)

    representative_events = []
    if _is_significant_event(node):
        representative_events.append(_representative_event(node))

    for child in children:
        child_stats = child["_analysis"]["stats"]
        stats["total_actions"] += child_stats["total_actions"]
        stats["draw_calls"] += child_stats["draw_calls"]
        stats["dispatches"] += child_stats["dispatches"]
        stats["copies"] += child_stats["copies"]
        stats["clears"] += child_stats["clears"]
        stats["resolves"] += child_stats["resolves"]
        stats["marker_actions"] += child_stats["marker_actions"]
        start_event_id = min(start_event_id, child["_analysis"]["event_range"]["start_event_id"])
        end_event_id = max(end_event_id, child["_analysis"]["event_range"]["end_event_id"])
        color_target_count_max = max(color_target_count_max, child["_analysis"]["output_summary"]["color_target_count_max"])
        color_targets = _merge_names(color_targets, child["_analysis"]["output_summary"]["color_targets"])
        depth_targets = _merge_names(depth_targets, child["_analysis"]["output_summary"]["depth_targets"])
        representative_events = _merge_representative_events(
            representative_events,
            child["_analysis"]["representative_events"],
        )

    output_summary = {
        "has_color_output": bool(color_targets),
        "has_depth_output": bool(depth_targets),
        "color_target_count_max": int(color_target_count_max),
        "color_targets": color_targets,
        "depth_targets": depth_targets,
    }

    annotated = dict(node)
    annotated["children"] = children
    annotated["_analysis"] = {
        "depth": depth,
        "event_range": {"start_event_id": start_event_id, "end_event_id": end_event_id},
        "stats": stats,
        "output_summary": output_summary,
        "representative_events": representative_events,
        "has_gpu_work": bool(
            stats["draw_calls"]
            or stats["dispatches"]
            or stats["copies"]
            or stats["clears"]
            or stats["resolves"]
        ),
        "marker_like": _is_marker_like(node),
    }
    return annotated


def _build_pass_payload(node, level, allow_non_marker_children, pass_index):
    if not _is_pass_candidate(node, level, allow_non_marker_children):
        return None

    category, confidence, reasons = _classify_pass(node, level)
    child_passes = []
    for child in node["children"]:
        child_pass = _build_pass_payload(child, level + 1, False, pass_index)
        if child_pass is not None:
            child_passes.append(child_pass)

    event_range = node["_analysis"]["event_range"]
    payload = {
        "pass_id": pass_id_from_range(event_range["start_event_id"], event_range["end_event_id"]),
        "name": node["name"],
        "category": category,
        "confidence": confidence,
        "reasons": reasons,
        "level": level,
        "event_range": event_range,
        "stats": dict(node["_analysis"]["stats"]),
        "output_summary": dict(node["_analysis"]["output_summary"]),
        "representative_events": list(node["_analysis"]["representative_events"]),
        "child_pass_count": len(child_passes),
        "child_passes": child_passes,
    }
    pass_index[payload["pass_id"]] = payload
    return payload


def _classify_pass(node, level):
    name_lower = node["name"].lower()
    stats = node["_analysis"]["stats"]
    output_summary = node["_analysis"]["output_summary"]
    scores = {}
    reasons = {}

    def add(category, score, reason):
        if category not in scores or score > scores[category]:
            scores[category] = score
            reasons[category] = []
        if reason not in reasons[category]:
            reasons[category].append(reason)

    total_copy_like = stats["copies"] + stats["clears"] + stats["resolves"]

    if _contains_hint(name_lower, _PRESENT_HINTS):
        add("presentation", 0.99, "pass name indicates presentation or swapchain work")
    if _contains_hint(name_lower, _UI_HINTS):
        add("ui_overlay", 0.93, "pass name indicates UI or overlay rendering")
    if _contains_hint(name_lower, _POST_PROCESS_HINTS):
        add("post_process", 0.86, "pass name indicates post-processing work")
    if _contains_hint(name_lower, _TRANSPARENCY_HINTS):
        add("transparency", 0.86, "pass name indicates translucent or particle rendering")
    if _contains_hint(name_lower, _LIGHTING_HINTS):
        add("lighting", 0.84, "pass name indicates lighting, AO, reflection, or fog work")
    if _contains_hint(name_lower, _SHADOW_HINTS):
        add("shadow_depth", 0.84, "pass name indicates shadow rendering")
    if _contains_hint(name_lower, _DEPTH_HINTS):
        add("depth_prepass", 0.8, "pass name indicates depth, HZB, or occlusion work")

    if stats["draw_calls"] == 0 and stats["dispatches"] == 0 and total_copy_like == 0:
        add("setup", 0.82, "pass contains markers or boundaries without direct GPU work")

    if total_copy_like > 0 and stats["draw_calls"] == 0 and stats["dispatches"] == 0:
        add("copy_resolve", 0.88, "pass contains only copy, clear, or resolve operations")

    if stats["dispatches"] > 0 and stats["draw_calls"] == 0:
        add("compute", 0.8, "pass contains dispatch work without draw calls")

    if stats["draw_calls"] > 0 and output_summary["has_depth_output"] and not output_summary["has_color_output"]:
        add("depth_prepass", 0.82, "draw pass writes depth targets without color outputs")
        if _contains_hint(name_lower, _SHADOW_HINTS) or _contains_hint(" ".join(output_summary["depth_targets"]).lower(), _SHADOW_HINTS):
            add("shadow_depth", 0.91, "depth-only pass also carries shadow hints")

    if stats["draw_calls"] > 0 and output_summary["has_color_output"]:
        if output_summary["color_target_count_max"] >= 2:
            add("geometry", 0.9, "draw pass writes multiple color targets")
        else:
            add("geometry", 0.72, "draw pass writes color targets")

    if level == 0 and _contains_hint(name_lower, _UI_HINTS):
        add("ui_overlay", 0.96, "top-level pass name strongly indicates a UI overlay")

    if not scores:
        return (
            "unknown",
            0.35,
            [
                "no strong structural or naming signals matched any known pass category",
                "pass statistics: draws={0}, dispatches={1}, copies={2}, clears={3}, resolves={4}".format(
                    stats["draw_calls"],
                    stats["dispatches"],
                    stats["copies"],
                    stats["clears"],
                    stats["resolves"],
                ),
            ],
        )

    ordered = sorted(
        PASS_CATEGORIES,
        key=lambda category: (-scores.get(category, 0.0), PASS_CATEGORIES.index(category)),
    )
    category = ordered[0]
    confidence = round(scores[category], 2)
    if confidence < 0.6:
        return (
            "unknown",
            confidence,
            reasons.get(category, []) + ["classification confidence stayed below the minimum threshold"],
        )
    return category, confidence, reasons.get(category, [])


def _is_pass_candidate(node, level, allow_non_marker_children):
    if _is_noise_node(node):
        return False
    analysis = node["_analysis"]
    if level == 0:
        return analysis["marker_like"] or analysis["has_gpu_work"] or _contains_hint(node["name"].lower(), _PRESENT_HINTS)
    if analysis["marker_like"]:
        return analysis["has_gpu_work"] or bool(node["children"])
    return bool(allow_non_marker_children and analysis["has_gpu_work"])


def _flatten_pass_tree(passes):
    payload = []
    for pass_payload in passes:
        payload.append(pass_payload)
        payload.extend(_flatten_pass_tree(pass_payload["child_passes"]))
    return payload


def _pass_summary(pass_payload):
    return {
        "pass_id": pass_payload["pass_id"],
        "name": pass_payload["name"],
        "category": pass_payload["category"],
        "confidence": pass_payload["confidence"],
        "reasons": list(pass_payload["reasons"]),
        "level": int(pass_payload["level"]),
        "event_range": dict(pass_payload["event_range"]),
        "stats": dict(pass_payload["stats"]),
        "output_summary": dict(pass_payload["output_summary"]),
        "representative_events": list(pass_payload["representative_events"]),
        "child_pass_count": int(pass_payload["child_pass_count"]),
    }


def _copy_pass_entry(item):
    payload = {
        "pass_id": item["pass_id"],
        "name": item["name"],
        "category": item["category"],
        "confidence": item["confidence"],
        "reasons": list(item.get("reasons", [])),
        "level": int(item["level"]),
        "event_range": dict(item["event_range"]),
        "stats": dict(item["stats"]),
        "output_summary": {
            "has_color_output": bool(item["output_summary"]["has_color_output"]),
            "has_depth_output": bool(item["output_summary"]["has_depth_output"]),
            "color_target_count_max": int(item["output_summary"]["color_target_count_max"]),
            "color_targets": list(item["output_summary"]["color_targets"]),
            "depth_targets": list(item["output_summary"]["depth_targets"]),
        },
        "representative_events": [_representative_event_copy(event) for event in item["representative_events"]],
        "child_pass_count": int(item["child_pass_count"]),
    }
    if "gpu_time_ms" in item:
        payload["gpu_time_ms"] = item["gpu_time_ms"]
    if "timed_event_count" in item:
        payload["timed_event_count"] = int(item["timed_event_count"])
    return payload


def _build_tail_chain(passes):
    if not passes:
        return []

    start_index = None
    for index in range(len(passes) - 1, -1, -1):
        category = passes[index]["category"]
        if category in ("presentation", "ui_overlay"):
            start_index = index
        elif start_index is not None and category not in _TAIL_CATEGORIES:
            break

    if start_index is None:
        return [dict(item) for item in passes[-3:]]
    return [dict(item) for item in passes[start_index:]]


def _build_analysis_warnings(passes):
    warnings = []
    unknown = [item["name"] for item in passes if item["category"] == "unknown"]
    if unknown:
        warnings.append(
            "Unknown pass classification for {0} pass(es): {1}".format(
                len(unknown),
                ", ".join(unknown[:5]),
            )
        )

    low_confidence = [item["name"] for item in passes if item["confidence"] < 0.7 and item["category"] != "unknown"]
    if low_confidence:
        warnings.append(
            "Low-confidence classification for {0} pass(es): {1}".format(
                len(low_confidence),
                ", ".join(low_confidence[:5]),
            )
        )
    return warnings


def _representative_event(node):
    return {
        "event_id": int(node["event_id"]),
        "name": node["name"],
        "flags": list(node.get("flags", [])),
    }


def _representative_event_copy(item):
    return {
        "event_id": int(item["event_id"]),
        "name": item["name"],
        "flags": list(item.get("flags", [])),
    }


def _merge_representative_events(existing, incoming):
    payload = list(existing)
    seen = set([item["event_id"] for item in payload])
    for item in incoming:
        event_id = item["event_id"]
        if event_id in seen:
            continue
        payload.append(item)
        seen.add(event_id)
        if len(payload) >= 5:
            break
    return payload


def _is_noise_node(node):
    name = node["name"]
    flags = set(node.get("flags", []))
    if name == "ID3D12GraphicsCommandList::EndEvent()":
        return True
    if "command_buffer_boundary" in flags and not _has_direct_gpu_work(flags):
        return True
    return False


def _is_marker_like(node):
    return bool(set(node.get("flags", [])) & _MARKER_FLAGS)


def _has_direct_gpu_work(flags):
    return bool(set(flags) & _GPU_WORK_FLAGS)


def _is_significant_event(node):
    flags = set(node.get("flags", []))
    if flags & _GPU_WORK_FLAGS:
        return True
    if _contains_hint(node["name"].lower(), _PRESENT_HINTS):
        return True
    if _is_marker_like(node) and node.get("child_count", 0):
        return True
    return False


def _collect_resource_names(items):
    names = []
    for item in items:
        name = (item or {}).get("resource_name") or ""
        if name and name not in names:
            names.append(name)
        if len(names) >= 4:
            break
    return names


def _merge_names(existing, incoming):
    payload = list(existing)
    for item in incoming:
        if item not in payload:
            payload.append(item)
        if len(payload) >= 4:
            break
    return payload


def _contains_hint(text, hints):
    for hint in hints:
        if hint in text:
            return True
    return False


def _index_action_nodes(nodes, output):
    for node in nodes:
        output[int(node["event_id"])] = node
        _index_action_nodes(node.get("children", []), output)


def _timed_event_entry(item, node):
    payload = {
        "event_id": int(item["event_id"]),
        "name": node["name"] if node is not None else "Event {0}".format(int(item["event_id"])),
        "flags": list(node.get("flags", [])) if node is not None else [],
        "parent_event_id": node.get("parent_event_id") if node is not None else None,
        "depth": int(node.get("_analysis", {}).get("depth", node.get("depth", 0))) if node is not None else 0,
        "metric_name": "gpu_time_ms",
        "metric_value": round(float(item["gpu_time_ms"]), 6),
        "gpu_time_ms": round(float(item["gpu_time_ms"]), 6),
    }
    return payload


def _normalize_timing_payload(timing_payload):
    payload = dict(timing_payload or {})
    payload.setdefault("timing_available", False)
    payload.setdefault("counter_name", "EventGPUDuration")
    payload.setdefault("rows", [])
    return payload


def _timing_metadata(timing_payload):
    payload = {
        "timing_available": bool(timing_payload.get("timing_available")),
        "counter_name": timing_payload.get("counter_name", "EventGPUDuration"),
    }
    if not payload["timing_available"]:
        payload["timing_unavailable_reason"] = timing_payload.get(
            "reason",
            "GPU duration counters are unavailable for this capture or replay device.",
        )
    return payload


def _timed_pass_summaries(pass_payloads, timing_payload):
    rows = list(timing_payload.get("rows", []))
    available = bool(timing_payload.get("timing_available"))
    payload = []

    for pass_payload in pass_payloads:
        summary = _pass_summary(pass_payload)
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


def _heuristic_pass_entry(pass_payload):
    heuristic_score = round(float(_pass_heuristic_score(pass_payload)), 6)
    return {
        "metric_name": "heuristic_score",
        "metric_value": heuristic_score,
        "heuristic_score": heuristic_score,
        **_pass_summary(pass_payload),
    }


def _heuristic_event_entries(nodes):
    payload = []
    for node in nodes:
        heuristic_score = _action_heuristic_score(node)
        if heuristic_score > 0:
            payload.append(
                {
                    "event_id": int(node["event_id"]),
                    "name": node["name"],
                    "flags": list(node.get("flags", [])),
                    "parent_event_id": node.get("parent_event_id"),
                    "depth": int(node.get("_analysis", {}).get("depth", node.get("depth", 0))),
                    "metric_name": "heuristic_score",
                    "metric_value": round(float(heuristic_score), 6),
                    "heuristic_score": round(float(heuristic_score), 6),
                }
            )
        payload.extend(_heuristic_event_entries(node.get("children", [])))
    return payload


def _pass_heuristic_score(pass_payload):
    stats = pass_payload["stats"]
    return (
        int(stats.get("draw_calls", 0)) * 1000000
        + int(stats.get("dispatches", 0)) * 500000
        + int(stats.get("copies", 0)) * 10000
        + int(stats.get("resolves", 0)) * 10000
        + int(stats.get("clears", 0)) * 5000
        + int(stats.get("total_actions", 0))
    )


def _action_heuristic_score(node):
    flags = set(node.get("flags", []))
    if "draw" in flags:
        return max(1, int(node.get("num_indices", 0))) * max(1, int(node.get("num_instances", 1)))
    if "dispatch" in flags:
        dispatch_threads = _positive_product(node.get("dispatch_threads_dimension", []))
        if dispatch_threads > 0:
            return dispatch_threads
        dispatch_groups = _positive_product(node.get("dispatch_dimension", []))
        if dispatch_groups > 0:
            return dispatch_groups
        return 1
    if "copy" in flags or "resolve" in flags:
        return 1000
    if "clear" in flags:
        return 500
    return 0


def _positive_product(values):
    payload = 1
    saw_value = False
    for value in values:
        integer = int(value)
        if integer <= 0:
            continue
        payload *= integer
        saw_value = True
    return payload if saw_value else 0


def _lower(value):
    if value is None:
        return None
    return str(value).strip().lower()
