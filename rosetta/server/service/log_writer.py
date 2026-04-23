"""请求流水落库封装:把 forwarder / controller 想记的一条 log 写进 `logs` 表。

架构决策
--------
- 服务层不接受 request-scoped session;`LogWriter` 自己从 `database.session._state`
  取 session_maker 按需开 session。与 `count_upstreams` 同套路
- 失败兜底:写 log 出任何异常都不向上冒(主请求已经完成),只 `logger.warning`
  —— DB 坏了不能把业务路径也拖垮
- model 提取惯例:非 responses 协议看 body_dict["model"];responses 同上
- 不做采样 / 批量,单机场景下 SQLite INSERT 成本可接受(~ms 级)

用法
----
`log_writer.record(...)` 或 forwarder 组合好字段后调用。本模块暴露单例
`log_writer`,与 `Forwarder` / `MockResponder` 的"类 + 单例"风格一致。
"""

from __future__ import annotations

import logging
from typing import Literal

from rosetta.server.database.session import get_session_maker
from rosetta.server.repository.log import LogRepo

_log = logging.getLogger("rosetta.server.log_writer")

LogStatus = Literal["ok", "error", "timeout"]


class LogWriter:
    """logs 表写入器(服务层单例)。失败兜底,不向上冒异常。"""

    async def record(
        self,
        *,
        upstream_id: str | None,
        model: str | None,
        status: LogStatus,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        """写一条 log。DB 未初始化 / 写失败只打 logger,不抛。"""
        session_maker = get_session_maker()
        if session_maker is None:
            _log.debug("log_writer: session_maker 未初始化,跳过落库")
            return
        try:
            async with session_maker() as session:
                await LogRepo(session).create(
                    upstream_id=upstream_id,
                    model=model,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    error=error,
                )
        except Exception as e:
            _log.warning(
                "log_writer: 写入失败,忽略 (status=%s, upstream_id=%s): %s",
                status, upstream_id, e,
            )


log_writer = LogWriter()
