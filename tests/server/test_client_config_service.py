from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rosetta.server.controller.upstreams import UpstreamOut
from rosetta.server.service.client_config import (
    apply_client_config,
    build_client_config_preview,
)


def _upstream() -> UpstreamOut:
    return UpstreamOut(
        id="u1",
        name="deepseek-main",
        native_api="responses",
        provider="openai",
        base_url="https://api.example.com/v1",
        api_key=None,
        model="deepseek-v4-flash",
        enabled=True,
        created_at=datetime(2026, 6, 25, tzinfo=UTC),
        test_result=None,
    )


def test_codex_preview_reads_original_and_generates_target_config(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "old"\n', encoding="utf-8")

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert preview.target == "codex"
    assert preview.path == config
    assert preview.exists is True
    assert preview.original == 'model = "old"\n'
    assert preview.generated.startswith("# Codex 全局模型设置")
    assert 'model = "deepseek-v4-flash"' in preview.generated
    assert 'base_url = "http://localhost:1687"' in preview.generated
    assert "allow_insecure = true" in preview.generated


def test_claude_preview_uses_default_model_mapping(tmp_path: Path) -> None:
    preview = build_client_config_preview(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
    )

    assert preview.path == tmp_path / ".claude" / "settings.json"
    assert preview.original == ""
    assert '"ANTHROPIC_BASE_URL": "http://localhost:1687"' in preview.generated
    assert '"ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-flash"' in preview.generated
    assert '"ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash"' in preview.generated
    assert '"ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-flash"' in preview.generated
    assert "ANTHROPIC_MODEL" not in preview.generated


def test_opencode_preview_appends_v1_once(tmp_path: Path) -> None:
    preview = build_client_config_preview(
        "opencode",
        _upstream(),
        "http://localhost:1687/v1",
        home=tmp_path,
    )

    assert preview.path == tmp_path / ".config" / "opencode" / "opencode.json"
    assert '"baseURL": "http://localhost:1687/v1"' in preview.generated
    assert '"model": "rosetta/deepseek-v4-flash"' in preview.generated


def test_apply_client_config_backs_up_existing_file_and_writes_generated(tmp_path: Path) -> None:
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"old": true}\n', encoding="utf-8")

    result = apply_client_config(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
        backup_suffix="20260625-153000",
    )

    assert result.path == config
    assert result.backup_path == tmp_path / ".claude" / "settings.json.bak-20260625-153000"
    assert result.backup_path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert config.read_text(encoding="utf-8") == result.generated
    assert '"ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-flash"' in result.generated


def test_apply_client_config_without_existing_file_has_no_backup(tmp_path: Path) -> None:
    result = apply_client_config(
        "codex",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
        backup_suffix="20260625-153000",
    )

    assert result.backup_path is None
    assert result.path.exists()
    assert result.path.read_text(encoding="utf-8") == result.generated
