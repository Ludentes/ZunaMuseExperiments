# Pipeline Architecture Design

**Date:** 2026-03-09
**Status:** Approved

---

## Overview

Pluggable signal processing pipeline replacing the monolithic `build_metrics()` function. Takes raw EEG/PPG/IMU from Muse 2 via BrainFlow, produces detected events (blinks, clenches, concentration states) routable to actions (WebSocket, MQTT, logging).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pipeline topology | Linear chain of stages | Data flows one direction; pub-sub is overkill for 4-channel Muse |
| Multi-stream handling | Single combined `PipelineFrame` carrying EEG/PPG/IMU | Simplest; cross-stream logic is trivial. Separate per-stream pipelines designed for but not implemented |
| Inter-stage data | Typed fields on `PipelineFrame` | Type-safe, IDE autocomplete, catches bugs at dev time |
| Timing | Two cadences: FAST (~16ms) and SLOW (~2s) | Blink detection needs <50ms latency; band powers are expensive and don't need 60fps |

## Core Types

### `backend/pipeline/types.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
import numpy as np


class Cadence(Enum):
    FAST = "fast"   # every poll cycle (~16ms)
    SLOW = "slow"   # every metrics cycle (~2s)


@dataclass
class Event:
    """A detected BCI event."""
    kind: str           # "single_blink", "double_blink", "clench", "concentration", ...
    timestamp: float    # time.time() when detected
    confidence: float   # 0.0 - 1.0
    channel: str | None = None   # source channel if applicable
    metadata: dict = field(default_factory=dict)


# Muse 2 band definitions (matches Muse SDK ranges)
BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (7.5, 13.0),
    "beta":  (13.0, 30.0),
    "gamma": (30.0, 44.0),
}


@dataclass
class PipelineFrame:
    """
    ⚠️  MAINTAINER CONTRACT ⚠️
    ──────────────────────────────────────────────────────────────
    Every field here MUST be documented with:
      - Which stage WRITES it
      - Which stages READ it
    When you add a stage that produces new data, ADD A FIELD HERE.
    When you remove a stage, REMOVE ITS FIELD.
    This dataclass IS the pipeline's data schema.
    Keep it current or debugging becomes hell.
    ──────────────────────────────────────────────────────────────

    Raw inputs — set by pipeline runner, never by stages:
        eeg, ppg, imu, timestamp

    Preprocessing outputs:
        eeg_filtered        — written by: BandPassFilter or WaveletDenoiser
                              read by: BandPowerExtractor, BlinkDetector (fallback)

    Feature extraction outputs:
        band_powers         — written by: BandPowerExtractor
                              read by: serialize.frame_to_metrics
        theta_beta_ratio    — written by: BandPowerExtractor
                              read by: serialize.frame_to_metrics
        frontal_alpha_asymmetry — written by: BandPowerExtractor
                              read by: serialize.frame_to_metrics
        signal_quality      — written by: SignalQualityChecker
                              read by: serialize.frame_to_metrics
        fit_status          — written by: SignalQualityChecker
                              read by: serialize.frame_to_metrics
        heart_rate_bpm      — written by: HeartRateExtractor
                              read by: serialize.frame_to_metrics
        spo2_percent        — written by: HeartRateExtractor
                              read by: serialize.frame_to_metrics
        hrv_rmssd_ms        — written by: HeartRateExtractor
                              read by: serialize.frame_to_metrics
        head_movement       — written by: HeadMotionExtractor
                              read by: serialize.frame_to_metrics
        head_pose           — written by: HeadMotionExtractor
                              read by: serialize.frame_to_metrics

    Detection outputs:
        events              — appended by: BlinkDetector, ClenchDetector
                              read by: Action handlers
        motion_artifact     — written by: HeadMotionExtractor
                              read by: serialize.frame_to_metrics
        jaw_clench          — written by: ClenchDetector
                              read by: serialize.frame_to_metrics
    """
    # ── Raw inputs (set by pipeline runner, never by stages) ──
    eeg: np.ndarray | None = None       # (4, N) µV at 256Hz
    ppg: np.ndarray | None = None       # (3, M) raw at 64Hz
    imu: np.ndarray | None = None       # (6, K) g's/dps at 52Hz
    timestamp: float = 0.0

    # ── Preprocessing outputs ──
    eeg_filtered: np.ndarray | None = None

    # ── Feature extraction outputs ──
    band_powers: dict[str, list[float]] | None = None
    theta_beta_ratio: list[float] | None = None
    frontal_alpha_asymmetry: float | None = None
    signal_quality: dict[str, float] | None = None
    fit_status: str | None = None
    heart_rate_bpm: float | None = None
    spo2_percent: float | None = None
    hrv_rmssd_ms: float | None = None
    head_movement: float | None = None
    head_pose: tuple[float, float] | None = None  # (pitch, roll)

    # ── Detection outputs ──
    events: list[Event] = field(default_factory=list)
    motion_artifact: bool = False
    jaw_clench: bool = False
```

### `backend/pipeline/base.py`

```python
from abc import ABC, abstractmethod
from .types import PipelineFrame, Event, Cadence


class Stage(ABC):
    """
    Base class for all pipeline stages.

    CONTRACT:
    - process() reads fields from frame, writes fields to frame.
    - If your stage needs state across frames (e.g. rolling window),
      keep it as instance attributes.
    - Side effects (logging) are allowed but not required.
    """
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None:
        """Mutate frame in-place."""
        ...


class Action(ABC):
    """Receives detected events and acts on them."""
    name: str

    @abstractmethod
    def handle(self, events: list[Event]) -> None: ...
```

### `backend/pipeline/__init__.py`

```python
import time
from .types import PipelineFrame, Event, Cadence
from .base import Stage, Action


class Pipeline:
    """
    Runs an ordered list of stages at two cadences.

    - FAST stages: every poll cycle (~16ms) — event detection
    - SLOW stages: every metrics cycle (~2s) — spectral features, vitals

    Usage:
        pipeline = Pipeline(stages=[...], actions=[...])
        # In stream loop (16ms):
        events = pipeline.tick_fast(eeg, ppg, imu)
        # In metrics loop (2s):
        frame = pipeline.tick_slow(eeg, ppg, imu)
    """
    def __init__(self, stages: list[Stage], actions: list[Action]):
        self._fast = [s for s in stages if s.cadence == Cadence.FAST]
        self._slow = [s for s in stages if s.cadence == Cadence.SLOW]
        self._actions = actions

    def tick_fast(self, eeg, ppg, imu) -> list[Event]:
        """Called every poll cycle. Returns detected events."""
        frame = PipelineFrame(eeg=eeg, ppg=ppg, imu=imu, timestamp=time.time())
        for stage in self._fast:
            stage.process(frame)
        for action in self._actions:
            action.handle(frame.events)
        return frame.events

    def tick_slow(self, eeg, ppg, imu) -> PipelineFrame:
        """Called every metrics cycle. Returns full frame for dashboard."""
        frame = PipelineFrame(eeg=eeg, ppg=ppg, imu=imu, timestamp=time.time())
        for stage in self._slow:
            stage.process(frame)
        return frame
```

## Stages Inventory

### SLOW path (2s metrics cycle)

| Stage | Reads | Writes | BrainFlow API |
|-------|-------|--------|---------------|
| `BandPassFilter` | `eeg` | `eeg_filtered` | `perform_bandpass`, `remove_environmental_noise` |
| `WaveletDenoiser` (alt) | `eeg` | `eeg_filtered` | `perform_wavelet_denoising` |
| `BandPowerExtractor` | `eeg_filtered` or `eeg` | `band_powers`, `theta_beta_ratio`, `frontal_alpha_asymmetry` | `get_psd_welch`, `get_band_power` |
| `SignalQualityChecker` | `eeg` | `signal_quality`, `fit_status` | `get_railed_percentage`, `calc_stddev` |
| `HeartRateExtractor` | `ppg` | `heart_rate_bpm`, `spo2_percent`, `hrv_rmssd_ms` | `get_heart_rate`, `get_oxygen_level` |
| `HeadMotionExtractor` | `imu` | `head_movement`, `head_pose`, `motion_artifact` | — (numpy) |

### FAST path (16ms poll cycle)

| Stage | Reads | Writes | BrainFlow API |
|-------|-------|--------|---------------|
| `BlinkDetector` | `eeg` | `events` (append) | `detect_peaks_z_score` |
| `ClenchDetector` | `eeg` | `events` (append), `jaw_clench` | `perform_bandpass` + threshold |

### Future stages (not implemented now)

| Stage | Cadence | Notes |
|-------|---------|-------|
| `ConcentrationScorer` | SLOW | BrainFlow `MLModel(MINDFULNESS)` or custom |
| `AlphaBlockingDetector` | SLOW | Alpha vs calibrated baseline |

## Actions

| Action | What it does |
|--------|-------------|
| `LogAction` | Logs events at INFO level. Always included. |
| `WebSocketBroadcastAction` | Sends events as JSON to connected dashboard clients. |
| `MQTTAction` | Publishes events to MQTT broker for Home Assistant automation. |

## File Layout

```
backend/pipeline/
├── __init__.py          # Pipeline class, exports
├── types.py             # PipelineFrame, Event, Cadence, BANDS
├── base.py              # Stage, Action ABCs
├── factory.py           # create_default_pipeline()
├── serialize.py         # frame_to_metrics() — PipelineFrame → JSON dict
├── stages/
│   ├── __init__.py
│   ├── preprocessing.py # BandPassFilter, WaveletDenoiser
│   ├── features.py      # BandPowerExtractor, SignalQualityChecker,
│   │                    # HeartRateExtractor, HeadMotionExtractor
│   └── detectors.py     # BlinkDetector, ClenchDetector
└── actions/
    ├── __init__.py
    ├── log.py           # LogAction
    ├── websocket.py     # WebSocketBroadcastAction
    └── mqtt.py          # MQTTAction
```

## Integration with EEGServer

```python
# main.py changes

class EEGServer:
    def __init__(self, config):
        ...
        self.pipeline = create_default_pipeline()

    async def _stream_loop(self):
        # Poll BrainFlow, broadcast raw, run FAST stages
        eeg = self.acq.get_eeg_data()
        ppg = ...
        imu = ...
        # ... buffer for recording, broadcast raw (unchanged) ...
        events = self.pipeline.tick_fast(eeg, ppg, imu)

    async def _metrics_loop(self):
        # Flush buffers, run SLOW stages, broadcast metrics
        eeg, ppg, imu = self._flush_buffers()
        frame = self.pipeline.tick_slow(eeg, ppg, imu)
        metrics = frame_to_metrics(frame)
        await self._broadcast_text(encode_metrics(metrics))
```

`build_metrics()` is deleted. `processing.py` stays as a utility module
for standalone functions that stage implementations import.

## Migration Plan

1. Create `pipeline/` package with types, base, Pipeline class
2. Move existing `processing.py` functions into stage classes (logic stays the same)
3. Add `frame_to_metrics()` that produces identical JSON to current `build_metrics()` output
4. Wire pipeline into `EEGServer`, delete `build_metrics()` call
5. Verify frontend sees no difference (no frontend changes needed)
6. Add BlinkDetector, ClenchDetector as new FAST stages
7. Add MQTTAction when ready for Home Assistant integration

## Extensibility Examples

**Swap preprocessor:** In `factory.py`, replace `BandPassFilter(...)` with `WaveletDenoiser(...)`.

**Add concentration scoring:** Add `ConcentrationScorer()` to the stages list in `factory.py`, add `concentration_score: float | None = None` to `PipelineFrame`.

**Add MQTT:** Uncomment `MQTTAction(...)` in `factory.py`.

**Custom ONNX classifier:** Create a new `Stage` subclass using BrainFlow's `MLModel(USER_DEFINED)`, add to stages list.

**ZUNA integration:** Create a `ZunaPreprocessor(Stage)` that replaces `BandPassFilter` — runs ZUNA inference on raw EEG, writes enhanced signal to `eeg_filtered`.
