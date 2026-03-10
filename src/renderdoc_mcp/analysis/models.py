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
DEFAULT_ACTION_PAGE_LIMIT = 50
DEFAULT_PASS_PAGE_LIMIT = 50
DEFAULT_TIMING_EVENT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 200
MAX_TIMING_EVENT_PAGE_LIMIT = 500
TOP_PASS_RANKING_LIMIT = 5
HOTSPOT_LIMIT = 10


class PageInfo:
    def __init__(
        self,
        cursor,
        next_cursor,
        limit,
        returned_count,
        total_count,
        matched_count,
        has_more,
    ):
        self.cursor = cursor
        self.next_cursor = next_cursor
        self.limit = limit
        self.returned_count = returned_count
        self.total_count = total_count
        self.matched_count = matched_count
        self.has_more = has_more

    def to_dict(self):
        return {
            "cursor": self.cursor,
            "next_cursor": self.next_cursor,
            "limit": self.limit,
            "returned_count": self.returned_count,
            "total_count": self.total_count,
            "matched_count": self.matched_count,
            "has_more": self.has_more,
        }


class TimingInfo:
    def __init__(
        self,
        timing_available,
        counter_name="EventGPUDuration",
        timing_unavailable_reason=None,
    ):
        self.timing_available = timing_available
        self.counter_name = counter_name
        self.timing_unavailable_reason = timing_unavailable_reason

    def to_dict(self):
        payload = {
            "timing_available": self.timing_available,
            "counter_name": self.counter_name,
        }
        if self.timing_unavailable_reason:
            payload["timing_unavailable_reason"] = self.timing_unavailable_reason
        return payload


class AnalysisCache:
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


def with_meta(
    payload,
    *,
    warnings=None,
    page=None,
    timing=None,
    extra_meta=None,
):
    meta = {}
    if warnings:
        meta["warnings"] = list(warnings)
    if page is not None:
        meta["page"] = page.to_dict()
    if timing is not None:
        meta["timing"] = timing.to_dict()
    if extra_meta:
        meta.update(extra_meta)
    payload["meta"] = meta
    return payload
