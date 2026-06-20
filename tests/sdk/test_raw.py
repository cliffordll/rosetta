from rosetta.sdk.raw import (
    RawChatRequest,
    RawChatResponse,
    RawSseFrame,
    format_raw_request,
    preview_raw_response_frames,
)


def test_raw_request_includes_api_key_header() -> None:
    req = RawChatRequest(
        url="/v1/messages",
        headers={"content-type": "application/json", "x-api-key": "sk-secret"},
        body={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )

    out = format_raw_request(req)

    assert "POST /v1/messages" in out
    assert "x-api-key: sk-secret" in out


def test_raw_response_preview_uses_edge_and_step_semantics() -> None:
    response = RawChatResponse(
        frames=[
            RawSseFrame(
                received_at=f"2026-06-20T12:00:{i:02d}.000Z",
                raw=f'event: frame_{i}\ndata: {{"index":{i}}}',
                event=f"frame_{i}",
                data={"index": i},
            )
            for i in range(25)
        ],
        error=None,
    )

    collapsed = preview_raw_response_frames(response, edge_frames=10, revealed_middle_frames=0)
    assert "event: frame_0" in collapsed.text
    assert "event: frame_9" in collapsed.text
    assert "event: frame_10" not in collapsed.text
    assert "... hidden 5 frames ..." in collapsed.text
    assert "event: frame_15" in collapsed.text
    assert "event: frame_24" in collapsed.text
    assert collapsed.hidden_frames == 5

    expanded = preview_raw_response_frames(response, edge_frames=10, revealed_middle_frames=10)
    assert "event: frame_10" in expanded.text
    assert "event: frame_14" in expanded.text
    assert expanded.hidden_frames == 0
