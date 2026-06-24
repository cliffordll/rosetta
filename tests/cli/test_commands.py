"""CLI 子命令结构测试(阶段 4.2 · 不调 server,只验 typer 接线)。

用 typer.testing.CliRunner 执行 `rosetta` / `rosetta <cmd> --help`,断言:
- 根命令和所有子命令可用(`rosetta --help` 退出 0)
- 每个子命令 `--help` 可显示(证明 register 正确)
- 无效子命令的退出码非 0(typer 默认行为)
- 必填参数缺失时子命令退出码非 0(以 `provider add` 为例)
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from rosetta.cli.__main__ import app
from rosetta.cli.commands import chat as chat_mod
from rosetta.cli.commands import logs as logs_mod
from rosetta.cli.commands import upstream as upstream_mod

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """剥 ANSI 颜色 / 样式转义,方便 substring 断言跨平台稳定。"""
    return _ANSI_RE.sub("", text)


@pytest.fixture(autouse=True)
def _wide_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """两件事:
    1. COLUMNS=200 —— CI 终端比本地窄,rich 会把 `--quiet` 等 option 换行拆开
    2. NO_COLOR=1 + TERM=dumb —— 禁 rich 在 help 里插 ANSI 颜色码,否则
       `\\x1b[1m--quiet` 里虽然含 --quiet,但 rich 可能把 `--` 和 `quiet`
       分别上色导致中间插入转义 → substring 断言失败
    """
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    # Windows CI runner 默认 stdout 用 cp1252,中文 option help 编码失败崩
    # 测试;Linux 默认 utf-8 不受影响。统一强制 utf-8。
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")


def test_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # 关键子命令名都出现
    out = _plain(result.output)
    for sub in ("status", "start", "stop", "upstream", "logs", "stats", "chat"):
        assert sub in out, f"--help 输出里缺少子命令 {sub!r}"


@pytest.mark.parametrize(
    "sub",
    ["status", "start", "stop", "upstream", "logs", "stats", "chat"],
)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_subcommand_help(sub: str, flag: str) -> None:
    result = runner.invoke(app, [sub, flag])
    assert result.exit_code == 0, f"{sub} {flag} 应成功,实际 exit={result.exit_code}"


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_root_help_accepts_short_and_long(flag: str) -> None:
    result = runner.invoke(app, [flag])
    assert result.exit_code == 0
    assert "rosetta" in _plain(result.output)


def test_unknown_subcommand_fails() -> None:
    result = runner.invoke(app, ["ghost-cmd"])
    assert result.exit_code != 0


def test_upstream_add_missing_required() -> None:
    """upstream add 缺 --name / --base-url 必须报参数错,不发请求。"""
    result = runner.invoke(app, ["upstream", "add"])
    assert result.exit_code != 0


def test_upstream_default_help_exists() -> None:
    result = runner.invoke(app, ["upstream", "default", "--help"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "--model" in out
    assert "default" in out


def test_upstream_defaults_help_exists() -> None:
    result = runner.invoke(app, ["upstream", "defaults", "--help"])
    assert result.exit_code == 0
    assert "defaults" in _plain(result.output)


def test_upstream_test_help_exists() -> None:
    result = runner.invoke(app, ["upstream", "test", "--help"])
    assert result.exit_code == 0
    assert "test" in _plain(result.output)


def test_upstream_guide_help_exists() -> None:
    result = runner.invoke(app, ["upstream", "guide", "--help"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "codex" in out
    assert "claude" in out


def test_upstream_guide_prints_provider_doc_path() -> None:
    result = runner.invoke(app, ["upstream", "guide", "codex"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "docs" in out
    assert "providers" in out
    assert "codex.md" in out


def test_upstream_list_table_omits_default_column(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        async def list_upstreams(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    id="u1",
                    name="main",
                    native_api="messages",
                    provider="anthropic",
                    model=None,
                    base_url="https://api.example.com",
                    enabled=True,
                    test_result=None,
                )
            ]

    @asynccontextmanager
    async def _discover_session(**_: object):
        yield _FakeClient()

    def _capture_table(columns: list[str], rows: list[list[object]], **kwargs: object) -> None:
        captured["columns"] = columns
        captured["rows"] = rows
        captured["kwargs"] = kwargs

    monkeypatch.setattr(upstream_mod.ProxyClient, "discover_session", _discover_session)
    monkeypatch.setattr(upstream_mod.Renderer, "table", _capture_table)

    asyncio.run(upstream_mod._list())

    assert captured["columns"] == [
        "id",
        "name",
        "native_api",
        "provider",
        "model",
        "base_url",
        "enabled",
        "test",
    ]
    assert captured["rows"] == [
        [
            "u1",
            "main",
            "messages (/v1/messages)",
            "anthropic",
            "-",
            "https://api.example.com",
            True,
            "-",
        ]
    ]
    assert captured["kwargs"] == {
        "no_wrap_columns": {"id", "name", "provider", "enabled", "test"},
        "max_widths": {"base_url": 52, "model": 32},
    }


def test_upstream_model_defaults_renders_model_table(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        async def list_model_defaults(self) -> dict[str, str]:
            return {"gpt-4o": "oai"}

    @asynccontextmanager
    async def _discover_session(**_: object):
        yield _FakeClient()

    def _capture_table(columns: list[str], rows: list[list[object]], **kwargs: object) -> None:
        captured["columns"] = columns
        captured["rows"] = rows
        captured["kwargs"] = kwargs

    monkeypatch.setattr(upstream_mod.ProxyClient, "discover_session", _discover_session)
    monkeypatch.setattr(upstream_mod.Renderer, "table", _capture_table)

    asyncio.run(upstream_mod._model_defaults())

    assert captured["columns"] == ["model", "upstream"]
    assert captured["rows"] == [["gpt-4o", "oai"]]


def test_upstream_test_renders_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        async def test_upstream(self, upstream_id: str) -> SimpleNamespace:
            captured["upstream_id"] = upstream_id
            return SimpleNamespace(
                ok=True,
                upstream_id=upstream_id,
                upstream_name="oai",
                native_api="completions",
                status_code=200,
                category="ok",
                summary="request succeeded with configured api_key/model",
                detail=None,
            )

    @asynccontextmanager
    async def _discover_session(**_: object):
        yield _FakeClient()

    def _capture_out(msg: str) -> None:
        captured["msg"] = msg

    monkeypatch.setattr(upstream_mod.ProxyClient, "discover_session", _discover_session)
    monkeypatch.setattr(upstream_mod.Renderer, "out", _capture_out)

    asyncio.run(upstream_mod._test("u1"))

    assert captured["upstream_id"] == "u1"
    assert "OK" in str(captured["msg"])
    assert "oai" in str(captured["msg"])
    assert "completions (/v1/chat/completions)" in str(captured["msg"])


def test_logs_config_help_exists() -> None:
    result = runner.invoke(app, ["logs", "config", "--help"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "--log-content" in out
    assert "--page-size" in out


def test_logs_clear_help_exists() -> None:
    result = runner.invoke(app, ["logs", "clear", "--help"])
    assert result.exit_code == 0
    assert "--yes" in _plain(result.output)


def test_logs_clear_requires_yes() -> None:
    result = runner.invoke(app, ["logs", "clear"])
    assert result.exit_code != 0
    assert "--yes" in _plain(result.output)


def test_logs_clear_yes_invokes_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _capture_clear() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(logs_mod, "_clear", _capture_clear)

    result = runner.invoke(app, ["logs", "clear", "--yes"])

    assert result.exit_code == 0
    assert called is True


def test_chat_invalid_server_api_fails() -> None:
    """--server-api 必须是 messages/completions/responses;其它值在命令入口报错。"""
    result = runner.invoke(app, ["chat", "--server-api", "bogus", "hi"])
    assert result.exit_code != 0


def test_chat_raw_help_uses_short_raw_option_names() -> None:
    result = runner.invoke(app, ["chat", "--help"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "--raw" in out
    assert "--raw-edge" in out
    assert "--raw-step" in out
    assert "--raw-full" in out
    assert "--raw-edge-frames" not in out
    assert "--raw-expand-step" not in out
    assert "交互展开" in out
    assert "每步展开" not in out


def test_chat_raw_repl_passes_raw_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--raw", "--raw-edge", "3", "--raw-step", "4"])

    assert result.exit_code == 0
    assert captured["text"] is None
    assert captured["raw"] is True
    assert captured["raw_edge"] == 3
    assert captured["raw_step"] == 4


def test_chat_raw_repl_uses_raw_edge_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--raw"])

    assert result.exit_code == 0
    assert captured["raw_edge"] == 5
    assert captured["raw_step"] == 10


# ---------- --quiet 全局 flag ----------


def test_quiet_flag_accepted_by_root_help() -> None:
    """根 --help 里有 --quiet / -q 选项。"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    out = _plain(result.output)
    assert "--quiet" in out
    assert "-q" in out


def test_quiet_flag_sets_renderer_state() -> None:
    """--quiet 触发根 callback 后,Renderer.QUIET = True。"""
    from rosetta.cli.core.render import Renderer

    Renderer.QUIET = False  # 保险丝
    # 用一个必然失败的子命令快速走完 callback + 子命令参数校验(不触 server)
    runner.invoke(app, ["--quiet", "chat", "--server-api", "bogus", "hi"])
    assert Renderer.QUIET is True
    Renderer.QUIET = False  # 复位,避免污染后续 test


def test_short_quiet_flag() -> None:
    from rosetta.cli.core.render import Renderer

    Renderer.QUIET = False
    runner.invoke(app, ["-q", "chat", "--server-api", "bogus", "hi"])
    assert Renderer.QUIET is True
    Renderer.QUIET = False


# ---------- --api-key / --model sentinel normalization ----------


def test_chat_api_key_sentinel_none_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """--api-key=none 应被规范化为 None,不会作为真实 key 透传。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--api-key", "none", "--upstream", "mock", "hi"])

    assert result.exit_code == 0, f"exit={result.exit_code}, out={result.output!r}"
    assert captured.get("api_key") is None, f"api_key 应为 None,实际={captured['api_key']!r}"


def test_chat_api_key_sentinel_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """--api-key=None / NONE 也应规范化为 None(大小写不敏感)。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--api-key", "None", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    assert captured.get("api_key") is None


def test_chat_api_key_empty_string_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """--api-key="" 是 falsy 值,不会被发送 auth header(行为等价于 None)。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--api-key", "", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    # 空串是 falsy,不会被 sentinel 处理,保持原值
    assert captured.get("api_key") == ""


def test_chat_api_key_real_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实的 --api-key=sk-xxx 不应被修改。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--api-key", "sk-real-key", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    assert captured.get("api_key") == "sk-real-key"


def test_chat_omitted_api_key_stays_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 --api-key 时(选项缺省),api_key 仍为 None。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    # 未传 --api-key → 参数默认值 None,断言两个路径都收敛到 None
    assert captured.get("api_key") is None


def test_chat_model_sentinel_none_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """--model=none 应被规范化为 None。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--model", "none", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    assert captured.get("model") is None, f"model 应为 None,实际={captured['model']!r}"


def test_chat_model_real_value_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实的 --model=claude-4 不应被修改。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(app, ["chat", "--model", "claude-4", "--upstream", "mock", "hi"])

    assert result.exit_code == 0
    assert captured.get("model") == "claude-4"


def test_chat_direct_mode_rejects_sentinel_api_key() -> None:
    """--base-url 模式下 --api-key=none 应因为规范化为 None 而触达必填校验。"""
    result = runner.invoke(
        app,
        [
            "chat",
            "--base-url",
            "https://api.example.com",
            "--api-key",
            "none",
            "--model",
            "claude-4",
            "hi",
        ],
    )
    # sentinel 规范化为 None → if not api_key → Renderer.die → typer 视为用户错误
    assert result.exit_code != 0


def test_chat_direct_mode_real_api_key_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """--base-url 模式下传入真实 api_key 不应报错。"""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(chat_mod, "_run", _capture_run)

    result = runner.invoke(
        app,
        [
            "chat",
            "--base-url",
            "https://api.example.com",
            "--api-key",
            "sk-real",
            "--model",
            "claude-4",
            "hi",
        ],
    )

    assert result.exit_code == 0
    assert captured.get("api_key") == "sk-real"


def test_chat_run_uses_server_stream_config_when_cli_omits_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        mode = "server"

        async def chat_config(self) -> SimpleNamespace:
            return SimpleNamespace(max_tokens=2048, stream=False)

    @asynccontextmanager
    async def _fake_session(**_: object):
        yield _FakeClient()

    class _FakeOnce:
        def __init__(self, ctx: object, **_: object) -> None:
            captured["stream"] = ctx.stream
            captured["max_tokens"] = ctx.max_tokens

        async def run(self, text: str) -> None:
            captured["text"] = text

    monkeypatch.setattr(chat_mod, "_session", _fake_session)
    from rosetta.cli.core import once as once_mod

    monkeypatch.setattr(once_mod, "ChatOnce", _FakeOnce)

    asyncio.run(
        chat_mod._run(
            text="hi",
            server_api=chat_mod.ServerApi.MESSAGES,
            model=None,
            upstream=None,
            api_key=None,
            base_url=None,
            max_tokens=8192,
            stream=None,
            raw=False,
            raw_edge=5,
            raw_step=10,
            raw_full=False,
        )
    )

    assert captured["stream"] is False
    assert captured["max_tokens"] == 2048


def test_chat_run_no_stream_overrides_server_stream_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeClient:
        mode = "server"

        async def chat_config(self) -> SimpleNamespace:
            return SimpleNamespace(max_tokens=2048, stream=True)

    @asynccontextmanager
    async def _fake_session(**_: object):
        yield _FakeClient()

    class _FakeOnce:
        def __init__(self, ctx: object, **_: object) -> None:
            captured["stream"] = ctx.stream

        async def run(self, text: str) -> None:
            captured["text"] = text

    monkeypatch.setattr(chat_mod, "_session", _fake_session)
    from rosetta.cli.core import once as once_mod

    monkeypatch.setattr(once_mod, "ChatOnce", _FakeOnce)

    asyncio.run(
        chat_mod._run(
            text="hi",
            server_api=chat_mod.ServerApi.MESSAGES,
            model=None,
            upstream=None,
            api_key=None,
            base_url=None,
            max_tokens=8192,
            stream=False,
            raw=False,
            raw_edge=5,
            raw_step=10,
            raw_full=False,
        )
    )

    assert captured["stream"] is False
