# Advanced Blink Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace ad-hoc baseline/threshold statistics with MAD-based robust statistics, and replace shape guard with BLINKER-style R² morphological validation, improving blink detection on noisy consumer EEG data.

**Architecture:** Two incremental upgrades to the existing BlinkDetector in `backend/pipeline/stages/detectors.py`. Phase 1 swaps the EMA baseline (mean/variance) for a rolling-window median/MAD, making the threshold immune to artifact contamination. Phase 2 replaces the shape guard's duration-only check with BLINKER's R² tent-shape fitting + BAR signal quality metric. Both phases are additive — each makes the detector better independently.

**Tech Stack:** Python, NumPy (no new dependencies). The `scipy.stats.linregress` is available but we'll use `np.polyfit` degree 1 to avoid adding scipy as a hard dependency for a single call.

**Key files:**
- `backend/pipeline/stages/detectors.py` — BlinkDetector class (lines 79-455)
- `tests/test_pipeline_stages_detectors.py` — unit tests
- `tests/test_blink_detector_drift.py` — drift/cold-start tests
- `scripts/eval_blink_detector.py` — evaluation harness

**Research:** `docs/research/2026-03-13-advanced-blink-detection-methods-practical.md`

---

## Task 0: Baseline Eval (reference numbers)

Run the eval harness twice to establish baseline numbers before any code changes.

**Step 1: Run eval on original data only**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name baseline-original --tag pre-advanced --exclude-pattern 20260313
```

Expected: F1 ~0.93-0.95 on developer's clean recordings.

**Step 2: Run eval on all data including office demo**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name baseline-all --tag pre-advanced-all
```

Expected: F1 will drop (office demo data is noisy). Record the exact numbers.

**Step 3: Record numbers**

Note precision, recall, F1, FP breakdown for both runs. These are our "before" numbers.

---

## Task 1: MAD-Based Robust Baseline — Rolling Window

Replace the EMA-based baseline (which is pulled by outliers) with a **rolling window of chunk means** + median/MAD computation.

**Files:**
- Modify: `backend/pipeline/stages/detectors.py` (BlinkDetector class)
- Test: `tests/test_pipeline_stages_detectors.py`

**Step 1: Write failing tests**

Add to `tests/test_pipeline_stages_detectors.py`:

```python
def test_blink_detector_mad_baseline_not_pulled_by_outliers():
    """MAD baseline should not be pulled by occasional large deflections."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100)

    # Establish baseline at 0 µV
    t = _establish_baseline(detector, rng, signal_mean=0.0, signal_sd=10.0)

    # Inject 5 large deflections (not blinks, just noise spikes)
    for _ in range(5):
        spike = rng.normal(0, 10, (4, 4)).astype(np.float64)
        spike[1, :] = -300.0
        spike[2, :] = -300.0
        frame = PipelineFrame(eeg=spike, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        t += 4 / 256

    # Baseline should still be near 0, not pulled toward -300
    assert abs(detector._baseline_median) < 30.0, (
        f"Baseline pulled to {detector._baseline_median}, expected near 0"
    )


def test_blink_detector_mad_robust_sd():
    """Robust SD (1.4826 * MAD) should be used for threshold calculation."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector()

    _establish_baseline(detector, rng, signal_mean=0.0, signal_sd=10.0)

    # The robust SD should exist and be reasonable
    assert hasattr(detector, '_baseline_mad')
    robust_sd = 1.4826 * detector._baseline_mad
    assert 5.0 < robust_sd < 30.0, f"Robust SD {robust_sd} out of expected range"
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py::test_blink_detector_mad_baseline_not_pulled_by_outliers tests/test_pipeline_stages_detectors.py::test_blink_detector_mad_robust_sd -v
```

Expected: FAIL — `_baseline_median` and `_baseline_mad` don't exist yet.

**Step 3: Implement rolling window + MAD baseline**

In `detectors.py`, modify BlinkDetector `__init__`:

```python
# Replace these EMA-based baseline fields:
#   self._baseline_mean: float = 0.0
#   self._baseline_var: float = 1.0
#   self._baseline_samples: int = 0

# With rolling window + MAD:
self._baseline_window: deque[float] = deque(maxlen=256)  # ~4s of chunk means at 64 chunks/s
self._baseline_median: float = 0.0
self._baseline_mad: float = 1.0
self._baseline_samples: int = 0  # keep for cold start counting
```

Replace `_update_baseline` method:

```python
def _update_baseline(self, chunk_mean: float, n_samples: int = 1) -> None:
    """Update rolling window baseline with median/MAD.

    Args:
        chunk_mean: Mean of the current chunk's frontal signal.
        n_samples: Number of samples in this chunk (for cold start counting).
    """
    self._baseline_samples += n_samples
    self._baseline_window.append(chunk_mean)

    if len(self._baseline_window) >= 8:  # need minimum data for meaningful statistics
        values = np.array(self._baseline_window)
        self._baseline_median = float(np.median(values))
        self._baseline_mad = float(np.median(np.abs(values - self._baseline_median)))
        if self._baseline_mad < 0.5:
            self._baseline_mad = 0.5  # floor to prevent zero-MAD in perfectly stable signals
```

Replace `_is_candidate` method:

```python
def _is_candidate(self, chunk_mean: float) -> bool:
    """Check if chunk_mean exceeds adaptive MAD-based threshold.

    Uses robust statistics: threshold = median - λ * 1.4826 * MAD
    The 1.4826 factor converts MAD to a consistent estimator of SD
    for normal distributions.
    """
    if self._baseline_samples < 256:
        return False  # cold start: accumulate baseline, don't detect

    robust_sd = 1.4826 * self._baseline_mad
    adaptive_thresh = self._baseline_median - self.threshold_sd * robust_sd
    return chunk_mean < adaptive_thresh
```

Update `process()` baseline update logic — replace the proximity guard to use MAD instead of variance:

```python
# Replace the baseline update block with:
chunk_mean = chunk_val
n_samp = len(frontal)
if self._baseline_samples < 256:
    if self._baseline_samples < 64:
        self._update_baseline(chunk_mean, n_samp)
    else:
        robust_sd = 1.4826 * self._baseline_mad
        if abs(chunk_mean - self._baseline_median) < 5 * robust_sd:
            self._update_baseline(chunk_mean, n_samp)
else:
    robust_sd = 1.4826 * self._baseline_mad
    if abs(chunk_mean - self._baseline_median) < 3 * robust_sd:
        self._update_baseline(chunk_mean, n_samp)
```

Also update the debug logging in `process()` that references `self._baseline_var`:

```python
# Change:
#   sd = max(np.sqrt(self._baseline_var), 1.0) if self._baseline_samples >= 256 else 0
# To:
sd = max(1.4826 * self._baseline_mad, 1.0) if self._baseline_samples >= 256 else 0

# And change:
#   adaptive = (self._baseline_mean - self.threshold_sd * sd) if ...
# To:
adaptive = (self._baseline_median - self.threshold_sd * sd) if self._baseline_samples >= 256 else None
```

**Step 4: Run all tests**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py tests/test_blink_detector_drift.py -v
```

Expected: All pass. The existing tests shouldn't break because the detection behavior is similar — just the statistics are more robust.

**Step 5: Fix any regressions**

If drift tests fail, it's likely because `_baseline_mean` or `_baseline_var` is referenced somewhere. Search for all occurrences and update:

```bash
grep -n "_baseline_mean\|_baseline_var" backend/pipeline/stages/detectors.py
```

Replace `_baseline_mean` → `_baseline_median` and `_baseline_var` → `(1.4826 * self._baseline_mad) ** 2` or just use `_baseline_mad` directly.

**Step 6: Commit**

```bash
git add backend/pipeline/stages/detectors.py tests/test_pipeline_stages_detectors.py
git commit -m "feat: replace EMA baseline with MAD-based robust statistics in BlinkDetector"
```

---

## Task 2: MAD Baseline — Eval Checkpoint

Run the eval harness to measure improvement from MAD upgrade.

**Step 1: Run eval on original data**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name mad-original --tag mad --exclude-pattern 20260313
```

Expected: F1 should be ≥ baseline (MAD shouldn't hurt clean data).

**Step 2: Run eval on all data**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name mad-all --tag mad
```

Expected: F1 should improve vs baseline-all (MAD helps noisy data).

**Step 3: Compare and record**

Compare Task 0 numbers with Task 2 numbers. If MAD made things worse on clean data, investigate — the threshold_sd multiplier may need adjustment (try 2.5 or 3.0 instead of 2.0).

**Step 4: Commit eval results**

```bash
git add experiments/
git commit -m "docs: MAD baseline eval results"
```

---

## Task 3: BLINKER R² Morphological Validation

Replace the current shape guard (duration-only check via contiguous sub-threshold measurement) with BLINKER's R² tent-shape fitting.

A blink waveform has a characteristic tent shape: linear downstroke → peak → linear upstroke. Fitting linear regressions to each half and computing R² measures how well the signal conforms to this shape. Non-blink artifacts (speech, noise, movement) have poor R².

**Files:**
- Modify: `backend/pipeline/stages/detectors.py` (BlinkDetector._check_shape)
- Test: `tests/test_pipeline_stages_detectors.py`

**Step 1: Write failing tests**

Add to `tests/test_pipeline_stages_detectors.py`:

```python
def test_blink_detector_r2_accepts_tent_shape():
    """A clean tent-shaped blink waveform should pass R² validation."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # Create a clean tent-shaped blink: linear down then linear up
    # 20 samples = ~78ms, realistic blink duration
    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0, blink_amp=-200.0,
                                blink_samples=20, total_samples=64)
    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) >= 1


def test_blink_detector_r2_rejects_plateau():
    """A flat plateau (not tent-shaped) should be rejected by R² guard."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # Create a plateau: abrupt drop, flat bottom, abrupt rise
    # This has poor R² because the "downstroke" and "upstroke" are vertical
    plateau = rng.normal(0, 5, (4, 128)).astype(np.float64)
    # Abrupt transition to -150µV for 40 samples then back
    plateau[1, 30:70] = -150.0
    plateau[2, 30:70] = -150.0

    all_events = []
    for start in range(0, 128, 4):
        end = min(start + 4, 128)
        chunk = plateau[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        all_events.extend(frame.events)
        t += 4 / 256

    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)
    all_events.extend(events2)

    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 0, "Plateau shape should be rejected by R² guard"
```

**Step 2: Run tests to verify behavior**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py::test_blink_detector_r2_accepts_tent_shape tests/test_pipeline_stages_detectors.py::test_blink_detector_r2_rejects_plateau -v
```

The tent test should pass (existing detector accepts blinks). The plateau test tells us whether the current shape guard already rejects this — if it does, we still want to refactor for R².

**Step 3: Implement R² tent-shape validation**

Replace `_check_shape` in BlinkDetector:

```python
def _check_shape(self) -> bool:
    """Validate blink shape using BLINKER-style R² tent fitting.

    A real blink has a characteristic tent shape: linear downstroke to peak,
    then linear upstroke back to baseline. We fit linear regressions to the
    inner 80% of each half and compute R². Good blinks have R² ≥ 0.7 on
    both halves.

    Also checks duration is within [min_deflection_ms, max_deflection_ms].

    Falls back to duration-only check if buffer is too small for R².

    Returns True if shape is blink-like.
    """
    if not self._buf_filled and self._buf_pos < self._HALF_WIN * 2:
        return True  # not enough data, accept

    # Reconstruct ordered buffer
    if self._buf_filled:
        buf = np.concatenate([
            self._frontal_buf[self._buf_pos:],
            self._frontal_buf[:self._buf_pos],
        ])
    else:
        buf = self._frontal_buf[:self._buf_pos]

    # Find the deepest point (blink peak is most negative)
    min_idx = int(np.argmin(buf))
    peak_val = float(buf[min_idx])
    half_amp = peak_val / 2.0

    # Find zero crossings (where signal crosses half-amplitude)
    # Walk left
    left_idx = min_idx
    for i in range(min_idx - 1, -1, -1):
        if buf[i] >= half_amp:
            left_idx = i
            break
    else:
        left_idx = 0

    # Walk right
    right_idx = min_idx
    for i in range(min_idx + 1, len(buf)):
        if buf[i] >= half_amp:
            right_idx = i
            break
    else:
        right_idx = len(buf) - 1

    # Duration check
    contiguous = right_idx - left_idx + 1
    dur_ms = contiguous / 256.0 * 1000.0

    if dur_ms < self.min_deflection_ms:
        self._log.debug("SHAPE: too brief %.0fms < %.0fms", dur_ms, self.min_deflection_ms)
        return False
    if dur_ms > self.max_deflection_ms:
        self._log.debug("SHAPE: too broad %.0fms > %.0fms", dur_ms, self.max_deflection_ms)
        return False

    # R² tent fitting: need at least 4 samples per half for meaningful regression
    downstroke = buf[left_idx:min_idx + 1]
    upstroke = buf[min_idx:right_idx + 1]

    if len(downstroke) < 4 or len(upstroke) < 4:
        return True  # too short for R², accept based on duration alone

    # Fit inner 80% of each half
    def r_squared(segment: np.ndarray) -> float:
        n = len(segment)
        start = int(n * 0.1)
        end = int(n * 0.9)
        if end - start < 3:
            return 1.0  # too few points, accept
        inner = segment[start:end]
        x = np.arange(len(inner), dtype=np.float64)
        coeffs = np.polyfit(x, inner, 1)
        predicted = np.polyval(coeffs, x)
        ss_res = np.sum((inner - predicted) ** 2)
        ss_tot = np.sum((inner - np.mean(inner)) ** 2)
        if ss_tot < 1e-10:
            return 1.0  # constant signal
        return 1.0 - ss_res / ss_tot

    r2_down = r_squared(downstroke)
    r2_up = r_squared(upstroke)

    min_r2 = 0.7  # BLINKER uses 0.90 for "good", but our 4-sample streaming
                   # produces noisier waveforms. 0.7 is conservative.

    if r2_down < min_r2 or r2_up < min_r2:
        self._log.debug("SHAPE R²: down=%.2f up=%.2f (min=%.2f) → REJECT",
                       r2_down, r2_up, min_r2)
        return False

    self._log.debug("SHAPE R²: down=%.2f up=%.2f → ACCEPT", r2_down, r2_up)
    return True
```

**Step 4: Run all tests**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py tests/test_blink_detector_drift.py -v
```

Expected: All pass. If the tent test fails, the R² threshold may need lowering (try 0.5). If drift tests fail, shape validation on real data may be rejecting valid blinks — lower min_r2.

**Step 5: Commit**

```bash
git add backend/pipeline/stages/detectors.py tests/test_pipeline_stages_detectors.py
git commit -m "feat: replace duration-only shape guard with R² tent-shape validation"
```

---

## Task 4: BAR (Blink-Amplitude Ratio) Guard

Add the BLINKER BAR metric: ratio of mean amplitude within the blink region to mean amplitude of surrounding non-blink signal. Valid blinks have BAR in [3, 50]. This rejects "blinks" in noisy sessions where the noise floor is close to blink amplitude.

**Files:**
- Modify: `backend/pipeline/stages/detectors.py`
- Test: `tests/test_pipeline_stages_detectors.py`

**Step 1: Write failing test**

```python
def test_blink_detector_bar_rejects_noisy_session():
    """A 'blink' in a very noisy signal (BAR < 3) should be rejected."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100)

    # Establish baseline with VERY high noise (simulates poor fit)
    t = _establish_baseline(detector, rng, signal_mean=0.0, signal_sd=80.0)

    # Inject a "blink" that's only slightly larger than noise
    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0, blink_amp=-150.0)
    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2
    blink_events = [e for e in all_events if "blink" in e.kind]
    # With noise SD=80, a -150µV blink is only ~2x the noise — BAR < 3
    assert len(blink_events) == 0, "Blink in very noisy signal should be rejected by BAR"
```

**Step 2: Run test**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py::test_blink_detector_bar_rejects_noisy_session -v
```

Expected: Might pass (high noise may prevent detection anyway) or fail. Either way, add the BAR guard.

**Step 3: Implement BAR guard**

Add to `_try_emit_blink`, after the shape guard and before refractory check:

```python
# Guard 3.5: BAR (Blink-Amplitude Ratio) — reject if blink is too close to noise floor
if self._buf_filled or self._buf_pos >= self._HALF_WIN * 2:
    if self._buf_filled:
        buf = np.concatenate([
            self._frontal_buf[self._buf_pos:],
            self._frontal_buf[:self._buf_pos],
        ])
    else:
        buf = self._frontal_buf[:self._buf_pos]

    min_idx = int(np.argmin(buf))
    peak_val = float(buf[min_idx])
    half_amp = peak_val / 2.0

    # Find blink region (sub half-amplitude)
    left = min_idx
    for i in range(min_idx - 1, -1, -1):
        if buf[i] >= half_amp:
            left = i
            break
    right = min_idx
    for i in range(min_idx + 1, len(buf)):
        if buf[i] >= half_amp:
            right = i
            break

    blink_region = buf[left:right + 1]
    non_blink = np.concatenate([buf[:max(0, left - 10)], buf[min(len(buf), right + 10):]])

    if len(blink_region) > 0 and len(non_blink) > 10:
        blink_amp = float(np.mean(np.abs(blink_region)))
        noise_amp = float(np.mean(np.abs(non_blink)))
        bar = blink_amp / noise_amp if noise_amp > 0.1 else 100.0

        if bar < 3.0:
            self._log.debug("REJECTED by BAR guard: BAR=%.1f (min=3.0)", bar)
            return
```

**Step 4: Run all tests**

```bash
python -m pytest tests/test_pipeline_stages_detectors.py tests/test_blink_detector_drift.py -v
```

**Step 5: Commit**

```bash
git add backend/pipeline/stages/detectors.py tests/test_pipeline_stages_detectors.py
git commit -m "feat: add BAR (Blink-Amplitude Ratio) guard to reject blinks in noisy sessions"
```

---

## Task 5: Final Eval + Comparison

**Step 1: Run eval on original data**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name advanced-original --tag advanced --exclude-pattern 20260313
```

**Step 2: Run eval on all data**

```bash
PYTHONPATH=. python scripts/eval_blink_detector.py --save --name advanced-all --tag advanced
```

**Step 3: Compare all results**

Create a summary table:

| Config | Data | P | R | F1 | FP_rest | FP_clench | FP_talk |
|--------|------|---|---|----|---------|-----------| --------|
| baseline | original | ? | ? | ? | ? | ? | ? |
| baseline | all | ? | ? | ? | ? | ? | ? |
| MAD | original | ? | ? | ? | ? | ? | ? |
| MAD | all | ? | ? | ? | ? | ? | ? |
| advanced | original | ? | ? | ? | ? | ? | ? |
| advanced | all | ? | ? | ? | ? | ? | ? |

The key questions:
1. Does MAD improve F1 on noisy data without hurting clean data?
2. Does R² + BAR reduce FPs without killing recall?
3. What's the combined effect?

**Step 4: Tune if needed**

If R² threshold (0.7) is too aggressive → lower to 0.5.
If BAR threshold (3.0) kills recall → lower to 2.0.
If MAD threshold_sd needs adjustment → try 2.5 or 3.0.

**Step 5: Commit everything**

```bash
git add experiments/ docs/
git commit -m "docs: advanced blink detection eval comparison"
```

---

## Task 6: Run Full Test Suite

**Step 1: Run all tests**

```bash
python -m pytest tests/ -v
```

Expected: All pass. If any drift tests or unit tests regress, fix before proceeding.

**Step 2: Final commit**

```bash
git add -A
git commit -m "feat: advanced blink detection — MAD + R² + BAR"
```

---

## Summary of Changes

| Component | Before | After |
|-----------|--------|-------|
| Baseline tracking | EMA of mean/variance | Rolling window (256 chunks) + median/MAD |
| Threshold formula | `mean - λ * sqrt(var)` | `median - λ * 1.4826 * MAD` |
| Shape guard | Duration only (contiguous sub-threshold) | R² tent fitting (inner 80% linear regression) + duration |
| Noise rejection | Implicit (threshold) | Explicit BAR guard (blink amp / noise amp ≥ 3) |
| Cold start | EMA accumulation 256 samples | Same (rolling window fills naturally) |
| Baseline drift | Proximity guard (3 SD) | Same principle, MAD-based (3 × 1.4826 × MAD) |
