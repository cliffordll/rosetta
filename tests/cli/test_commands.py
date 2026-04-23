"""CLI 子命令结构测试(阶段 4.2 · 不调 server,只验 typer 接线)。

用 typer.testing.CliRunner 执行 `rosetta` / `rosetta <cmd> --help`,断言:
- 根命令和所有子命令可用(`rosetta --help` 退出 0)
- 每个子命令 `--help` 可显示(证明 register 正确)
- 无效子命令的退出码非 0(typer 默认行为)
- 必填参数缺失时子命令退出码非 0(以 `provider add` 为例)
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from rosetta.cli.__main__ import app

runner = CliRunner()


def test_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # 关键子命令名都出现
    out = result.output
    for sub in ("status", "start", "stop", "upstream", "logs", "stats", "chat"):
        assert sub in out, f"--help 输出里缺少子命令 {sub!r}"


@pytest.mark.parametrize(
    "sub",
    ["status", "start", "stop", "upstream", "logs", "stats", "chat"],
)
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_subcommand_help(sub: str, flag: str) -> None:
    result = runner.invoke(app, [sub, flag])
    assert result.exit_code == 0, (
        f"{sub} {flag} 应成功,实际 exit={result.exit_code}"
    )


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_root_help_accepts_short_and_long(flag: str) -> None:
    result = runner.invoke(app, [flag])
    assert result.exit_code == 0
    assert "rosetta" in result.output


def test_unknown_subcommand_fails() -> None:
    result = runner.invoke(app, ["ghost-cmd"])
    assert result.exit_code != 0


def test_upstream_add_missing_required() -> None:
    """upstream add 缺 --name / --protocol / --api-key 必须报参数错,不发请求。"""
    result = runner.invoke(app, ["upstream", "add"])
    assert result.exit_code != 0


def test_chat_invalid_protocol_fails() -> None:
    """--protocol 必须是 messages/completions/responses;其它值在 argparse 前就报错。"""
    result = runner.invoke(app, ["chat", "--protocol", "bogus", "hi"])
    assert result.exit_code != 0


# ---------- --quiet 全局 flag ----------


def test_quiet_flag_accepted_by_root_help() -> None:
    """根 --help 里有 --quiet / -q 选项。"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--quiet" in result.output
    assert "-q" in result.output


def test_quiet_flag_sets_renderer_state() -> None:
    """--quiet 触发根 callback 后,Renderer.QUIET = True。"""
    from rosetta.cli.core.render import Renderer

    Renderer.QUIET = False  # 保险丝
    # 用一个必然失败的子命令快速走完 callback + 子命令参数校验(不触 server)
    runner.invoke(app, ["--quiet", "chat", "--protocol", "bogus", "hi"])
    assert Renderer.QUIET is True
    Renderer.QUIET = False  # 复位,避免污染后续 test


def test_short_quiet_flag() -> None:
    from rosetta.cli.core.render import Renderer

    Renderer.QUIET = False
    runner.invoke(app, ["-q", "chat", "--protocol", "bogus", "hi"])
    assert Renderer.QUIET is True
    Renderer.QUIET = False
