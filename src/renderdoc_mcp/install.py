from __future__ import annotations

import hashlib
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
INSTALL_METADATA_FILENAME = ".renderdoc_mcp_install.json"
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


def _build_install_metadata() -> dict[str, object]:
    digest = hashlib.sha256()
    installed_files: list[str] = []
    source_root = resources.files(EXTENSION_PACKAGE).joinpath(EXTENSION_NAME)

    with resources.as_file(source_root) as source_dir:
        for source_path in sorted(path for path in source_dir.rglob("*") if path.is_file()):
            relative_path = source_path.relative_to(source_dir).as_posix()
            if relative_path in SHARED_ANALYSIS_MODULES:
                continue
            installed_files.append(relative_path)
            digest.update(relative_path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(source_path.read_bytes())
            digest.update(b"\0")

    for module_name in SHARED_ANALYSIS_MODULES:
        source_module = resources.files(SHARED_ANALYSIS_PACKAGE).joinpath(module_name)
        with resources.as_file(source_module) as source_file:
            installed_files.append(module_name)
            digest.update(module_name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(source_file.read_bytes())
            digest.update(b"\0")

    return {
        "version": 1,
        "extension_name": EXTENSION_NAME,
        "source_hash": digest.hexdigest(),
        "files": sorted(installed_files),
    }


def _read_install_metadata(target_dir: Path) -> dict[str, object] | None:
    metadata_path = target_dir / INSTALL_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _install_is_current(target_dir: Path, metadata: dict[str, object]) -> bool:
    if not target_dir.is_dir():
        return False

    installed_files = metadata.get("files")
    if not isinstance(installed_files, list) or not installed_files:
        return False

    for relative_path in installed_files:
        if not isinstance(relative_path, str):
            return False
        if not (target_dir / relative_path).is_file():
            return False

    return _read_install_metadata(target_dir) == metadata


def _write_install_metadata(target_dir: Path, metadata: dict[str, object]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / INSTALL_METADATA_FILENAME).write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _copy_extension_files(target_dir: Path) -> None:
    source_root = resources.files(EXTENSION_PACKAGE).joinpath(EXTENSION_NAME)
    with resources.as_file(source_root) as source_dir:
        _copy_tree(source_dir, target_dir)
    _sync_shared_analysis(target_dir)


def install_extension(always_load: bool | None = None) -> Path:
    user_qrenderdoc_dir().mkdir(parents=True, exist_ok=True)

    target_dir = extension_install_dir()
    metadata = _build_install_metadata()
    if not _install_is_current(target_dir, metadata):
        _copy_extension_files(target_dir)
        _write_install_metadata(target_dir, metadata)

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
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict):
            return False
        config = payload
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
