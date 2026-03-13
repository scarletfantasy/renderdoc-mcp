from .models import (
    DEFAULT_ACTION_PAGE_LIMIT,
    LEGACY_ACTION_LIST_NODE_LIMIT,
    PageInfo,
    with_meta,
)
from .pass_classification import action_summary, compact_action_entry


def build_action_tree_result(nodes, total_count, max_depth=None, name_filter=None, limit=None):
    name_filter_lower = _lower(name_filter)
    filtered = _filter_action_tree(nodes, max_depth, name_filter_lower, 0)
    flat = []
    _flatten_action_tree(filtered, flat)

    preview_limit = int(limit if limit is not None else LEGACY_ACTION_LIST_NODE_LIMIT)
    preview_budget = {"remaining": preview_limit, "returned": 0}
    preview = _take_action_tree_preview(filtered, preview_budget)
    has_more = len(flat) > preview_budget["returned"]

    return with_meta(
        {
            "actions": preview,
        },
        page=PageInfo(
            cursor="0",
            next_cursor=str(preview_budget["returned"]) if has_more else "",
            limit=preview_limit,
            returned_count=preview_budget["returned"],
            total_count=int(total_count),
            matched_count=len(flat),
            has_more=has_more,
        ),
        extra_meta={"page_mode": "tree_preview"},
    )


def build_action_list_result(nodes, total_count, max_depth=None, name_filter=None, cursor=None, limit=None):
    name_filter_lower = _lower(name_filter)
    filtered = _filter_action_tree(nodes, max_depth, name_filter_lower, 0)
    flat = []
    _flatten_action_tree(filtered, flat)

    page_limit = int(limit if limit is not None else DEFAULT_ACTION_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = flat[offset : offset + page_limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(flat)

    return with_meta(
        {
            "actions": page,
        },
        page=PageInfo(
            cursor=str(offset),
            next_cursor=str(next_offset) if has_more else "",
            limit=page_limit,
            returned_count=len(page),
            total_count=int(total_count),
            matched_count=len(flat),
            has_more=has_more,
        ),
        extra_meta={"page_mode": "flat_preorder"},
    )


def filter_action_tree(nodes, max_depth=None, name_filter=None):
    return _filter_action_tree(nodes, max_depth, _lower(name_filter), 0)


def flatten_action_tree(nodes):
    flat = []
    _flatten_action_tree(nodes, flat)
    return flat


def build_action_children_result(
    analysis_cache,
    parent_event_id=None,
    cursor=None,
    limit=None,
    name_filter=None,
    flags_filter=None,
):
    parent_key = "" if parent_event_id in (None, "") else str(int(parent_event_id))
    child_ids = list(analysis_cache.get("action_children_index", {}).get(parent_key, []))
    action_index = analysis_cache.get("action_index", {})
    name_filter_lower = _lower(name_filter)
    required_flags = {item for item in (_lower(flags_filter) or "").replace(",", " ").split() if item}

    children = []
    for event_id in child_ids:
        node = action_index.get(int(event_id))
        if node is None:
            continue
        entry = compact_action_entry(node)
        if name_filter_lower and name_filter_lower not in entry["name"].lower():
            continue
        if required_flags and not required_flags.issubset(set(entry["flags"])):
            continue
        children.append(entry)

    page_limit = int(limit if limit is not None else DEFAULT_ACTION_PAGE_LIMIT)
    offset = int(cursor or 0)
    page = children[offset : offset + page_limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(children)

    return with_meta(
        {
            "parent_event_id": parent_key,
            "name_filter": name_filter or "",
            "flags_filter": " ".join(sorted(required_flags)),
            "actions": page,
        },
        page=PageInfo(
            cursor=str(offset),
            next_cursor=str(next_offset) if has_more else "",
            limit=page_limit,
            returned_count=len(page),
            total_count=len(child_ids),
            matched_count=len(children),
            has_more=has_more,
        ),
    )


def build_action_summary_result(analysis_cache, event_id):
    node = analysis_cache.get("action_index", {}).get(int(event_id))
    if node is None:
        return None
    return {"action": action_summary(node), "meta": {}}


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


def _lower(value):
    if value is None:
        return None
    return str(value).strip().lower()
