from rosetta.cli.core.prompt import complete_repl_input


def test_repl_prompt_completes_slash_commands() -> None:
    labels = [item.text for item in complete_repl_input("/ra")]

    assert "/raw" in labels
    assert "/raw_edge" in labels
    assert "/raw_step" in labels


def test_repl_prompt_completes_server_api_values() -> None:
    labels = [item.text for item in complete_repl_input("/server_api ")]

    assert labels == ["messages", "completions", "responses"]


def test_repl_prompt_completes_raw_values() -> None:
    labels = [item.text for item in complete_repl_input("/raw ")]

    assert labels == ["on", "off"]


def test_repl_prompt_completes_model_clear() -> None:
    labels = [item.text for item in complete_repl_input("/model ")]

    assert labels == ["clear"]
