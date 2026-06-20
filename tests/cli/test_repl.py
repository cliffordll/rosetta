from types import SimpleNamespace

from rosetta.cli.core.repl import ChatRepl


class FakeCtx:
    def __init__(self) -> None:
        self.model = "claude-test"
        self.server_api = SimpleNamespace(value="messages")

    def set_model(self, model: str | None) -> None:
        self.model = model


class FakeInput:
    async def read(self, prompt: str) -> str:
        return "/exit"


async def test_repl_uses_async_input_reader() -> None:
    ctx = FakeCtx()
    repl = ChatRepl(ctx=ctx, input_reader=FakeInput())  # type: ignore[arg-type]

    await repl.run()


def test_raw_edge_and_step_slash_commands_update_repl_config(monkeypatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=True, raw_edge=10, raw_step=10)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw_edge 3") is False
    assert repl._handle_slash("/raw_step 4") is False

    assert repl.raw_edge == 3
    assert repl.raw_step == 4
    assert "raw_edge → 3" in messages
    assert "raw_step → 4" in messages


def test_raw_slash_command_toggles_raw_mode(monkeypatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=False)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw on") is False
    assert repl.raw is True
    assert repl._handle_slash("/raw off") is False
    assert repl.raw is False

    assert "raw → on" in messages
    assert "raw → off" in messages


def test_raw_slash_command_rejects_unknown_value(monkeypatch) -> None:
    errors: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.error_bubble", errors.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=False)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw maybe") is False

    assert repl.raw is False
    assert errors == ["/raw 参数必须是 on 或 off"]


def test_raw_without_args_shows_current_config(monkeypatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=True)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw") is False

    assert messages == ["raw = on"]


def test_raw_edge_and_step_reject_non_positive_values(monkeypatch) -> None:
    errors: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.error_bubble", errors.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=True, raw_edge=10, raw_step=10)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw_edge 0") is False
    assert repl._handle_slash("/raw_step nope") is False

    assert repl.raw_edge == 10
    assert repl.raw_step == 10
    assert len(errors) == 2
    assert all("必须是正整数" in message for message in errors)


def test_raw_edge_and_step_without_args_show_current_config(monkeypatch) -> None:
    messages: list[str] = []

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=SimpleNamespace(), raw=True, raw_edge=7, raw_step=8)  # type: ignore[arg-type]

    assert repl._handle_slash("/raw_edge") is False
    assert repl._handle_slash("/raw_step") is False

    assert messages == ["raw_edge = 7", "raw_step = 8"]


def test_model_and_server_api_without_args_show_current_config(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/model") is False
    assert repl._handle_slash("/server_api") is False

    assert messages == ["model = claude-test", "server_api = messages"]


def test_model_clear_resets_model_to_auto(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/model clear") is False

    assert ctx.model is None
    assert messages == ["model → auto(用 upstream.model 兜底)"]
