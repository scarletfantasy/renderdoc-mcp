from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from renderdoc_mcp.errors import ReplayFailureError
from renderdoc_mcp.services.common import ServiceContext

SUPPORTED_RESOURCE_KINDS = {"all", "textures", "buffers"}
MAX_BUFFER_READ_SIZE = 65536
MAX_TEXTURE_PREVIEW_DIMENSION = 64
MAX_TEXTURE_PREVIEW_PIXELS = 1024
SUPPORTED_TEXTURE_EXPORT_TYPES = {
    ".dds": "DDS",
    ".hdr": "HDR",
    ".jpeg": "JPG",
    ".jpg": "JPG",
    ".png": "PNG",
}


class ResourceQueries:
    def __init__(self, context: ServiceContext) -> None:
        self.context = context

    def list_resources(self, capture_path: str, kind: str = "all", name_filter: str | None = None) -> dict[str, Any]:
        kind = self.context.normalize_optional_string(kind) or "all"
        name_filter = self.context.normalize_optional_string(name_filter)

        if kind not in SUPPORTED_RESOURCE_KINDS:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "kind must be one of 'all', 'textures', or 'buffers'.",
                    {"kind": kind},
                ),
                "Resource listing failed.",
            )

        params: dict[str, Any] = {"kind": kind}
        if name_filter:
            params["name_filter"] = name_filter

        return self.context.run_tool(
            capture_path,
            "Listed capture resources.",
            lambda normalized: self.context.capture_tool(normalized, "list_resources", params),
        )

    def get_texture_data(
        self,
        capture_path: str,
        texture_id: str,
        mip_level: int,
        x: int,
        y: int,
        width: int,
        height: int,
        array_slice: int = 0,
        sample: int = 0,
    ) -> dict[str, Any]:
        try:
            params = {
                "texture_id": self.context.normalize_required_string(texture_id, "texture_id"),
                "mip_level": self.context.normalize_non_negative_int(mip_level, "mip_level"),
                "x": self.context.normalize_non_negative_int(x, "x"),
                "y": self.context.normalize_non_negative_int(y, "y"),
                "width": self.context.normalize_positive_int(width, "width"),
                "height": self.context.normalize_positive_int(height, "height"),
                "array_slice": self.context.normalize_non_negative_int(array_slice, "array_slice"),
                "sample": self.context.normalize_non_negative_int(sample, "sample"),
            }
        except ReplayFailureError as exc:
            return self.context.error_response(capture_path, exc, "Fetched texture preview data.")

        if params["width"] > MAX_TEXTURE_PREVIEW_DIMENSION:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    f"width must be less than or equal to {MAX_TEXTURE_PREVIEW_DIMENSION}.",
                    {"width": params["width"]},
                ),
                "Fetched texture preview data.",
            )
        if params["height"] > MAX_TEXTURE_PREVIEW_DIMENSION:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    f"height must be less than or equal to {MAX_TEXTURE_PREVIEW_DIMENSION}.",
                    {"height": params["height"]},
                ),
                "Fetched texture preview data.",
            )
        if params["width"] * params["height"] > MAX_TEXTURE_PREVIEW_PIXELS:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    f"width * height must be less than or equal to {MAX_TEXTURE_PREVIEW_PIXELS}.",
                    {"width": params["width"], "height": params["height"]},
                ),
                "Fetched texture preview data.",
            )

        return self.context.run_tool(
            capture_path,
            "Fetched texture preview data.",
            lambda normalized: self.context.capture_tool(normalized, "get_texture_data", params),
        )

    def get_buffer_data(
        self,
        capture_path: str,
        buffer_id: str,
        offset: int,
        size: int,
    ) -> dict[str, Any]:
        try:
            params = {
                "buffer_id": self.context.normalize_required_string(buffer_id, "buffer_id"),
                "offset": self.context.normalize_non_negative_int(offset, "offset"),
                "size": self.context.normalize_positive_int(size, "size"),
            }
        except ReplayFailureError as exc:
            return self.context.error_response(capture_path, exc, "Fetched buffer contents.")

        if params["size"] > MAX_BUFFER_READ_SIZE:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    f"size must be less than or equal to {MAX_BUFFER_READ_SIZE}.",
                    {"size": params["size"]},
                ),
                "Fetched buffer contents.",
            )

        response = self.context.run_tool(
            capture_path,
            "Fetched buffer contents.",
            lambda normalized: self.context.capture_tool(normalized, "get_buffer_data", params),
        )
        result = response.get("result")
        if isinstance(result, dict) and "data_hex_preview" not in result and result.get("data_base64"):
            try:
                decoded = base64.b64decode(str(result["data_base64"]), validate=False)
            except Exception:
                decoded = b""
            result["data_hex_preview"] = decoded[:64].hex(" ")
        return response

    def save_texture_to_file(
        self,
        capture_path: str,
        texture_id: str,
        output_path: str,
        mip_level: int = 0,
        array_slice: int = 0,
    ) -> dict[str, Any]:
        try:
            normalized_output_path = self.context.normalize_required_string(output_path, "output_path")
            params = {
                "texture_id": self.context.normalize_required_string(texture_id, "texture_id"),
                "output_path": normalized_output_path,
                "mip_level": self.context.normalize_non_negative_int(mip_level, "mip_level"),
                "array_slice": self.context.normalize_non_negative_int(array_slice, "array_slice"),
            }
        except ReplayFailureError as exc:
            return self.context.error_response(capture_path, exc, "Saved texture contents to disk.")

        extension = Path(normalized_output_path).suffix.lower()
        if extension not in SUPPORTED_TEXTURE_EXPORT_TYPES:
            return self.context.error_response(
                capture_path,
                ReplayFailureError(
                    "output_path must end in one of: .dds, .hdr, .jpeg, .jpg, .png.",
                    {"output_path": normalized_output_path},
                ),
                "Saved texture contents to disk.",
            )

        return self.context.run_tool(
            capture_path,
            "Saved texture contents to disk.",
            lambda normalized: self.context.capture_tool(normalized, "save_texture_to_file", params),
        )
