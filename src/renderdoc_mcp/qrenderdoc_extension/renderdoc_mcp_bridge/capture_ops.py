from .component import BridgeComponent


class CaptureOps(BridgeComponent):
    def handlers(self):
        return {
            "load_capture": lambda params: self._load_capture(params.get("capture_path", "")),
            "get_capture_status": lambda params: self._capture_status(),
            "get_capture_overview": lambda params: self._get_capture_overview(),
            "get_analysis_worklist": lambda params: self._get_analysis_worklist(
                params.get("focus", "performance"),
                params.get("limit", 10),
            ),
            "list_passes": lambda params: self._list_passes(
                params.get("parent_pass_id"),
                params.get("cursor"),
                params.get("limit"),
                params.get("category_filter"),
                params.get("name_filter"),
                params.get("sort_by", "event_order"),
            ),
            "get_pass_summary": lambda params: self._get_pass_summary(params.get("pass_id", "")),
            "list_timing_events": lambda params: self._list_timing_events(
                params.get("pass_id", ""),
                params.get("cursor"),
                params.get("limit"),
                params.get("sort_by", "event_order"),
            ),
            "close_capture": lambda params: self._close_capture(),
        }

    def _load_capture(self, capture_path):
        return self._call_bridge_client("_load_capture", capture_path)

    def _get_capture_overview(self):
        return self._call_bridge_client("_get_capture_overview")

    def _get_analysis_worklist(self, focus, limit):
        return self._call_bridge_client("_get_analysis_worklist", focus, limit)

    def _list_passes(self, parent_pass_id, cursor, limit, category_filter, name_filter, sort_by):
        return self._call_bridge_client("_list_passes", parent_pass_id, cursor, limit, category_filter, name_filter, sort_by)

    def _get_pass_summary(self, pass_id):
        return self._call_bridge_client("_get_pass_summary", pass_id)

    def _list_timing_events(self, pass_id, cursor, limit, sort_by):
        return self._call_bridge_client("_list_timing_events", pass_id, cursor, limit, sort_by)

    def _close_capture(self):
        return self._call_bridge_client("_close_capture")
