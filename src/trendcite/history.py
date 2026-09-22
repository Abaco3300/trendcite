"""The local history boundary: append-only snapshot storage, and nothing more.

Velocity, novelty and persistence need to know what a signal looked like *last* time.
That is the only reason this module exists, and it is deliberately the smallest thing
that can supply it:

* **Append-only.** Records are added, never edited or deleted. A snapshot is what was
  true at a capture time; rewriting it would rewrite history and make a stored
  velocity unverifiable.
* **Local only.** A file on the user's machine, or memory. There is no hosted
  service, no account, no network call, and :class:`HistoryStore` is a protocol
  precisely so that adding one later is a new implementation, not a rewrite.
* **Off by default.** :class:`NullHistoryStore` is what runs unless the caller asks
  for otherwise, so the default CLI behaviour writes nothing and stays deterministic
  and offline.

A store never decides anything. It hands back snapshots; :mod:`trendcite.signal_scoring`
decides what they mean.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .observation import ObservationSnapshot
from .signal import SignalSnapshot, sort_snapshots
from .versions import HISTORY_FORMAT_VERSION

RECORD_SIGNAL = "signal_snapshot"
RECORD_OBSERVATION = "observation_snapshot"

#: Refuse to load absurd files rather than exhausting memory on a corrupt one.
MAX_HISTORY_BYTES = 32 * 1024 * 1024


def _float_map(value: object) -> dict[str, float]:
    """Read back a stored metrics map, dropping anything that is not a number."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        out[str(key)] = float(raw)
    return out


@runtime_checkable
class HistoryStore(Protocol):
    """Append-only access to what previous runs recorded."""

    def append_signal_snapshots(self, snapshots: Sequence[SignalSnapshot]) -> None:
        """Record evaluation events. Must not modify anything already stored."""

    def append_observation_snapshots(self, snapshots: Sequence[ObservationSnapshot]) -> None:
        """Record metric readings. Must not modify anything already stored."""

    def signal_history(self, signal_id: str) -> list[SignalSnapshot]:
        """Every stored snapshot for one signal, oldest first."""

    def observation_history(self, observation_id: str) -> list[ObservationSnapshot]:
        """Every stored reading for one observation, oldest first."""


class NullHistoryStore:
    """Stores nothing and knows nothing. The default, so a plain run touches no disk."""

    def append_signal_snapshots(self, snapshots: Sequence[SignalSnapshot]) -> None:
        return None

    def append_observation_snapshots(self, snapshots: Sequence[ObservationSnapshot]) -> None:
        return None

    def signal_history(self, signal_id: str) -> list[SignalSnapshot]:
        return []

    def observation_history(self, observation_id: str) -> list[ObservationSnapshot]:
        return []


class InMemoryHistoryStore:
    """Process-local history. Useful for tests and for a multi-run session in one process."""

    def __init__(self, snapshots: Sequence[SignalSnapshot] = ()) -> None:
        self._signals: list[SignalSnapshot] = list(snapshots)
        self._observations: list[ObservationSnapshot] = []

    def append_signal_snapshots(self, snapshots: Sequence[SignalSnapshot]) -> None:
        self._signals.extend(snapshots)

    def append_observation_snapshots(self, snapshots: Sequence[ObservationSnapshot]) -> None:
        self._observations.extend(snapshots)

    def signal_history(self, signal_id: str) -> list[SignalSnapshot]:
        return sort_snapshots(s for s in self._signals if s.signal_id == signal_id)

    def observation_history(self, observation_id: str) -> list[ObservationSnapshot]:
        return sorted(
            (o for o in self._observations if o.observation_id == observation_id),
            key=lambda o: (o.captured_at, o.observation_id),
        )


class JsonlHistoryStore:
    """Append-only JSON-lines history in a single local file.

    One self-describing record per line, so a truncated or partially written file
    costs at most the last line. Unreadable lines are skipped rather than raising:
    a corrupt history must degrade the run to "no history", never break it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # --------------------------------------------------------------------- writing

    def _append(self, kind: str, payloads: Sequence[dict[str, Any]]) -> None:
        if not payloads:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            for payload in payloads:
                record = {"v": HISTORY_FORMAT_VERSION, "kind": kind, "data": payload}
                fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")

    def append_signal_snapshots(self, snapshots: Sequence[SignalSnapshot]) -> None:
        self._append(RECORD_SIGNAL, [s.to_dict() for s in snapshots])

    def append_observation_snapshots(self, snapshots: Sequence[ObservationSnapshot]) -> None:
        self._append(RECORD_OBSERVATION, [s.to_dict() for s in snapshots])

    # --------------------------------------------------------------------- reading

    def _records(self, kind: str) -> list[dict[str, Any]]:
        if not self.path.is_file() or self.path.stat().st_size > MAX_HISTORY_BYTES:
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("kind") != kind:
                    continue
                if record.get("v") != HISTORY_FORMAT_VERSION:
                    continue  # a different format version is not ours to interpret
                data = record.get("data")
                if isinstance(data, dict):
                    out.append(data)
        return out

    def signal_history(self, signal_id: str) -> list[SignalSnapshot]:
        found: list[SignalSnapshot] = []
        for data in self._records(RECORD_SIGNAL):
            if data.get("signal_id") != signal_id:
                continue
            try:
                found.append(SignalSnapshot.from_dict(data))
            except (KeyError, TypeError, ValueError):
                continue
        return sort_snapshots(found)

    def observation_history(self, observation_id: str) -> list[ObservationSnapshot]:
        # Readings are stored for audit and for future cross-run metric work;
        # signal-level history is what the current evaluation consumes.
        found: list[ObservationSnapshot] = []
        for data in self._records(RECORD_OBSERVATION):
            if data.get("observation_id") != observation_id:
                continue
            try:
                found.append(
                    ObservationSnapshot(
                        observation_id=str(data["observation_id"]),
                        captured_at=datetime.fromisoformat(str(data["captured_at"])),
                        source=str(data.get("source", "")),
                        story_key=str(data.get("story_key", "")),
                        event_time=datetime.fromisoformat(str(data["event_time"])),
                        observed_at=datetime.fromisoformat(str(data["observed_at"])),
                        metrics=_float_map(data.get("metrics")),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(found, key=lambda o: (o.captured_at, o.observation_id))
