"""Adapter protocol shared by all sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..http import Transport
from ..models import EvidenceItem


class SourceUnavailable(RuntimeError):
    """The source cannot be used right now (not configured, blocked, offline)."""


class SourceAdapter(ABC):
    """A read-only evidence source.

    ``collect`` must either return normalised items or raise an exception; the
    pipeline records the failure and continues with the remaining sources.
    """

    name: str = "base"
    description: str = ""

    def __init__(self, transport: Transport | None = None) -> None:
        self.transport = transport

    @abstractmethod
    def collect(self, now: datetime) -> list[EvidenceItem]:
        """Fetch and normalise items from the live source."""
