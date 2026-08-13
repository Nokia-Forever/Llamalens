from __future__ import annotations

import asyncio

from starlette.requests import Request

from app.api.events import _event_stream
from app.services import task_queue


class DisconnectAfterFirstEvent:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return self.calls >= 1


def test_event_stream_emits_initial_queue_and_unsubscribes(monkeypatch):
    task_queue._scheduler = None
    scheduler = task_queue.get_scheduler()
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/events/queue", "headers": []})
    disconnect = DisconnectAfterFirstEvent()
    monkeypatch.setattr(request, "is_disconnected", disconnect)

    async def consume() -> list[str]:
        chunks: list[str] = []
        async for chunk in _event_stream(request):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume())
    assert chunks and chunks[0].startswith("event: queue\ndata: ")
    assert '"status": "idle"' in chunks[0]
    assert scheduler._subscribers == []


def test_event_stream_keeps_alive_after_empty_subscription(monkeypatch):
    task_queue._scheduler = None
    scheduler = task_queue.get_scheduler()
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/events/queue", "headers": []})
    calls = 0

    async def is_disconnected() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    monkeypatch.setattr(request, "is_disconnected", is_disconnected)
    monkeypatch.setattr("app.api.events._keepalive_seconds", lambda: 0.01)

    async def consume() -> list[str]:
        chunks: list[str] = []
        async for chunk in _event_stream(request):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume())
    assert chunks[0].startswith("event: queue")
    assert chunks[1] == ": keepalive\n\n"
    assert scheduler._subscribers == []
