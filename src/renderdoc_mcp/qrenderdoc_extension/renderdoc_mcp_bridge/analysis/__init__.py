"""Repo-time shim for the extension analysis package.

The installer overwrites this package with the canonical shared analysis tree so
the copied qrenderdoc extension stays self-contained outside the Python package.
"""

from renderdoc_mcp.analysis import frame_analysis

__all__ = ["frame_analysis"]
