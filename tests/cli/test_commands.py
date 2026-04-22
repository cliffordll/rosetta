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
    for sub in ("status", "start", "stop", "provider", "route", "logs", "stats", "chat"):
        assert sub in out, f"--help 输出里缺少子命令 {sub!r}"


@pytest.mark.parametrize(
    "sub",
    ["status", "start", "stop", "provider", "route", "logs", "stats", "chat"],
)
def test_subcommand_help(sub: str) -> None:
    result = runner.invoke(app, [sub, "--help"])
    assert result.exit_code == 0, f"{sub} --help 应成功,实际 exit={result.exit_code}"


def test_unknown_subcommand_fails() -> None:
    result = runner.invoke(app, ["ghost-cmd"])
    assert result.exit_code != 0


def test_provider_add_missing_required() -> None:
    """provider add 缺 --name / --type / --api-key 必须报参数错,不发请求。"""
    result = runner.invoke(app, ["provider", "add"])
    assert result.exit_code != 0


def test_chat_invalid_format_fails() -> None:
    """--format 必须是 messages/completions/responses;其它值在 argparse 前就报错。"""
    result = runner.invoke(app, ["chat", "--format", "bogus", "hi"])
    assert result.exit_code != 0
