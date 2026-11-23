"""Request-local delivery of upstream visible text, with bounded backpressure."""

import asyncio
from contextlib import suppress
from contextvars import ContextVar

text_sink = ContextVar("text_sink", default=None)


async def live_events(generate):
    queue = asyncio.Queue(maxsize=16)

    async def produce():
        token = text_sink.set(queue.put)
        try:
            return await generate()
        finally:
            text_sink.reset(token)

    task = asyncio.create_task(produce())
    read = None
    try:
        while not task.done() or not queue.empty():
            if not queue.empty():
                yield "text", queue.get_nowait()
                continue
            read = asyncio.create_task(queue.get())
            ready, _ = await asyncio.wait(
                (task, read), timeout=10, return_when=asyncio.FIRST_COMPLETED
            )
            if read in ready:
                yield "text", read.result()
            else:
                read.cancel()
                with suppress(asyncio.CancelledError):
                    await read
                if not ready:
                    yield "heartbeat", None
            read = None
        yield "result", await task
    finally:
        for pending in (task, read):
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


class TextSnapshot:
    """Forward only the suffix of each cumulative visible answer."""

    def __init__(self):
        self.sink = text_sink.get()
        self.published = ""

    async def update(self, value):
        if self.sink is None:
            return
        if not value.startswith(self.published):
            from .provider_types import ProviderError

            raise ProviderError("غيّر المزوّد نصًا سبق بثه.")
        if len(value) > len(self.published):
            await self.sink(value[len(self.published) :])
            self.published = value
