from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

from renderdoc_mcp.paths import extension_install_dir, ui_config_path, user_qrenderdoc_dir

EXTENSION_PACKAGE = "renderdoc_mcp.qrenderdoc_extension"
EXTENSION_NAME = "renderdoc_mcp_bridge"


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def install_extension() -> Path:
    user_qrenderdoc_dir().mkdir(parents=True, exist_ok=True)

    target_dir = extension_install_dir()
    source_root = resources.files(EXTENSION_PACKAGE).joinpath(EXTENSION_NAME)
    with resources.as_file(source_root) as source_dir:
        _copy_tree(source_dir, target_dir)

    _ensure_always_load()
    return target_dir


def _ensure_always_load() -> None:
    config_path = ui_config_path()
    config: dict[str, object]

    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}

    always_load = list(config.get("AlwaysLoad_Extensions", []))
    if EXTENSION_NAME not in always_load:
        always_load.append(EXTENSION_NAME)
    config["AlwaysLoad_Extensions"] = always_load

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
