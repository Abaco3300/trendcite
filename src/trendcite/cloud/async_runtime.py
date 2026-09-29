"""Transport-neutral async contracts for the Cloudflare execution plane."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ScheduledHandler(Protocol):
    async def run_once(self, *, scheduled_time: str, cron: str) -> dict[str, Any]: ...


class QueueHandler(Protocol):
    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class AsyncCloudRuntime:
    """Thin runtime dispatcher.

    Cloudflare-specific objects stay outside the domain package.  This class gives the
    Worker one async interface for scheduled and Queue events without forcing the
    synchronous SQLite application layer into an active event loop.
    """

    scheduled_handler: ScheduledHandler
    queue_handler: QueueHandler

    async def scheduled(self, *, scheduled_time: str, cron: str) -> dict[str, Any]:
        return await self.scheduled_handler.run_once(
            scheduled_time=scheduled_time,
            cron=cron,
        )

    async def queue(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.queue_handler.handle(payload)
