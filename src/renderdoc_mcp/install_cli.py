from __future__ import annotations

import argparse
from collections.abc import Sequence

from renderdoc_mcp.install import install_extension


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the bundled RenderDoc extension.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--always-load",
        dest="always_load",
        action="store_true",
        help="Add renderdoc_mcp_bridge to UI.config AlwaysLoad_Extensions.",
    )
    group.add_argument(
        "--no-always-load",
        dest="always_load",
        action="store_false",
        help="Install the extension without modifying UI.config.",
    )
    parser.set_defaults(always_load=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = install_extension(always_load=args.always_load)
    print(target)
    return 0
