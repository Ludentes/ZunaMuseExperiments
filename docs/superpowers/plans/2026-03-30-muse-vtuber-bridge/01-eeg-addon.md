# Plan 1: EEG Addon — Blink/Clench/Focus/Relax → VMC Blendshapes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect Muse 2, detect blinks/clench/focus/relaxation via EEG, output as VMC blendshapes visible in VSeeFace within 5 minutes.

**Architecture:** Port EEG detectors from zyphraexps pipeline (SpeechDetector, BlinkDetector, ClenchDetector). Add new BandPowerStage and FocusRelaxStage with artifact-gated EMA and BFiVRC-compatible formulas. VMC output via python-osc (5 message types, ~60 lines).

**Tech Stack:** BrainFlow, numpy, scipy, python-osc

**Depends on:** Plan 0 (repo setup, pipeline framework, BrainFlowSource)

---

### Task 1: SpeechDetector (blink guard)

**Files:**
- Create: `src/muse_vtuber/pipeline/speech.py`
- Create: `tests/test_speech.py`

Adapt from `zyphraexps/backend/pipeline/stages/detectors.py` — the `SpeechDetector` class. Uses adaptive HF RMS baseline on temporal channels (TP9/TP10) to detect sustained EMG from speech/vocalization. Guards the blink detector from false positives during talking.

- [ ] **Step 1: Write test**

`tests/test_speech.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.speech import SpeechDetector, SpeechResult
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


def _make_frame(temporal_amplitude: float = 5.0, n_samples: int = 16) -> PipelineFrame:
    """Create frame with 4-channel EEG. Temporal channels (0,3) at given amplitude."""
    eeg = np.random.randn(4, n_samples) * 2.0
    eeg[0] = np.random.randn(n_samples) * temporal_amplitude  # TP9
    eeg[3] = np.random.randn(n_samples) * temporal_amplitude  # TP10
    return PipelineFrame(eeg=eeg, imu=None, timestamp=1.0)


def test_speech_detector_cadence():
    det = SpeechDetector()
    assert det.cadence == Cadence.FAST


def test_quiet_not_speech():
    """Low temporal HF should not trigger speech."""
    det = SpeechDetector()
    for _ in range(100):
        frame = _make_frame(temporal_amplitude=3.0)
        det.process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert result.speech_active is False


def test_loud_temporal_triggers_speech():
    """High sustained temporal HF triggers speech detection."""
    det = SpeechDetector()
    for _ in range(100):
        frame = _make_frame(temporal_amplitude=50.0)
        det.process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert result.speech_active is True


def test_none_eeg_safe():
    det = SpeechDetector()
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    det.process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert result.speech_active is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_speech.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SpeechDetector**

`src/muse_vtuber/pipeline/speech.py`:
```python
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

import numpy as np

from muse_vtuber.pipeline.base import Stage
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


@dataclass
class SpeechResult:
    speech_active: bool


def _hf_rms(sig: np.ndarray) -> float:
    """RMS of first-order diff — approximates high-frequency energy."""
    if len(sig) < 2:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(sig) ** 2)))


class SpeechDetector(Stage):
    """Detect speech via sustained temporal EMG.

    Adaptive baseline: rolling median of temporal HF RMS.
    Flags speech when enough recent chunks exceed baseline × hf_ratio_thresh.
    """

    name = "speech_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        hf_thresh: float = 15.0,
        hf_ratio_thresh: float = 2.0,
        window_chunks: int = 48,
        min_active_frac: float = 0.4,
    ):
        self.hf_thresh = hf_thresh
        self.hf_ratio_thresh = hf_ratio_thresh
        self.window_chunks = window_chunks
        self.min_active = int(window_chunks * min_active_frac)
        self._hf_history: deque[float] = deque(maxlen=window_chunks)
        self._hf_baseline_history: deque[float] = deque(maxlen=256)
        self._hf_baseline: float = 0.0
        self._update_ctr: int = 0

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            frame.set(SpeechResult(speech_active=False))
            return

        temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0
        t_hf = _hf_rms(temporal)
        self._hf_history.append(t_hf)

        if self._hf_baseline > 1.0:
            effective_thresh = max(self._hf_baseline * self.hf_ratio_thresh, self.hf_thresh)
        else:
            effective_thresh = self.hf_thresh

        active = False
        if len(self._hf_history) >= self.window_chunks:
            n_above = sum(1 for v in self._hf_history if v > effective_thresh)
            active = n_above >= self.min_active

        self._update_ctr += 1
        if self._update_ctr >= 8:
            self._update_ctr = 0
            if not active:
                self._hf_baseline_history.append(t_hf)
                if len(self._hf_baseline_history) >= 8:
                    self._hf_baseline = float(np.median(self._hf_baseline_history))

        frame.set(SpeechResult(speech_active=active))
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_speech.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/speech.py tests/test_speech.py
git commit -m "feat: SpeechDetector for blink guard"
```

---

### Task 2: ClenchDetector

**Files:**
- Create: `src/muse_vtuber/pipeline/clench.py`
- Create: `tests/test_clench.py`

Port from zyphraexps. Bandpass 20-45Hz on temporal channels, envelope detection, duration threshold.

- [ ] **Step 1: Write test**

`tests/test_clench.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.clench import ClenchDetector, ClenchResult
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


def test_clench_detector_cadence():
    det = ClenchDetector()
    assert det.cadence == Cadence.FAST


def _make_clench_frame(clenching: bool, n_samples: int = 64) -> PipelineFrame:
    """Simulate clench: high 20-45Hz energy on temporal channels."""
    eeg = np.random.randn(4, n_samples) * 2.0
    if clenching:
        t = np.linspace(0, n_samples / 256.0, n_samples)
        emg = np.sin(2 * np.pi * 30 * t) * 80.0  # 30Hz, 80µV
        eeg[0] += emg  # TP9
        eeg[3] += emg  # TP10
    return PipelineFrame(eeg=eeg, imu=None, timestamp=1.0)


def test_quiet_no_clench():
    det = ClenchDetector()
    for _ in range(20):
        frame = _make_clench_frame(clenching=False)
        det.process(frame)
    result = frame.get(ClenchResult)
    assert result is not None
    assert result.jaw_clench is False


def test_sustained_emg_triggers_clench():
    det = ClenchDetector()
    # Feed many frames of clench signal
    for _ in range(30):
        frame = _make_clench_frame(clenching=True)
        det.process(frame)
    result = frame.get(ClenchResult)
    assert result is not None
    assert result.jaw_clench is True


def test_none_eeg_safe():
    det = ClenchDetector()
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    det.process(frame)
    result = frame.get(ClenchResult)
    assert result is not None
    assert result.jaw_clench is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_clench.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement ClenchDetector**

`src/muse_vtuber/pipeline/clench.py`:
```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter

from muse_vtuber.pipeline.base import Stage
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


@dataclass
class ClenchResult:
    jaw_clench: bool


class ClenchDetector(Stage):
    """Detect jaw clench via sustained high-frequency EMG on temporal channels.

    Bandpass 20-45Hz, compute RMS envelope, threshold with duration gate.
    """

    name = "clench_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        bp_low: float = 20.0,
        bp_high: float = 45.0,
        rms_threshold: float = 25.0,
        min_chunks: int = 5,
        sample_rate: int = 256,
    ):
        self.bp_low = bp_low
        self.bp_high = bp_high
        self.rms_threshold = rms_threshold
        self.min_chunks = min_chunks
        self.sample_rate = sample_rate
        self._above_count: int = 0

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 4:
            frame.set(ClenchResult(jaw_clench=False))
            return

        # Average temporal channels (TP9 + TP10)
        temporal = ((frame.eeg[0] + frame.eeg[3]) / 2.0).astype(np.float64).copy()

        # Bandpass 20-45Hz
        try:
            DataFilter.perform_bandpass(
                temporal, self.sample_rate,
                self.bp_low, self.bp_high,
                4, 0, 0.0,
            )
        except Exception:
            frame.set(ClenchResult(jaw_clench=False))
            return

        rms = float(np.sqrt(np.mean(temporal ** 2)))

        if rms > self.rms_threshold:
            self._above_count += 1
        else:
            self._above_count = max(0, self._above_count - 2)

        clenching = self._above_count >= self.min_chunks
        frame.set(ClenchResult(jaw_clench=clenching))
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_clench.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/clench.py tests/test_clench.py
git commit -m "feat: ClenchDetector for jaw clench detection"
```

---

### Task 3: BlinkDetector

**Files:**
- Create: `src/muse_vtuber/pipeline/blink.py`
- Create: `tests/test_blink.py`

Port from zyphraexps — the full BlinkDetector with MAD-based adaptive threshold, sustained deflection, motion guard, clench guard, speech fusion, and shape validation. This is ~400 lines (stripped of debug logging). Copy wholesale from `zyphraexps/backend/pipeline/stages/detectors.py` BlinkDetector class, adapting imports.

- [ ] **Step 1: Write test**

`tests/test_blink.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.blink import BlinkDetector
from muse_vtuber.pipeline.clench import ClenchResult
from muse_vtuber.pipeline.speech import SpeechResult
from muse_vtuber.pipeline.types import Cadence, Event, PipelineFrame


def test_blink_detector_cadence():
    det = BlinkDetector()
    assert det.cadence == Cadence.FAST


def _simulate_blink(
    det: BlinkDetector,
    warmup_frames: int = 200,
    blink_amplitude: float = -120.0,
    blink_duration_chunks: int = 4,
) -> list[Event]:
    """Feed warmup (baseline), then a synthetic blink, then settle. Return all events."""
    events: list[Event] = []
    rng = np.random.default_rng(42)

    # Warmup: establish baseline
    for i in range(warmup_frames):
        eeg = rng.normal(0, 10, (4, 16))
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=i * 0.016)
        frame.set(SpeechResult(speech_active=False))
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)
        events.extend(frame.events)

    # Blink: large negative deflection on frontal channels
    for j in range(blink_duration_chunks):
        eeg = rng.normal(0, 10, (4, 16))
        eeg[1] += blink_amplitude  # AF7
        eeg[2] += blink_amplitude  # AF8
        t = (warmup_frames + j) * 0.016
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=t)
        frame.set(SpeechResult(speech_active=False))
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)
        events.extend(frame.events)

    # Post-blink settle
    for k in range(50):
        eeg = rng.normal(0, 10, (4, 16))
        t = (warmup_frames + blink_duration_chunks + k) * 0.016
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=t)
        frame.set(SpeechResult(speech_active=False))
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)
        events.extend(frame.events)

    return events


def test_detects_synthetic_blink():
    det = BlinkDetector()
    events = _simulate_blink(det)
    blink_events = [e for e in events if e.kind == "blink"]
    assert len(blink_events) >= 1


def test_no_blink_on_quiet_signal():
    det = BlinkDetector()
    rng = np.random.default_rng(42)
    events: list[Event] = []
    for i in range(500):
        eeg = rng.normal(0, 10, (4, 16))
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=i * 0.016)
        frame.set(SpeechResult(speech_active=False))
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)
        events.extend(frame.events)
    blinks = [e for e in events if e.kind == "blink"]
    assert len(blinks) == 0


def test_speech_suppresses_blink():
    """During speech, blinks should be rejected."""
    det = BlinkDetector()
    rng = np.random.default_rng(42)
    events: list[Event] = []

    # Warmup
    for i in range(200):
        eeg = rng.normal(0, 10, (4, 16))
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=i * 0.016)
        frame.set(SpeechResult(speech_active=False))
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)

    # Blink during speech — should be rejected
    for j in range(4):
        eeg = rng.normal(0, 10, (4, 16))
        eeg[1] -= 120
        eeg[2] -= 120
        t = (200 + j) * 0.016
        frame = PipelineFrame(eeg=eeg, imu=None, timestamp=t)
        frame.set(SpeechResult(speech_active=True))  # Speech active
        frame.set(ClenchResult(jaw_clench=False))
        det.process(frame)
        events.extend(frame.events)

    blinks = [e for e in events if e.kind == "blink"]
    assert len(blinks) == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_blink.py -v
```

Expected: FAIL

- [ ] **Step 3: Port BlinkDetector from zyphraexps**

Copy `zyphraexps/backend/pipeline/stages/detectors.py` BlinkDetector class to `src/muse_vtuber/pipeline/blink.py`. Change imports:
- `from backend.pipeline.base import Stage` → `from muse_vtuber.pipeline.base import Stage`
- `from backend.pipeline.types import ...` → `from muse_vtuber.pipeline.types import ...`
- Import `SpeechResult` from `muse_vtuber.pipeline.speech`
- Import `ClenchResult` from `muse_vtuber.pipeline.clench`
- Remove any references to `PreprocessingResult` or `ZunaResult` — use `frame.eeg` directly

The BlinkDetector is ~400-770 lines. Copy it entirely — do not simplify. The tuning constants were validated on recorded Muse data.

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_blink.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/blink.py tests/test_blink.py
git commit -m "feat: BlinkDetector ported from zyphraexps"
```

---

### Task 4: BandPowerStage with artifact-gated EMA

**Files:**
- Create: `src/muse_vtuber/pipeline/band_power.py`
- Create: `tests/test_band_power.py`

New implementation (not a direct port). Computes per-hemisphere band power with EMA smoothing. Artifact gate: when blink/clench/speech is active, EMA freezes to prevent contamination.

- [ ] **Step 1: Write test**

`tests/test_band_power.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.band_power import BandPowerResult, BandPowerStage
from muse_vtuber.pipeline.clench import ClenchResult
from muse_vtuber.pipeline.speech import SpeechResult
from muse_vtuber.pipeline.types import BAND_NAMES, Cadence, PipelineFrame


def _make_alpha_frame(n_samples: int = 256) -> PipelineFrame:
    """Create frame with strong 10Hz alpha signal on all channels."""
    t = np.linspace(0, n_samples / 256.0, n_samples)
    alpha_signal = np.sin(2 * np.pi * 10 * t) * 20.0  # 10Hz, 20µV
    eeg = np.tile(alpha_signal, (4, 1)) + np.random.randn(4, n_samples) * 2.0
    frame = PipelineFrame(eeg=eeg, imu=None, timestamp=1.0)
    frame.set(SpeechResult(speech_active=False))
    frame.set(ClenchResult(jaw_clench=False))
    return frame


def test_band_power_cadence():
    stage = BandPowerStage()
    assert stage.cadence == Cadence.SLOW


def test_band_power_computes_all_bands():
    stage = BandPowerStage()
    frame = _make_alpha_frame()
    stage.process(frame)
    result = frame.get(BandPowerResult)
    assert result is not None
    for band in BAND_NAMES:
        assert band in result.band_powers_avg
        assert result.band_powers_avg[band] >= 0.0


def test_alpha_dominant_in_alpha_signal():
    """Alpha band should have highest power when signal is 10Hz."""
    stage = BandPowerStage()
    frame = _make_alpha_frame(n_samples=512)
    stage.process(frame)
    result = frame.get(BandPowerResult)
    assert result is not None
    assert result.band_powers_avg["alpha"] > result.band_powers_avg["delta"]
    assert result.band_powers_avg["alpha"] > result.band_powers_avg["beta"]


def test_hemisphere_separation():
    """Left (TP9+AF7) and right (AF8+TP10) powers computed separately."""
    stage = BandPowerStage()
    frame = _make_alpha_frame()
    stage.process(frame)
    result = frame.get(BandPowerResult)
    assert result is not None
    assert "alpha" in result.band_powers_left
    assert "alpha" in result.band_powers_right


def test_artifact_gate_freezes_ema():
    """During speech, EMA should not update (freeze to last clean value)."""
    stage = BandPowerStage(ema_decay=0.5)  # aggressive decay for test visibility

    # Feed clean frames to establish baseline
    for _ in range(5):
        frame = _make_alpha_frame()
        stage.process(frame)
    result_clean = frame.get(BandPowerResult)
    clean_alpha = result_clean.band_powers_avg["alpha"]

    # Feed frame during speech (should freeze)
    frame_speech = _make_alpha_frame()
    frame_speech.set(SpeechResult(speech_active=True))
    frame_speech.set(ClenchResult(jaw_clench=False))
    # Override EEG with garbage — if EMA updates, value would change drastically
    frame_speech.eeg = np.random.randn(4, 256) * 100.0
    stage.process(frame_speech)
    result_speech = frame_speech.get(BandPowerResult)

    # EMA should have frozen — value should be close to clean
    assert abs(result_speech.band_powers_avg["alpha"] - clean_alpha) < clean_alpha * 0.5


def test_none_eeg_safe():
    stage = BandPowerStage()
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    stage.process(frame)
    assert frame.get(BandPowerResult) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_band_power.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement BandPowerStage**

`src/muse_vtuber/pipeline/band_power.py`:
```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations

from muse_vtuber.pipeline.base import Stage
from muse_vtuber.pipeline.clench import ClenchResult
from muse_vtuber.pipeline.speech import SpeechResult
from muse_vtuber.pipeline.types import (
    BAND_NAMES,
    BANDS,
    FRONTAL_CHS,
    LEFT_CHS,
    RIGHT_CHS,
    Cadence,
    PipelineFrame,
)

log = logging.getLogger("band_power")


@dataclass
class BandPowerResult:
    """Band power per hemisphere and average, EMA-smoothed."""

    band_powers_left: dict[str, float]
    band_powers_right: dict[str, float]
    band_powers_avg: dict[str, float]
    band_powers_per_ch: dict[str, list[float]]  # raw per-channel for debug


class BandPowerStage(Stage):
    """Compute frequency band power with artifact-gated EMA smoothing.

    When blink, clench, or speech is active, the EMA target freezes
    to the last clean value to prevent artifact contamination.
    """

    name = "band_power"
    cadence = Cadence.SLOW

    def __init__(self, ema_decay: float = 0.04, sample_rate: int = 256):
        self.ema_decay = ema_decay
        self.sample_rate = sample_rate
        self._ema: dict[str, list[float]] = {}  # band -> [ch0, ch1, ch2, ch3]

    def _is_artifact(self, frame: PipelineFrame) -> bool:
        speech = frame.get(SpeechResult)
        clench = frame.get(ClenchResult)
        if speech and speech.speech_active:
            return True
        if clench and clench.jaw_clench:
            return True
        # Check for blink event in current frame
        return any(e.kind == "blink" for e in frame.events)

    def _compute_raw_band_powers(self, eeg: np.ndarray) -> dict[str, list[float]] | None:
        """Compute raw band power per channel. Returns None on failure."""
        nfft = DataFilter.get_nearest_power_of_two(self.sample_rate)
        if eeg.shape[1] < nfft:
            return None

        n_channels = eeg.shape[0]
        band_powers: dict[str, list[float]] = {b: [] for b in BAND_NAMES}

        for ch_idx in range(n_channels):
            channel_data = eeg[ch_idx].astype(np.float64).copy()
            try:
                mu = np.mean(channel_data)
                sd = np.std(channel_data)
                if sd > 0:
                    np.clip(channel_data, mu - 4 * sd, mu + 4 * sd, out=channel_data)
                DataFilter.detrend(channel_data, DetrendOperations.LINEAR.value)
                psd = DataFilter.get_psd_welch(
                    channel_data, nfft, nfft // 2,
                    self.sample_rate, WindowOperations.HANNING.value,
                )
                for band_name in BAND_NAMES:
                    low, high = BANDS[band_name]
                    power = DataFilter.get_band_power(psd, low, high)
                    band_powers[band_name].append(float(power))
            except Exception:
                for band_name in BAND_NAMES:
                    band_powers[band_name].append(0.0)

        return band_powers

    def _update_ema(self, raw: dict[str, list[float]], artifact: bool) -> None:
        """Update EMA. If artifact, skip update (freeze)."""
        if artifact:
            return
        alpha = self.ema_decay
        for band, values in raw.items():
            if band not in self._ema:
                self._ema[band] = list(values)
            else:
                for i in range(len(values)):
                    if i < len(self._ema[band]):
                        self._ema[band][i] = alpha * values[i] + (1 - alpha) * self._ema[band][i]
                    else:
                        self._ema[band].append(values[i])

    def _hemisphere_avg(self, band: str, indices: list[int]) -> float:
        if band not in self._ema:
            return 0.0
        values = self._ema[band]
        selected = [values[i] for i in indices if i < len(values)]
        return sum(selected) / len(selected) if selected else 0.0

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        raw = self._compute_raw_band_powers(frame.eeg)
        if raw is None:
            return

        artifact = self._is_artifact(frame)
        self._update_ema(raw, artifact)

        left = {b: self._hemisphere_avg(b, LEFT_CHS) for b in BAND_NAMES}
        right = {b: self._hemisphere_avg(b, RIGHT_CHS) for b in BAND_NAMES}
        avg = {b: (left[b] + right[b]) / 2.0 for b in BAND_NAMES}

        frame.set(BandPowerResult(
            band_powers_left=left,
            band_powers_right=right,
            band_powers_avg=avg,
            band_powers_per_ch=raw,
        ))
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_band_power.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/band_power.py tests/test_band_power.py
git commit -m "feat: BandPowerStage with artifact-gated EMA smoothing"
```

---

### Task 5: FocusRelaxStage

**Files:**
- Create: `src/muse_vtuber/pipeline/focus.py`
- Create: `tests/test_focus.py`

Derives focus/relaxation from band power ratios. Uses BFiVRC-compatible formulas: `tanh(1.1 * log(beta/theta))` for focus, `tanh(1.1 * log(alpha/theta))` for relaxation.

- [ ] **Step 1: Write test**

`tests/test_focus.py`:
```python
import math

import numpy as np
import pytest

from muse_vtuber.pipeline.band_power import BandPowerResult
from muse_vtuber.pipeline.focus import FocusRelaxResult, FocusRelaxStage
from muse_vtuber.pipeline.types import BAND_NAMES, Cadence, PipelineFrame


def _make_frame_with_bands(
    alpha: float = 5.0,
    beta: float = 3.0,
    theta: float = 4.0,
) -> PipelineFrame:
    """Create frame with pre-computed band power result."""
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    bands = {b: 1.0 for b in BAND_NAMES}
    bands["alpha"] = alpha
    bands["beta"] = beta
    bands["theta"] = theta
    frame.set(BandPowerResult(
        band_powers_left=dict(bands),
        band_powers_right=dict(bands),
        band_powers_avg=dict(bands),
        band_powers_per_ch={b: [1.0, 1.0, 1.0, 1.0] for b in BAND_NAMES},
    ))
    return frame


def test_focus_cadence():
    stage = FocusRelaxStage()
    assert stage.cadence == Cadence.SLOW


def test_focus_formula_matches_bfivrc():
    """Focus = tanh(1.1 * log(beta / theta))"""
    stage = FocusRelaxStage()
    beta, theta = 8.0, 4.0
    frame = _make_frame_with_bands(beta=beta, theta=theta)
    stage.process(frame)
    result = frame.get(FocusRelaxResult)
    assert result is not None
    expected = math.tanh(1.1 * math.log(beta / theta))
    assert abs(result.focus_avg - expected) < 0.01


def test_relaxation_formula_matches_bfivrc():
    """Relax = tanh(1.1 * log(alpha / theta))"""
    stage = FocusRelaxStage()
    alpha, theta = 10.0, 4.0
    frame = _make_frame_with_bands(alpha=alpha, theta=theta)
    stage.process(frame)
    result = frame.get(FocusRelaxResult)
    assert result is not None
    expected = math.tanh(1.1 * math.log(alpha / theta))
    assert abs(result.relax_avg - expected) < 0.01


def test_unsigned_variants():
    """Unsigned variants clamp to [0, 1]."""
    stage = FocusRelaxStage()
    frame = _make_frame_with_bands(beta=1.0, theta=10.0)  # low focus (negative)
    stage.process(frame)
    result = frame.get(FocusRelaxResult)
    assert result is not None
    assert 0.0 <= result.focus_avg_unsigned <= 1.0
    assert 0.0 <= result.relax_avg_unsigned <= 1.0


def test_zero_theta_safe():
    """Zero theta should not crash (division by zero)."""
    stage = FocusRelaxStage()
    frame = _make_frame_with_bands(theta=0.0)
    stage.process(frame)
    result = frame.get(FocusRelaxResult)
    assert result is not None


def test_no_band_power_noop():
    stage = FocusRelaxStage()
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    stage.process(frame)
    assert frame.get(FocusRelaxResult) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_focus.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement FocusRelaxStage**

`src/muse_vtuber/pipeline/focus.py`:
```python
from __future__ import annotations

import math
from dataclasses import dataclass

from muse_vtuber.pipeline.band_power import BandPowerResult
from muse_vtuber.pipeline.base import Stage
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


@dataclass
class FocusRelaxResult:
    """Focus and relaxation metrics, per hemisphere and average."""

    focus_left: float     # signed [-1, 1]
    focus_right: float
    focus_avg: float
    relax_left: float     # signed [-1, 1]
    relax_right: float
    relax_avg: float
    focus_avg_unsigned: float   # [0, 1] for animation
    relax_avg_unsigned: float


def _neurofeedback_ratio(numerator: float, denominator: float) -> float:
    """BFiVRC formula: tanh(1.1 * log(num / denom)). Safe for zero denom."""
    if denominator <= 1e-10 or numerator <= 1e-10:
        return 0.0
    return math.tanh(1.1 * math.log(numerator / denominator))


def _signed_to_unsigned(val: float) -> float:
    """Map [-1, 1] → [0, 1]."""
    return max(0.0, min(1.0, (val + 1.0) / 2.0))


class FocusRelaxStage(Stage):
    """Derive focus/relaxation from band power ratios.

    Focus: tanh(1.1 * log(beta / theta))  — matches BrainFlowsIntoVRChat.
    Relax: tanh(1.1 * log(alpha / theta))  — matches BrainFlowsIntoVRChat.
    """

    name = "focus_relax"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        focus_left = _neurofeedback_ratio(
            bp.band_powers_left.get("beta", 0.0),
            bp.band_powers_left.get("theta", 0.0),
        )
        focus_right = _neurofeedback_ratio(
            bp.band_powers_right.get("beta", 0.0),
            bp.band_powers_right.get("theta", 0.0),
        )
        focus_avg = _neurofeedback_ratio(
            bp.band_powers_avg.get("beta", 0.0),
            bp.band_powers_avg.get("theta", 0.0),
        )

        relax_left = _neurofeedback_ratio(
            bp.band_powers_left.get("alpha", 0.0),
            bp.band_powers_left.get("theta", 0.0),
        )
        relax_right = _neurofeedback_ratio(
            bp.band_powers_right.get("alpha", 0.0),
            bp.band_powers_right.get("theta", 0.0),
        )
        relax_avg = _neurofeedback_ratio(
            bp.band_powers_avg.get("alpha", 0.0),
            bp.band_powers_avg.get("theta", 0.0),
        )

        frame.set(FocusRelaxResult(
            focus_left=round(focus_left, 4),
            focus_right=round(focus_right, 4),
            focus_avg=round(focus_avg, 4),
            relax_left=round(relax_left, 4),
            relax_right=round(relax_right, 4),
            relax_avg=round(relax_avg, 4),
            focus_avg_unsigned=round(_signed_to_unsigned(focus_avg), 4),
            relax_avg_unsigned=round(_signed_to_unsigned(relax_avg), 4),
        ))
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_focus.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/focus.py tests/test_focus.py
git commit -m "feat: FocusRelaxStage with BFiVRC-compatible formulas"
```

---

### Task 6: VMC blendshape output

**Files:**
- Create: `src/muse_vtuber/outputs/vmc.py`
- Create: `tests/test_vmc_output.py`

VMC protocol over python-osc. Sends blendshapes (blink, clench, focus, relaxation) and status heartbeat. Bone output (head tracking) will be added in Plan 2.

- [ ] **Step 1: Write test**

`tests/test_vmc_output.py`:
```python
import pytest

from muse_vtuber.outputs.vmc import VMCOutput, VMCBlendshapes


def test_vmc_output_builds_blendshape_messages():
    """VMC output converts blendshapes to OSC messages."""
    vmc = VMCOutput(host="127.0.0.1", port=0)  # port 0 = don't actually send

    blendshapes = VMCBlendshapes(
        blink=1.0,
        clench=0.5,
        focus=0.7,
        relaxation=0.3,
    )
    messages = vmc.build_blendshape_messages(blendshapes)

    # Should have: 4 Blend/Val + 1 Blend/Apply + 1 OK + 1 T = 7
    addresses = [m.address for m in messages]
    assert "/VMC/Ext/Blend/Val" in addresses
    assert "/VMC/Ext/Blend/Apply" in addresses
    assert "/VMC/Ext/OK" in addresses
    assert "/VMC/Ext/T" in addresses

    # Check blink value
    blink_msgs = [m for m in messages if m.address == "/VMC/Ext/Blend/Val" and m.params[0] == "blink"]
    assert len(blink_msgs) == 1
    assert blink_msgs[0].params[1] == 1.0


def test_vmc_blendshape_names():
    """Blendshape names follow VMC convention."""
    vmc = VMCOutput(host="127.0.0.1", port=0)
    blendshapes = VMCBlendshapes(blink=0.5, clench=0.0, focus=0.0, relaxation=0.0)
    messages = vmc.build_blendshape_messages(blendshapes)
    blend_names = [m.params[0] for m in messages if m.address == "/VMC/Ext/Blend/Val"]
    assert "blink" in blend_names
    assert "muse_clench" in blend_names
    assert "muse_focus" in blend_names
    assert "muse_relaxation" in blend_names
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_vmc_output.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement VMC output**

`src/muse_vtuber/outputs/vmc.py`:
```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.udp_client import SimpleUDPClient

log = logging.getLogger("vmc")


@dataclass
class VMCBlendshapes:
    blink: float = 0.0       # 0-1
    clench: float = 0.0      # 0-1
    focus: float = 0.0       # 0-1
    relaxation: float = 0.0  # 0-1


@dataclass
class VMCBoneTransform:
    """Bone position + rotation for /VMC/Ext/Bone/Pos."""
    bone_name: str
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    rot_w: float = 1.0


def _blend_val(name: str, value: float) -> OscMessage:
    builder = OscMessageBuilder(address="/VMC/Ext/Blend/Val")
    builder.add_arg(name)
    builder.add_arg(float(value))
    return builder.build()


def _blend_apply() -> OscMessage:
    builder = OscMessageBuilder(address="/VMC/Ext/Blend/Apply")
    return builder.build()


def _bone_pos(bone: VMCBoneTransform) -> OscMessage:
    builder = OscMessageBuilder(address="/VMC/Ext/Bone/Pos")
    builder.add_arg(bone.bone_name)
    builder.add_arg(float(bone.pos_x))
    builder.add_arg(float(bone.pos_y))
    builder.add_arg(float(bone.pos_z))
    builder.add_arg(float(bone.rot_x))
    builder.add_arg(float(bone.rot_y))
    builder.add_arg(float(bone.rot_z))
    builder.add_arg(float(bone.rot_w))
    return builder.build()


def _ok() -> OscMessage:
    builder = OscMessageBuilder(address="/VMC/Ext/OK")
    builder.add_arg(1)
    return builder.build()


def _time_msg() -> OscMessage:
    builder = OscMessageBuilder(address="/VMC/Ext/T")
    builder.add_arg(float(time.monotonic()))
    return builder.build()


class VMCOutput:
    """VMC protocol output via UDP/OSC.

    Sends blendshapes for EEG expressions and bone transforms for head tracking.
    Uses python-osc directly (no python-vmcp dependency).
    """

    # Standard blendshape mapping: internal name → VMC name
    BLEND_MAP = {
        "blink": "blink",
        "clench": "muse_clench",
        "focus": "muse_focus",
        "relaxation": "muse_relaxation",
    }

    def __init__(self, host: str = "127.0.0.1", port: int = 39539):
        self.host = host
        self.port = port
        self._client: SimpleUDPClient | None = None
        if port > 0:
            self._client = SimpleUDPClient(host, port)

    def build_blendshape_messages(self, blendshapes: VMCBlendshapes) -> list[OscMessage]:
        """Build OSC messages for blendshape frame (without sending)."""
        messages: list[OscMessage] = []
        values = {
            "blink": blendshapes.blink,
            "clench": blendshapes.clench,
            "focus": blendshapes.focus,
            "relaxation": blendshapes.relaxation,
        }
        for internal_name, vmc_name in self.BLEND_MAP.items():
            messages.append(_blend_val(vmc_name, values[internal_name]))
        messages.append(_blend_apply())
        messages.append(_ok())
        messages.append(_time_msg())
        return messages

    def build_bone_messages(self, bones: list[VMCBoneTransform]) -> list[OscMessage]:
        """Build OSC messages for bone transforms."""
        return [_bone_pos(bone) for bone in bones]

    def send_blendshapes(self, blendshapes: VMCBlendshapes) -> None:
        """Send blendshape frame over UDP."""
        if self._client is None:
            return
        for msg in self.build_blendshape_messages(blendshapes):
            self._client.send(msg)

    def send_bones(self, bones: list[VMCBoneTransform]) -> None:
        """Send bone transforms over UDP."""
        if self._client is None:
            return
        for msg in self.build_bone_messages(bones):
            self._client.send(msg)

    def send_frame(
        self,
        blendshapes: VMCBlendshapes | None = None,
        bones: list[VMCBoneTransform] | None = None,
    ) -> None:
        """Send a complete VMC frame (blendshapes + bones + status)."""
        if self._client is None:
            return
        if bones:
            self.send_bones(bones)
        if blendshapes:
            self.send_blendshapes(blendshapes)
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_vmc_output.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/outputs/vmc.py tests/test_vmc_output.py
git commit -m "feat: VMC blendshape output via python-osc"
```

---

### Task 7: Config + main entry point (wire everything together)

**Files:**
- Create: `src/muse_vtuber/config.py`
- Create: `src/muse_vtuber/main.py`
- Create: `tests/test_config.py`

CLI entry point with TOML config. Connects BrainFlow, runs pipeline, outputs VMC. This is the integration point — makes Tier 3 actually work end-to-end.

- [ ] **Step 1: Write config test**

`tests/test_config.py`:
```python
import pytest

from muse_vtuber.config import AppConfig, load_config_from_dict


def test_default_config():
    cfg = AppConfig()
    assert cfg.board_id == "MUSE_2_BOARD"
    assert cfg.vmc_port == 39539
    assert cfg.vmc_enabled is True
    assert cfg.osc_enabled is False


def test_load_from_dict():
    cfg = load_config_from_dict({
        "device": {"board_id": "SYNTHETIC_BOARD", "mac_address": ""},
        "outputs": {
            "vmc": {"enabled": True, "port": 12345},
            "osc": {"enabled": True, "port": 9000},
        },
    })
    assert cfg.board_id == "SYNTHETIC_BOARD"
    assert cfg.vmc_port == 12345
    assert cfg.osc_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_config.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement config**

`src/muse_vtuber/config.py`:
```python
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


@dataclass
class AppConfig:
    # Device
    board_id: str = "MUSE_2_BOARD"
    mac_address: str = ""
    serial_port: str = ""

    # Processing
    ema_decay: float = 0.04
    window_seconds: float = 1.0

    # VMC output
    vmc_enabled: bool = True
    vmc_host: str = "127.0.0.1"
    vmc_port: int = 39539

    # VRChat OSC output
    osc_enabled: bool = False
    osc_host: str = "127.0.0.1"
    osc_port: int = 9000

    # VTube Studio
    vts_enabled: bool = False
    vts_port: int = 8001

    # Head tracking
    head_tracking_enabled: bool = True
    madgwick_beta: float = 0.8
    smoothing_min_cutoff: float = 0.3
    smoothing_beta: float = 1.5

    # Fusion
    fusion_enabled: bool = False
    openseeface_port: int = 11573
    fusion_alpha: float = 0.96

    # Debug
    debug: bool = False


def load_config_from_dict(data: dict) -> AppConfig:
    """Load config from parsed TOML dict."""
    cfg = AppConfig()

    device = data.get("device", {})
    cfg.board_id = device.get("board_id", cfg.board_id)
    cfg.mac_address = device.get("mac_address", cfg.mac_address)
    cfg.serial_port = device.get("serial_port", cfg.serial_port)

    processing = data.get("processing", {})
    cfg.ema_decay = processing.get("ema_decay", cfg.ema_decay)
    cfg.window_seconds = processing.get("window_seconds", cfg.window_seconds)

    outputs = data.get("outputs", {})
    vmc = outputs.get("vmc", {})
    cfg.vmc_enabled = vmc.get("enabled", cfg.vmc_enabled)
    cfg.vmc_host = vmc.get("host", cfg.vmc_host)
    cfg.vmc_port = vmc.get("port", cfg.vmc_port)

    osc = outputs.get("osc", {})
    cfg.osc_enabled = osc.get("enabled", cfg.osc_enabled)
    cfg.osc_host = osc.get("host", cfg.osc_host)
    cfg.osc_port = osc.get("port", cfg.osc_port)

    vts = outputs.get("vts", {})
    cfg.vts_enabled = vts.get("enabled", cfg.vts_enabled)
    cfg.vts_port = vts.get("port", cfg.vts_port)

    head = data.get("head_tracking", {})
    cfg.head_tracking_enabled = head.get("enabled", cfg.head_tracking_enabled)
    cfg.madgwick_beta = head.get("madgwick_beta", cfg.madgwick_beta)
    cfg.smoothing_min_cutoff = head.get("smoothing_min_cutoff", cfg.smoothing_min_cutoff)
    cfg.smoothing_beta = head.get("smoothing_beta", cfg.smoothing_beta)

    fusion = data.get("fusion", {})
    cfg.fusion_enabled = fusion.get("enabled", cfg.fusion_enabled)
    cfg.openseeface_port = fusion.get("openseeface_port", cfg.openseeface_port)
    cfg.fusion_alpha = fusion.get("alpha", cfg.fusion_alpha)

    return cfg


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from TOML file, falling back to defaults."""
    if config_path and config_path.exists():
        if tomllib is None:
            raise ImportError("tomli required for Python < 3.11: pip install tomli")
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return load_config_from_dict(data)

    # Try default location
    default = Path.home() / ".config" / "muse-vtuber" / "config.toml"
    if default.exists() and tomllib:
        with open(default, "rb") as f:
            data = tomllib.load(f)
        return load_config_from_dict(data)

    return AppConfig()


def parse_cli_args(args: list[str] | None = None) -> AppConfig:
    """Parse CLI arguments, layered on top of config file."""
    parser = argparse.ArgumentParser(description="Muse VTuber Bridge")
    parser.add_argument("--config", type=Path, help="Path to config.toml")
    parser.add_argument("--board-id", type=str, help="BrainFlow board ID or name")
    parser.add_argument("--mac", type=str, help="Device MAC address")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic board")
    parser.add_argument("--vmc-port", type=int, help="VMC output port")
    parser.add_argument("--osc", action="store_true", help="Enable VRChat OSC output")
    parser.add_argument("--osc-port", type=int, help="VRChat OSC port")
    parser.add_argument("--debug", action="store_true", help="Debug logging")
    parsed = parser.parse_args(args)

    cfg = load_config(parsed.config)

    if parsed.synthetic:
        cfg.board_id = "SYNTHETIC_BOARD"
    if parsed.board_id:
        cfg.board_id = parsed.board_id
    if parsed.mac:
        cfg.mac_address = parsed.mac
    if parsed.vmc_port:
        cfg.vmc_port = parsed.vmc_port
    if parsed.osc:
        cfg.osc_enabled = True
    if parsed.osc_port:
        cfg.osc_port = parsed.osc_port
    if parsed.debug:
        cfg.debug = True

    return cfg
```

- [ ] **Step 4: Run config tests**

```bash
cd muse-vtuber
uv run pytest tests/test_config.py -v
```

Expected: 2 passed

- [ ] **Step 5: Implement main entry point**

`src/muse_vtuber/main.py`:
```python
from __future__ import annotations

import logging
import signal
import sys
import time

from muse_vtuber.config import AppConfig, parse_cli_args
from muse_vtuber.outputs.vmc import VMCBlendshapes, VMCOutput
from muse_vtuber.pipeline.band_power import BandPowerResult, BandPowerStage
from muse_vtuber.pipeline.base import Pipeline
from muse_vtuber.pipeline.blink import BlinkDetector
from muse_vtuber.pipeline.clench import ClenchDetector, ClenchResult
from muse_vtuber.pipeline.focus import FocusRelaxResult, FocusRelaxStage
from muse_vtuber.pipeline.speech import SpeechDetector
from muse_vtuber.pipeline.types import Cadence, PipelineFrame
from muse_vtuber.source import BrainFlowSource

log = logging.getLogger("muse_vtuber")


def create_pipeline(config: AppConfig) -> Pipeline:
    """Create the processing pipeline with all stages."""
    stages = [
        SpeechDetector(),
        BlinkDetector(),
        ClenchDetector(),
        BandPowerStage(ema_decay=config.ema_decay),
        FocusRelaxStage(),
    ]
    return Pipeline(stages=stages)


def extract_blendshapes(frame: PipelineFrame) -> VMCBlendshapes:
    """Extract blendshape values from pipeline frame results."""
    blink_val = 0.0
    for event in frame.events:
        if event.kind == "blink":
            blink_val = 1.0
            break

    clench_result = frame.get(ClenchResult)
    clench_val = 1.0 if (clench_result and clench_result.jaw_clench) else 0.0

    focus_result = frame.get(FocusRelaxResult)
    focus_val = focus_result.focus_avg_unsigned if focus_result else 0.0
    relax_val = focus_result.relax_avg_unsigned if focus_result else 0.0

    return VMCBlendshapes(
        blink=blink_val,
        clench=clench_val,
        focus=focus_val,
        relaxation=relax_val,
    )


def run(config: AppConfig) -> None:
    """Main run loop. Blocking."""
    log.info("Starting Muse VTuber Bridge (board=%s)", config.board_id)

    source = BrainFlowSource(
        board_id=config.board_id,
        mac_address=config.mac_address,
        serial_port=config.serial_port,
    )
    pipeline = create_pipeline(config)

    # Output sinks
    vmc_output = VMCOutput(config.vmc_host, config.vmc_port) if config.vmc_enabled else None

    # Graceful shutdown
    running = True

    def on_signal(sig, _frame):
        nonlocal running
        log.info("Shutting down...")
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    source.start()
    log.info("Connected. Streaming EEG → VMC on %s:%d", config.vmc_host, config.vmc_port)

    sample_rate = source.eeg_sample_rate
    poll_interval = 1.0 / 60  # 60Hz poll rate
    slow_cadence_interval = 1.0
    last_slow = time.monotonic()

    try:
        while running:
            eeg = source.poll_eeg()
            imu = source.poll_imu()

            if eeg is None and imu is None:
                time.sleep(poll_interval)
                continue

            now = time.monotonic()
            frame = PipelineFrame(eeg=eeg, imu=imu, timestamp=now)

            # Run FAST stages every poll
            pipeline.run(Cadence.FAST, frame)

            # Run SLOW stages periodically
            if now - last_slow >= slow_cadence_interval:
                pipeline.run(Cadence.SLOW, frame)
                last_slow = now

            # Extract and send blendshapes
            blendshapes = extract_blendshapes(frame)

            if vmc_output:
                vmc_output.send_blendshapes(blendshapes)

            if config.debug and frame.events:
                for event in frame.events:
                    log.info("Event: %s (confidence=%.2f)", event.kind, event.confidence)

            time.sleep(poll_interval)

    finally:
        source.stop()
        log.info("Stopped.")


def cli() -> None:
    """CLI entry point."""
    config = parse_cli_args()
    level = logging.DEBUG if config.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)-15s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    run(config)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 6: Test CLI runs with synthetic board**

```bash
cd muse-vtuber
timeout 3 uv run muse-vtuber --synthetic --debug || true
```

Expected: Starts, prints "Connected. Streaming EEG → VMC...", runs for 3 seconds, then exits on timeout.

- [ ] **Step 7: Commit**

```bash
git add src/muse_vtuber/config.py src/muse_vtuber/main.py tests/test_config.py
git commit -m "feat: config + main entry point — Tier 3 EEG addon complete"
```

---

### Done Criteria

- [x] `uv run pytest` — all tests pass
- [x] `uv run muse-vtuber --synthetic --debug` — starts, streams, outputs VMC
- [x] Pipeline: SpeechDetector → BlinkDetector → ClenchDetector → BandPowerStage → FocusRelaxStage
- [x] VMC output sends: `blink`, `muse_clench`, `muse_focus`, `muse_relaxation` blendshapes
- [x] Focus/relaxation formulas match BFiVRC: `tanh(1.1 * log(beta/theta))`
- [x] Artifact-gated EMA: band power freezes during blink/clench/speech

### Manual Verification

1. Start VSeeFace with VMC receiver on port 39539
2. Run `muse-vtuber --synthetic --debug --vmc-port 39539`
3. Verify blendshape values appear in VSeeFace VMC receiver panel
4. With real Muse: `muse-vtuber --mac XX:XX:XX:XX:XX:XX --debug`
5. Blink → see `blink` blendshape spike to 1.0
6. Clench jaw → see `muse_clench` go to 1.0
