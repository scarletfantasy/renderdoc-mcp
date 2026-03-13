from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from renderdoc_mcp.application.services.input_normalizer import InputNormalizer


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    bridge_method: str
    handler: Callable[[Any], Callable[..., dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    uri: str
    name: str
    description: str
    handler: Callable[[Any], Callable[..., dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class OpenCaptureCommand:
    capture_path: str

    @classmethod
    def from_raw(cls, normalizer: InputNormalizer, capture_path: str) -> "OpenCaptureCommand":
        return cls(capture_path=normalizer.normalize_capture_path(capture_path))


@dataclass(frozen=True, slots=True)
class ListActionsCommand:
    capture_id: str
    parent_event_id: int | None
    name_filter: str | None
    flags_filter: str | None
    cursor: int | None
    limit: int | None

    @classmethod
    def from_raw(
        cls,
        normalizer: InputNormalizer,
        capture_id: str,
        parent_event_id: int | str | None = None,
        name_filter: str | None = None,
        flags_filter: str | None = None,
        cursor: int | str | None = None,
        limit: int | str | None = None,
    ) -> "ListActionsCommand":
        return cls(
            capture_id=normalizer.normalize_required_capture_id(capture_id),
            parent_event_id=normalizer.normalize_optional_int(parent_event_id, "parent_event_id"),
            name_filter=normalizer.normalize_optional_string(name_filter),
            flags_filter=normalizer.normalize_optional_string(flags_filter),
            cursor=normalizer.normalize_optional_int(cursor, "cursor"),
            limit=normalizer.normalize_optional_int(limit, "limit"),
        )


@dataclass(frozen=True, slots=True)
class GetResourceSummaryCommand:
    capture_id: str
    resource_id: str

    @classmethod
    def from_raw(
        cls,
        normalizer: InputNormalizer,
        capture_id: str,
        resource_id: str,
    ) -> "GetResourceSummaryCommand":
        return cls(
            capture_id=normalizer.normalize_required_capture_id(capture_id),
            resource_id=normalizer.normalize_required_string(resource_id, "resource_id"),
        )
