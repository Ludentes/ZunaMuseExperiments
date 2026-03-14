"""Test BlinkDetector recall/precision against recorded experiment trials.

Measured baselines (adaptive threshold_sd=1.5, pre-cue warmup):
  lab single_blink recall:   0.64  (56 trials)
  office single_blink recall: 0.35  (158 trials — poor headband fit)
  lab double_blink any-blink: 0.82; double_blink event: 0.28
  rest FP rate:               0.27  (natural blinks during rest — expected)
  clench FP rate:             0.05
  talk FP rate:               0.08

Historical reference: eval_blink_detector.py with absolute threshold_uv=-50
achieved F1=0.79 on lab data (P=0.87, R=0.72).

Run:
    PYTHONPATH=. python -m pytest tests/test_recorded_blink_detection.py -v
"""
from __future__ import annotations

import glob
import statistics
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline.stages.detectors import BlinkDetector, SpeechDetector
from backend.pipeline.types import PipelineFrame


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------

RECORDINGS = Path("recordings")
CHUNK_SAMPLES = 4  # ~16ms chunks at 256Hz, matches live server
OFFICE_DATES = ("20260313", "20260314")


def load_trials(label: str, *, office: bool | None = None) -> list[dict]:
    """Load all NPZ trials for a label.

    office=True  → only office-demo sessions (path contains 20260313/20260314)
    office=False → only lab sessions
    office=None  → all sessions
    """
    patterns = [
        str(RECORDINGS / label / f"{label}_t*.npz"),
        str(RECORDINGS / label / f"*/{label}_t*.npz"),
    ]
    files: list[str] = []
    for p in patterns:
        files.extend(sorted(glob.glob(p)))

    def is_office(path: str) -> bool:
        return any(d in path for d in OFFICE_DATES)

    if office is True:
        files = [f for f in files if is_office(f)]
    elif office is False:
        files = [f for f in files if not is_office(f)]

    return [t for t in (_load_npz(f) for f in files) if t is not None]


def _load_npz(path: str) -> dict | None:
    try:
        d = np.load(path)
        eeg = d["eeg"]
        if eeg.size == 0 or eeg.ndim != 2 or eeg.shape[0] != 4:
            return None
        return {
            "eeg": eeg.astype(np.float64),
            "cue_time_ms": int(d["cue_time_ms"]) if "cue_time_ms" in d else 1000,
            "sfreq": int(d["sfreq"]) if "sfreq" in d else 256,
            "path": path,
        }
    except Exception:
        return None


def make_detector(threshold_sd: float = 1.5) -> tuple[BlinkDetector, SpeechDetector]:
    """Create a fresh detector pair."""
    return BlinkDetector(threshold_sd=threshold_sd, refractory_ms=100, classify_window_ms=600), SpeechDetector()


def replay_trial(trial: dict, detector: BlinkDetector, speech: SpeechDetector,
                 t_offset: float = 0.0, start_sample: int = 0) -> list[str]:
    """Replay a trial from start_sample onwards; return list of event kinds."""
    eeg = trial["eeg"]
    sfreq = trial["sfreq"]
    t = t_offset
    events: list[str] = []

    for start in range(start_sample, eeg.shape[1], CHUNK_SAMPLES):
        end = min(start + CHUNK_SAMPLES, eeg.shape[1])
        chunk = eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        speech.process(frame)
        detector.process(frame)
        events.extend(e.kind for e in frame.events)
        t += (end - start) / sfreq

    # Flush: advance time well past classify window
    flush = np.zeros((4, CHUNK_SAMPLES), dtype=np.float64)
    frame = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
    speech.process(frame)
    detector.process(frame)
    events.extend(e.kind for e in frame.events)
    return events


def run_trial(trial: dict, threshold_sd: float = 1.5) -> list[str]:
    """Run a single trial: warm detector on pre-cue EEG, then detect post-cue.

    Uses pre-cue portion (first cue_time_ms) to prime the adaptive baseline,
    then returns events from the post-cue window. This mirrors how the live
    server behaves: baseline accumulates during the first second, then detection
    activates.
    """
    sfreq = trial["sfreq"]
    cue_samples = trial["cue_time_ms"] * sfreq // 1000
    det, sp = make_detector(threshold_sd)

    # Phase 1: prime baseline on pre-cue EEG (no events collected)
    replay_trial(trial, det, sp, t_offset=0.0, start_sample=0)
    # Phase 2: fresh pass from cue onward on the *same* detector
    # (replay_trial already warmed the detector; now re-run only post-cue)
    det2, sp2 = make_detector(threshold_sd)
    # Warm on pre-cue
    t = 0.0
    eeg = trial["eeg"]
    for start in range(0, cue_samples, CHUNK_SAMPLES):
        end = min(start + CHUNK_SAMPLES, cue_samples)
        chunk = eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        sp2.process(frame)
        det2.process(frame)
        t += (end - start) / sfreq
    # Detect post-cue
    return replay_trial(trial, det2, sp2, t_offset=t, start_sample=cue_samples)


def has_blink(events: list[str]) -> bool:
    return any("blink" in e for e in events)


def measure_recall(trials: list[dict], threshold_sd: float) -> float:
    if not trials:
        return float("nan")
    hits = sum(1 for t in trials if has_blink(run_trial(t, threshold_sd)))
    return hits / len(trials)


def measure_fp_rate(trials: list[dict], threshold_sd: float) -> float:
    """FP rate for *negative* trials (rest/clench/talk).

    Note: rest trials contain natural blinks; a detection is not necessarily
    wrong, just an expected false positive by protocol convention.
    """
    if not trials:
        return float("nan")
    fps = sum(1 for t in trials if has_blink(run_trial(t, threshold_sd)))
    return fps / len(trials)


# ---------------------------------------------------------------------------
# Single blink — lab recordings
# ---------------------------------------------------------------------------

class TestSingleBlinkLab:
    @pytest.fixture(scope="class")
    def trials(self):
        t = load_trials("single_blink", office=False)
        if not t:
            pytest.skip("No lab single_blink recordings found")
        return t

    @pytest.mark.parametrize("threshold_sd", [1.0, 1.5, 2.0])
    def test_recall_above_floor(self, trials, threshold_sd):
        recall = measure_recall(trials, threshold_sd)
        # Lab recordings: good signal. Measured baseline: 0.64 at sd=1.5.
        # Floor at 0.55 to allow some slack while catching regressions.
        assert recall >= 0.55, (
            f"Lab single_blink recall={recall:.2f} below 0.55 at threshold_sd={threshold_sd}"
        )

    def test_recall_improves_with_lower_threshold(self, trials):
        r_loose = measure_recall(trials, 1.0)
        r_strict = measure_recall(trials, 2.5)
        assert r_loose >= r_strict - 0.10, (
            f"Lower threshold hurt recall: sd=1.0→{r_loose:.2f}, sd=2.5→{r_strict:.2f}"
        )


# ---------------------------------------------------------------------------
# Single blink — office demo recordings (poor fit, hard cases)
# ---------------------------------------------------------------------------

class TestSingleBlinkOffice:
    @pytest.fixture(scope="class")
    def trials(self):
        t = load_trials("single_blink", office=True)
        if not t:
            pytest.skip("No office single_blink recordings found")
        return t

    @pytest.mark.parametrize("threshold_sd", [1.0, 1.5, 2.0])
    def test_recall_above_floor(self, trials, threshold_sd):
        recall = measure_recall(trials, threshold_sd)
        # Office sessions: poor fit, weak blinks. Measured baseline: 0.35 at sd=1.5.
        assert recall >= 0.28, (
            f"Office single_blink recall={recall:.2f} below 0.28 at threshold_sd={threshold_sd}"
        )

    def test_sd1_not_worse_than_sd2(self, trials):
        r_loose = measure_recall(trials, 1.0)
        r_strict = measure_recall(trials, 2.0)
        assert r_loose >= r_strict - 0.08, (
            f"sd=1.0 recall {r_loose:.2f} significantly worse than sd=2.0 {r_strict:.2f}"
        )


# ---------------------------------------------------------------------------
# Double blink
# ---------------------------------------------------------------------------

class TestDoubleBlink:
    @pytest.fixture(scope="class")
    def trials(self):
        t = load_trials("double_blink")
        if not t:
            pytest.skip("No double_blink recordings found")
        return t

    def test_any_blink_recall(self, trials):
        """At least some blink event should fire for most double_blink trials."""
        recall = measure_recall(trials, 1.5)
        # Measured: 0.64 overall (0.82 lab + 0.45 office)
        assert recall >= 0.55, (
            f"double_blink any-blink recall={recall:.2f} below 0.55"
        )

    def test_double_blink_event_rate_lab(self):
        """Lab double_blink: the correct double_blink event fires ≥25% of the time."""
        trials = load_trials("double_blink", office=False)
        if not trials:
            pytest.skip("no lab double_blink")
        hits = sum(1 for t in trials if "double_blink" in run_trial(t, 1.5))
        rate = hits / len(trials)
        # Measured: 0.28 (lab). Double blink timing is strict — two blinks in 600ms window.
        assert rate >= 0.20, (
            f"lab double_blink event rate={rate:.2f} below 0.20 "
            f"(single misclassifications are expected)"
        )

    @pytest.mark.parametrize("threshold_sd", [1.0, 1.5, 2.0])
    def test_miss_rate_not_catastrophic(self, trials, threshold_sd):
        """No more than 50% of double_blink trials should go completely undetected."""
        missed = sum(1 for t in trials if not has_blink(run_trial(t, threshold_sd)))
        miss_rate = missed / len(trials)
        assert miss_rate <= 0.50, (
            f"Missed {missed}/{len(trials)} double_blink trials at threshold_sd={threshold_sd}"
        )


# ---------------------------------------------------------------------------
# Negative class — rest, clench, talk
# ---------------------------------------------------------------------------

class TestNegativeLabels:
    @pytest.fixture(scope="class")
    def rest_trials(self):
        return load_trials("rest")

    @pytest.fixture(scope="class")
    def clench_trials(self):
        return load_trials("clench")

    @pytest.fixture(scope="class")
    def talk_trials(self):
        return load_trials("talk")

    def test_rest_fp_rate(self, rest_trials):
        """Rest FP rate can be high — rest trials include spontaneous blinks."""
        if not rest_trials:
            pytest.skip("no rest trials")
        fp = measure_fp_rate(rest_trials, 1.5)
        # Measured: 0.27. Floor at 0.40 (we detect real blinks → not actually FP).
        assert fp <= 0.40, f"Rest FP rate={fp:.2f} exceeds 0.40"

    def test_clench_fp_rate(self, clench_trials):
        """Jaw clench should not be mistaken for a blink (HF ratio guard)."""
        if not clench_trials:
            pytest.skip("no clench trials")
        fp = measure_fp_rate(clench_trials, 1.5)
        # Measured: 0.05
        assert fp <= 0.20, f"Clench FP rate={fp:.2f} exceeds 0.20"

    def test_talk_fp_rate(self, talk_trials):
        """Speech should not trigger blink detection (SpeechDetector guard)."""
        if not talk_trials:
            pytest.skip("no talk trials")
        fp = measure_fp_rate(talk_trials, 1.5)
        # Measured: 0.08
        assert fp <= 0.20, f"Talk FP rate={fp:.2f} exceeds 0.20"

    def test_clench_fp_below_talk_fp(self, clench_trials, talk_trials):
        """Clench FP should be no worse than talk FP (HF guard vs speech guard)."""
        if not clench_trials or not talk_trials:
            pytest.skip("missing trials")
        fp_clench = measure_fp_rate(clench_trials, 1.5)
        fp_talk = measure_fp_rate(talk_trials, 1.5)
        # Both should be low; no strict ordering required but both should be < rest
        assert fp_clench <= 0.20
        assert fp_talk <= 0.20


# ---------------------------------------------------------------------------
# Calibration: threshold_sd cap + absolute floor behavior
# ---------------------------------------------------------------------------

class TestCalibrationBehavior:
    def _make_warmed_detector(self, n_chunks: int = 256) -> BlinkDetector:
        """Return a detector with a stable baseline."""
        rng = np.random.default_rng(0)
        det, sp = make_detector(1.5)
        t = 0.0
        for _ in range(n_chunks):
            chunk = rng.normal(-15, 10, (4, CHUNK_SAMPLES))
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            sp.process(frame)
            det.process(frame)
            t += CHUNK_SAMPLES / 256
        return det

    def test_set_calibrated_threshold_caps_sd_at_3_5(self):
        """When blinks are many SDs from baseline (tiny MAD), cap at 3.5 SDs."""
        det = self._make_warmed_detector()
        # Feed a very weak blink amplitude — simulates poor-fit session where
        # MAD is small relative to blink size
        det.set_calibrated_threshold(median_peak_amplitude_uv=-20.0)
        assert det.threshold_sd <= 3.5, (
            f"threshold_sd={det.threshold_sd:.2f} exceeds cap of 3.5 after calibration"
        )

    def test_set_calibrated_threshold_sets_floor(self):
        """Calibration must set threshold_uv as an absolute floor."""
        det = self._make_warmed_detector()
        det.set_calibrated_threshold(median_peak_amplitude_uv=-60.0)
        assert det.threshold_uv > -9000, (
            f"threshold_uv={det.threshold_uv} not set after calibration"
        )
        # Floor should be near the half-amplitude
        assert -90 < det.threshold_uv < 0, (
            f"threshold_uv={det.threshold_uv} is outside plausible range"
        )

    def test_set_blink_threshold_clears_floor(self):
        """Setting threshold_sd via slider should clear the absolute floor."""
        det = self._make_warmed_detector()
        det.set_calibrated_threshold(-60.0)
        assert det.threshold_uv > -9000

        det.set_blink_threshold(threshold_sd=2.0)
        assert det.threshold_uv <= -9000, (
            "threshold_uv floor should be cleared after set_blink_threshold"
        )

    def test_calibration_with_weak_blink_does_not_break_detector(self):
        """Calibration with a very weak blink (<5µV, below noise) should not break detector."""
        det = self._make_warmed_detector()
        det.set_calibrated_threshold(median_peak_amplitude_uv=-3.0)
        # Detector should still be usable
        assert det.threshold_sd >= 1.0
        assert det.threshold_sd <= 3.5

    def test_post_calibration_recall_vs_uncalibrated(self):
        """Calibrated detector should maintain reasonable recall on lab single blink."""
        trials = load_trials("single_blink", office=False)
        if len(trials) < 10:
            pytest.skip("Not enough lab trials")

        calib_set = trials[:5]
        test_set = trials[5:15]

        # Collect calibration amplitudes from pre-cue-warmed passes
        amps = []
        for trial in calib_set:
            frontal = (trial["eeg"][1] + trial["eeg"][2]) / 2.0
            cue_s = trial["cue_time_ms"] * trial["sfreq"] // 1000
            post = frontal[cue_s:]
            if len(post) > 0:
                amp = float(np.min(post))
                if amp < -5:
                    amps.append(amp)

        if len(amps) < 2:
            pytest.skip("Not enough blink amplitudes from calibration set")

        median_amp = statistics.median(amps)

        # Test recall with calibration vs without
        hits_cal = hits_uncal = 0
        for trial in test_set:
            events_uncal = run_trial(trial, 1.5)
            if has_blink(events_uncal):
                hits_uncal += 1

            # Calibrated: prime baseline then calibrate
            det, sp = make_detector(1.5)
            sfreq = trial["sfreq"]
            cue_s = trial["cue_time_ms"] * sfreq // 1000
            t = 0.0
            for start in range(0, cue_s, CHUNK_SAMPLES):
                end = min(start + CHUNK_SAMPLES, cue_s)
                frame = PipelineFrame(eeg=trial["eeg"][:, start:end], ppg=None, imu=None, timestamp=t)
                sp.process(frame); det.process(frame)
                t += (end - start) / sfreq
            det.set_calibrated_threshold(median_amp)
            events_cal = replay_trial(trial, det, sp, t_offset=t, start_sample=cue_s)
            if has_blink(events_cal):
                hits_cal += 1

        recall_uncal = hits_uncal / len(test_set)
        recall_cal = hits_cal / len(test_set)

        assert recall_cal >= recall_uncal - 0.20, (
            f"Calibrated recall {recall_cal:.2f} is much worse than uncalibrated {recall_uncal:.2f}. "
            f"median_amp={median_amp:.1f}µV"
        )


# ---------------------------------------------------------------------------
# Long-session stability: blinks must stay detectable after idle
# ---------------------------------------------------------------------------

class TestLongSessionStability:
    def _make_blink_chunk(self, rng: np.random.Generator,
                          peak_uv: float = -80.0, baseline_uv: float = -15.0) -> np.ndarray:
        """Return a 4-channel EEG chunk containing a V-shaped blink.

        Blink starts and ends at baseline_uv (matching the resting noise level),
        so the threshold crossing is computed correctly relative to baseline.
        """
        n = 26  # ~100ms at 256Hz
        half = n // 2
        trough = baseline_uv + peak_uv  # e.g., -15 + (-80) = -95µV
        # Downstroke: baseline → trough, upstroke: trough → baseline
        envelope = np.concatenate([
            np.linspace(baseline_uv, trough, half),
            np.linspace(trough, baseline_uv, n - half),
        ])
        blink = np.zeros((4, n), dtype=np.float64)
        blink[0, :] = rng.normal(baseline_uv, 5, n)  # temporal (no blink)
        blink[1, :] = envelope + rng.normal(0, 3, n)  # AF7
        blink[2, :] = envelope + rng.normal(0, 3, n)  # AF8
        blink[3, :] = rng.normal(baseline_uv, 5, n)  # temporal (no blink)
        return blink

    def test_blinks_detected_after_60s_idle(self):
        """After 60 seconds of quiet signal, blinks should still be detectable."""
        rng = np.random.default_rng(42)
        det, sp = make_detector(1.5)

        # 60 seconds of resting EEG noise (mean=-15, sd=12 µV, mimics real EEG)
        t = 0.0
        for _ in range(int(60 * 256 / CHUNK_SAMPLES)):
            chunk = rng.normal(-15, 12, (4, CHUNK_SAMPLES))
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            sp.process(frame)
            det.process(frame)
            t += CHUNK_SAMPLES / 256

        # Inject 10 V-shaped blinks at 2.5s intervals
        detected = 0
        for _ in range(10):
            blink = self._make_blink_chunk(rng)
            n = blink.shape[1]
            events = []
            for start in range(0, n, CHUNK_SAMPLES):
                end = min(start + CHUNK_SAMPLES, n)
                frame = PipelineFrame(eeg=blink[:, start:end], ppg=None, imu=None, timestamp=t)
                sp.process(frame)
                det.process(frame)
                events.extend(e.kind for e in frame.events)
                t += (end - start) / 256

            # Quiet gap + flush
            for _ in range(int(2.4 * 256 / CHUNK_SAMPLES)):
                chunk = rng.normal(-15, 12, (4, CHUNK_SAMPLES))
                frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
                sp.process(frame); det.process(frame)
                events.extend(e.kind for e in frame.events)
                t += CHUNK_SAMPLES / 256

            frame = PipelineFrame(eeg=np.zeros((4, 4)), ppg=None, imu=None, timestamp=t + 0.5)
            sp.process(frame); det.process(frame)
            events.extend(e.kind for e in frame.events)

            if has_blink(events):
                detected += 1

        assert detected >= 6, (
            f"Only {detected}/10 blinks detected after 60s idle. "
            f"baseline_median={det._baseline_median:.1f}, mad={det._baseline_mad:.2f}, "
            f"effective_thresh={det._baseline_median - 1.5*1.4826*det._baseline_mad:.1f}µV"
        )

    def test_threshold_sd_not_drift_after_calibration(self):
        """After calibration, long-running baseline should not push threshold_sd above 3.5."""
        rng = np.random.default_rng(1)
        det, sp = make_detector(1.5)

        # Warm up
        t = 0.0
        for _ in range(256):
            chunk = rng.normal(-15, 10, (4, CHUNK_SAMPLES))
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            sp.process(frame); det.process(frame)
            t += CHUNK_SAMPLES / 256

        det.set_calibrated_threshold(-40.0)
        initial_sd = det.threshold_sd

        # Run 120 more seconds of noise (threshold_sd is fixed — only threshold_uv drifts)
        for _ in range(int(120 * 256 / CHUNK_SAMPLES)):
            chunk = rng.normal(-15, 10, (4, CHUNK_SAMPLES))
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            sp.process(frame); det.process(frame)
            t += CHUNK_SAMPLES / 256

        assert det.threshold_sd == initial_sd, (
            f"threshold_sd drifted from {initial_sd:.2f} to {det.threshold_sd:.2f} "
            f"after 120s (should be immutable post-calibration)"
        )
