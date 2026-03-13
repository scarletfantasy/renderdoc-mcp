from .component import BridgeComponent


class ShaderDebugOps(BridgeComponent):
    def handlers(self):
        return {
            "start_pixel_shader_debug": lambda params: self._start_pixel_shader_debug(
                int(params.get("event_id", 0)),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                params.get("texture_id"),
                params.get("sample"),
                params.get("primitive_id"),
                params.get("view"),
                int(params.get("state_limit", 32)),
            ),
            "continue_shader_debug": lambda params: self._continue_shader_debug(
                params.get("shader_debug_id", ""),
                int(params.get("state_limit", 32)),
            ),
            "get_shader_debug_step": lambda params: self._get_shader_debug_step(
                params.get("shader_debug_id", ""),
                int(params.get("step_index", 0)),
                int(params.get("change_limit", 64)),
            ),
            "end_shader_debug": lambda params: self._end_shader_debug(params.get("shader_debug_id", "")),
        }

    def _start_pixel_shader_debug(self, event_id, x, y, texture_id, sample, primitive_id, view, state_limit):
        return self._call_bridge_client(
            "_start_pixel_shader_debug",
            event_id,
            x,
            y,
            texture_id,
            sample,
            primitive_id,
            view,
            state_limit,
        )

    def _continue_shader_debug(self, shader_debug_id, state_limit):
        return self._call_bridge_client("_continue_shader_debug", shader_debug_id, state_limit)

    def _get_shader_debug_step(self, shader_debug_id, step_index, change_limit):
        return self._call_bridge_client("_get_shader_debug_step", shader_debug_id, step_index, change_limit)

    def _end_shader_debug(self, shader_debug_id):
        return self._call_bridge_client("_end_shader_debug", shader_debug_id)
