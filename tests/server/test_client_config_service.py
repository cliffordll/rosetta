from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rosetta.server.controller.upstreams import UpstreamOut
from rosetta.server.service.client_config import (
    apply_client_config,
    apply_client_config_clear,
    build_client_config_clear_preview,
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
    assert 'model = "deepseek-v4-flash"' in preview.generated
    assert 'base_url = "http://localhost:1687/v1"' in preview.generated
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
    assert '"ANTHROPIC_API_KEY"' not in preview.generated
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


def test_codex_preview_appends_v1_once(tmp_path: Path) -> None:
    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/v1",
        home=tmp_path,
    )

    assert 'base_url = "http://localhost:1687/v1"' in preview.generated
    assert "http://localhost:1687/v1/v1" not in preview.generated


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
    assert result.exists is True
    assert result.path.exists()
    assert result.path.read_text(encoding="utf-8") == result.generated


def test_codex_merge_preserves_user_custom_key(tmp_path: Path) -> None:
    """codex TOML: original 中的非 Rosetta key 在 merge 后保留。"""
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('custom_setting = "hello"\nmodel = "old"\n', encoding="utf-8")

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert 'custom_setting = "hello"' in preview.generated
    assert 'model = "deepseek-v4-flash"' in preview.generated


def test_codex_merge_adds_rosetta_table(tmp_path: Path) -> None:
    """codex TOML: 原文件无 [model_providers.rosetta] 时追加。"""
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("my_key = 42\n", encoding="utf-8")

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert "my_key = 42" in preview.generated
    assert "[model_providers.rosetta]" in preview.generated
    assert 'name = "Rosetta"' in preview.generated


def test_codex_merge_bad_toml_falls_back(tmp_path: Path) -> None:
    """codex TOML: 原文件非法不崩, fallback 到完整生成。"""
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("{{invalid toml}}\n", encoding="utf-8")

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert 'model = "deepseek-v4-flash"' in preview.generated
    assert 'base_url = "http://localhost:1687/v1"' in preview.generated


def test_claude_merge_preserves_user_env(tmp_path: Path) -> None:
    """claude JSON: original env 中的用户变量在 merge 后保留。"""
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"env": {"MY_CUSTOM_VAR": "val", "OTHER": 42}}\n', encoding="utf-8")

    preview = build_client_config_preview(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
    )

    assert '"MY_CUSTOM_VAR": "val"' in preview.generated
    assert '"OTHER": 42' in preview.generated
    assert '"ANTHROPIC_BASE_URL": "http://localhost:1687"' in preview.generated
    assert '"ANTHROPIC_API_KEY"' not in preview.generated


def test_claude_merge_removes_existing_api_key_env(tmp_path: Path) -> None:
    """claude JSON: API key 改由外部环境变量提供,生成配置不保留旧 env key。"""
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"env": {"ANTHROPIC_API_KEY": "old-key", "MY_CUSTOM_VAR": "val"}}\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
    )

    assert '"ANTHROPIC_API_KEY"' not in preview.generated
    assert '"MY_CUSTOM_VAR": "val"' in preview.generated
    assert '"ANTHROPIC_BASE_URL": "http://localhost:1687"' in preview.generated


def test_claude_merge_preserves_user_top_level_keys(tmp_path: Path) -> None:
    """claude JSON: env 之外的顶层 key 保留。"""
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"project": {"path": "/home/user/proj"}, "theme": "dark"}\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
    )

    assert '"path": "/home/user/proj"' in preview.generated
    assert '"theme": "dark"' in preview.generated


def test_opencode_merge_preserves_other_providers(tmp_path: Path) -> None:
    """opencode JSON: provider 中除了 rosetta 的其他 provider 保留。"""
    config = tmp_path / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"provider": {"openai": {"apiKey": "sk-xxx"}}, "customKey": 1}\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "opencode",
        _upstream(),
        "http://localhost:1687/v1",
        home=tmp_path,
    )

    assert '"openai"' in preview.generated
    assert '"customKey": 1' in preview.generated
    assert '"rosetta"' in preview.generated
    assert '"model": "rosetta/deepseek-v4-flash"' in preview.generated


def test_opencode_merge_bad_json_falls_back(tmp_path: Path) -> None:
    """opencode JSON: 原文件非法时不崩。"""
    config = tmp_path / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text("not json\n", encoding="utf-8")

    preview = build_client_config_preview(
        "opencode",
        _upstream(),
        "http://localhost:1687/v1",
        home=tmp_path,
    )

    assert '"model": "rosetta/deepseek-v4-flash"' in preview.generated


def test_apply_client_config_merges_with_existing_json(tmp_path: Path) -> None:
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"env": {"MY_CUSTOM_VAR": "keep", "ANTHROPIC_BASE_URL": "old"}, "theme": "dark"}\n',
        encoding="utf-8",
    )

    result = apply_client_config(
        "claude",
        _upstream(),
        "http://localhost:1687",
        home=tmp_path,
        backup_suffix="20260625-153000",
    )

    written = config.read_text(encoding="utf-8")
    assert written == result.generated
    assert '"MY_CUSTOM_VAR": "keep"' in written
    assert '"theme": "dark"' in written
    assert '"ANTHROPIC_BASE_URL": "http://localhost:1687"' in written
    assert '"ANTHROPIC_BASE_URL": "old"' not in written


def test_codex_merge_overwrites_existing_rosetta_provider(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'model = "old"\n'
        'custom_setting = "keep"\n'
        "\n"
        "[model_providers.rosetta]\n"
        'base_url = "http://old"\n'
        'wire_api = "chat"\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert 'custom_setting = "keep"' in preview.generated
    assert 'model = "deepseek-v4-flash"' in preview.generated
    assert 'base_url = "http://localhost:1687/v1"' in preview.generated
    assert 'base_url = "http://old"' not in preview.generated
    assert 'wire_api = "responses"' in preview.generated
    assert 'wire_api = "chat"' not in preview.generated


def test_codex_merge_preserves_comments_and_unmanaged_tables(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "# keep top comment\n"
        'model = "old" # keep inline comment\n'
        'custom_setting = "keep"\n'
        "\n"
        "[tui]\n"
        "# keep tui comment\n"
        'theme = "dark"\n'
        "\n"
        "[model_providers.rosetta]\n"
        "# old rosetta block comment can be replaced\n"
        'base_url = "http://old"\n'
        'wire_api = "chat"\n'
        "\n"
        "[model_providers.other]\n"
        'base_url = "http://other"\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://localhost:1687/",
        home=tmp_path,
    )

    assert "# keep top comment" in preview.generated
    assert "# keep inline comment" in preview.generated
    assert '[tui]\n# keep tui comment\ntheme = "dark"' in preview.generated
    assert '[model_providers.other]\nbase_url = "http://other"' in preview.generated
    assert 'model = "deepseek-v4-flash"' in preview.generated
    assert 'base_url = "http://localhost:1687/v1"' in preview.generated
    assert 'base_url = "http://old"' not in preview.generated
    assert preview.generated.count("[model_providers.rosetta]") == 1


def test_codex_clear_removes_rosetta_and_preserves_user_config(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "# keep comment\n"
        'model = "deepseek-v4-flash" # rosetta managed\n'
        'model_provider = "rosetta"\n'
        'custom_setting = "keep"\n'
        "\n"
        "[tui]\n"
        'theme = "dark"\n'
        "\n"
        "[model_providers.rosetta]\n"
        'base_url = "http://localhost:1687"\n'
        'wire_api = "responses"\n'
        "\n"
        "[model_providers.other]\n"
        'base_url = "http://other"\n',
        encoding="utf-8",
    )

    preview = build_client_config_clear_preview("codex", home=tmp_path)

    assert "# keep comment" in preview.generated
    assert 'custom_setting = "keep"' in preview.generated
    assert '[tui]\ntheme = "dark"' in preview.generated
    assert '[model_providers.other]\nbase_url = "http://other"' in preview.generated
    assert 'model = "deepseek-v4-flash"' not in preview.generated
    assert 'model_provider = "rosetta"' not in preview.generated
    assert "[model_providers.rosetta]" not in preview.generated


def test_codex_clear_compacts_blank_lines_after_removing_rosetta_config(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'custom_setting = "keep"\n'
        'model = "deepseek-v4-flash"\n'
        'model_provider = "rosetta"\n'
        "model_context_window = 1047576\n"
        "model_auto_compact_token_limit = 105197\n"
        "\n"
        "[model_providers.rosetta]\n"
        'base_url = "http://localhost:1687/v1"\n'
        'wire_api = "responses"\n'
        "\n"
        "\n"
        "[tui]\n"
        'theme = "dark"\n'
        "\n"
        "[history]\n"
        'persistence = "save-all"\n',
        encoding="utf-8",
    )

    preview = build_client_config_clear_preview("codex", home=tmp_path)

    assert preview.generated == (
        'custom_setting = "keep"\n\n[tui]\ntheme = "dark"\n\n[history]\npersistence = "save-all"\n'
    )


def test_codex_clear_removes_rosetta_table_surrounding_blank_lines(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "[tui]\n"
        'theme = "dark"\n'
        "\n"
        "[model_providers.rosetta]\n"
        'base_url = "http://localhost:1687/v1"\n'
        'wire_api = "responses"\n'
        "\n"
        "[history]\n"
        'persistence = "save-all"\n',
        encoding="utf-8",
    )

    preview = build_client_config_clear_preview("codex", home=tmp_path)

    assert preview.generated == ('[tui]\ntheme = "dark"\n\n[history]\npersistence = "save-all"\n')


def test_claude_clear_removes_rosetta_env_only(tmp_path: Path) -> None:
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"env": {'
        '"ANTHROPIC_BASE_URL": "http://localhost:1687", '
        '"ANTHROPIC_API_KEY": "rosetta-local", '
        '"MY_VAR": "keep"}, '
        '"theme": "dark"}\n',
        encoding="utf-8",
    )

    preview = build_client_config_clear_preview("claude", home=tmp_path)

    assert '"MY_VAR": "keep"' in preview.generated
    assert '"theme": "dark"' in preview.generated
    assert "ANTHROPIC_BASE_URL" not in preview.generated
    assert "ANTHROPIC_API_KEY" not in preview.generated


def test_opencode_clear_removes_rosetta_provider_and_model(tmp_path: Path) -> None:
    config = tmp_path / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"provider": {'
        '"rosetta": {"name": "Rosetta"}, '
        '"openai": {"apiKey": "sk"}}, '
        '"model": "rosetta/deepseek", '
        '"theme": "dark"}\n',
        encoding="utf-8",
    )

    preview = build_client_config_clear_preview("opencode", home=tmp_path)

    assert '"openai"' in preview.generated
    assert '"theme": "dark"' in preview.generated
    assert '"rosetta"' not in preview.generated
    assert '"model"' not in preview.generated


def test_apply_client_config_clear_backs_up_and_writes_generated(tmp_path: Path) -> None:
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{"env": {"ANTHROPIC_BASE_URL": "http://localhost:1687", "MY_VAR": "keep"}}\n',
        encoding="utf-8",
    )

    result = apply_client_config_clear(
        "claude",
        home=tmp_path,
        backup_suffix="20260625-153000",
    )

    assert result.backup_path == tmp_path / ".claude" / "settings.json.bak-20260625-153000"
    assert (
        result.backup_path.read_text(encoding="utf-8")
        == '{"env": {"ANTHROPIC_BASE_URL": "http://localhost:1687", "MY_VAR": "keep"}}\n'
    )
    assert config.read_text(encoding="utf-8") == result.generated
    assert "ANTHROPIC_BASE_URL" not in result.generated
    assert "MY_VAR" in result.generated


def test_codex_merge_inserts_rosetta_provider_before_first_user_table(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        'custom_setting = "keep"\n\n[tui]\ntheme = "dark"\n',
        encoding="utf-8",
    )

    preview = build_client_config_preview(
        "codex",
        _upstream(),
        "http://127.0.0.1:1687/",
        home=tmp_path,
    )

    model_provider_index = preview.generated.index('model_provider = "rosetta"')
    rosetta_table_index = preview.generated.index("[model_providers.rosetta]")
    tui_index = preview.generated.index("[tui]")
    assert model_provider_index < rosetta_table_index < tui_index
    between = preview.generated[model_provider_index:rosetta_table_index]
    assert 'custom_setting = "keep"' not in between
