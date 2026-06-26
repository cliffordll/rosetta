"""Client configuration preview and local file application helpers."""

from __future__ import annotations

import json
import re
import shutil
import tomllib as _toml
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

ClientConfigTarget = Literal["codex", "claude", "opencode"]

# Rosetta 在 codex TOML 配置中控制的顶层 key, merge 时只覆盖这些。
_ROSETTA_CODEX_KEYS: frozenset[str] = frozenset(
    {
        "model_context_window",
        "model_auto_compact_token_limit",
        "model",
        "model_provider",
    }
)
_ROSETTA_CLAUDE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
    }
)


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
        generated=build_client_config(target, upstream, rosetta_base_url, original=original),
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
        exists=True,
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
        backup_path=backup_path,
    )


def build_client_config_clear_preview(
    target: ClientConfigTarget,
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
        generated=clear_client_config(target, original),
        language=_LANGUAGES[target],
    )


def apply_client_config_clear(
    target: ClientConfigTarget,
    *,
    home: Path | None = None,
    backup_suffix: str | None = None,
) -> ClientConfigApplyResult:
    preview = build_client_config_clear_preview(target, home=home)
    backup_path: Path | None = None

    if preview.path.exists():
        suffix = backup_suffix or datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = preview.path.with_name(f"{preview.path.name}.bak-{suffix}")
        shutil.copy2(preview.path, backup_path)
        preview.path.write_text(preview.generated, encoding="utf-8")

    return ClientConfigApplyResult(
        target=preview.target,
        path=preview.path,
        exists=preview.path.exists(),
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
        backup_path=backup_path,
    )


def clear_client_config(target: ClientConfigTarget, original: str) -> str:
    if not original:
        return ""
    match target:
        case "codex":
            return _clear_codex_config(original)
        case "claude":
            return _clear_claude_config(original)
        case "opencode":
            return _clear_opencode_config(original)


def client_config_path(target: ClientConfigTarget, *, home: Path | None = None) -> Path:
    root = home or Path.home()
    return root.joinpath(*_FILENAMES[target])


def build_client_config(
    target: ClientConfigTarget,
    upstream: UpstreamLike,
    rosetta_base_url: str,
    *,
    original: str = "",
) -> str:
    model = (upstream.model or "").strip() or upstream.name
    root_base_url = _trim_trailing_slash(rosetta_base_url)
    match target:
        case "codex":
            return _build_codex_config(model, root_base_url, original=original)
        case "claude":
            return _build_claude_config(model, root_base_url, original=original)
        case "opencode":
            return _build_opencode_config(model, _with_v1_path(root_base_url), original=original)


def _clear_codex_config(original: str) -> str:
    text = original.replace("\r\n", "\n")
    text = _remove_top_level_toml_keys(text, _ROSETTA_CODEX_KEYS)
    text = _remove_toml_table(text, "model_providers.rosetta")
    text = _remove_empty_toml_table(text, "model_providers")
    text = _compact_toml_blank_lines(text)
    return text.rstrip() + "\n" if text.strip() else ""


def _clear_claude_config(original: str) -> str:
    try:
        data = json.loads(original)
    except json.JSONDecodeError:
        return original
    if not isinstance(data, dict):
        return original

    cleaned = dict(data)
    env = cleaned.get("env")
    if isinstance(env, dict):
        next_env = {k: v for k, v in env.items() if k not in _ROSETTA_CLAUDE_ENV_KEYS}
        if next_env:
            cleaned["env"] = next_env
        else:
            cleaned.pop("env", None)
    return _json_dumps(cleaned)


def _clear_opencode_config(original: str) -> str:
    try:
        data = json.loads(original)
    except json.JSONDecodeError:
        return original
    if not isinstance(data, dict):
        return original

    cleaned = dict(data)
    provider = cleaned.get("provider")
    if isinstance(provider, dict):
        next_provider = dict(provider)
        next_provider.pop("rosetta", None)
        if next_provider:
            cleaned["provider"] = next_provider
        else:
            cleaned.pop("provider", None)

    if isinstance(cleaned.get("model"), str) and cleaned["model"].startswith("rosetta/"):
        cleaned.pop("model", None)
    return _json_dumps(cleaned)


def _build_codex_config(model: str, root_base_url: str, *, original: str = "") -> str:
    rosetta = _codex_rosetta_config(model, _with_v1_path(root_base_url))
    if not original or not original.strip():
        return _toml_dumps(rosetta)

    try:
        base = _toml.loads(original)
    except _toml.TOMLDecodeError:
        return _toml_dumps(rosetta)

    if not isinstance(base, dict):
        return _toml_dumps(rosetta)

    return _patch_codex_toml(original, rosetta)


def _codex_rosetta_config(model: str, root_base_url: str) -> dict[str, object]:
    return {
        "model_context_window": 1047576,
        "model_auto_compact_token_limit": 105197,
        "model": model,
        "model_provider": "rosetta",
        "model_providers": {
            "rosetta": {
                "name": "Rosetta",
                "base_url": root_base_url,
                "env_key": "OPENAI_API_KEY",
                "wire_api": "responses",
                "allow_insecure": True,
            }
        },
    }


def _remove_top_level_toml_keys(text: str, keys: frozenset[str]) -> str:
    lines = text.splitlines()
    table_start = next(
        (i for i, line in enumerate(lines) if _is_toml_table_header(line)), len(lines)
    )
    kept: list[str] = []
    for i, line in enumerate(lines):
        if i < table_start:
            match = re.match(r"^\s*([A-Za-z0-9_-]+)\s*=", line)
            if match is not None and match.group(1) in keys:
                continue
        kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _remove_toml_table(text: str, table: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{table}]"), None)
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and not _is_toml_table_header(lines[end]):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1

    has_before_blank = start > 0 and not lines[start - 1].strip()
    has_after_blank = end < len(lines) and not lines[end].strip()
    has_before_content = any(line.strip() for line in lines[:start])
    has_after_content = any(line.strip() for line in lines[end:])

    delete_start = start
    delete_end = end
    if has_before_blank and has_after_blank:
        delete_start = start - 1
        delete_end = end if has_before_content and has_after_content else end + 1
    elif has_before_blank:
        delete_start = start - 1
    elif has_after_blank:
        delete_end = end + 1
    del lines[delete_start:delete_end]
    return "\n".join(lines).rstrip() + "\n"


def _remove_empty_toml_table(text: str, table: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{table}]"), None)
    if start is None:
        return text
    end = start + 1
    meaningful = [line for line in lines[end:] if line.strip()]
    if meaningful and not _is_toml_table_header(meaningful[0]):
        return text
    del lines[start:end]
    return "\n".join(lines).rstrip() + "\n"


def _compact_toml_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    compacted: list[str] = []
    blank_pending = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank:
            blank_pending = True
            continue

        if blank_pending and compacted:
            compacted.append("")
        compacted.append(line)
        blank_pending = False
    return "\n".join(compacted) + ("\n" if compacted else "")


def _patch_codex_toml(original: str, rosetta: dict[str, object]) -> str:
    text = original.replace("\r\n", "\n")
    text = _patch_top_level_toml_keys(text, {k: rosetta[k] for k in _ROSETTA_CODEX_KEYS})
    provider = rosetta["model_providers"]
    assert isinstance(provider, dict)
    rosetta_provider = provider["rosetta"]
    assert isinstance(rosetta_provider, dict)
    return _patch_toml_table(text, "model_providers.rosetta", rosetta_provider)


def _patch_top_level_toml_keys(text: str, values: dict[str, object]) -> str:
    lines = text.splitlines()
    table_start = next(
        (i for i, line in enumerate(lines) if _is_toml_table_header(line)), len(lines)
    )
    seen: set[str] = set()

    for i in range(table_start):
        match = re.match(r"^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)(.*)$", lines[i])
        if match is None:
            continue
        key = match.group(2)
        if key not in values:
            continue
        value_part = match.group(4)
        comment_at = _inline_comment_index(value_part)
        comment = f" {value_part[comment_at:].strip()}" if comment_at is not None else ""
        lines[i] = f"{match.group(1)}{key}{match.group(3)}{_toml_value(values[key])}{comment}"
        seen.add(key)

    missing = [key for key in sorted(values) if key not in seen]
    if missing:
        inserted = [f"{key} = {_toml_value(values[key])}" for key in missing]
        lines[table_start:table_start] = inserted + ([""] if table_start < len(lines) else [])
    return "\n".join(lines).rstrip() + "\n"


def _patch_toml_table(text: str, table: str, values: dict[str, object]) -> str:
    block = _toml_table_block(table, values)
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip() == f"[{table}]"),
        None,
    )
    if start is None:
        insert_at = next(
            (i for i, line in enumerate(lines) if _is_toml_table_header(line)), len(lines)
        )
        block_lines = ["", *block.rstrip().splitlines()]
        if insert_at < len(lines):
            block_lines.append("")
        lines[insert_at:insert_at] = block_lines
        return "\n".join(lines).rstrip() + "\n"

    end = start + 1
    while end < len(lines) and not _is_toml_table_header(lines[end]):
        end += 1
    lines[start:end] = block.rstrip().splitlines()
    return "\n".join(lines).rstrip() + "\n"


def _toml_table_block(table: str, values: dict[str, object]) -> str:
    lines = [f"[{table}]"]
    for key in sorted(values):
        lines.append(f"{key} = {_toml_value(values[key])}")
    return "\n".join(lines) + "\n"


def _is_toml_table_header(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def _inline_comment_index(value: str) -> int | None:
    in_string = False
    escaped = False
    for i, ch in enumerate(value):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if ch == "#" and not in_string:
            return i
    return None


def _build_claude_config(model: str, root_base_url: str, *, original: str = "") -> str:
    rosetta_env = {
        "ANTHROPIC_BASE_URL": root_base_url,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
    }
    if not original or not original.strip():
        return _json_dumps({"env": rosetta_env})

    try:
        base = json.loads(original)
    except json.JSONDecodeError:
        return _json_dumps({"env": rosetta_env})

    if not isinstance(base, dict):
        return _json_dumps({"env": rosetta_env})

    merged = dict(base)
    user_env = base.get("env", {})
    if isinstance(user_env, dict):
        merged_env = {k: v for k, v in user_env.items() if k not in _ROSETTA_CLAUDE_ENV_KEYS}
        merged_env.update(rosetta_env)
        merged["env"] = merged_env
    else:
        merged["env"] = rosetta_env

    return _json_dumps(merged)


def _build_opencode_config(model: str, openai_base_url: str, *, original: str = "") -> str:
    rosetta_provider = {
        "rosetta": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Rosetta",
            "options": {
                "baseURL": openai_base_url,
                "apiKey": "{env:OPENAI_API_KEY}",
            },
            "models": {model: {}},
        },
    }
    rosetta_model = f"rosetta/{model}"

    if not original or not original.strip():
        return _json_dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "provider": rosetta_provider,
                "model": rosetta_model,
            }
        )

    try:
        base = json.loads(original)
    except json.JSONDecodeError:
        return _json_dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "provider": rosetta_provider,
                "model": rosetta_model,
            }
        )

    if not isinstance(base, dict):
        return _json_dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "provider": rosetta_provider,
                "model": rosetta_model,
            }
        )

    merged = dict(base)
    merged["$schema"] = "https://opencode.ai/config.json"
    merged["model"] = rosetta_model

    user_providers = base.get("provider", {})
    if isinstance(user_providers, dict):
        merged_providers = dict(user_providers)
        merged_providers["rosetta"] = rosetta_provider["rosetta"]
        merged["provider"] = merged_providers
    else:
        merged["provider"] = rosetta_provider

    return _json_dumps(merged)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _trim_trailing_slash(value: str) -> str:
    return value.strip().rstrip("/")


def _with_v1_path(base_url: str) -> str:
    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(val: object) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return f'"{_escape_toml(val)}"'
    if isinstance(val, list):
        return "[" + ", ".join(_toml_value(v) for v in val) + "]"
    if isinstance(val, dict):
        # inline table: 只处理 scalar 值 (TOML inline-table 语法)
        if not val:
            return "{}"
        items = ", ".join(f"{k} = {_toml_value(v)}" for k, v in sorted(val.items()))
        return f"{{ {items} }}"
    raise ValueError(f"unsupported TOML type: {type(val).__name__}")


def _toml_dumps(data: dict) -> str:
    """dict -> TOML 序列化, 只处理标量 + table 两层嵌套。"""
    lines: list[str] = []
    _toml_emit(data, lines)
    lines.append("")
    return "\n".join(lines)


def _toml_emit(data: dict, lines: list[str], *, prefix: str | None = None) -> None:
    scalars: dict[str, object] = {}
    tables: dict[str, dict[str, object]] = {}
    for k, v in data.items():
        if isinstance(v, dict) and v:
            tables[k] = v
        else:
            scalars[k] = v

    for k in sorted(scalars):
        lines.append(f"{k} = {_toml_value(scalars[k])}")
    for k in sorted(tables):
        path = f"{prefix}.{k}" if prefix else k
        lines.append("")
        lines.append(f"[{path}]")
        _toml_emit(tables[k], lines, prefix=path)
