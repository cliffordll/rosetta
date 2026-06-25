"""Client configuration preview and local file application helpers."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

ClientConfigTarget = Literal["codex", "claude", "opencode"]


class UpstreamLike(Protocol):
    name: str
    model: str | None


@dataclass(frozen=True)
class ClientConfigPreview:
    target: ClientConfigTarget
    path: Path
    exists: bool
    original: str
    generated: str
    language: Literal["toml", "json"]


@dataclass(frozen=True)
class ClientConfigApplyResult(ClientConfigPreview):
    backup_path: Path | None


_FILENAMES: dict[ClientConfigTarget, tuple[str, ...]] = {
    "codex": (".codex", "config.toml"),
    "claude": (".claude", "settings.json"),
    "opencode": (".config", "opencode", "opencode.json"),
}
_LANGUAGES: dict[ClientConfigTarget, Literal["toml", "json"]] = {
    "codex": "toml",
    "claude": "json",
    "opencode": "json",
}


def build_client_config_preview(
    target: ClientConfigTarget,
    upstream: UpstreamLike,
    rosetta_base_url: str,
    *,
    home: Path | None = None,
) -> ClientConfigPreview:
    path = client_config_path(target, home=home)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    return ClientConfigPreview(
        target=target,
        path=path,
        exists=path.exists(),
        original=original,
        generated=build_client_config(target, upstream, rosetta_base_url),
        language=_LANGUAGES[target],
    )


def apply_client_config(
    target: ClientConfigTarget,
    upstream: UpstreamLike,
    rosetta_base_url: str,
    *,
    home: Path | None = None,
    backup_suffix: str | None = None,
) -> ClientConfigApplyResult:
    preview = build_client_config_preview(target, upstream, rosetta_base_url, home=home)
    path = preview.path
    backup_path: Path | None = None

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        suffix = backup_suffix or datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak-{suffix}")
        shutil.copy2(path, backup_path)
    path.write_text(preview.generated, encoding="utf-8")

    return ClientConfigApplyResult(
        target=preview.target,
        path=preview.path,
        exists=preview.exists,
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
        backup_path=backup_path,
    )


def client_config_path(target: ClientConfigTarget, *, home: Path | None = None) -> Path:
    root = home or Path.home()
    return root.joinpath(*_FILENAMES[target])


def build_client_config(
    target: ClientConfigTarget,
    upstream: UpstreamLike,
    rosetta_base_url: str,
) -> str:
    model = (upstream.model or "").strip() or upstream.name
    root_base_url = _trim_trailing_slash(rosetta_base_url)
    match target:
        case "codex":
            return _build_codex_config(model, root_base_url)
        case "claude":
            return _build_claude_config(model, root_base_url)
        case "opencode":
            return _build_opencode_config(model, _with_v1_path(root_base_url))


def _build_codex_config(model: str, root_base_url: str) -> str:
    return f'''# Codex 全局模型设置。上下文窗口远大于自动压缩阈值,适合长对话。
model_context_window = 1047576
model_auto_compact_token_limit = 105197
model = "{_escape_toml(model)}"
model_provider = "rosetta"

# Rosetta 提供方。base_url 指向本地 Rosetta,不要直接填上游地址。
[model_providers.rosetta]
name = "Rosetta"
base_url = "{_escape_toml(root_base_url)}"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
allow_insecure = true
'''


def _build_claude_config(model: str, root_base_url: str) -> str:
    return _json_dumps(
        {
            "env": {
                "ANTHROPIC_BASE_URL": root_base_url,
                "ANTHROPIC_API_KEY": "rosetta-local",
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
            }
        }
    )


def _build_opencode_config(model: str, openai_base_url: str) -> str:
    return _json_dumps(
        {
            "$schema": "https://opencode.ai/config.json",
            "provider": {
                "rosetta": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Rosetta",
                    "options": {
                        "baseURL": openai_base_url,
                        "apiKey": "{env:OPENAI_API_KEY}",
                    },
                    "models": {model: {}},
                }
            },
            "model": f"rosetta/{model}",
        }
    )


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _trim_trailing_slash(value: str) -> str:
    return value.strip().rstrip("/")


def _with_v1_path(base_url: str) -> str:
    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
