"""Server-Sent Events hub: thread-safe pub/sub keyed by project id.

Background workers (transcription, export) run in threads and ``publish()``
events; SSE endpoints ``subscribe()`` to an asyncio queue. Publishing from a
worker thread hops onto the event loop via ``call_soon_threadsafe``. SSE, not
WebSockets — one-way progress is all we need (spec §4).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, pid: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[pid].add(q)
        return q

    def unsubscribe(self, pid: str, q: asyncio.Queue) -> None:
        self._subs.get(pid, set()).discard(q)

    def publish(self, pid: str, event: dict[str, Any]) -> None:
        """Publish an event to all subscribers of ``pid`` (thread-safe)."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._deliver, pid, event)
        else:
            self._deliver(pid, event)

    def _deliver(self, pid: str, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(pid, set())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - drop if a client stalls
                pass


def sse_format(event: dict[str, Any]) -> str:
    """Encode an event as an SSE frame. ``event['type']`` becomes the event name."""
    etype = event.get("type", "message")
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {etype}\ndata: {payload}\n\n"


async def event_stream(
    hub: EventHub,
    pid: str,
    snapshot: dict[str, Any],
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    poll: float = 0.5,
    keepalive: float = 15.0,
) -> AsyncIterator[str]:
    """Async generator backing the SSE endpoint (extracted so it's unit-testable).

    Subscribes *before* emitting the snapshot so no event can slip through the
    gap. Polls on a short interval so client disconnects are noticed promptly.
    """
    q = hub.subscribe(pid)
    try:
        yield sse_format(snapshot)
        last = time.monotonic()
        while True:
            if await is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=poll)
                yield sse_format(event)
            except TimeoutError:
                now = time.monotonic()
                if now - last >= keepalive:
                    last = now
                    yield ": keepalive\n\n"
    finally:
        hub.unsubscribe(pid, q)
