# Phase 1: Signal Readiness — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build three signal components that Phase 2 (HABridgeStage) depends on: an eyes-closed detector, validated concentration scoring, and a headband state machine.

**Architecture:** All three components are SLOW pipeline stages. EyesClosedDetector reads BandPowerResult (frontal alpha) and emits EyesClosedResult with hysteresis. HeadbandStateTracker reads SignalQualityResult and manages a 3-state machine (ready/fitting/off). ConcentrationScorer already exists — we validate it with a script and tune if needed. Each stage follows the existing pattern: dataclass result + Stage subclass + frame.set().

**Tech Stack:** Python 3.12, NumPy, BrainFlow (existing), pytest

**Key context:**
- Pipeline stages live in `backend/pipeline/stages/`
- Base class: `Stage(ABC)` with `name`, `cadence`, `process(frame)`
- Results stored via `frame.set(result)`, retrieved via `frame.get(ResultClass)`
- SLOW stages run every 0.5s on a 2s rolling EEG window (512 samples at 256Hz)
- Existing recordings in `recordings/eyes_closed/` and `recordings/eyes_open/` (3 trials each, 30s, 4ch)
- Frontal alpha (AF7+AF8) eyes-closed/open ratio: ~1.15x raw, 1.64x with ZUNA
- Design spec: alpha > 2x baseline for >1.5s = closed, < 1.3x baseline = open

---

### Task 1: Validate alpha blocking on existing recordings

Before writing any stage code, confirm the raw frontal alpha ratio is usable. This is a validation script, not production code.

**Files:**
- Create: `scripts/validate_eyes_closed.py`

**Step 1: Write the validation script**

```python
"""Validate alpha blocking signal on eyes_closed vs eyes_open recordings.

Usage: python scripts/validate_eyes_closed.py
"""
import glob
import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations


def compute_frontal_alpha(eeg: np.ndarray, sfreq: int = 256) -> float:
    """Compute mean frontal (AF7+AF8) alpha power from 4ch EEG."""
    nfft = DataFilter.get_nearest_power_of_two(sfreq)
    alpha_powers = []
    for ch_idx in [1, 2]:  # AF7, AF8
        data = eeg[ch_idx].astype(np.float64).copy()
        DataFilter.detrend(data, DetrendOperations.LINEAR.value)
        psd = DataFilter.get_psd_welch(data, nfft, nfft // 2, sfreq, WindowOperations.HANNING.value)
        alpha = DataFilter.get_band_power(psd, 7.5, 13.0)
        alpha_powers.append(alpha)
    return float(np.mean(alpha_powers))


def load_recordings(label: str) -> list[np.ndarray]:
    """Load all .npz recordings for a label."""
    files = sorted(glob.glob(f"recordings/{label}/**/*.npz", recursive=True))
    recordings = []
    for f in files:
        d = np.load(f, allow_pickle=True)
        recordings.append(d["eeg"])
    return recordings


def main():
    ec_recordings = load_recordings("eyes_closed")
    eo_recordings = load_recordings("eyes_open")
    rest_recordings = load_recordings("rest")

    print(f"Eyes closed: {len(ec_recordings)} recordings")
    print(f"Eyes open:   {len(eo_recordings)} recordings")
    print(f"Rest:        {len(rest_recordings)} recordings")

    # Compute alpha for each
    ec_alphas = [compute_frontal_alpha(r) for r in ec_recordings]
    eo_alphas = [compute_frontal_alpha(r) for r in eo_recordings]

    ec_mean = np.mean(ec_alphas)
    eo_mean = np.mean(eo_alphas)
    ratio = ec_mean / eo_mean if eo_mean > 0 else 0

    print(f"\nFrontal alpha power (AF7+AF8 mean):")
    print(f"  Eyes closed: {ec_mean:.2f} µV²  (per trial: {[f'{a:.2f}' for a in ec_alphas]})")
    print(f"  Eyes open:   {eo_mean:.2f} µV²  (per trial: {[f'{a:.2f}' for a in eo_alphas]})")
    print(f"  Ratio (EC/EO): {ratio:.2f}x")

    # Also compute on sliding 2s windows to simulate real-time
    print(f"\n--- Sliding window analysis (2s windows, 0.5s step) ---")
    window = 512  # 2s at 256Hz
    step = 128    # 0.5s

    for label, recordings in [("eyes_closed", ec_recordings), ("eyes_open", eo_recordings)]:
        all_alphas = []
        for rec in recordings:
            for start in range(0, rec.shape[1] - window, step):
                chunk = rec[:, start:start + window]
                all_alphas.append(compute_frontal_alpha(chunk))
        mean = np.mean(all_alphas)
        std = np.std(all_alphas)
        print(f"  {label}: mean={mean:.2f}, std={std:.2f}, n={len(all_alphas)} windows")

    # Compute rest baseline for threshold calibration
    if rest_recordings:
        rest_alphas = []
        for rec in rest_recordings:
            for start in range(0, rec.shape[1] - window, step):
                chunk = rec[:, start:start + window]
                rest_alphas.append(compute_frontal_alpha(chunk))
        rest_mean = np.mean(rest_alphas)
        rest_std = np.std(rest_alphas)
        print(f"  rest:        mean={rest_mean:.2f}, std={rest_std:.2f}, n={len(rest_alphas)} windows")

        # What multiplier of rest baseline separates EC from EO?
        ec_all = []
        for rec in ec_recordings:
            for start in range(0, rec.shape[1] - window, step):
                chunk = rec[:, start:start + window]
                ec_all.append(compute_frontal_alpha(chunk))
        eo_all = []
        for rec in eo_recordings:
            for start in range(0, rec.shape[1] - window, step):
                chunk = rec[:, start:start + window]
                eo_all.append(compute_frontal_alpha(chunk))

        print(f"\n--- Threshold analysis ---")
        for mult in [1.2, 1.3, 1.5, 1.8, 2.0, 2.5]:
            thresh = rest_mean * mult
            ec_detect = sum(1 for a in ec_all if a > thresh) / len(ec_all) * 100
            eo_false = sum(1 for a in eo_all if a > thresh) / len(eo_all) * 100
            print(f"  {mult:.1f}x rest: EC detection={ec_detect:.0f}%, EO false alarm={eo_false:.0f}%")


if __name__ == "__main__":
    main()
```

**Step 2: Run the validation**

Run: `PYTHONPATH=. python scripts/validate_eyes_closed.py`

Expected: Output showing alpha power ratios and threshold analysis. Record the results — they determine the threshold we'll use in the detector.

**Step 3: Commit**

```bash
git add scripts/validate_eyes_closed.py
git commit -m "feat: add eyes-closed alpha blocking validation script"
```

**Step 4: Evaluate results and decide threshold**

Based on the validation output:
- If EC/EO ratio is >1.5x: use the threshold multiplier that gives >80% detection with <10% false alarm
- If EC/EO ratio is <1.3x on raw 4ch: the detector will need to rely on ZUNA's 1.64x ratio, and we should note this limitation
- Save the validation results to `docs/research/2026-03-11-eyes-closed-validation.md`

---

### Task 2: EyesClosedResult dataclass and detector tests

**Files:**
- Create: `tests/test_eyes_closed_detector.py`
- Modify: `backend/pipeline/stages/features.py` (add result dataclass only)

**Step 1: Write the failing tests**

Create `tests/test_eyes_closed_detector.py`:

```python
"""Tests for EyesClosedDetector pipeline stage."""
import time

import numpy as np

from backend.pipeline.stages.features import BandPowerResult
from backend.pipeline.types import PipelineFrame


def _make_frame_with_alpha(frontal_alpha: float, other_alpha: float = 10.0) -> PipelineFrame:
    """Build a PipelineFrame with BandPowerResult pre-populated.

    frontal_alpha: alpha power for AF7 (idx 1) and AF8 (idx 2)
    other_alpha: alpha power for TP9 (idx 0) and TP10 (idx 3)
    """
    frame = PipelineFrame(
        eeg=np.zeros((4, 512)),
        ppg=None, imu=None,
        timestamp=time.time(),
    )
    frame.set(BandPowerResult(
        band_powers={
            "delta": [100.0] * 4,
            "theta": [20.0] * 4,
            "alpha": [other_alpha, frontal_alpha, frontal_alpha, other_alpha],
            "beta": [10.0] * 4,
            "gamma": [5.0] * 4,
        },
        theta_beta_ratio=[2.0] * 4,
        frontal_alpha_asymmetry=0.0,
    ))
    return frame


def test_eyes_closed_result_import():
    from backend.pipeline.stages.features import EyesClosedResult
    r = EyesClosedResult(eyes_closed=True, alpha_ratio=2.5, baseline_alpha=10.0)
    assert r.eyes_closed is True
    assert r.alpha_ratio == 2.5


def test_eyes_closed_detector_import():
    from backend.pipeline.stages.features import EyesClosedDetector
    stage = EyesClosedDetector()
    assert stage.name == "eyes_closed_detector"
    assert stage.cadence.value == "slow"


def test_baseline_cold_start():
    """First few calls should establish baseline, not detect eyes closed."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    # Feed normal alpha for cold start (baseline establishment)
    for _ in range(5):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        stage.process(frame)
    result = frame.get(EyesClosedResult)
    assert result is not None
    assert result.eyes_closed is False
    assert result.baseline_alpha > 0


def test_detects_eyes_closed():
    """High alpha sustained for >1.5s should trigger eyes_closed."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    # Establish baseline with normal alpha
    for _ in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        stage.process(frame)
    baseline = frame.get(EyesClosedResult).baseline_alpha

    # Send high alpha (2x+ baseline) for >1.5s (4 ticks at 0.5s = 2s)
    for i in range(4):
        frame = _make_frame_with_alpha(frontal_alpha=baseline * 3.0)
        frame.timestamp = time.time() + i * 0.5 + 2.0  # ensure >1.5s
        stage.process(frame)
    result = frame.get(EyesClosedResult)
    assert result.eyes_closed is True


def test_hysteresis_prevents_flicker():
    """Once eyes_closed, should stay closed until alpha drops below lower threshold."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    # Establish baseline
    for _ in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        stage.process(frame)

    # Trigger eyes closed
    for i in range(4):
        frame = _make_frame_with_alpha(frontal_alpha=30.0)
        frame.timestamp = time.time() + i * 0.5 + 2.0
        stage.process(frame)
    assert frame.get(EyesClosedResult).eyes_closed is True

    # Alpha drops to 1.5x baseline — still between thresholds, should stay closed
    frame = _make_frame_with_alpha(frontal_alpha=15.0)
    frame.timestamp = time.time() + 5.0
    stage.process(frame)
    assert frame.get(EyesClosedResult).eyes_closed is True

    # Alpha drops below 1.3x baseline — should open
    frame = _make_frame_with_alpha(frontal_alpha=8.0)
    frame.timestamp = time.time() + 6.0
    stage.process(frame)
    assert frame.get(EyesClosedResult).eyes_closed is False


def test_skips_without_band_power():
    """Should not crash if BandPowerResult is missing."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=0.0)
    stage.process(frame)
    assert frame.get(EyesClosedResult) is None


def test_alpha_ratio_reported():
    """Result should report current alpha/baseline ratio."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    for _ in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        stage.process(frame)
    # Double the alpha
    frame = _make_frame_with_alpha(frontal_alpha=20.0)
    stage.process(frame)
    result = frame.get(EyesClosedResult)
    assert result is not None
    assert result.alpha_ratio > 1.5  # should be ~2.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_eyes_closed_detector.py::test_eyes_closed_result_import -v`
Expected: FAIL — `ImportError: cannot import name 'EyesClosedResult'`

**Step 3: Add EyesClosedResult dataclass only**

Add to `backend/pipeline/stages/features.py` after `HeadMotionResult`:

```python
@dataclass
class EyesClosedResult:
    eyes_closed: bool
    alpha_ratio: float      # current frontal alpha / baseline
    baseline_alpha: float   # current baseline value
```

**Step 4: Run first test only**

Run: `python -m pytest tests/test_eyes_closed_detector.py::test_eyes_closed_result_import -v`
Expected: PASS (dataclass import works, detector import still fails)

**Step 5: Commit**

```bash
git add backend/pipeline/stages/features.py tests/test_eyes_closed_detector.py
git commit -m "feat: add EyesClosedResult dataclass and detector tests"
```

---

### Task 3: EyesClosedDetector implementation

**Files:**
- Modify: `backend/pipeline/stages/features.py`

**Step 1: Write the implementation**

Add to `backend/pipeline/stages/features.py` after `EyesClosedResult`:

```python
class EyesClosedDetector(Stage):
    """Detect eyes-closed state via sustained frontal alpha power increase.

    Uses frontal channels (AF7 + AF8) alpha power from BandPowerResult.
    Maintains a slow-adapting baseline and detects when alpha exceeds
    the baseline by a configurable multiplier for a sustained duration.

    Hysteresis: once eyes_closed is True, alpha must drop below a lower
    threshold (open_threshold) to transition back to eyes_open. This
    prevents flickering at the boundary.

    Must run AFTER BandPowerExtractor in the SLOW pipeline.
    """

    name = "eyes_closed_detector"
    cadence = Cadence.SLOW

    def __init__(
        self,
        close_threshold: float = 2.0,   # alpha must exceed baseline by this factor
        open_threshold: float = 1.3,    # alpha must drop below this to re-open
        sustain_seconds: float = 1.5,   # how long alpha must stay high before triggering
        baseline_alpha: float = 0.002,  # EMA rate for baseline adaptation (very slow)
        cold_start_ticks: int = 6,      # ~3s at 0.5s/tick before detection enabled
    ):
        self.close_threshold = close_threshold
        self.open_threshold = open_threshold
        self.sustain_seconds = sustain_seconds
        self._baseline_ema_alpha = baseline_alpha
        self._cold_start_ticks = cold_start_ticks

        self._baseline: float = 0.0
        self._tick_count: int = 0
        self._eyes_closed: bool = False
        self._high_since: float = 0.0   # monotonic time when alpha first went high

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None or "alpha" not in bp.band_powers:
            return

        alpha_list = bp.band_powers["alpha"]
        # Frontal channels: AF7 (idx 1) and AF8 (idx 2) in 4ch layout
        # In 23ch ZUNA layout, find by name
        ch_names = list(CH_NAMES)
        if len(alpha_list) > len(CH_NAMES):
            from backend.pipeline.stages.zuna import ZUNA_CH_NAMES
            ch_names = ZUNA_CH_NAMES
        af7_idx = ch_names.index("AF7") if "AF7" in ch_names else 1
        af8_idx = ch_names.index("AF8") if "AF8" in ch_names else 2

        if af7_idx >= len(alpha_list) or af8_idx >= len(alpha_list):
            return

        frontal_alpha = (alpha_list[af7_idx] + alpha_list[af8_idx]) / 2.0
        self._tick_count += 1

        # Baseline update
        if self._tick_count <= self._cold_start_ticks:
            # Cold start: simple running average
            self._baseline = (
                self._baseline * (self._tick_count - 1) + frontal_alpha
            ) / self._tick_count
        else:
            # EMA — only update during eyes-open to prevent baseline drift
            if not self._eyes_closed:
                self._baseline = (
                    self._baseline_ema_alpha * frontal_alpha
                    + (1 - self._baseline_ema_alpha) * self._baseline
                )

        # Don't detect during cold start
        if self._tick_count < self._cold_start_ticks:
            frame.set(EyesClosedResult(
                eyes_closed=False,
                alpha_ratio=0.0,
                baseline_alpha=self._baseline,
            ))
            return

        ratio = frontal_alpha / self._baseline if self._baseline > 0 else 0.0
        now = frame.timestamp or time.monotonic()

        if not self._eyes_closed:
            # Check for eyes closing
            if ratio >= self.close_threshold:
                if self._high_since == 0.0:
                    self._high_since = now
                elif now - self._high_since >= self.sustain_seconds:
                    self._eyes_closed = True
            else:
                self._high_since = 0.0
        else:
            # Check for eyes opening
            if ratio < self.open_threshold:
                self._eyes_closed = False
                self._high_since = 0.0

        frame.set(EyesClosedResult(
            eyes_closed=self._eyes_closed,
            alpha_ratio=round(ratio, 2),
            baseline_alpha=round(self._baseline, 2),
        ))
```

Note: add `import time` at the top of features.py if not already present.

**Step 2: Run all detector tests**

Run: `python -m pytest tests/test_eyes_closed_detector.py -v`
Expected: All PASS

**Step 3: Run full test suite to check for regressions**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/pipeline/stages/features.py
git commit -m "feat: add EyesClosedDetector with hysteresis and adaptive baseline"
```

---

### Task 4: Wire EyesClosedDetector into factory and serialization

**Files:**
- Modify: `backend/pipeline/factory.py`
- Modify: `backend/pipeline/serialize.py`
- Modify: `tests/test_pipeline_factory.py`
- Modify: `tests/test_pipeline_serialize.py`

**Step 1: Write the failing tests**

Append to `tests/test_pipeline_factory.py`:

```python
def test_factory_includes_eyes_closed_detector():
    pipeline = create_default_pipeline()
    names = [s.name for s in pipeline.stages]
    assert "eyes_closed_detector" in names
    # Must come after band_power_extractor
    bp_idx = names.index("band_power_extractor")
    ec_idx = names.index("eyes_closed_detector")
    assert ec_idx > bp_idx
```

Append to `tests/test_pipeline_serialize.py`:

```python
from backend.pipeline.stages.features import EyesClosedResult


def test_serialize_eyes_closed_result():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(EyesClosedResult(eyes_closed=True, alpha_ratio=2.1, baseline_alpha=12.5))
    metrics = frame_to_metrics(frame)
    assert "eyes_closed" in metrics
    assert metrics["eyes_closed"]["active"] is True
    assert metrics["eyes_closed"]["alpha_ratio"] == 2.1
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_factory.py::test_factory_includes_eyes_closed_detector tests/test_pipeline_serialize.py::test_serialize_eyes_closed_result -v`
Expected: FAIL

**Step 3: Update factory.py**

Add import and stage to `create_default_pipeline`:

```python
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    ConcentrationScorer,
    EyesClosedDetector,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
```

In the stages list, insert `EyesClosedDetector()` after `ConcentrationScorer()` and before `BandPowerBroadcaster()`:

```python
    stages.extend([
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
        EyesClosedDetector(),     # <-- NEW: after band power, before broadcaster
        BandPowerBroadcaster(),
        # FAST — ...
    ])
```

**Step 4: Update serialize.py**

Add to `backend/pipeline/serialize.py`:

```python
from backend.pipeline.stages.features import (
    BandPowerResult,
    ConcentrationResult,
    EyesClosedResult,
    HeadMotionResult,
    HeartRateResult,
    SignalQualityResult,
)
```

Add serialization block in `frame_to_metrics()`:

```python
    ec = frame.get(EyesClosedResult)
    if ec:
        metrics["eyes_closed"] = {
            "active": ec.eyes_closed,
            "alpha_ratio": ec.alpha_ratio,
            "baseline_alpha": ec.baseline_alpha,
        }
```

**Step 5: Run tests**

Run: `python -m pytest tests/test_pipeline_factory.py tests/test_pipeline_serialize.py -v`
Expected: All PASS

**Step 6: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add backend/pipeline/factory.py backend/pipeline/serialize.py tests/test_pipeline_factory.py tests/test_pipeline_serialize.py
git commit -m "feat: wire EyesClosedDetector into pipeline factory and serialization"
```

---

### Task 5: Validate ConcentrationScorer output range

The ConcentrationScorer already exists. We need to verify its output is usable for continuous control (produces a meaningful 0→1 range that varies with mental state).

**Files:**
- Create: `scripts/validate_concentration.py`

**Step 1: Write the validation script**

```python
"""Validate ConcentrationScorer output on existing recordings.

Checks that the BrainFlow MINDFULNESS/RESTFULNESS models produce
usable 0-1 scores that differentiate between mental states.

Usage: PYTHONPATH=. python scripts/validate_concentration.py
"""
import glob

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations
from brainflow.ml_model import MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers

from backend.pipeline.stages.features import BandPowerExtractor, BandPowerResult
from backend.pipeline.types import PipelineFrame, BANDS, BAND_NAMES


def get_concentration_scores(eeg: np.ndarray, sfreq: int = 256) -> list[tuple[float, float]]:
    """Compute (concentration, relaxation) for each 2s window."""
    window = sfreq * 2  # 2s
    step = sfreq // 2   # 0.5s

    extractor = BandPowerExtractor()

    mind_params = BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
    rest_params = BrainFlowModelParams(BrainFlowMetrics.RESTFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
    mindfulness = MLModel(mind_params)
    restfulness = MLModel(rest_params)
    try:
        mindfulness.release()
    except Exception:
        pass
    mindfulness.prepare()
    try:
        restfulness.release()
    except Exception:
        pass
    restfulness.prepare()

    scores = []
    try:
        for start in range(0, eeg.shape[1] - window, step):
            chunk = eeg[:, start:start + window]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=0.0)
            extractor.process(frame)
            bp = frame.get(BandPowerResult)
            if bp is None:
                continue

            # Same normalization as ConcentrationScorer
            band_names_ordered = ["delta", "theta", "alpha", "beta", "gamma"]
            total = 0.0
            sums = []
            for b in band_names_ordered:
                s = sum(bp.band_powers.get(b, [0.0]))
                sums.append(s)
                total += s
            if total <= 0:
                continue
            features = np.array([s / total for s in sums], dtype=np.float64)

            conc = float(mindfulness.predict(features))
            relax = float(restfulness.predict(features))
            scores.append((conc, relax))
    finally:
        mindfulness.release()
        restfulness.release()

    return scores


def load_recordings(label: str) -> list[np.ndarray]:
    files = sorted(glob.glob(f"recordings/{label}/**/*.npz", recursive=True))
    return [np.load(f, allow_pickle=True)["eeg"] for f in files]


def main():
    labels = ["rest", "meditation", "mental_math", "eyes_closed", "eyes_open"]
    for label in labels:
        recordings = load_recordings(label)
        if not recordings:
            print(f"  {label}: no recordings found")
            continue
        all_scores = []
        for rec in recordings:
            all_scores.extend(get_concentration_scores(rec))
        if not all_scores:
            print(f"  {label}: no valid windows")
            continue
        concs = [s[0] for s in all_scores]
        relax = [s[1] for s in all_scores]
        print(f"  {label}:")
        print(f"    concentration: mean={np.mean(concs):.3f}, std={np.std(concs):.3f}, "
              f"min={np.min(concs):.3f}, max={np.max(concs):.3f}")
        print(f"    relaxation:    mean={np.mean(relax):.3f}, std={np.std(relax):.3f}, "
              f"min={np.min(relax):.3f}, max={np.max(relax):.3f}")

    # Key question: does mental_math produce higher concentration than rest/meditation?
    rest_recs = load_recordings("rest")
    math_recs = load_recordings("mental_math")
    if rest_recs and math_recs:
        rest_scores = []
        for rec in rest_recs:
            rest_scores.extend([s[0] for s in get_concentration_scores(rec)])
        math_scores = []
        for rec in math_recs:
            math_scores.extend([s[0] for s in get_concentration_scores(rec)])
        print(f"\n  Separation: math_mean={np.mean(math_scores):.3f} vs rest_mean={np.mean(rest_scores):.3f}")
        print(f"  Delta: {np.mean(math_scores) - np.mean(rest_scores):.3f}")
        if np.mean(math_scores) > np.mean(rest_scores):
            print("  ✓ Math > Rest — concentration score is directionally correct")
        else:
            print("  ✗ Math ≤ Rest — concentration score may need tuning")


if __name__ == "__main__":
    main()
```

**Step 2: Run the validation**

Run: `PYTHONPATH=. python scripts/validate_concentration.py`

Expected: Output showing score ranges per mental state. Key question: does the score differentiate rest vs. mental_math?

**Step 3: Evaluate and document results**

If scores are clustered (e.g., all 0.45-0.55): the BrainFlow model isn't useful for continuous control. We'd need to fall back to raw theta/beta ratio (which our earlier experiment showed d=1.61 separation).

If scores spread across 0-1 with state differentiation: the existing ConcentrationScorer is good enough.

Save results to `docs/research/2026-03-11-concentration-validation.md`.

**Step 4: Commit**

```bash
git add scripts/validate_concentration.py
git commit -m "feat: add concentration score validation script"
```

---

### Task 6: ConcentrationScorer tuning (if needed)

**This task is conditional** — only needed if Task 5 shows the BrainFlow MLModel output doesn't differentiate states well.

**Files:**
- Modify: `backend/pipeline/stages/features.py`
- Modify: `tests/test_pipeline_stages_features.py`

**Option A: If BrainFlow MLModel works** — no changes needed, skip to Task 7.

**Option B: If MLModel doesn't differentiate** — add a fallback using raw theta/beta ratio.

The fallback adds a `use_raw_ratio` flag to ConcentrationScorer:

```python
class ConcentrationScorer(Stage):
    name = "concentration_scorer"
    cadence = Cadence.SLOW

    def __init__(self, use_raw_ratio: bool = False):
        self.use_raw_ratio = use_raw_ratio
        if not use_raw_ratio:
            # existing BrainFlow model init...
            ...
        self._ema_concentration: float = 0.5
        self._ema_alpha: float = 0.15

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        if self.use_raw_ratio:
            # Use frontal theta/beta ratio directly
            # AF7 (idx 1) and AF8 (idx 2)
            theta = (bp.band_powers["theta"][1] + bp.band_powers["theta"][2]) / 2
            beta = (bp.band_powers["beta"][1] + bp.band_powers["beta"][2]) / 2
            raw_ratio = theta / beta if beta > 0 else 5.0

            # Map ratio to 0-1: high ratio = relaxed, low ratio = focused
            # Typical range: 1.0 (focused) to 5.0 (relaxed)
            # Invert: concentration = 1.0 when ratio is low
            concentration = max(0.0, min(1.0, 1.0 - (raw_ratio - 1.0) / 4.0))
            relaxation = 1.0 - concentration
        else:
            # existing BrainFlow model path...
            ...

        # EMA smoothing for stability
        self._ema_concentration = (
            self._ema_alpha * concentration
            + (1 - self._ema_alpha) * self._ema_concentration
        )

        frame.set(ConcentrationResult(
            concentration_score=round(self._ema_concentration, 3),
            relaxation_score=round(1.0 - self._ema_concentration, 3),
        ))
```

**Test for the fallback:**

```python
def test_concentration_raw_ratio_focused():
    """Low theta/beta ratio should produce high concentration."""
    from backend.pipeline.stages.features import ConcentrationScorer, ConcentrationResult
    frame = _make_eeg_frame(512)
    # Manually set band powers with low theta/beta
    frame.set(BandPowerResult(
        band_powers={
            "delta": [100.0] * 4,
            "theta": [5.0, 5.0, 5.0, 5.0],    # low theta
            "alpha": [10.0] * 4,
            "beta": [20.0, 20.0, 20.0, 20.0],  # high beta
            "gamma": [5.0] * 4,
        },
        theta_beta_ratio=[0.25] * 4,
        frontal_alpha_asymmetry=0.0,
    ))
    scorer = ConcentrationScorer(use_raw_ratio=True)
    scorer.process(frame)
    cr = frame.get(ConcentrationResult)
    assert cr is not None
    assert cr.concentration_score > 0.6  # should be high
```

**Step 1: Implement the chosen option based on Task 5 results**

**Step 2: Run tests**

Run: `python -m pytest tests/test_pipeline_stages_features.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add backend/pipeline/stages/features.py tests/test_pipeline_stages_features.py
git commit -m "feat: add raw theta/beta fallback to ConcentrationScorer"
```

---

### Task 7: HeadbandStateTracker — tests

**Files:**
- Create: `tests/test_headband_state.py`
- Modify: `backend/pipeline/stages/features.py` (add result dataclass)

**Step 1: Write the failing tests**

Create `tests/test_headband_state.py`:

```python
"""Tests for HeadbandStateTracker pipeline stage.

State machine:
  ready --(all channels rail)--> headband_off
    ^                                |
    |                          (channels return)
    |                                v
    +---(good fit 3s)----------- fitting
"""
import time

import numpy as np

from backend.pipeline.stages.features import SignalQualityResult
from backend.pipeline.types import PipelineFrame


def _make_quality_frame(fit_status: str, qualities: dict[str, float] | None = None) -> PipelineFrame:
    """Build a PipelineFrame with SignalQualityResult."""
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=time.time())
    if qualities is None:
        if fit_status == "good":
            qualities = {"TP9": 0.9, "AF7": 0.9, "AF8": 0.9, "TP10": 0.9}
        elif fit_status == "adjust":
            qualities = {"TP9": 0.5, "AF7": 0.9, "AF8": 0.9, "TP10": 0.5}
        else:
            qualities = {"TP9": 0.1, "AF7": 0.1, "AF8": 0.1, "TP10": 0.1}
    frame.set(SignalQualityResult(quality=qualities, fit_status=fit_status))
    return frame


def test_headband_state_result_import():
    from backend.pipeline.stages.features import HeadbandStateResult
    r = HeadbandStateResult(state="ready", seconds_in_state=5.0)
    assert r.state == "ready"


def test_headband_state_tracker_import():
    from backend.pipeline.stages.features import HeadbandStateTracker
    stage = HeadbandStateTracker()
    assert stage.name == "headband_state_tracker"
    assert stage.cadence.value == "slow"


def test_starts_in_fitting():
    """Initial state should be 'fitting' until stable signal confirmed."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    frame = _make_quality_frame("good")
    stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result is not None
    assert result.state == "fitting"


def test_transitions_to_ready_after_stable():
    """Should become 'ready' after good fit for 3+ seconds."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    # Feed good quality for 3.5s (7 ticks at 0.5s)
    for i in range(8):
        frame = _make_quality_frame("good")
        frame.timestamp = time.time() + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "ready"


def test_transitions_to_off_on_all_rail():
    """Should go to 'headband_off' when all channels are poor quality."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    # First reach ready
    for i in range(8):
        frame = _make_quality_frame("good")
        frame.timestamp = time.time() + i * 0.5
        stage.process(frame)
    assert frame.get(HeadbandStateResult).state == "ready"

    # All channels go poor (simulates headband removal)
    for i in range(3):
        frame = _make_quality_frame("poor")
        frame.timestamp = time.time() + 5.0 + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "headband_off"


def test_off_to_fitting_on_signal_return():
    """Should go from 'off' to 'fitting' when channels return."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    # Go to off state
    for i in range(3):
        frame = _make_quality_frame("poor")
        frame.timestamp = time.time() + i * 0.5
        stage.process(frame)
    # force into headband_off for testing
    stage._state = "headband_off"

    # Signal returns
    frame = _make_quality_frame("adjust")
    frame.timestamp = time.time() + 5.0
    stage.process(frame)
    assert frame.get(HeadbandStateResult).state == "fitting"


def test_adjust_does_not_become_ready():
    """'adjust' fit should stay in 'fitting', only 'good' transitions to 'ready'."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    for i in range(10):
        frame = _make_quality_frame("adjust")
        frame.timestamp = time.time() + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "fitting"


def test_skips_without_quality():
    """Should not crash if SignalQualityResult is missing."""
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=0.0)
    stage.process(frame)
    assert frame.get(HeadbandStateResult) is None
```

**Step 2: Run to verify failure**

Run: `python -m pytest tests/test_headband_state.py::test_headband_state_result_import -v`
Expected: FAIL

**Step 3: Add HeadbandStateResult dataclass**

Add to `backend/pipeline/stages/features.py`:

```python
@dataclass
class HeadbandStateResult:
    state: str              # "ready", "fitting", "headband_off"
    seconds_in_state: float
```

**Step 4: Run first test only**

Run: `python -m pytest tests/test_headband_state.py::test_headband_state_result_import -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/features.py tests/test_headband_state.py
git commit -m "feat: add HeadbandStateResult dataclass and state tracker tests"
```

---

### Task 8: HeadbandStateTracker implementation

**Files:**
- Modify: `backend/pipeline/stages/features.py`

**Step 1: Write the implementation**

Add to `backend/pipeline/stages/features.py`:

```python
class HeadbandStateTracker(Stage):
    """Track headband connection state via signal quality.

    State machine:
      fitting --(good fit for ready_seconds)--> ready
      ready   --(poor fit for off_seconds)----> headband_off
      headband_off --(any non-poor signal)----> fitting
      ready/fitting --(poor fit < off_seconds)-> fitting (reset good timer)

    Must run AFTER SignalQualityChecker in the SLOW pipeline.
    """

    name = "headband_state_tracker"
    cadence = Cadence.SLOW

    def __init__(
        self,
        ready_seconds: float = 3.0,   # good fit duration to become ready
        off_seconds: float = 1.5,     # poor fit duration to become off
    ):
        self.ready_seconds = ready_seconds
        self.off_seconds = off_seconds
        self._state: str = "fitting"
        self._state_entered: float = 0.0
        self._good_since: float = 0.0
        self._poor_since: float = 0.0

    def process(self, frame: PipelineFrame) -> None:
        sq = frame.get(SignalQualityResult)
        if sq is None:
            return

        now = frame.timestamp or time.monotonic()
        if self._state_entered == 0.0:
            self._state_entered = now

        fit = sq.fit_status

        if self._state == "fitting":
            if fit == "good":
                if self._good_since == 0.0:
                    self._good_since = now
                elif now - self._good_since >= self.ready_seconds:
                    self._state = "ready"
                    self._state_entered = now
                    self._good_since = 0.0
                    self._poor_since = 0.0
            else:
                self._good_since = 0.0
                if fit == "poor":
                    if self._poor_since == 0.0:
                        self._poor_since = now
                    elif now - self._poor_since >= self.off_seconds:
                        self._state = "headband_off"
                        self._state_entered = now
                        self._poor_since = 0.0
                else:
                    self._poor_since = 0.0

        elif self._state == "ready":
            if fit == "poor":
                if self._poor_since == 0.0:
                    self._poor_since = now
                elif now - self._poor_since >= self.off_seconds:
                    self._state = "headband_off"
                    self._state_entered = now
                    self._poor_since = 0.0
            else:
                self._poor_since = 0.0

        elif self._state == "headband_off":
            if fit != "poor":
                self._state = "fitting"
                self._state_entered = now
                self._good_since = now if fit == "good" else 0.0
                self._poor_since = 0.0

        frame.set(HeadbandStateResult(
            state=self._state,
            seconds_in_state=round(now - self._state_entered, 1),
        ))
```

**Step 2: Run all state tracker tests**

Run: `python -m pytest tests/test_headband_state.py -v`
Expected: All PASS

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add backend/pipeline/stages/features.py
git commit -m "feat: add HeadbandStateTracker with ready/fitting/off state machine"
```

---

### Task 9: Wire HeadbandStateTracker into factory and serialization

**Files:**
- Modify: `backend/pipeline/factory.py`
- Modify: `backend/pipeline/serialize.py`
- Modify: `tests/test_pipeline_factory.py`
- Modify: `tests/test_pipeline_serialize.py`

**Step 1: Write the failing tests**

Append to `tests/test_pipeline_factory.py`:

```python
def test_factory_includes_headband_state_tracker():
    pipeline = create_default_pipeline()
    names = [s.name for s in pipeline.stages]
    assert "headband_state_tracker" in names
    # Must come after signal_quality_checker
    sq_idx = names.index("signal_quality_checker")
    hs_idx = names.index("headband_state_tracker")
    assert hs_idx > sq_idx
```

Append to `tests/test_pipeline_serialize.py`:

```python
from backend.pipeline.stages.features import HeadbandStateResult


def test_serialize_headband_state_result():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadbandStateResult(state="ready", seconds_in_state=5.0))
    metrics = frame_to_metrics(frame)
    assert "headband" in metrics
    assert metrics["headband"]["state"] == "ready"
    assert metrics["headband"]["seconds_in_state"] == 5.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_factory.py::test_factory_includes_headband_state_tracker tests/test_pipeline_serialize.py::test_serialize_headband_state_result -v`
Expected: FAIL

**Step 3: Update factory.py**

Add `HeadbandStateTracker` to imports and insert after `SignalQualityChecker()`:

```python
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    ConcentrationScorer,
    EyesClosedDetector,
    HeadbandStateTracker,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
```

```python
    stages.extend([
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeadbandStateTracker(),   # <-- NEW: after quality checker
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
        EyesClosedDetector(),
        BandPowerBroadcaster(),
        # FAST — ...
    ])
```

**Step 4: Update serialize.py**

Add to imports:

```python
from backend.pipeline.stages.features import (
    ...,
    HeadbandStateResult,
)
```

Add serialization block:

```python
    hs = frame.get(HeadbandStateResult)
    if hs:
        metrics["headband"] = {
            "state": hs.state,
            "seconds_in_state": hs.seconds_in_state,
        }
```

**Step 5: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add backend/pipeline/factory.py backend/pipeline/serialize.py tests/test_pipeline_factory.py tests/test_pipeline_serialize.py
git commit -m "feat: wire HeadbandStateTracker into pipeline factory and serialization"
```

---

### Task 10: Integration test — full Phase 1 pipeline

**Files:**
- Modify: `tests/test_pipeline_integration.py`

**Step 1: Write the integration test**

Append to `tests/test_pipeline_integration.py`:

```python
def test_phase1_signals_present_in_full_pipeline():
    """Verify all Phase 1 signals (eyes-closed, headband state) flow through pipeline."""
    from backend.pipeline.factory import create_default_pipeline
    from backend.pipeline.stages.features import EyesClosedResult, HeadbandStateResult
    from backend.pipeline.types import Cadence, PipelineFrame
    import numpy as np
    import time

    pipeline = create_default_pipeline()
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    pipeline.run(Cadence.SLOW, frame)

    # All Phase 1 results should be present
    ec = frame.get(EyesClosedResult)
    assert ec is not None, "EyesClosedResult missing from pipeline output"

    hs = frame.get(HeadbandStateResult)
    assert hs is not None, "HeadbandStateResult missing from pipeline output"
    assert hs.state in ("ready", "fitting", "headband_off")

    # Serialization should include both
    from backend.pipeline.serialize import frame_to_metrics
    metrics = frame_to_metrics(frame)
    assert "eyes_closed" in metrics
    assert "headband" in metrics
```

**Step 2: Run test**

Run: `python -m pytest tests/test_pipeline_integration.py::test_phase1_signals_present_in_full_pipeline -v`
Expected: PASS

**Step 3: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_pipeline_integration.py
git commit -m "test: add Phase 1 integration test for eyes-closed and headband state"
```

---

Plan complete and saved to `docs/plans/2026-03-11-phase1-signal-readiness.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?