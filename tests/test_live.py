import asyncio

import pytest

from proxy.live import live_events, text_sink


@pytest.mark.asyncio
async def test_first_delta_before_completion():
    release = asyncio.Event()

    async def generate():
        await text_sink.get()("أول")
        await release.wait()
        await text_sink.get()(" جزء")
        return "أول جزء"

    stream = live_events(generate)
    assert await asyncio.wait_for(anext(stream), 1) == ("text", "أول")
    release.set()
    assert [event async for event in stream] == [
        ("text", " جزء"),
        ("result", "أول جزء"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("openai", [True, False])
async def test_official_api_forwards_visible_text_before_terminal_event(openai):
    import json

    import httpx

    from proxy.official_apis import stream_text

    release = asyncio.Event()
    delta = (
        {"type": "response.output_text.delta", "delta": "أول"}
        if openai
        else {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "hidden", "thought": True}, {"text": "أول"}]
                    }
                }
            ]
        }
    )
    terminal = (
        {"type": "response.completed"}
        if openai
        else {"candidates": [{"finishReason": "STOP"}]}
    )

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(delta) + "\n\n").encode()
            await release.wait()
            yield ("data: " + json.dumps(terminal) + "\n\n").encode()

    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
    async with httpx.AsyncClient(transport=transport) as client:
        stream = live_events(
            lambda: stream_text(client, "https://example.test", {}, {}, openai)
        )
        try:
            assert await asyncio.wait_for(anext(stream), 1) == ("text", "أول")
            release.set()
            assert await anext(stream) == ("result", "أول")
        finally:
            await stream.aclose()
