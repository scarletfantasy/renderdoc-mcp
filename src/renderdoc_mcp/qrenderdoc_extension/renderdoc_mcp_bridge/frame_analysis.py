"""Repo-time shim for the shared analysis module.

The installer overwrites the copied extension's `frame_analysis.py` with the
canonical shared implementation so the qrenderdoc extension stays self-contained
outside the Python package.
"""

from renderdoc_mcp.analysis.frame_analysis import *  # noqa: F401,F403
