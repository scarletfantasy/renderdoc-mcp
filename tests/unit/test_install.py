from __future__ import annotations

import json
from pathlib import Path

from renderdoc_mcp import install as install_module
from renderdoc_mcp import install_cli


def test_ensure_always_load_is_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "UI.config"
    original_text = '{\n  "OtherSetting": true,\n  "AlwaysLoad_Extensions": ["renderdoc_mcp_bridge"]\n}'
    config_path.write_text(original_text, encoding="utf-8")

    changed = install_module._ensure_always_load(config_path)

    assert changed is False
    assert config_path.read_text(encoding="utf-8") == original_text


def test_ensure_always_load_preserves_existing_key_order(tmp_path: Path) -> None:
    config_path = tmp_path / "UI.config"
    config_path.write_text(
        '{\n  "First": 1,\n  "AlwaysLoad_Extensions": ["existing_extension"],\n  "Last": 2\n}',
        encoding="utf-8",
    )

    changed = install_module._ensure_always_load(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))

    assert changed is True
    assert list(payload.keys()) == ["First", "AlwaysLoad_Extensions", "Last"]
    assert payload["AlwaysLoad_Extensions"] == ["existing_extension", "renderdoc_mcp_bridge"]
    assert payload["First"] == 1
    assert payload["Last"] == 2


def test_install_extension_skips_ui_config_write_when_always_load_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    copied_to: list[Path] = []
    ensured_calls: list[Path] = []
    user_dir = tmp_path / "qrenderdoc"
    extension_dir = user_dir / "extensions" / "renderdoc_mcp_bridge"

    monkeypatch.setattr(install_module, "user_qrenderdoc_dir", lambda: user_dir)
    monkeypatch.setattr(install_module, "extension_install_dir", lambda: extension_dir)
    monkeypatch.setattr(install_module, "_copy_extension_files", lambda target_dir: copied_to.append(target_dir))
    monkeypatch.setattr(install_module, "_ensure_always_load", lambda config_path=None: ensured_calls.append(config_path))

    target = install_module.install_extension(always_load=False)

    assert target == extension_dir
    assert user_dir.is_dir()
    assert copied_to == [extension_dir]
    assert ensured_calls == []


def test_install_extension_respects_env_opt_out(tmp_path: Path, monkeypatch) -> None:
    copied_to: list[Path] = []
    ensured_calls: list[Path] = []
    user_dir = tmp_path / "qrenderdoc"
    extension_dir = user_dir / "extensions" / "renderdoc_mcp_bridge"

    monkeypatch.setenv("RENDERDOC_INSTALL_ALWAYS_LOAD", "0")
    monkeypatch.setattr(install_module, "user_qrenderdoc_dir", lambda: user_dir)
    monkeypatch.setattr(install_module, "extension_install_dir", lambda: extension_dir)
    monkeypatch.setattr(install_module, "_copy_extension_files", lambda target_dir: copied_to.append(target_dir))
    monkeypatch.setattr(install_module, "_ensure_always_load", lambda config_path=None: ensured_calls.append(config_path))

    target = install_module.install_extension()

    assert target == extension_dir
    assert copied_to == [extension_dir]
    assert ensured_calls == []


def test_install_cli_passes_explicit_opt_out(monkeypatch, capsys) -> None:
    captured: list[bool | None] = []
    target_path = Path(r"C:\temp\renderdoc_mcp_bridge")

    monkeypatch.setattr(
        install_cli,
        "install_extension",
        lambda always_load=None: captured.append(always_load) or target_path,
    )

    exit_code = install_cli.main(["--no-always-load"])

    assert exit_code == 0
    assert captured == [False]
    assert capsys.readouterr().out.strip() == str(target_path)
