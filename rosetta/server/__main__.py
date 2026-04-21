"""python -m rosetta.server 入口。

默认绑 127.0.0.1:0 让 OS 分配 ephemeral 端口;uvicorn 启动日志里会打印实际端口,
后续(阶段 1.4)写入 ~/.rosetta/endpoint.json 供 CLI / GUI 发现。
"""

from __future__ import annotations

import uvicorn

from rosetta.server.app import create_app


def main() -> None:
    app = create_app()
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=0,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
