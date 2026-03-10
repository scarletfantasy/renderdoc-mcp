from __future__ import annotations

from renderdoc_mcp.analysis import frame_analysis


def _resource(name: str) -> dict[str, str]:
    return {"resource_id": name.lower(), "resource_name": name}


def _action(
    event_id: int,
    name: str,
    flags: list[str] | None = None,
    outputs: list[dict[str, str]] | None = None,
    depth_output: dict[str, str] | None = None,
    children: list[dict] | None = None,
    num_indices: int = 0,
    num_instances: int = 1,
    dispatch_dimension: list[int] | None = None,
    dispatch_threads_dimension: list[int] | None = None,
) -> dict:
    payload = {
        "event_id": event_id,
        "action_id": event_id,
        "name": name,
        "custom_name": "",
        "flags": list(flags or []),
        "child_count": 0,
        "is_fake_marker": False,
        "num_indices": num_indices,
        "num_instances": num_instances,
        "dispatch_dimension": list(dispatch_dimension or [0, 0, 0]),
        "dispatch_threads_dimension": list(dispatch_threads_dimension or [0, 0, 0]),
        "outputs": list(outputs or []),
        "depth_output": depth_output or {"resource_id": "", "resource_name": ""},
        "parent_event_id": None,
        "children": list(children or []),
    }

    for child in payload["children"]:
        child["parent_event_id"] = event_id
    payload["child_count"] = len(payload["children"])
    return payload


def _count_stats(nodes: list[dict]) -> dict[str, int]:
    stats = {"total_actions": 0, "draw_calls": 0, "dispatches": 0, "copies": 0, "clears": 0}
    for node in nodes:
        stats["total_actions"] += 1
        flags = set(node["flags"])
        if "draw" in flags:
            stats["draw_calls"] += 1
        if "dispatch" in flags:
            stats["dispatches"] += 1
        if "copy" in flags:
            stats["copies"] += 1
        if "clear" in flags:
            stats["clears"] += 1
        child_stats = _count_stats(node["children"])
        for key, value in child_stats.items():
            stats[key] += value
    return stats


def _metadata(nodes: list[dict]) -> dict:
    return {
        "capture": {"loaded": True, "filename": "sample.rdc"},
        "api": "D3D12",
        "frame": {"frame_number": 1},
        "statistics": _count_stats(nodes),
        "resource_counts": {"textures": 4, "buffers": 2},
    }


def test_build_frame_analysis_indexes_nested_passes_and_actions() -> None:
    nodes = [
        _action(
            10,
            "Scene",
            ["push_marker"],
            children=[
                _action(
                    20,
                    "BasePass",
                    ["push_marker"],
                    children=[
                        _action(
                            21,
                            "Draw",
                            ["draw"],
                            outputs=[_resource("GBufferA"), _resource("GBufferB")],
                            depth_output=_resource("SceneDepth"),
                        )
                    ],
                )
            ],
        ),
        _action(30, "Present(Backbuffer)", []),
    ]

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))

    assert analysis["root_pass_ids"] == ["pass:10-21", "pass:30-30"]
    assert analysis["pass_children_index"]["pass:10-21"] == ["pass:20-21"]
    assert analysis["action_children_index"][""] == [10, 30]
    assert analysis["action_children_index"]["10"] == [20]


def test_list_passes_can_drill_into_parent_pass_id() -> None:
    nodes = [
        _action(
            10,
            "Scene",
            ["push_marker"],
            children=[
                _action(20, "ShadowDepths", ["push_marker"], children=[_action(21, "Draw", ["draw"])]),
                _action(
                    30,
                    "BasePass",
                    ["push_marker"],
                    children=[_action(31, "Draw", ["draw"], outputs=[_resource("Color")])],
                ),
            ],
        )
    ]

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))
    root = frame_analysis.list_passes(analysis, limit=50)
    scene_children = frame_analysis.list_passes(analysis, parent_pass_id="pass:10-31", limit=50)

    assert [item["name"] for item in root["passes"]] == ["Scene"]
    assert {item["name"] for item in scene_children["passes"]} == {"ShadowDepths", "BasePass"}


def test_list_actions_returns_direct_children_only() -> None:
    nodes = [
        _action(
            10,
            "Scene",
            ["push_marker"],
            children=[
                _action(20, "Compute", ["dispatch"]),
                _action(30, "BasePass", ["push_marker"], children=[_action(31, "Draw", ["draw"])]),
            ],
        )
    ]

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))
    root = frame_analysis.build_action_children_result(analysis, limit=50)
    scene_children = frame_analysis.build_action_children_result(analysis, parent_event_id=10, flags_filter="push_marker")

    assert [item["event_id"] for item in root["actions"]] == [10]
    assert [item["event_id"] for item in scene_children["actions"]] == [30]


def test_list_timing_events_pages_gpu_rows() -> None:
    nodes = [
        _action(
            100,
            "BasePass",
            ["push_marker"],
            children=[
                _action(101, "Depth", ["draw"]),
                _action(102, "Color", ["draw"]),
                _action(103, "Light", ["draw"]),
            ],
        )
    ]

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))
    result = frame_analysis.list_timing_events(
        analysis,
        "pass:100-103",
        {
            "timing_available": True,
            "counter_name": "EventGPUDuration",
            "rows": [
                {"event_id": 101, "gpu_time_ms": 0.5},
                {"event_id": 102, "gpu_time_ms": 1.25},
                {"event_id": 103, "gpu_time_ms": 0.75},
            ],
        },
        cursor=0,
        limit=2,
        sort_by="gpu_time",
    )

    assert result["basis"] == "gpu_timing"
    assert result["meta"]["page"]["returned_count"] == 2
    assert result["events"][0]["event_id"] == 102
    assert result["total_gpu_time_ms"] == 2.5


def test_list_passes_gpu_time_builds_reusable_timing_index() -> None:
    nodes = [
        _action(
            100,
            "Frame",
            ["push_marker"],
            children=[
                _action(110, "Shadow", ["push_marker"], children=[_action(111, "ShadowDraw", ["draw"])]),
                _action(120, "BasePass", ["push_marker"], children=[_action(121, "BaseDraw", ["draw"])]),
            ],
        )
    ]
    timing_payload = {
        "timing_available": True,
        "counter_name": "EventGPUDuration",
        "rows": [
            {"event_id": 121, "gpu_time_ms": 2.0},
            {"event_id": 111, "gpu_time_ms": 1.0},
        ],
    }

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))
    first = frame_analysis.list_passes(analysis, parent_pass_id="pass:100-121", limit=50, sort_by="gpu_time", timing_payload=timing_payload)
    second = frame_analysis.list_passes(analysis, parent_pass_id="pass:100-121", limit=50, sort_by="gpu_time", timing_payload=timing_payload)

    assert [item["name"] for item in first["passes"]] == ["BasePass", "Shadow"]
    assert first["passes"][0]["gpu_time_ms"] == 2.0
    assert first["passes"][1]["gpu_time_ms"] == 1.0
    assert second["passes"] == first["passes"]
    assert "_timing_index" in timing_payload
    assert [item["event_id"] for item in timing_payload["rows"]] == [111, 121]


def test_build_performance_hotspots_uses_nested_passes() -> None:
    nodes = [
        _action(
            10,
            "Scene",
            ["push_marker"],
            children=[
                _action(
                    20,
                    "BasePass",
                    ["push_marker"],
                    children=[_action(21, "Draw", ["draw"], num_indices=1000)],
                )
            ],
        )
    ]

    analysis = frame_analysis.build_frame_analysis(nodes, _metadata(nodes))
    hotspots = frame_analysis.build_performance_hotspots(
        analysis,
        {"timing_available": False, "counter_name": "EventGPUDuration", "rows": [], "reason": "unsupported"},
    )

    assert hotspots["basis"] == "heuristic"
    assert hotspots["top_passes"][0]["name"] == "BasePass"
