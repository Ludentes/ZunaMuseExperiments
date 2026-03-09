# Pipeline Architecture Design

**Date:** 2026-03-09
**Status:** Approved (v2 — typed result registry)

---

## Overview

Pluggable signal processing pipeline replacing the monolithic `build_metrics()` function. Takes raw EEG/PPG/IMU from Muse 2 via BrainFlow, produces detected events (blinks, clenches, concentration states) routable to actions (WebSocket, MQTT, logging).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Pipeline topology | Linear chain of stages | Data flows one direction; pub-sub is overkill for 4-channel Muse |
| Multi-stream handling | Single combined `PipelineFrame` carrying EEG/PPG/IMU | Simplest; cross-stream logic is trivial. Separate per-stream pipelines designed for but not implemented |
| Inter-stage data | **Typed result registry** — fixed input fields + open typed result slots | Adding a stage never requires modifying `PipelineFrame`. Each stage owns its result dataclass. Type-safe via generics. |
| Timing | Two cadences: FAST (~16ms) and SLOW (~2s) | Blink detection needs <50ms latency; band powers are expensive and don't need 60fps |

### Why typed result registry over flat fields

v1 had every stage output as a field on `PipelineFrame`. This meant adding any new stage required modifying `PipelineFrame`, updating its docstring contract, updating the serializer, and possibly the frontend — 3-4 files touched per new capability. The "keep this current" warning was papering over a structural coupling problem.

v2 splits the frame into:
- **Fixed inputs** (hardware-determined, rarely change): `eeg`, `ppg`, `imu`, `timestamp`
- **Open results** (stage-determined, change often): typed dataclasses stored by class key
- **Events** (always present, append-only): `list[Event]`

Adding a new stage = write the stage class + its result dataclass. Nothing else changes.

## Core Types

### `backend/pipeline/types.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, overload
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

T = TypeVar("T")


@dataclass
class PipelineFrame:
    """
    Carries raw sensor data through the pipeline. Stages read inputs
    and store typed results via set()/get().

    INPUTS (fixed, hardware-determined — only change if hardware changes):
        eeg:       (4, N) µV at 256Hz — TP9, AF7, AF8, TP10
        ppg:       (3, M) raw at 64Hz — Red, IR, Ambient
        imu:       (6, K) g's/dps at 52Hz — accel[3] + gyro[3]
        timestamp: time.time() when frame was created

    RESULTS (open, stage-determined — stages store via frame.set()):
        Access with frame.get(ResultClass). Each stage defines its own
        result dataclass. No need to modify PipelineFrame when adding stages.

    EVENTS (append-only):
        Detector stages append Event objects. Action handlers consume them.
    """
    # ── Fixed inputs ──
    eeg: np.ndarray | None = None
    ppg: np.ndarray | None = None
    imu: np.ndarray | None = None
    timestamp: float = 0.0

    # ── Open result registry ──
    _results: dict[str, Any] = field(default_factory=dict, repr=False)

    # ── Detected events ──
    events: list[Event] = field(default_factory=list)

    def set(self, result: Any) -> None:
        """Store a stage result, keyed by its class name.

        Usage:
            frame.set(BandPowerResult(band_powers=..., theta_beta_ratio=...))
        """
        self._results[type(result).__name__] = result

    def get(self, cls: type[T]) -> T | None:
        """Retrieve a typed stage result, or None if not yet computed.

        Usage:
            bp = frame.get(BandPowerResult)
            if bp:
                print(bp.band_powers)
        """
        return self._results.get(cls.__name__)

    def has(self, cls: type) -> bool:
        """Check if a stage result is present."""
        return cls.__name__ in self._results

    def all_results(self) -> dict[str, Any]:
        """Return all stored results. Used by serializer."""
        return dict(self._results)
```

### Stage Result Dataclasses

Each stage defines its own result type. These live alongside the stage implementation, not in `types.py`.

```python
# In stages/preprocessing.py
@dataclass
class PreprocessingResult:
    """Output of BandPassFilter or WaveletDenoiser."""
    eeg_filtered: np.ndarray   # same shape as input eeg, filtered

# In stages/features.py
@dataclass
class BandPowerResult:
    """Output of BandPowerExtractor."""
    band_powers: dict[str, list[float]]   # {band_name: [per_ch_power]}
    theta_beta_ratio: list[float]
    frontal_alpha_asymmetry: float

@dataclass
class SignalQualityResult:
    """Output of SignalQualityChecker."""
    quality: dict[str, float]    # {channel_name: 0.0-1.0}
    fit_status: str              # "good", "adjust", "poor"

@dataclass
class HeartRateResult:
    """Output of HeartRateExtractor."""
    heart_rate_bpm: float
    spo2_percent: float
    hrv_rmssd_ms: float

@dataclass
class HeadMotionResult:
    """Output of HeadMotionExtractor."""
    head_movement: float
    head_pose: tuple[float, float]   # (pitch, roll) degrees
    motion_artifact: bool

# In stages/detectors.py
@dataclass
class ClenchResult:
    """Output of ClenchDetector."""
    jaw_clench: bool

# Future — no PipelineFrame changes needed:

@dataclass
class ConcentrationResult:
    """Output of ConcentrationScorer."""
    concentration_score: float    # 0.0 - 1.0
    relaxation_score: float       # 0.0 - 1.0

@dataclass
class AlphaBlockingResult:
    """Output of AlphaBlockingDetector."""
    alpha_blocked: bool
    alpha_ratio: float   # current / baseline
```

### `backend/pipeline/base.py`

```python
from abc import ABC, abstractmethod
from .types import PipelineFrame, Event, Cadence


class Stage(ABC):
    """
    Base class for all pipeline stages.

    CONTRACT:
    - process() reads from frame (inputs or other stages' results via frame.get())
    - process() writes its result via frame.set(MyResult(...))
    - Detector stages also append to frame.events
    - If your stage needs state across frames (e.g. rolling window),
      keep it as instance attributes.
    """
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None:
        """Read inputs/results from frame, compute, store results via frame.set()."""
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

## Stage Example: Reading Another Stage's Output

```python
class BandPowerExtractor(Stage):
    name = "band_power_extractor"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        # Prefer filtered EEG if a preprocessor ran before us
        prep = frame.get(PreprocessingResult)
        eeg = prep.eeg_filtered if prep else frame.eeg
        if eeg is None:
            return

        band_powers = ...  # compute using BrainFlow
        theta_beta = ...
        faa = ...

        frame.set(BandPowerResult(
            band_powers=band_powers,
            theta_beta_ratio=theta_beta,
            frontal_alpha_asymmetry=faa,
        ))
```

## Serializer: `frame_to_metrics()`

The serializer maps result objects to the JSON shape the frontend expects. It's the **only place** that knows about the frontend's metrics format. When a new stage is added, only the serializer needs a new `if` block — not the frame, not the pipeline, not the stages.

```python
# backend/pipeline/serialize.py

def frame_to_metrics(frame: PipelineFrame) -> dict:
    """Convert PipelineFrame to the metrics JSON the frontend expects.

    This is the single translation layer between pipeline internals
    and the WebSocket protocol. Add a block here when adding a new
    stage whose results should appear on the dashboard.
    """
    metrics: dict = {}

    bp = frame.get(BandPowerResult)
    if bp:
        metrics["eeg"] = {
            "band_powers": bp.band_powers,
            "theta_beta_ratio": bp.theta_beta_ratio,
            "frontal_alpha_asymmetry": bp.frontal_alpha_asymmetry,
        }

    sq = frame.get(SignalQualityResult)
    if sq:
        metrics.setdefault("eeg", {}).update({
            "signal_quality": sq.quality,
            "fit_status": sq.fit_status,
        })

    hr = frame.get(HeartRateResult)
    if hr:
        metrics["ppg"] = {
            "heart_rate_bpm": round(hr.heart_rate_bpm, 1),
            "spo2_percent": round(hr.spo2_percent, 1),
            "hrv_rmssd_ms": round(hr.hrv_rmssd_ms, 1),
        }

    hm = frame.get(HeadMotionResult)
    if hm:
        metrics["imu"] = {
            "head_movement": hm.head_movement,
            "head_pose": {"pitch": hm.head_pose[0], "roll": hm.head_pose[1]},
            "motion_artifact": hm.motion_artifact,
        }

    cl = frame.get(ClenchResult)
    if cl:
        metrics.setdefault("imu", {})["jaw_clench"] = cl.jaw_clench

    # Future results automatically ignored until serializer updated
    return metrics
```

## Stages Inventory

### SLOW path (2s metrics cycle)

| Stage | Reads | Writes (via `frame.set()`) | BrainFlow API |
|-------|-------|--------|---------------|
| `BandPassFilter` | `frame.eeg` | `PreprocessingResult` | `perform_bandpass`, `remove_environmental_noise` |
| `WaveletDenoiser` (alt) | `frame.eeg` | `PreprocessingResult` | `perform_wavelet_denoising` |
| `BandPowerExtractor` | `PreprocessingResult` or `frame.eeg` | `BandPowerResult` | `get_psd_welch`, `get_band_power` |
| `SignalQualityChecker` | `frame.eeg` | `SignalQualityResult` | `get_railed_percentage`, `calc_stddev` |
| `HeartRateExtractor` | `frame.ppg` | `HeartRateResult` | `get_heart_rate`, `get_oxygen_level` |
| `HeadMotionExtractor` | `frame.imu` | `HeadMotionResult` | — (numpy) |

### FAST path (16ms poll cycle)

| Stage | Reads | Writes | BrainFlow API |
|-------|-------|--------|---------------|
| `BlinkDetector` | `frame.eeg` | `frame.events` (append) | `detect_peaks_z_score` |
| `ClenchDetector` | `frame.eeg` | `frame.events` (append), `ClenchResult` | `perform_bandpass` + threshold |

### Future stages (no PipelineFrame changes needed)

| Stage | Cadence | Result type | Notes |
|-------|---------|-------------|-------|
| `ConcentrationScorer` | SLOW | `ConcentrationResult` | BrainFlow `MLModel(MINDFULNESS/RESTFULNESS)` |
| `AlphaBlockingDetector` | SLOW | `AlphaBlockingResult` | Alpha vs calibrated baseline |
| `ICAFilter` | SLOW | `PreprocessingResult` | BrainFlow `perform_ica` — alternative preprocessor |
| `WaveletFeatureExtractor` | SLOW | `BandPowerResult` | Wavelet decomposition as alternative to FFT bands |
| `CSPClassifier` | SLOW | custom result | BrainFlow `get_csp` — needs labeled calibration data |

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
│   ├── preprocessing.py # BandPassFilter, WaveletDenoiser, PreprocessingResult
│   ├── features.py      # BandPowerExtractor, SignalQualityChecker,
│   │                    # HeartRateExtractor, HeadMotionExtractor + their results
│   └── detectors.py     # BlinkDetector, ClenchDetector + ClenchResult
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

## Adding a New Stage: Checklist

1. **Write the result dataclass** — in your stage file, define `@dataclass class MyResult`
2. **Write the stage class** — extend `Stage`, implement `process()`, call `frame.set(MyResult(...))`
3. **Add to factory** — one line in `create_default_pipeline()` stage list
4. **If dashboard needs it** — add an `if` block in `serialize.py`'s `frame_to_metrics()`
5. **That's it.** No `PipelineFrame` changes. No base class changes. No other stages affected.

## Migration Plan

1. Create `pipeline/` package with types, base, Pipeline class
2. Move existing `processing.py` functions into stage classes (logic stays the same)
3. Add `frame_to_metrics()` that produces identical JSON to current `build_metrics()` output
4. Wire pipeline into `EEGServer`, delete `build_metrics()` call
5. Verify frontend sees no difference (no frontend changes needed)
6. Add BlinkDetector, ClenchDetector as new FAST stages
7. Add MQTTAction when ready for Home Assistant integration

## Extensibility Examples

**Swap preprocessor:** In `factory.py`, replace `BandPassFilter(...)` with `WaveletDenoiser(...)`. Both write `PreprocessingResult`, so `BandPowerExtractor` doesn't care which one ran.

**Add concentration scoring:** Write `ConcentrationScorer` stage + `ConcentrationResult` dataclass. Add to factory. Add serializer block. No other files touched.

**Add MQTT:** Uncomment `MQTTAction(...)` in `factory.py`.

**Custom ONNX classifier:** Write a new `Stage` subclass using BrainFlow's `MLModel(USER_DEFINED)`, define its result dataclass, add to factory.

**ZUNA integration:** Write `ZunaPreprocessor(Stage)` that writes `PreprocessingResult`. Swap with `BandPassFilter` in factory. All downstream stages see filtered EEG the same way.

## BrainFlow API Coverage

Every BrainFlow function maps to exactly one stage. Swapping the underlying implementation never leaks beyond the stage boundary.

| BrainFlow Function | Stage | Swap by... |
|---|---|---|
| `perform_bandpass`, `perform_bandstop`, `perform_highpass`, `perform_lowpass`, `remove_environmental_noise` | `BandPassFilter` | Replace stage with `WaveletDenoiser` or `ICAFilter` |
| `perform_wavelet_denoising` | `WaveletDenoiser` | Replace stage with `BandPassFilter` |
| `perform_rolling_filter` | `BandPowerExtractor` (config option for smoothing) | Change config param |
| `get_psd_welch`, `get_band_power`, `detrend` | `BandPowerExtractor` | Replace stage with `WaveletFeatureExtractor` using wavelet decomposition |
| `get_avg_band_powers`, `get_custom_band_powers` | `BandPowerExtractor` (alternative impl) | Swap internal implementation, same result type |
| `detect_peaks_z_score` | `BlinkDetector`, `ClenchDetector` | Replace with custom threshold detector |
| `perform_wavelet_transform`, `restore_data_from_wavelet_detailed_coeffs` | `WaveletFeatureExtractor` | Replace with `BandPowerExtractor` |
| `perform_ica` | `ICAFilter` | Replace with `BandPassFilter` or `WaveletDenoiser` |
| `get_csp` | `CSPClassifier` | Replace with `ConcentrationScorer` |
| `get_railed_percentage`, `calc_stddev` | `SignalQualityChecker` | Swap internal implementation |
| `get_heart_rate`, `get_oxygen_level` | `HeartRateExtractor` | Swap with custom PPG peak detection |
| `MLModel(MINDFULNESS)`, `MLModel(RESTFULNESS)` | `ConcentrationScorer` | Swap with custom ONNX model |
| `MLModel(USER_DEFINED)` | Any custom stage | — |
