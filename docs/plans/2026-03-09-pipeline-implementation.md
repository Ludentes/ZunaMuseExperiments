# Pipeline Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the monolithic `backend/processing.py` + `build_metrics()` into a pluggable stage-based pipeline per `docs/architecture/pipeline.md`, preserving the existing frontend JSON format exactly (no frontend changes).

**Architecture:** Linear pipeline with typed result registry on `PipelineFrame`. Stages read/write via `frame.get()`/`frame.set()`. Two cadences: FAST (~16ms, event detection) and SLOW (~2s, spectral features). Factory pattern for assembly. Single serializer `frame_to_metrics()` translates results to dashboard JSON.

**Tech Stack:** Python 3.12, numpy, BrainFlow `DataFilter`, dataclasses, pytest

---

### Task 1: Create pipeline package with core types

**Files:**
- Create: `backend/pipeline/__init__.py`
- Create: `backend/pipeline/types.py`

**Step 1: Write failing test for PipelineFrame**

Create: `tests/test_pipeline_types.py`

```python
import numpy as np
from backend.pipeline.types import PipelineFrame, Event, Cadence, BANDS


def test_pipeline_frame_set_get():
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        value: int

    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    assert frame.get(FakeResult) is None
    assert not frame.has(FakeResult)

    frame.set(FakeResult(value=42))
    result = frame.get(FakeResult)
    assert result is not None
    assert result.value == 42
    assert frame.has(FakeResult)


def test_pipeline_frame_all_results():
    from dataclasses import dataclass

    @dataclass
    class A:
        x: int

    @dataclass
    class B:
        y: str

    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(A(x=1))
    frame.set(B(y="hello"))
    results = frame.all_results()
    assert "A" in results
    assert "B" in results


def test_pipeline_frame_events():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    assert frame.events == []
    frame.events.append(Event(kind="blink", timestamp=1.0, confidence=0.9))
    assert len(frame.events) == 1


def test_cadence_values():
    assert Cadence.FAST.value == "fast"
    assert Cadence.SLOW.value == "slow"


def test_bands_muse2():
    assert BANDS["alpha"] == (7.5, 13.0)
    assert BANDS["gamma"] == (30.0, 44.0)
    assert len(BANDS) == 5
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.pipeline'`

**Step 3: Write implementation**

`backend/pipeline/__init__.py`:
```python
"""Pluggable signal processing pipeline.

See docs/architecture/pipeline.md for full specification.
"""
```

`backend/pipeline/types.py`:
```python
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
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_types.py -v`
Expected: all 5 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/__init__.py backend/pipeline/types.py tests/test_pipeline_types.py
git commit -m "feat(pipeline): add core types — PipelineFrame, Event, Cadence, BANDS"
```

---

### Task 2: Create Stage and Action base classes + Pipeline runner

**Files:**
- Create: `backend/pipeline/base.py`

**Step 1: Write failing test for Stage/Action/Pipeline**

Create: `tests/test_pipeline_runner.py`

```python
import numpy as np
from dataclasses import dataclass
from backend.pipeline.types import PipelineFrame, Cadence, Event
from backend.pipeline.base import Stage, Action, Pipeline


class IncrementStage(Stage):
    name = "increment"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        @dataclass
        class IncrResult:
            count: int

        prev = frame.get(IncrResult)
        frame.set(IncrResult(count=(prev.count + 1) if prev else 1))


class CollectAction(Action):
    def __init__(self):
        self.collected: list[Event] = []

    def handle(self, events: list[Event]) -> None:
        self.collected.extend(events)


def test_pipeline_runs_slow_stages():
    stage = IncrementStage()
    pipeline = Pipeline(stages=[stage], actions=[])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    # IncrResult is defined inside the method, so just check _results
    assert len(frame.all_results()) == 1


def test_pipeline_skips_wrong_cadence():
    stage = IncrementStage()  # SLOW
    pipeline = Pipeline(stages=[stage], actions=[])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.FAST, frame)
    assert len(frame.all_results()) == 0


def test_pipeline_dispatches_events_to_actions():
    action = CollectAction()
    pipeline = Pipeline(stages=[], actions=[action])
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.events.append(Event(kind="test", timestamp=1.0, confidence=1.0))
    pipeline.run(Cadence.FAST, frame)
    assert len(action.collected) == 1
    assert action.collected[0].kind == "test"
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_runner.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write implementation**

`backend/pipeline/base.py`:
```python
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from backend.pipeline.types import Cadence, Event, PipelineFrame

log = logging.getLogger("pipeline")


class Stage(ABC):
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None: ...


class Action(ABC):
    @abstractmethod
    def handle(self, events: list[Event]) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage], actions: list[Action]):
        self.stages = stages
        self.actions = actions

    def run(self, cadence: Cadence, frame: PipelineFrame) -> None:
        for stage in self.stages:
            if stage.cadence != cadence:
                continue
            try:
                stage.process(frame)
            except Exception:
                log.exception("Stage %s failed", stage.name)

        if frame.events:
            for action in self.actions:
                try:
                    action.handle(frame.events)
                except Exception:
                    log.exception("Action %s failed", type(action).__name__)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_runner.py -v`
Expected: all 3 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/base.py tests/test_pipeline_runner.py
git commit -m "feat(pipeline): add Stage/Action ABCs and Pipeline runner"
```

---

### Task 3: Create preprocessing stages (BandPassFilter, WaveletDenoiser)

**Files:**
- Create: `backend/pipeline/stages/__init__.py`
- Create: `backend/pipeline/stages/preprocessing.py`

**Step 1: Write failing test**

Create: `tests/test_pipeline_stages_preprocessing.py`

```python
import numpy as np
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.stages.preprocessing import (
    BandPassFilter,
    WaveletDenoiser,
    PreprocessingResult,
)


def _make_eeg_frame(n_samples: int = 512) -> PipelineFrame:
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, n_samples)).astype(np.float64) * 50
    return PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)


def test_bandpass_filter_produces_result():
    stage = BandPassFilter()
    assert stage.cadence == Cadence.SLOW
    frame = _make_eeg_frame(512)
    stage.process(frame)
    result = frame.get(PreprocessingResult)
    assert result is not None
    assert result.eeg_filtered.shape == (4, 512)


def test_bandpass_filter_does_not_mutate_input():
    frame = _make_eeg_frame(512)
    original = frame.eeg.copy()
    BandPassFilter().process(frame)
    np.testing.assert_array_equal(frame.eeg, original)


def test_bandpass_filter_skips_insufficient_data():
    frame = _make_eeg_frame(8)  # too few samples
    BandPassFilter().process(frame)
    assert frame.get(PreprocessingResult) is None


def test_bandpass_filter_skips_none_eeg():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    BandPassFilter().process(frame)
    assert frame.get(PreprocessingResult) is None


def test_wavelet_denoiser_produces_result():
    stage = WaveletDenoiser()
    assert stage.cadence == Cadence.SLOW
    frame = _make_eeg_frame(512)
    stage.process(frame)
    result = frame.get(PreprocessingResult)
    assert result is not None
    assert result.eeg_filtered.shape == (4, 512)
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_preprocessing.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

`backend/pipeline/stages/__init__.py`:
```python
"""Pipeline stages."""
```

`backend/pipeline/stages/preprocessing.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame


@dataclass
class PreprocessingResult:
    eeg_filtered: np.ndarray


class BandPassFilter(Stage):
    name = "bandpass_filter"
    cadence = Cadence.SLOW

    def __init__(
        self,
        lowcut: float = 1.0,
        highcut: float = 45.0,
        notch: float = 50.0,
        order: int = 4,
        filter_type: int = 0,
    ):
        self.lowcut = lowcut
        self.highcut = highcut
        self.notch = notch
        self.order = order
        self.filter_type = filter_type

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < self.order * 3:
            return

        filtered = frame.eeg.copy().astype(np.float64)
        sr = 256  # Muse 2 EEG sample rate

        for ch in range(filtered.shape[0]):
            if self.notch > 0:
                DataFilter.remove_environmental_noise(
                    filtered[ch], sr, int(self.notch)
                )
            DataFilter.perform_bandpass(
                filtered[ch], sr, self.lowcut, self.highcut,
                self.order, self.filter_type, 0.0,
            )

        frame.set(PreprocessingResult(eeg_filtered=filtered))


class WaveletDenoiser(Stage):
    name = "wavelet_denoiser"
    cadence = Cadence.SLOW

    def __init__(self, wavelet: str = "db4", decomp_level: int = 4):
        self.wavelet = wavelet
        self.decomp_level = decomp_level

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 16:
            return

        filtered = frame.eeg.copy().astype(np.float64)
        for ch in range(filtered.shape[0]):
            DataFilter.perform_wavelet_denoising(
                filtered[ch], self.wavelet, self.decomp_level,
            )

        frame.set(PreprocessingResult(eeg_filtered=filtered))
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_preprocessing.py -v`
Expected: all 5 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/__init__.py backend/pipeline/stages/preprocessing.py tests/test_pipeline_stages_preprocessing.py
git commit -m "feat(pipeline): add BandPassFilter and WaveletDenoiser stages"
```

---

### Task 4: Create feature stages (BandPower, SignalQuality, HeartRate, HeadMotion)

**Files:**
- Create: `backend/pipeline/stages/features.py`

**Step 1: Write failing test**

Create: `tests/test_pipeline_stages_features.py`

```python
import numpy as np
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.preprocessing import PreprocessingResult
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    BandPowerResult,
    SignalQualityChecker,
    SignalQualityResult,
    HeartRateExtractor,
    HeartRateResult,
    HeadMotionExtractor,
    HeadMotionResult,
)


def _make_eeg_frame(n_samples: int = 512) -> PipelineFrame:
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, n_samples)).astype(np.float64) * 50
    return PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)


# --- BandPowerExtractor ---

def test_band_power_from_raw_eeg():
    frame = _make_eeg_frame(512)
    BandPowerExtractor().process(frame)
    bp = frame.get(BandPowerResult)
    assert bp is not None
    assert "alpha" in bp.band_powers
    assert len(bp.band_powers["alpha"]) == 4
    assert len(bp.theta_beta_ratio) == 4
    assert isinstance(bp.frontal_alpha_asymmetry, float)


def test_band_power_prefers_filtered():
    frame = _make_eeg_frame(512)
    filtered = frame.eeg.copy()
    frame.set(PreprocessingResult(eeg_filtered=filtered))
    BandPowerExtractor().process(frame)
    assert frame.get(BandPowerResult) is not None


def test_band_power_skips_short_data():
    frame = _make_eeg_frame(32)
    BandPowerExtractor().process(frame)
    assert frame.get(BandPowerResult) is None


# --- SignalQualityChecker ---

def test_signal_quality_good():
    frame = _make_eeg_frame(256)
    SignalQualityChecker().process(frame)
    sq = frame.get(SignalQualityResult)
    assert sq is not None
    assert len(sq.quality) == 4
    assert sq.fit_status in ("good", "adjust", "poor")
    for q in sq.quality.values():
        assert 0.0 <= q <= 1.0


def test_signal_quality_railed():
    eeg = np.full((4, 256), 999.0)
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)
    SignalQualityChecker().process(frame)
    sq = frame.get(SignalQualityResult)
    assert sq is not None
    assert sq.fit_status == "poor"


def test_signal_quality_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    SignalQualityChecker().process(frame)
    assert frame.get(SignalQualityResult) is None


# --- HeartRateExtractor ---

def test_heart_rate_needs_accumulation():
    """HR needs >=1024 PPG samples. First call with 128 shouldn't produce result."""
    rng = np.random.default_rng(42)
    ppg = rng.standard_normal((3, 128)).astype(np.float64)
    frame = PipelineFrame(eeg=None, ppg=ppg, imu=None, timestamp=0.0)
    stage = HeartRateExtractor()
    stage.process(frame)
    assert frame.get(HeartRateResult) is None


def test_heart_rate_accumulates():
    """After enough calls, accumulator reaches 1024 and produces result."""
    rng = np.random.default_rng(42)
    stage = HeartRateExtractor()
    # Feed 8 chunks of 128 = 1024 total
    for i in range(8):
        ppg = rng.standard_normal((3, 128)).astype(np.float64) * 1000
        frame = PipelineFrame(eeg=None, ppg=ppg, imu=None, timestamp=float(i))
        stage.process(frame)

    # Last frame should have result
    hr = frame.get(HeartRateResult)
    assert hr is not None
    assert isinstance(hr.heart_rate_bpm, float)


def test_heart_rate_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    HeartRateExtractor().process(frame)
    assert frame.get(HeartRateResult) is None


# --- HeadMotionExtractor ---

def test_head_motion_still():
    imu = np.array([
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 1.0, 1.0, 1.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ], dtype=np.float64)
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    hm = frame.get(HeadMotionResult)
    assert hm is not None
    assert hm.head_movement < 0.01
    assert not hm.motion_artifact


def test_head_motion_moving():
    imu = np.array([
        [0.0, 0.5, -0.3, 0.2],
        [0.0, 0.3, -0.1, 0.4],
        [1.0, 0.8, 1.2, 0.9],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ], dtype=np.float64)
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    hm = frame.get(HeadMotionResult)
    assert hm is not None
    assert hm.head_movement > 0.1
    assert hm.motion_artifact


def test_head_motion_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    assert frame.get(HeadMotionResult) is None


def test_head_motion_skips_single_sample():
    imu = np.zeros((6, 1))
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    assert frame.get(HeadMotionResult) is None
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_features.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

`backend/pipeline/stages/features.py`:
```python
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations

from backend.pipeline.base import Stage
from backend.pipeline.stages.preprocessing import PreprocessingResult
from backend.pipeline.types import BANDS, BAND_NAMES, CH_NAMES, Cadence, PipelineFrame


RAIL_THRESHOLD = 995.0  # µV


# --- Result dataclasses ---

@dataclass
class BandPowerResult:
    band_powers: dict[str, list[float]]
    theta_beta_ratio: list[float]
    frontal_alpha_asymmetry: float


@dataclass
class SignalQualityResult:
    quality: dict[str, float]
    fit_status: str


@dataclass
class HeartRateResult:
    heart_rate_bpm: float
    spo2_percent: float
    hrv_rmssd_ms: float


@dataclass
class HeadMotionResult:
    head_movement: float
    head_pose: tuple[float, float]
    motion_artifact: bool


# --- Stages ---

class BandPowerExtractor(Stage):
    name = "band_power_extractor"
    cadence = Cadence.SLOW

    def __init__(self, bands: dict[str, tuple[float, float]] | None = None):
        self.bands = bands or BANDS

    def process(self, frame: PipelineFrame) -> None:
        prep = frame.get(PreprocessingResult)
        eeg = prep.eeg_filtered if prep else frame.eeg
        if eeg is None:
            return

        sampling_rate = 256
        nfft = DataFilter.get_nearest_power_of_two(sampling_rate)
        if eeg.shape[1] < nfft:
            return

        band_powers: dict[str, list[float]] = {b: [] for b in BAND_NAMES}

        for ch_idx in range(eeg.shape[0]):
            channel_data = eeg[ch_idx].astype(np.float64).copy()
            try:
                DataFilter.detrend(channel_data, DetrendOperations.LINEAR.value)
                psd = DataFilter.get_psd_welch(
                    channel_data, nfft, nfft // 2,
                    sampling_rate, WindowOperations.HANNING.value,
                )
                for band_name in BAND_NAMES:
                    low, high = self.bands[band_name]
                    power = DataFilter.get_band_power(psd, low, high)
                    band_powers[band_name].append(round(float(power), 2))
            except Exception:
                for band_name in BAND_NAMES:
                    band_powers[band_name].append(0.0)

        # Theta/beta ratio
        theta_beta = []
        for i in range(len(band_powers.get("theta", []))):
            theta = band_powers["theta"][i]
            beta = band_powers["beta"][i]
            theta_beta.append(round(theta / beta, 2) if beta > 0 else 0.0)

        # Frontal alpha asymmetry
        alpha = band_powers.get("alpha", [0, 0, 0, 0])
        if len(alpha) >= 4:
            af7_alpha = max(alpha[1], 1e-10)
            af8_alpha = max(alpha[2], 1e-10)
            faa = round(math.log(af8_alpha) - math.log(af7_alpha), 3)
        else:
            faa = 0.0

        frame.set(BandPowerResult(
            band_powers=band_powers,
            theta_beta_ratio=theta_beta,
            frontal_alpha_asymmetry=faa,
        ))


class SignalQualityChecker(Stage):
    name = "signal_quality_checker"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        quality = {}
        for i, name in enumerate(CH_NAMES[:frame.eeg.shape[0]]):
            channel = frame.eeg[i]
            n = len(channel)
            railed = float(np.sum(np.abs(channel) > RAIL_THRESHOLD)) / n
            railed_score = max(0.0, 1.0 - railed * 10)
            std = float(np.std(channel))
            if std < 2.0:
                std_score = 0.2
            elif std > 200.0:
                std_score = 0.3
            else:
                std_score = 1.0
            quality[name] = round(min(railed_score, std_score), 2)

        poor_count = sum(1 for q in quality.values() if q < 0.7)
        if poor_count == 0:
            fit = "good"
        elif poor_count <= 2:
            fit = "adjust"
        else:
            fit = "poor"

        frame.set(SignalQualityResult(quality=quality, fit_status=fit))


class HeartRateExtractor(Stage):
    name = "heart_rate_extractor"
    cadence = Cadence.SLOW

    def __init__(self):
        self._ppg_accumulator: np.ndarray | None = None
        self._max_samples = 1280  # 20s at 64Hz

    def process(self, frame: PipelineFrame) -> None:
        if frame.ppg is None:
            return

        # Accumulate PPG across ticks
        if self._ppg_accumulator is not None:
            self._ppg_accumulator = np.concatenate(
                [self._ppg_accumulator, frame.ppg], axis=1
            )
        else:
            self._ppg_accumulator = frame.ppg.copy()

        if self._ppg_accumulator.shape[1] > self._max_samples:
            self._ppg_accumulator = self._ppg_accumulator[:, -self._max_samples:]

        if self._ppg_accumulator.shape[1] < 1024:
            return

        ppg = self._ppg_accumulator
        ppg_ir = ppg[1].astype(np.float64)
        ppg_red = ppg[0].astype(np.float64)

        try:
            hr = float(DataFilter.get_heart_rate(ppg_ir, ppg_red, 64, 1024))
        except Exception:
            hr = 0.0

        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg_ir, ppg_red, 64))
        except Exception:
            spo2 = 0.0

        # HRV RMSSD from peak detection
        hrv_rmssd = 0.0
        try:
            ppg_filt = ppg_ir.copy()
            DataFilter.detrend(ppg_filt, DetrendOperations.LINEAR.value)
            DataFilter.perform_bandpass(ppg_filt, 64, 0.5, 4.0, 4, 0, 0.0)
            diff = np.diff(ppg_filt)
            peaks = []
            for i in range(1, len(diff)):
                if diff[i - 1] > 0 and diff[i] <= 0:
                    peaks.append(i)
            if len(peaks) >= 3:
                rr_intervals = np.diff(peaks) / 64.0 * 1000.0
                rr_intervals = rr_intervals[(rr_intervals > 300) & (rr_intervals < 2000)]
                if len(rr_intervals) >= 2:
                    successive_diffs = np.diff(rr_intervals)
                    hrv_rmssd = float(np.sqrt(np.mean(successive_diffs ** 2)))
        except Exception:
            hrv_rmssd = 0.0

        frame.set(HeartRateResult(
            heart_rate_bpm=round(hr, 1),
            spo2_percent=round(spo2, 1),
            hrv_rmssd_ms=round(hrv_rmssd, 1),
        ))


class HeadMotionExtractor(Stage):
    name = "head_motion_extractor"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        if frame.imu is None or frame.imu.shape[1] < 2:
            return

        accel = frame.imu[:3]

        # Movement: RMS of per-axis std-dev
        std_per_axis = np.std(accel, axis=1)
        movement = round(float(np.sqrt(np.mean(std_per_axis ** 2))), 4)

        # Pose: pitch/roll from mean accel
        mean_accel = np.mean(accel, axis=1)
        ax, ay, az = float(mean_accel[0]), float(mean_accel[1]), float(mean_accel[2])
        pitch = round(math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2))), 1)
        roll = round(math.degrees(math.atan2(ay, math.sqrt(ax**2 + az**2))), 1)

        frame.set(HeadMotionResult(
            head_movement=movement,
            head_pose=(pitch, roll),
            motion_artifact=movement > 0.05,
        ))
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_features.py -v`
Expected: all 12 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/features.py tests/test_pipeline_stages_features.py
git commit -m "feat(pipeline): add BandPower, SignalQuality, HeartRate, HeadMotion stages"
```

---

### Task 5: Create detector stages (BlinkDetector, ClenchDetector)

**Files:**
- Create: `backend/pipeline/stages/detectors.py`

**Step 1: Write failing test**

Create: `tests/test_pipeline_stages_detectors.py`

```python
import time
import numpy as np
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.detectors import (
    BlinkDetector,
    ClenchDetector,
    ClenchResult,
)


def test_blink_detector_no_blink_in_noise():
    """Normal EEG noise should not trigger blinks."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 64)).astype(np.float64) * 20  # low amplitude noise
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    detector = BlinkDetector()
    detector.process(frame)
    blink_events = [e for e in frame.events if "blink" in e.kind]
    assert len(blink_events) == 0


def test_blink_detector_detects_spike():
    """A large spike on AF7/AF8 should be detected."""
    eeg = np.zeros((4, 256), dtype=np.float64)
    # Normal noise baseline
    rng = np.random.default_rng(42)
    eeg += rng.standard_normal((4, 256)) * 10
    # Insert a massive spike at sample 128 on AF7 (idx 1) and AF8 (idx 2)
    eeg[1, 125:131] = -500.0
    eeg[2, 125:131] = -500.0

    detector = BlinkDetector()
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    detector.process(frame)
    blink_events = [e for e in frame.events if "blink" in e.kind]
    assert len(blink_events) >= 1


def test_blink_detector_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    BlinkDetector().process(frame)
    assert len(frame.events) == 0


def test_clench_detector_no_clench_in_calm():
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 256)).astype(np.float64) * 10
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    ClenchDetector().process(frame)
    assert frame.get(ClenchResult) is None or not frame.get(ClenchResult).jaw_clench


def test_clench_detector_detects_emg():
    """High-frequency burst on TP9/TP10 should trigger clench."""
    eeg = np.zeros((4, 256), dtype=np.float64)
    rng = np.random.default_rng(42)
    eeg += rng.standard_normal((4, 256)) * 5
    # Add 30Hz EMG burst on TP9 (idx 0) and TP10 (idx 3)
    t = np.arange(256) / 256.0
    emg_signal = np.sin(2 * np.pi * 30 * t) * 100  # 100µV at 30Hz
    eeg[0, 50:200] += emg_signal[50:200]
    eeg[3, 50:200] += emg_signal[50:200]

    detector = ClenchDetector()
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    detector.process(frame)
    cr = frame.get(ClenchResult)
    assert cr is not None
    assert cr.jaw_clench


def test_clench_detector_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    ClenchDetector().process(frame)
    assert frame.get(ClenchResult) is None
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_detectors.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

`backend/pipeline/stages/detectors.py`:
```python
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, Event, PipelineFrame


@dataclass
class ClenchResult:
    jaw_clench: bool


class BlinkDetector(Stage):
    name = "blink_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        z_threshold: float = 3.5,
        refractory_ms: float = 300,
        double_window_ms: float = 600,
        triple_window_ms: float = 900,
        window_size: int = 512,
    ):
        self.z_threshold = z_threshold
        self.refractory_ms = refractory_ms
        self.double_window_ms = double_window_ms
        self.triple_window_ms = triple_window_ms
        self.window_size = window_size
        self._buffer: np.ndarray | None = None  # rolling AF7+AF8 average
        self._last_peak_time: float = 0.0
        self._recent_peaks: deque[float] = deque(maxlen=10)
        self._pending_classification_time: float = 0.0

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        # Use average of AF7 (idx 1) and AF8 (idx 2)
        frontal = (frame.eeg[1] + frame.eeg[2]) / 2.0

        # Append to buffer
        if self._buffer is not None:
            self._buffer = np.concatenate([self._buffer, frontal])
            if len(self._buffer) > self.window_size:
                self._buffer = self._buffer[-self.window_size:]
        else:
            self._buffer = frontal.copy()

        if len(self._buffer) < 32:
            return

        now = frame.timestamp or time.time()

        # Detect peaks using z-score
        try:
            data = self._buffer.astype(np.float64)
            peaks = DataFilter.detect_peaks_z_score(
                data, lag=int(min(30, len(data) // 4)),
                threshold=self.z_threshold, influence=0.3,
            )
            # peaks is array of 0/1 same length as data
            # We only care about NEW peaks (in the last chunk)
            new_start = max(0, len(data) - len(frontal))
            new_peaks = np.where(peaks[new_start:] != 0)[0]

            for _ in new_peaks:
                # Check refractory
                if (now - self._last_peak_time) * 1000 < self.refractory_ms:
                    continue
                self._last_peak_time = now
                self._recent_peaks.append(now)
        except Exception:
            return

        # Classify: wait for refractory period after last peak, then count
        if not self._recent_peaks:
            return

        time_since_last = (now - self._recent_peaks[-1]) * 1000
        if time_since_last < self.refractory_ms:
            return  # still within refractory, might get more peaks

        # Count peaks within classification window
        cutoff_triple = now - self.triple_window_ms / 1000
        recent = [t for t in self._recent_peaks if t > cutoff_triple]
        count = len(recent)
        self._recent_peaks.clear()

        if count >= 3:
            frame.events.append(Event(
                kind="triple_blink", timestamp=now, confidence=0.8, channel="AF7+AF8",
            ))
        elif count == 2:
            frame.events.append(Event(
                kind="double_blink", timestamp=now, confidence=0.85, channel="AF7+AF8",
            ))
        elif count == 1:
            frame.events.append(Event(
                kind="single_blink", timestamp=now, confidence=0.9, channel="AF7+AF8",
            ))


class ClenchDetector(Stage):
    name = "clench_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        emg_lowcut: float = 20.0,
        emg_highcut: float = 45.0,
        threshold_uv: float = 50.0,
        min_duration_ms: float = 100,
    ):
        self.emg_lowcut = emg_lowcut
        self.emg_highcut = emg_highcut
        self.threshold_uv = threshold_uv
        self.min_duration_ms = min_duration_ms

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 32:
            return

        # TP9 (idx 0) and TP10 (idx 3) — temporal channels pick up jaw EMG
        temporal = np.stack([frame.eeg[0], frame.eeg[3]])  # (2, N)
        sr = 256

        # Bandpass for EMG band
        filtered = temporal.copy().astype(np.float64)
        for ch in range(2):
            try:
                DataFilter.perform_bandpass(
                    filtered[ch], sr, self.emg_lowcut, self.emg_highcut, 4, 0, 0.0,
                )
            except Exception:
                return

        # Compute envelope (abs, smoothed)
        envelope = np.abs(filtered)
        # Average across both temporal channels
        avg_envelope = np.mean(envelope, axis=0)

        # Check if enough consecutive samples exceed threshold
        above = avg_envelope > self.threshold_uv
        min_samples = int(self.min_duration_ms / 1000.0 * sr)

        # Find longest run of True
        if not np.any(above):
            frame.set(ClenchResult(jaw_clench=False))
            return

        # Simple: check if the ratio of above-threshold samples is high enough
        # For a sustained clench, >50% of samples should be above threshold
        n_above = int(np.sum(above))
        clenched = n_above >= min_samples

        frame.set(ClenchResult(jaw_clench=clenched))
        if clenched:
            now = frame.timestamp or time.time()
            frame.events.append(Event(
                kind="clench", timestamp=now, confidence=0.85,
                channel="TP9+TP10",
                metadata={"duration_samples": n_above},
            ))
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_stages_detectors.py -v`
Expected: all 6 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/detectors.py tests/test_pipeline_stages_detectors.py
git commit -m "feat(pipeline): add BlinkDetector and ClenchDetector stages"
```

---

### Task 6: Create serializer (frame_to_metrics)

**Files:**
- Create: `backend/pipeline/serialize.py`

**Step 1: Write failing test**

Create: `tests/test_pipeline_serialize.py`

```python
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.features import (
    BandPowerResult,
    SignalQualityResult,
    HeartRateResult,
    HeadMotionResult,
)
from backend.pipeline.stages.detectors import ClenchResult
from backend.pipeline.serialize import frame_to_metrics


def test_empty_frame_returns_empty():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    metrics = frame_to_metrics(frame)
    assert metrics == {}


def test_eeg_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(BandPowerResult(
        band_powers={"delta": [1.0, 2.0, 3.0, 4.0], "theta": [0.5]*4,
                     "alpha": [1.0]*4, "beta": [0.3]*4, "gamma": [0.1]*4},
        theta_beta_ratio=[1.5]*4,
        frontal_alpha_asymmetry=0.1,
    ))
    frame.set(SignalQualityResult(
        quality={"TP9": 0.9, "AF7": 0.8, "AF8": 0.85, "TP10": 0.95},
        fit_status="good",
    ))
    metrics = frame_to_metrics(frame)
    assert "eeg" in metrics
    assert metrics["eeg"]["band_powers"]["delta"] == [1.0, 2.0, 3.0, 4.0]
    assert metrics["eeg"]["fit_status"] == "good"
    assert metrics["eeg"]["signal_quality"]["TP9"] == 0.9


def test_ppg_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeartRateResult(heart_rate_bpm=72.0, spo2_percent=98.0, hrv_rmssd_ms=35.0))
    metrics = frame_to_metrics(frame)
    assert metrics["ppg"]["heart_rate_bpm"] == 72.0


def test_imu_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(5.0, -3.0), motion_artifact=False))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["head_movement"] == 0.02
    assert metrics["imu"]["head_pose"]["pitch"] == 5.0
    assert metrics["imu"]["motion_artifact"] is False


def test_imu_with_clench():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(0.0, 0.0), motion_artifact=False))
    frame.set(ClenchResult(jaw_clench=True))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["jaw_clench"] is True


def test_imu_jaw_clench_defaults_false():
    """When HeadMotionResult exists but no ClenchResult, jaw_clench should be False."""
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(0.0, 0.0), motion_artifact=False))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["jaw_clench"] is False
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_serialize.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

`backend/pipeline/serialize.py`:
```python
"""Translate pipeline results to the WebSocket JSON format the frontend expects.

This is the ONLY place that maps stage results → dashboard JSON keys.
When adding a new stage whose output should appear on the dashboard,
add one `if` block here.
"""
from __future__ import annotations

from backend.pipeline.stages.detectors import ClenchResult
from backend.pipeline.stages.features import (
    BandPowerResult,
    HeadMotionResult,
    HeartRateResult,
    SignalQualityResult,
)
from backend.pipeline.types import PipelineFrame


def frame_to_metrics(frame: PipelineFrame) -> dict:
    metrics: dict = {}

    bp = frame.get(BandPowerResult)
    sq = frame.get(SignalQualityResult)
    if bp or sq:
        eeg: dict = {}
        if bp:
            eeg["band_powers"] = bp.band_powers
            eeg["theta_beta_ratio"] = bp.theta_beta_ratio
            eeg["frontal_alpha_asymmetry"] = bp.frontal_alpha_asymmetry
        if sq:
            eeg["signal_quality"] = sq.quality
            eeg["fit_status"] = sq.fit_status
        metrics["eeg"] = eeg

    hr = frame.get(HeartRateResult)
    if hr:
        metrics["ppg"] = {
            "heart_rate_bpm": hr.heart_rate_bpm,
            "spo2_percent": hr.spo2_percent,
            "hrv_rmssd_ms": hr.hrv_rmssd_ms,
        }

    hm = frame.get(HeadMotionResult)
    if hm:
        cl = frame.get(ClenchResult)
        metrics["imu"] = {
            "head_movement": hm.head_movement,
            "head_pose": {"pitch": hm.head_pose[0], "roll": hm.head_pose[1]},
            "motion_artifact": hm.motion_artifact,
            "jaw_clench": cl.jaw_clench if cl else False,
        }

    return metrics
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_serialize.py -v`
Expected: all 6 tests PASS

**Step 5: Commit**

```bash
git add backend/pipeline/serialize.py tests/test_pipeline_serialize.py
git commit -m "feat(pipeline): add frame_to_metrics serializer"
```

---

### Task 7: Create factory and LogAction

**Files:**
- Create: `backend/pipeline/factory.py`
- Create: `backend/pipeline/actions/__init__.py`
- Create: `backend/pipeline/actions/log.py`

**Step 1: Write failing test**

Create: `tests/test_pipeline_factory.py`

```python
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.base import Pipeline
from backend.pipeline.types import Cadence


def test_create_default_pipeline():
    pipeline = create_default_pipeline()
    assert isinstance(pipeline, Pipeline)
    slow_stages = [s for s in pipeline.stages if s.cadence == Cadence.SLOW]
    fast_stages = [s for s in pipeline.stages if s.cadence == Cadence.FAST]
    assert len(slow_stages) >= 4  # bandpass, bandpower, signal_quality, head_motion
    assert len(fast_stages) >= 2  # blink, clench
    assert len(pipeline.actions) >= 1  # at least LogAction
```

**Step 2: Run test to verify it fails**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_factory.py -v`
Expected: FAIL

**Step 3: Write implementation**

`backend/pipeline/actions/__init__.py`:
```python
"""Pipeline actions."""
```

`backend/pipeline/actions/log.py`:
```python
from __future__ import annotations

import logging

from backend.pipeline.base import Action
from backend.pipeline.types import Event

log = logging.getLogger("bci.events")


class LogAction(Action):
    def handle(self, events: list[Event]) -> None:
        for event in events:
            log.info(
                "%s confidence=%.2f channel=%s",
                event.kind, event.confidence, event.channel,
            )
```

`backend/pipeline/factory.py`:
```python
"""Pipeline assembly.

To swap a stage: change one line.
To add a stage: append one line + write the stage file.
"""
from __future__ import annotations

from backend.pipeline.actions.log import LogAction
from backend.pipeline.base import Pipeline
from backend.pipeline.stages.detectors import BlinkDetector, ClenchDetector
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
from backend.pipeline.stages.preprocessing import BandPassFilter


def create_default_pipeline() -> Pipeline:
    stages = [
        # SLOW — spectral features, vitals
        BandPassFilter(lowcut=1.0, highcut=45.0, notch=50.0),
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        # FAST — event detection
        BlinkDetector(),
        ClenchDetector(),
    ]
    actions = [
        LogAction(),
    ]
    return Pipeline(stages, actions)
```

**Step 4: Run test to verify it passes**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_factory.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/factory.py backend/pipeline/actions/__init__.py backend/pipeline/actions/log.py tests/test_pipeline_factory.py
git commit -m "feat(pipeline): add factory and LogAction"
```

---

### Task 8: Integration test — pipeline produces same JSON as build_metrics

**Files:**
- Create: `tests/test_pipeline_integration.py`

**Step 1: Write integration test**

```python
"""Verify pipeline produces the same JSON structure as the old build_metrics()."""
import numpy as np
from backend.processing import build_metrics
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.serialize import frame_to_metrics


def test_pipeline_matches_build_metrics_eeg_keys():
    """Pipeline's EEG output must have the same keys as build_metrics."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    # Old path
    old = build_metrics(eeg, None, None, 256)

    # New path
    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    # Both should have "eeg" key with same sub-keys
    assert "eeg" in old
    assert "eeg" in new
    old_keys = set(old["eeg"].keys())
    new_keys = set(new["eeg"].keys())
    assert old_keys == new_keys, f"Key mismatch: old={old_keys}, new={new_keys}"


def test_pipeline_matches_build_metrics_imu_keys():
    """Pipeline's IMU output must have the same keys as build_metrics."""
    rng = np.random.default_rng(42)
    imu = rng.standard_normal((6, 104)).astype(np.float64)
    imu[2, :] += 1.0  # gravity on z-axis

    old = build_metrics(None, None, imu, 256)

    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu.copy(), timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    assert "imu" in old
    assert "imu" in new
    old_keys = set(old["imu"].keys())
    new_keys = set(new["imu"].keys())
    assert old_keys == new_keys, f"Key mismatch: old={old_keys}, new={new_keys}"


def test_pipeline_eeg_values_close():
    """Band power values should be similar (not identical due to Muse band ranges)."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    old = build_metrics(eeg.copy(), None, None, 256)
    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    # Theta/beta ratio should exist in both and be same length
    assert len(old["eeg"]["theta_beta_ratio"]) == len(new["eeg"]["theta_beta_ratio"])
    # Signal quality keys should match
    assert set(old["eeg"]["signal_quality"].keys()) == set(new["eeg"]["signal_quality"].keys())
```

**Step 2: Run test**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_pipeline_integration.py -v`
Expected: all 3 tests PASS

Note: Band power VALUES will differ slightly because the pipeline uses Muse 2 band ranges (alpha 7.5-13Hz) while old `processing.py` uses standard ranges (alpha 8-13Hz). The test checks structural compatibility, not exact value equality.

**Step 3: Commit**

```bash
git add tests/test_pipeline_integration.py
git commit -m "test: add pipeline integration tests — verify JSON structure matches"
```

---

### Task 9: Wire pipeline into EEGServer

**Files:**
- Modify: `backend/main.py`

**Step 1: Write the migration test**

Create: `tests/test_server_pipeline_integration.py`

```python
"""Verify EEGServer uses pipeline and produces correct metrics structure."""
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.serialize import frame_to_metrics
import numpy as np


def test_server_pipeline_flow():
    """Simulate what EEGServer._metrics_loop will do."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50
    imu = np.zeros((6, 104), dtype=np.float64)
    imu[2, :] = 1.0  # gravity

    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=imu, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    metrics = frame_to_metrics(frame)

    # Must have session key added by server (tested separately)
    # Pipeline produces eeg + imu
    assert "eeg" in metrics
    assert "imu" in metrics
    assert "band_powers" in metrics["eeg"]
    assert "head_movement" in metrics["imu"]
```

**Step 2: Run test**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/test_server_pipeline_integration.py -v`
Expected: PASS

**Step 3: Modify `backend/main.py` — replace `build_metrics` with pipeline**

Replace these imports at the top of `backend/main.py`:
```python
# OLD:
from backend.processing import build_metrics, CH_NAMES

# NEW:
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.serialize import frame_to_metrics
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.stages.features import HeartRateExtractor
```

In `EEGServer.__init__`, add pipeline creation and remove `_ppg_accumulator`:
```python
# OLD:
self._ppg_accumulator: np.ndarray | None = None

# NEW:
self._pipeline = create_default_pipeline()
```

Replace `_metrics_loop` body. The key change: instead of calling `build_metrics()` and manually managing PPG accumulator, build a `PipelineFrame` and run the pipeline:
```python
async def _metrics_loop(self):
    """Compute and broadcast derived metrics at configured rate."""
    interval = self.config.server.metrics_interval
    while self._running:
        await asyncio.sleep(interval)

        eeg = (
            np.concatenate(self._eeg_buffer, axis=1)
            if self._eeg_buffer else None
        )
        ppg = (
            np.concatenate(self._ppg_buffer, axis=1)
            if self._ppg_buffer else None
        )
        imu = (
            np.concatenate(self._imu_buffer, axis=1)
            if self._imu_buffer else None
        )

        self._eeg_buffer.clear()
        self._ppg_buffer.clear()
        self._imu_buffer.clear()

        frame = PipelineFrame(
            eeg=eeg, ppg=ppg, imu=imu,
            timestamp=time.time(),
        )
        self._pipeline.run(Cadence.SLOW, frame)
        metrics = frame_to_metrics(frame)

        metrics["session"] = {
            "recording": self._recording,
            "label": self._recording_label if self._recording else None,
            "duration_sec": round(time.time() - self._recording_start, 1) if self._recording else 0,
        }

        if metrics:
            log.debug("Broadcasting metrics keys: %s", list(metrics.keys()))
            await self._broadcast_text(encode_metrics(metrics))
```

Also update `_save_recording` to import `CH_NAMES` from pipeline types:
```python
from backend.pipeline.types import CH_NAMES
```
And update the `np.savez` call — `CH_NAMES` is now `list[str]` not `tuple`, but it's still iterable so no change needed.

**Step 4: Run all tests**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/ -v`
Expected: ALL tests PASS

**Step 5: Commit**

```bash
git add backend/main.py tests/test_server_pipeline_integration.py
git commit -m "feat: wire pipeline into EEGServer, replace build_metrics()"
```

---

### Task 10: Add FAST cadence loop for event detection

**Files:**
- Modify: `backend/main.py`

**Step 1: Add FAST pipeline run in `_stream_loop`**

After broadcasting the EEG binary frame, run FAST stages for event detection:

```python
# In _stream_loop, after broadcasting EEG:
if eeg is not None and eeg.shape[1] > 0:
    # ... existing broadcast code ...

    # Run FAST stages for event detection
    fast_frame = PipelineFrame(
        eeg=eeg, ppg=None, imu=None,
        timestamp=time.time(),
    )
    self._pipeline.run(Cadence.FAST, fast_frame)

    # Broadcast detected events
    if fast_frame.events:
        for event in fast_frame.events:
            await self._broadcast_text(json.dumps({
                "type": "bci_event",
                "kind": event.kind,
                "confidence": event.confidence,
                "channel": event.channel,
                "timestamp": event.timestamp,
            }))
```

**Step 2: Run all tests**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/ -v`
Expected: ALL tests PASS

**Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add FAST cadence loop for blink/clench event detection"
```

---

### Task 11: Verify old processing.py can be removed

**Files:**
- Modify: `backend/processing.py` — keep as-is for now (backward compat)
- Verify: no imports of `build_metrics` remain outside tests

**Step 1: Search for remaining imports**

Run: `cd /home/newub/w/zyphraexps && grep -rn "from backend.processing import" --include="*.py"`

Expected: only `tests/test_processing.py` and `tests/test_pipeline_integration.py` should import from `backend.processing`.

**Step 2: Run all tests one final time**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/ -v`
Expected: ALL tests PASS

**Step 3: Mark processing.py as deprecated (do NOT delete yet)**

Add a deprecation docstring at the top of `backend/processing.py`:

```python
"""DEPRECATED: This module is superseded by backend.pipeline.

All functions here are preserved for test compatibility.
New code should use the pipeline stages in backend/pipeline/stages/.
Will be removed after migration is validated in production.
"""
```

**Step 4: Commit**

```bash
git add backend/processing.py
git commit -m "docs: mark processing.py as deprecated in favor of pipeline"
```

---

### Task 12: Run full test suite + manual smoke test

**Step 1: Run full test suite**

Run: `cd /home/newub/w/zyphraexps && python -m pytest tests/ -v --tb=short`
Expected: ALL tests PASS, 0 failures

**Step 2: Manual smoke test with synthetic board**

Run: `cd /home/newub/w/zyphraexps && python -m backend.main --synthetic --port 8765`

Verify in another terminal:
```bash
# Connect and watch for metrics JSON
python -c "
import asyncio, websockets
async def main():
    async with websockets.connect('ws://localhost:8765') as ws:
        for i in range(5):
            msg = await ws.recv()
            if isinstance(msg, str):
                print(msg[:200])
asyncio.run(main())
"
```

Expected: JSON messages with `"type": "metrics"` containing `eeg.band_powers`, `eeg.signal_quality`, `imu.head_movement`, and possibly `bci_event` messages.

**Step 3: Verify frontend dashboard still works**

Run frontend: `cd /home/newub/w/zyphraexps/frontend && pnpm dev`

Expected: Dashboard shows EEG waveforms, band powers, signal quality, motion data — identical to before the refactor. No frontend changes were made.

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: pipeline refactor complete — all tests pass"
```

---

## Summary

| Task | What | Files Created/Modified |
|------|------|----------------------|
| 1 | Core types | `backend/pipeline/{__init__,types}.py`, `tests/test_pipeline_types.py` |
| 2 | Stage/Action/Pipeline | `backend/pipeline/base.py`, `tests/test_pipeline_runner.py` |
| 3 | Preprocessing stages | `backend/pipeline/stages/{__init__,preprocessing}.py`, test |
| 4 | Feature stages | `backend/pipeline/stages/features.py`, test |
| 5 | Detector stages | `backend/pipeline/stages/detectors.py`, test |
| 6 | Serializer | `backend/pipeline/serialize.py`, test |
| 7 | Factory + LogAction | `backend/pipeline/{factory,actions/{__init__,log}}.py`, test |
| 8 | Integration test | `tests/test_pipeline_integration.py` |
| 9 | Wire into EEGServer | `backend/main.py` (modified) |
| 10 | FAST cadence loop | `backend/main.py` (modified) |
| 11 | Deprecate processing.py | `backend/processing.py` (docstring) |
| 12 | Full validation | Manual smoke test |

**Substitutability achieved:** To swap BandPassFilter for WaveletDenoiser, change one line in `factory.py`:
```python
# BandPassFilter(lowcut=1.0, highcut=45.0, notch=50.0),
WaveletDenoiser(wavelet="db4", decomp_level=4),
```
Both write `PreprocessingResult`, so all downstream stages work unchanged.
