"""CLI 渲染工具:表格 / 状态行 / 错误气泡。

规则
----
- 成功信息:默认颜色(不染色),简洁一行
- 错误 / 失败:stderr 输出,红色
- 表格:rich.Table,边框用 `simple`,标题灰度,保持信息密度
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping
from typing import Any

from rich.console import Console
from rich.table import Table

_stdout = Console()
_stderr = Console(stderr=True, style="red")


def out(msg: str) -> None:
    _stdout.print(msg, highlight=False)


def err(msg: str) -> None:
    _stderr.print(msg, highlight=False)


def die(msg: str, *, code: int = 1) -> None:
    """打印错误到 stderr 并退出。"""
    err(msg)
    sys.exit(code)


def table(columns: list[str], rows: Iterable[Iterable[Any]], *, title: str | None = None) -> None:
    """打印 rich 表格;rows 传任意可迭代,元素会转 str。"""
    t = Table(title=title, show_header=True, header_style="bold")
    for col in columns:
        t.add_column(col)
    for row in rows:
        t.add_row(*(_fmt_cell(v) for v in row))
    _stdout.print(t)


def _fmt_cell(v: Any) -> str:
    if v is None:
        return "-"
    return str(v)


def kv(pairs: Mapping[str, Any]) -> None:
    """打印 key/value 竖表;常用于 status / stats 汇总。"""
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column()
    for k, v in pairs.items():
        t.add_row(k, _fmt_cell(v))
    _stdout.print(t)
