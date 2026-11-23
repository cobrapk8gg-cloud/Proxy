"""Request-local delivery of upstream visible text, with bounded backpressure."""

import asyncio
from contextvars import ContextVar
from contextlib import suppress

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
