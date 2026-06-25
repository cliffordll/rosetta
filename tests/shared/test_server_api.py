from __future__ import annotations

from rosetta.shared.server_api import ServerApi, upstream_endpoint_url


def test_upstream_endpoint_url_allows_base_url_with_path_prefix() -> None:
    assert (
        upstream_endpoint_url("https://gateway.example.com/proxy/ant/", ServerApi.MESSAGES)
        == "https://gateway.example.com/proxy/ant/v1/messages"
    )


def test_upstream_endpoint_url_does_not_duplicate_v1_prefix() -> None:
    assert (
        upstream_endpoint_url("https://api.openai.com/v1", ServerApi.CHAT_COMPLETIONS)
        == "https://api.openai.com/v1/chat/completions"
    )
