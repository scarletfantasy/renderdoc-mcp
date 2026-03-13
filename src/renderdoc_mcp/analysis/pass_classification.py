from .models import PASS_CATEGORIES, TOP_PASS_RANKING_LIMIT
from .resource_usage import build_resource_usage_index

_TAIL_CATEGORIES = {"setup", "copy_resolve", "ui_overlay", "presentation"}
_GPU_WORK_FLAGS = {"draw", "dispatch", "copy", "resolve", "clear"}
_MARKER_FLAGS = {"push_marker", "set_marker"}
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


def build_frame_analysis(nodes, metadata):
    annotated_nodes = [_annotate_action_node(node, 0) for node in nodes]
    action_index = {}
    index_action_nodes(annotated_nodes, action_index)
    action_children_index = {"": [int(node["event_id"]) for node in annotated_nodes]}
    _index_action_children(annotated_nodes, action_children_index)

    top_level_passes = []
    pass_index = {}
    for node in annotated_nodes:
        pass_payload = _build_pass_payload(node, 0, True, pass_index, "")
        if pass_payload is not None:
            top_level_passes.append(pass_payload)

    top_level_summaries = [pass_summary(pass_payload) for pass_payload in top_level_passes]
    all_passes = _flatten_pass_tree(top_level_passes)
    root_pass_ids = [item["pass_id"] for item in top_level_passes]
    pass_children_index = {"": list(root_pass_ids)}
    _index_pass_children(top_level_passes, pass_children_index)
    warnings = build_analysis_warnings(all_passes)

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
        "top_draw_passes": [pass_summary(item) for item in draw_rankings],
        "top_compute_passes": [pass_summary(item) for item in compute_rankings],
        "tail_chain": build_tail_chain(top_level_summaries),
        "warnings": warnings,
    }

    return {
        "analysis": public_analysis,
        "action_tree": annotated_nodes,
        "passes": top_level_passes,
        "all_passes": all_passes,
        "pass_index": pass_index,
        "pass_children_index": pass_children_index,
        "root_pass_ids": root_pass_ids,
        "action_index": action_index,
        "action_children_index": action_children_index,
        "root_action_ids": action_children_index[""],
        "resource_usage_index": build_resource_usage_index(annotated_nodes),
        "statistics": metadata["statistics"],
        "resource_counts": metadata["resource_counts"],
        "frame": metadata["frame"],
        "api": metadata["api"],
        "capture": metadata["capture"],
        "total_actions": metadata["statistics"]["total_actions"],
    }


def get_pass_details(analysis_cache, pass_id):
    return analysis_cache["pass_index"].get(pass_id)


def get_pass_summary(analysis_cache, pass_id):
    pass_payload = analysis_cache["pass_index"].get(pass_id)
    if pass_payload is None:
        return None
    return pass_summary(pass_payload)


def pass_id_from_range(start_event_id, end_event_id):
    return "pass:{0}-{1}".format(int(start_event_id), int(end_event_id))


def pass_summary(pass_payload):
    return {
        "pass_id": pass_payload["pass_id"],
        "parent_pass_id": pass_payload.get("parent_pass_id", ""),
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


def pass_list_entry(pass_payload):
    payload = {
        "pass_id": pass_payload["pass_id"],
        "parent_pass_id": pass_payload.get("parent_pass_id", ""),
        "name": pass_payload["name"],
        "category": pass_payload["category"],
        "confidence": pass_payload["confidence"],
        "event_range": dict(pass_payload["event_range"]),
        "stats": dict(pass_payload["stats"]),
        "child_pass_count": int(pass_payload["child_pass_count"]),
    }
    if "gpu_time_ms" in pass_payload:
        payload["gpu_time_ms"] = pass_payload["gpu_time_ms"]
    if "timed_event_count" in pass_payload:
        payload["timed_event_count"] = int(pass_payload["timed_event_count"])
    return payload


def copy_pass_entry(item):
    payload = {
        "pass_id": item["pass_id"],
        "parent_pass_id": item.get("parent_pass_id", ""),
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
        "representative_events": [representative_event_copy(event) for event in item["representative_events"]],
        "child_pass_count": int(item["child_pass_count"]),
    }
    if "gpu_time_ms" in item:
        payload["gpu_time_ms"] = item["gpu_time_ms"]
    if "timed_event_count" in item:
        payload["timed_event_count"] = int(item["timed_event_count"])
    return payload


def build_tail_chain(passes):
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


def build_analysis_warnings(passes):
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


def index_action_nodes(nodes, output):
    for node in nodes:
        output[int(node["event_id"])] = node
        index_action_nodes(node.get("children", []), output)


def compact_action_entry(node):
    analysis = node.get("_analysis", {})
    return {
        "event_id": int(node["event_id"]),
        "name": node["name"],
        "flags": list(node.get("flags", [])),
        "depth": int(analysis.get("depth", node.get("depth", 0))),
        "child_count": int(node.get("child_count", len(node.get("children", [])))),
        "parent_event_id": node.get("parent_event_id"),
    }


def action_summary(node):
    payload = compact_action_entry(node)
    payload["num_indices"] = int(node.get("num_indices", 0))
    payload["num_instances"] = int(node.get("num_instances", 1))
    payload["dispatch_dimension"] = [int(value) for value in node.get("dispatch_dimension", [0, 0, 0])]
    payload["dispatch_threads_dimension"] = [
        int(value) for value in node.get("dispatch_threads_dimension", [0, 0, 0])
    ]
    payload["resource_usage_summary"] = {
        "output_count": len(node.get("outputs", [])),
        "has_depth_output": bool((node.get("depth_output") or {}).get("resource_id")),
        "output_resources": _collect_resource_names(node.get("outputs", [])),
        "depth_resource": (node.get("depth_output") or {}).get("resource_name") or "",
    }
    return payload


def representative_event_copy(item):
    return {
        "event_id": int(item["event_id"]),
        "name": item["name"],
        "flags": list(item.get("flags", [])),
    }


def _annotate_action_node(node, depth):
    children = [_annotate_action_node(child, depth + 1) for child in node["children"]]

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


def _build_pass_payload(node, level, allow_non_marker_children, pass_index, parent_pass_id):
    if not _is_pass_candidate(node, level, allow_non_marker_children):
        return None

    category, confidence, reasons = _classify_pass(node, level)
    child_passes = []
    for child in node["children"]:
        child_pass = _build_pass_payload(child, level + 1, False, pass_index, parent_pass_id="")
        if child_pass is not None:
            child_passes.append(child_pass)

    event_range = node["_analysis"]["event_range"]
    pass_id = pass_id_from_range(event_range["start_event_id"], event_range["end_event_id"])
    payload = {
        "pass_id": pass_id,
        "parent_pass_id": parent_pass_id,
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
    for child_pass in child_passes:
        child_pass["parent_pass_id"] = pass_id
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


def _index_pass_children(passes, output):
    for pass_payload in passes:
        output[pass_payload["pass_id"]] = [child["pass_id"] for child in pass_payload.get("child_passes", [])]
        _index_pass_children(pass_payload.get("child_passes", []), output)


def _index_action_children(nodes, output):
    for node in nodes:
        output[str(int(node["event_id"]))] = [int(child["event_id"]) for child in node.get("children", [])]
        _index_action_children(node.get("children", []), output)


def _representative_event(node):
    return {
        "event_id": int(node["event_id"]),
        "name": node["name"],
        "flags": list(node.get("flags", [])),
    }


def _merge_representative_events(existing, incoming):
    payload = list(existing)
    seen = {item["event_id"] for item in payload}
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
