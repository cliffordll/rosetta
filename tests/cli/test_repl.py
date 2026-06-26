from types import SimpleNamespace

from rosetta.cli.core.repl import ChatRepl


class FakeCtx:
    def __init__(self) -> None:
        self.model = "claude-test"
        self.upstream = "ant-main"
        self.api_key = None
        self.max_tokens = 1024
        self.stream = True
        self.server_api = SimpleNamespace(value="messages")

    def set_model(self, model: str | None) -> None:
        self.model = model

    def set_upstream(self, upstream: str | None) -> None:
        self.upstream = upstream

    def set_api_key(self, api_key: str | None) -> None:
        self.api_key = api_key

    def set_max_tokens(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    def set_stream(self, stream: bool) -> None:
        self.stream = stream


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


def test_slash_commands_without_args_show_current_config(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/model") is False
    assert repl._handle_slash("/upstream") is False
    assert repl._handle_slash("/api_key") is False
    assert repl._handle_slash("/server_api") is False

    assert messages == [
        "model = claude-test",
        "upstream = ant-main",
        "api_key = 不覆盖(走 upstream.api_key)",
        "server_api = messages",
    ]


def test_model_clear_resets_model_to_auto(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/model clear") is False

    assert ctx.model is None
    assert messages == ["model → auto(用 upstream.model 兜底)"]


def test_upstream_slash_command_sets_and_clears_upstream(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/upstream u-openai-main") is False
    assert ctx.upstream == "u-openai-main"
    assert repl._handle_slash("/upstream clear") is False
    assert ctx.upstream is None

    assert messages == ["upstream → u-openai-main", "upstream → auto(按 model 匹配)"]


def test_api_key_slash_command_sets_and_clears_override(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/api_key sk-test") is False
    assert ctx.api_key == "sk-test"
    assert repl._handle_slash("/api_key clear") is False
    assert ctx.api_key is None

    assert messages == ["api_key → 覆盖中", "api_key → 不覆盖(走 upstream.api_key)"]


def test_max_tokens_slash_command_without_arg_shows_current(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()
    ctx.max_tokens = 4096

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/max_tokens") is False
    assert messages == ["max_tokens = 4096"]


def test_max_tokens_slash_command_sets_value(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()
    ctx.max_tokens = 1024

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/max_tokens 8192") is False
    assert ctx.max_tokens == 8192
    assert messages == ["max_tokens → 8192"]


def test_max_tokens_slash_command_rejects_non_positive(monkeypatch) -> None:
    errors: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.error_bubble", errors.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/max_tokens 0") is False
    assert repl._handle_slash("/max_tokens nope") is False
    assert ctx.max_tokens == 1024  # unchanged
    assert len(errors) == 2
    assert all("必须是正整数" in msg for msg in errors)


def test_stream_slash_command_without_arg_shows_current(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()
    ctx.stream = False

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/stream") is False
    assert messages == ["stream = off"]


def test_stream_slash_command_turns_on(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()
    ctx.stream = False

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/stream on") is False
    assert ctx.stream is True
    assert messages == ["stream → on"]


def test_stream_slash_command_turns_off(monkeypatch) -> None:
    messages: list[str] = []
    ctx = FakeCtx()
    ctx.stream = True

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.out", messages.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/stream off") is False
    assert ctx.stream is False
    assert messages == ["stream → off"]


def test_stream_slash_command_rejects_unknown_value(monkeypatch) -> None:
    errors: list[str] = []
    ctx = FakeCtx()

    monkeypatch.setattr("rosetta.cli.core.repl.Renderer.error_bubble", errors.append)

    repl = ChatRepl(ctx=ctx)  # type: ignore[arg-type]

    assert repl._handle_slash("/stream maybe") is False
    assert ctx.stream is True  # unchanged
    assert errors == ["/stream 参数必须是 on 或 off"]
