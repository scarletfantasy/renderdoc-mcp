from .models import HOTSPOT_LIMIT, with_meta
from .pass_classification import index_action_nodes, pass_summary
from .timing import normalize_timing_payload, timed_event_entry, timing_info_from_payload


def build_performance_hotspots(
    analysis_cache,
    timing_payload,
    limit=HOTSPOT_LIMIT,
):
    limit = int(limit or HOTSPOT_LIMIT)
    action_index = {}
    index_action_nodes(analysis_cache["action_tree"], action_index)
    normalized_timing = normalize_timing_payload(timing_payload)
    timing_info = timing_info_from_payload(normalized_timing)
    candidate_passes = _hotspot_pass_candidates(analysis_cache)

    result = {
        "basis": "gpu_timing" if timing_info.timing_available else "heuristic",
        "top_passes": [],
        "top_events": [],
    }

    if timing_info.timing_available:
        pass_rankings = []
        for pass_payload in candidate_passes:
            start_event_id = int(pass_payload["event_range"]["start_event_id"])
            end_event_id = int(pass_payload["event_range"]["end_event_id"])
            rows = [
                item
                for item in normalized_timing.get("rows", [])
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
                    **pass_summary(pass_payload),
                }
            )

        result["top_passes"] = sorted(
            pass_rankings,
            key=lambda item: (-item["gpu_time_ms"], item["event_range"]["start_event_id"]),
        )[:limit]

        event_rankings = [timed_event_entry(item, action_index.get(int(item["event_id"]))) for item in normalized_timing.get("rows", [])]
        result["top_events"] = sorted(
            event_rankings,
            key=lambda item: (-item["gpu_time_ms"], item["event_id"]),
        )[:limit]
        return with_meta(result, timing=timing_info)

    result["fallback_explanation"] = normalized_timing.get(
        "reason",
        "GPU duration counters are unavailable, so hotspots were ranked with draw, dispatch, copy, and clear heuristics.",
    )
    result["top_passes"] = sorted(
        [_heuristic_pass_entry(item) for item in candidate_passes],
        key=lambda item: (-item["heuristic_score"], item["event_range"]["start_event_id"]),
    )[:limit]
    result["top_events"] = sorted(
        _heuristic_event_entries(analysis_cache["action_tree"]),
        key=lambda item: (-item["heuristic_score"], item["event_id"]),
    )[:limit]
    return with_meta(result, timing=timing_info)


def _heuristic_pass_entry(pass_payload):
    heuristic_score = round(float(_pass_heuristic_score(pass_payload)), 6)
    return {
        "metric_name": "heuristic_score",
        "metric_value": heuristic_score,
        "heuristic_score": heuristic_score,
        **pass_summary(pass_payload),
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


def _hotspot_pass_candidates(analysis_cache):
    all_passes = list(analysis_cache.get("all_passes", analysis_cache["passes"]))
    leaf_passes = [item for item in all_passes if int(item.get("child_pass_count", 0)) == 0]
    return leaf_passes or all_passes
