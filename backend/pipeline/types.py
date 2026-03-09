from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import numpy as np

T = TypeVar("T")

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (7.5, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 44.0),
}

CH_NAMES: list[str] = ["TP9", "AF7", "AF8", "TP10"]

BAND_NAMES: list[str] = list(BANDS.keys())


class Cadence(Enum):
    FAST = "fast"
    SLOW = "slow"


@dataclass
class Event:
    kind: str
    timestamp: float
    confidence: float = 1.0
    channel: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineFrame:
    eeg: np.ndarray | None
    ppg: np.ndarray | None
    imu: np.ndarray | None
    timestamp: float
    _results: dict[str, Any] = field(default_factory=dict, repr=False)
    events: list[Event] = field(default_factory=list)

    def set(self, result: Any) -> None:
        """Store a result by its class name."""
        self._results[type(result).__name__] = result

    def get(self, cls: type[T]) -> T | None:
        """Retrieve a typed result, or None if not set."""
        return self._results.get(cls.__name__)

    def has(self, cls: type) -> bool:
        """Check if a result type has been set."""
        return cls.__name__ in self._results

    def all_results(self) -> dict[str, Any]:
        """Return all results (for serializer)."""
        return dict(self._results)
