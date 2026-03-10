from __future__ import annotations

import json
import os
import shutil
from importlib import resources
from pathlib import Path

from renderdoc_mcp.paths import extension_install_dir, ui_config_path, user_qrenderdoc_dir

EXTENSION_PACKAGE = "renderdoc_mcp.qrenderdoc_extension"
EXTENSION_NAME = "renderdoc_mcp_bridge"
SHARED_ANALYSIS_PACKAGE = "renderdoc_mcp.analysis"
SHARED_ANALYSIS_MODULES = [
    "frame_analysis.py",
    "models.py",
    "action_listing.py",
    "pass_classification.py",
    "timing.py",
    "hotspots.py",
]
TRUE_LIKE_VALUES = {"1", "true", "yes", "on"}
FALSE_LIKE_VALUES = {"0", "false", "no", "off"}


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _env_optional_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None

    normalized = raw.strip().lower()
    if normalized in TRUE_LIKE_VALUES:
        return True
    if normalized in FALSE_LIKE_VALUES:
        return False
    return None


def _resolve_always_load(always_load: bool | None) -> bool:
    if always_load is not None:
        return always_load

    env_value = _env_optional_bool("RENDERDOC_INSTALL_ALWAYS_LOAD")
    if env_value is not None:
        return env_value

    return True


def _copy_extension_files(target_dir: Path) -> None:
    source_root = resources.files(EXTENSION_PACKAGE).joinpath(EXTENSION_NAME)
    with resources.as_file(source_root) as source_dir:
        _copy_tree(source_dir, target_dir)
    _sync_shared_analysis(target_dir)


def install_extension(always_load: bool | None = None) -> Path:
    user_qrenderdoc_dir().mkdir(parents=True, exist_ok=True)

    target_dir = extension_install_dir()
    _copy_extension_files(target_dir)

    if _resolve_always_load(always_load):
        _ensure_always_load()
    return target_dir


def _sync_shared_analysis(target_dir: Path) -> None:
    for module_name in SHARED_ANALYSIS_MODULES:
        source_module = resources.files(SHARED_ANALYSIS_PACKAGE).joinpath(module_name)
        with resources.as_file(source_module) as source_file:
            shutil.copy2(source_file, target_dir / module_name)


def _ensure_always_load(config_path: Path | None = None) -> bool:
    config_path = config_path or ui_config_path()
    config: dict[str, object]

    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        config = {}

    existing_value = config.get("AlwaysLoad_Extensions", [])
    always_load = list(existing_value) if isinstance(existing_value, list) else []
    if EXTENSION_NAME not in always_load:
        always_load.append(EXTENSION_NAME)
    else:
        return False

    config["AlwaysLoad_Extensions"] = always_load

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return True
