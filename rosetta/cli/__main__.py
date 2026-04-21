"""`rosetta` CLI 入口。

子命令
------
- `rosetta status`
- `rosetta start`
- `rosetta stop`
- `rosetta provider {list,add}`
- `rosetta route {list,add,remove,clear}`
- `rosetta logs [-n N]`
- `rosetta stats [period]`
- `rosetta chat [text]`  # 一次性 / REPL
"""

from __future__ import annotations

import typer

from rosetta.cli.commands import (
    chat as chat_mod,
)
from rosetta.cli.commands import (
    logs as logs_mod,
)
from rosetta.cli.commands import (
    provider as provider_mod,
)
from rosetta.cli.commands import (
    route as route_mod,
)
from rosetta.cli.commands import (
    start as start_mod,
)
from rosetta.cli.commands import (
    stats as stats_mod,
)
from rosetta.cli.commands import (
    status as status_mod,
)
from rosetta.cli.commands import (
    stop as stop_mod,
)

app = typer.Typer(
    name="rosetta",
    help="rosetta — 本地 LLM API 格式转换中枢(CLI)",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

for mod in (
    status_mod,
    start_mod,
    stop_mod,
    provider_mod,
    route_mod,
    logs_mod,
    stats_mod,
    chat_mod,
):
    mod.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
