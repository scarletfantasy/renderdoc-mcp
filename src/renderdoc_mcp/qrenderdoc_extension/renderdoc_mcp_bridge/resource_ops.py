from .component import BridgeComponent


class ResourceOps(BridgeComponent):
    def handlers(self):
        return {
            "list_resources": lambda params: self._list_resources(
                params.get("kind", "all"),
                params.get("cursor"),
                params.get("limit"),
                params.get("name_filter"),
                params.get("sort_by", "name"),
            ),
            "get_resource_summary": lambda params: self._get_resource_summary(params.get("resource_id", "")),
            "list_resource_usages": lambda params: self._list_resource_usages(
                params.get("resource_id", ""),
                params.get("usage_kind", "all"),
                params.get("cursor"),
                params.get("limit"),
            ),
            "get_pixel_history": lambda params: self._get_pixel_history(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
                params.get("cursor"),
                params.get("limit"),
            ),
            "debug_pixel": lambda params: self._debug_pixel(
                params.get("texture_id", ""),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            ),
            "get_texture_data": lambda params: self._get_texture_data(
                params.get("texture_id", ""),
                int(params.get("mip_level", 0)),
                int(params.get("x", 0)),
                int(params.get("y", 0)),
                int(params.get("width", 0)),
                int(params.get("height", 0)),
                int(params.get("array_slice", 0)),
                int(params.get("sample", 0)),
            ),
            "get_buffer_data": lambda params: self._get_buffer_data(
                params.get("buffer_id", ""),
                int(params.get("offset", 0)),
                int(params.get("size", 0)),
                params.get("encoding", "hex"),
            ),
            "save_texture_to_file": lambda params: self._save_texture_to_file(
                params.get("texture_id", ""),
                params.get("output_path", ""),
                int(params.get("mip_level", 0)),
                int(params.get("array_slice", 0)),
            ),
        }

    def _get_pixel_history(self, texture_id, x, y, mip_level, array_slice, sample, cursor, limit):
        return self._call_bridge_client("_get_pixel_history", texture_id, x, y, mip_level, array_slice, sample, cursor, limit)

    def _debug_pixel(self, texture_id, x, y, mip_level, array_slice, sample):
        return self._call_bridge_client("_debug_pixel", texture_id, x, y, mip_level, array_slice, sample)

    def _get_texture_data(self, texture_id, mip_level, x, y, width, height, array_slice, sample):
        return self._call_bridge_client("_get_texture_data", texture_id, mip_level, x, y, width, height, array_slice, sample)

    def _get_buffer_data(self, buffer_id, offset, size, encoding):
        return self._call_bridge_client("_get_buffer_data", buffer_id, offset, size, encoding)

    def _save_texture_to_file(self, texture_id, output_path, mip_level, array_slice):
        return self._call_bridge_client("_save_texture_to_file", texture_id, output_path, mip_level, array_slice)

    def _list_resources(self, kind, cursor, limit, name_filter, sort_by):
        return self._call_bridge_client("_list_resources", kind, cursor, limit, name_filter, sort_by)

    def _get_resource_summary(self, resource_id):
        return self._call_bridge_client("_get_resource_summary", resource_id)

    def _list_resource_usages(self, resource_id, usage_kind, cursor, limit):
        return self._call_bridge_client("_list_resource_usages", resource_id, usage_kind, cursor, limit)
