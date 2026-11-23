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
    assert [event async for event in stream] == [("text", " جزء"), ("result", "أول جزء")]
