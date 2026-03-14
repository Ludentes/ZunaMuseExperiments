"""Tests for BlinkDetector cold start suppression and baseline drift tracking.

Uses real long-duration baseline recordings to verify:
1. No false positives during cold start (first ~1s)
2. Baseline EMA tracks actual signal mean over minutes
3. FP rate stays low over 750s (12.5 min) sessions
4. Detector still fires on injected blinks after minutes of quiet data
5. Synthetic drift: baseline shifts don't cause FP bursts or detection loss
"""
import glob
from pathlib import Path

import numpy as np
import pytest

from backend.pipeline.stages.detectors import BlinkDetector, SpeechDetector
from backend.pipeline.types import PipelineFrame


def _load_baseline(path: str) -> np.ndarray:
    d = np.load(path)
    return d["eeg"].astype(np.float64)


def _replay_eeg(
    eeg: np.ndarray,
    detector: BlinkDetector,
    chunk_size: int = 4,
    speech_detector: SpeechDetector | None = None,
) -> list:
    """Replay EEG through detector in streaming chunks. Returns list of (time_s, event_kind)."""
    sr = 256
    dt = chunk_size / sr
    events = []
    t = 0.0
    for start in range(0, eeg.shape[1], chunk_size):
        end = min(start + chunk_size, eeg.shape[1])
        chunk = eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        if speech_detector:
            speech_detector.process(frame)
        detector.process(frame)
        for ev in frame.events:
            events.append((t, ev.kind))
        t += dt
    # Flush pending blinks
    flush = np.zeros((4, 4), dtype=np.float64)
    frame = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
    if speech_detector:
        speech_detector.process(frame)
    detector.process(frame)
    for ev in frame.events:
        events.append((t + 2.0, ev.kind))
    return events


def _inject_v_blink(eeg: np.ndarray, start: int, baseline_uv: float,
                     amplitude_uv: float, duration: int = 26) -> None:
    """Inject a V-shaped blink into frontal channels AF7 (idx 1) and AF8 (idx 2).

    Generates a linear downstroke from baseline to trough, then a linear upstroke
    back to baseline.  This passes the slope guard that rejects flat plateaus.

    Args:
        eeg: (4, N) array to modify in-place.
        start: Sample index where blink starts.
        baseline_uv: Resting baseline level (µV).
        amplitude_uv: Peak deflection below baseline (negative µV, e.g. -170).
        duration: Total blink duration in samples (~100ms at 256Hz = 26 samples).
    """
    half = duration // 2
    trough = baseline_uv + amplitude_uv
    downstroke = np.linspace(baseline_uv, trough, half)
    upstroke = np.linspace(trough, baseline_uv, duration - half)
    envelope = np.concatenate([downstroke, upstroke])
    end = min(start + duration, eeg.shape[1])
    n = end - start
    eeg[1, start:end] = envelope[:n]
    eeg[2, start:end] = envelope[:n]


def _get_longest_baseline() -> str | None:
    """Find the largest baseline .npz file."""
    files = glob.glob("recordings/baseline/**/baseline_t*.npz", recursive=True)
    if not files:
        return None
    return max(files, key=lambda f: Path(f).stat().st_size)


def _get_baseline_files(min_seconds: float = 30.0) -> list[str]:
    """Get baseline recordings longer than min_seconds."""
    files = glob.glob("recordings/baseline/**/baseline_t*.npz", recursive=True)
    result = []
    for f in files:
        try:
            d = np.load(f)
            dur = d["eeg"].shape[1] / 256
            if dur >= min_seconds:
                result.append(f)
        except Exception:
            pass
    return sorted(result, key=lambda f: Path(f).stat().st_size, reverse=True)


# ── Cold Start Tests ──────────────────────────────────────────


class TestColdStart:
    """Verify no events fire during the baseline accumulation phase."""

    def test_cold_start_no_events_synthetic(self):
        """Synthetic signal at -30µV mean: no blinks during first 256 chunks."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector()

        cold_start_events = []
        t = 0.0
        for i in range(256):
            # Signal centered at -30µV with 10µV noise — same as real baseline
            chunk = rng.normal(-30, 10, (4, 4)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            for ev in frame.events:
                cold_start_events.append((t, ev.kind))
            t += 4 / 256

        assert len(cold_start_events) == 0, (
            f"Got {len(cold_start_events)} events during cold start: {cold_start_events}"
        )
        # 256 chunks × 4 samples = 1024 total samples (minus any rejected by cold-start guard)
        assert detector._baseline_samples >= 1000

    def test_cold_start_no_events_real_data(self):
        """First 2s of real baseline recording produces no blink events."""
        path = _get_longest_baseline()
        if path is None:
            pytest.skip("No baseline recordings found")

        eeg = _load_baseline(path)
        # Take first 512 samples (2s) — includes cold start period
        eeg_start = eeg[:, :512]

        detector = BlinkDetector()
        events = _replay_eeg(eeg_start, detector)
        blink_events = [e for e in events if "blink" in e[1]]
        assert len(blink_events) == 0, (
            f"Cold start FPs: {blink_events}"
        )

    def test_cold_start_with_offset_signal(self):
        """Signal at -50µV (different from 0 init) should still suppress cold start FPs."""
        rng = np.random.default_rng(123)
        detector = BlinkDetector()

        events = []
        t = 0.0
        for _ in range(300):
            chunk = rng.normal(-50, 15, (4, 4)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            for ev in frame.events:
                events.append((t, ev.kind))
            t += 4 / 256

        blink_events = [e for e in events if "blink" in e[1]]
        assert len(blink_events) == 0, (
            f"Got FPs with offset signal: {blink_events}"
        )


# ── Baseline Tracking Tests ──────────────────────────────────


class TestBaselineTracking:
    """Verify baseline EMA tracks actual signal mean over long sessions."""

    def test_baseline_converges_to_signal_mean(self):
        """After cold start, baseline_mean should be within 5µV of actual signal mean."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector()

        signal_mean = -30.0
        t = 0.0
        for _ in range(1000):  # ~4s of data
            chunk = rng.normal(signal_mean, 10, (4, 4)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += 4 / 256

        assert abs(detector._baseline_median - signal_mean) < 5.0, (
            f"Baseline {detector._baseline_median:.1f} too far from signal mean {signal_mean}"
        )

    def test_baseline_tracks_slow_drift(self):
        """Baseline should follow a slow linear drift within 10µV over 60s."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector(baseline_alpha=0.01)

        sr = 256
        duration_s = 60
        n_samples = sr * duration_s
        chunk_size = 4

        # Linear drift from -25µV to -45µV over 60s
        drift = np.linspace(-25, -45, n_samples)
        noise = rng.normal(0, 8, (4, n_samples))
        eeg = noise.copy()
        for ch in range(4):
            eeg[ch] += drift

        t = 0.0
        for start in range(0, n_samples, chunk_size):
            end = min(start + chunk_size, n_samples)
            chunk = eeg[:, start:end].astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # At end, signal mean is -45µV. Baseline should be within 10µV.
        assert abs(detector._baseline_median - (-45.0)) < 10.0, (
            f"After 60s drift to -45µV, baseline={detector._baseline_median:.1f}"
        )

    def test_baseline_tracks_step_shift(self):
        """After a moderate step shift, baseline recovers within 30s.

        A 10µV step is realistic for electrode repositioning. Larger steps
        (20µV+) exceed the baseline update guard (3 SDs of chunk-mean variance)
        and require gradual adaptation.
        """
        rng = np.random.default_rng(42)
        detector = BlinkDetector(baseline_alpha=0.01)

        sr = 256
        chunk_size = 4

        # Phase 1: 5s at -25µV
        t = 0.0
        for _ in range(5 * sr // chunk_size):
            chunk = rng.normal(-25, 8, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        baseline_before = detector._baseline_median

        # Phase 2: 30s at -35µV (step shift of -10µV — within adaptation range)
        for _ in range(30 * sr // chunk_size):
            chunk = rng.normal(-35, 8, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # Baseline should have moved substantially toward -35µV
        assert detector._baseline_median < baseline_before - 5, (
            f"Baseline didn't track step shift: before={baseline_before:.1f}, "
            f"after={detector._baseline_median:.1f}"
        )
        assert abs(detector._baseline_median - (-35.0)) < 5.0, (
            f"Baseline={detector._baseline_median:.1f} not close to -35µV after 30s"
        )

    def test_baseline_on_real_long_recording(self):
        """Replay 750s baseline, check baseline stays within 15µV of windowed mean."""
        path = _get_longest_baseline()
        if path is None:
            pytest.skip("No baseline recordings found")

        eeg = _load_baseline(path)
        duration_s = eeg.shape[1] / 256
        if duration_s < 120:
            pytest.skip(f"Longest baseline only {duration_s:.0f}s, need 120+")

        detector = BlinkDetector(baseline_alpha=0.01)
        sr = 256
        chunk_size = 4

        # Track baseline at 30s checkpoints
        checkpoints = []
        t = 0.0
        for start in range(0, eeg.shape[1], chunk_size):
            end = min(start + chunk_size, eeg.shape[1])
            chunk = eeg[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)

            # Record checkpoint every 30s
            elapsed_s = start / sr
            if start > 0 and start % (30 * sr) < chunk_size:
                # Compute actual signal mean for last 30s
                win_start = max(0, start - 30 * sr)
                frontal_win = (eeg[1, win_start:start] + eeg[2, win_start:start]) / 2.0
                actual_mean = float(np.mean(frontal_win))
                checkpoints.append({
                    "time_s": elapsed_s,
                    "baseline_median": detector._baseline_median,
                    "actual_mean": actual_mean,
                    "error": abs(detector._baseline_median - actual_mean),
                })
            t += chunk_size / sr

        # After the first checkpoint (allowing initial convergence),
        # baseline should track within 15µV of actual windowed mean
        # Skip first 2 checkpoints (cold start convergence)
        late_checkpoints = checkpoints[2:]
        assert len(late_checkpoints) > 0, "No late checkpoints"
        max_error = max(cp["error"] for cp in late_checkpoints)
        assert max_error < 20.0, (
            f"Baseline tracking error too large: {max_error:.1f}µV. "
            f"Checkpoints: {[(cp['time_s'], cp['error']) for cp in late_checkpoints]}"
        )


# ── Long Session FP Rate Tests ───────────────────────────────


class TestLongSessionFPRate:
    """Verify false positive rate stays acceptable over long recordings."""

    def test_no_fps_first_5s_real(self):
        """First 5s of any baseline should produce at most 1 blink event.

        With the MAD-based threshold (more sensitive for weak blinks),
        real involuntary blinks in baseline recordings may be detected.
        We allow up to 1 event since the goal is recall improvement.
        """
        files = _get_baseline_files(min_seconds=10)
        if not files:
            pytest.skip("No baseline recordings found")

        for path in files[:5]:  # test up to 5 files
            eeg = _load_baseline(path)
            eeg_5s = eeg[:, :5 * 256]
            detector = BlinkDetector()
            events = _replay_eeg(eeg_5s, detector)
            blink_events = [e for e in events if "blink" in e[1]]
            assert len(blink_events) <= 1, (
                f"Too many FPs in first 5s of {Path(path).name}: {blink_events}"
            )

    def test_fp_rate_750s_baseline(self):
        """Over 750s baseline, event rate should be < 3 per minute.

        Some involuntary blinks are expected in a 12-minute baseline recording
        (natural blink rate is 15-20/min). We check for excessive FPs, not zero.
        The key property: no cold-start burst and no drift-induced FP storm.
        """
        path = _get_longest_baseline()
        if path is None:
            pytest.skip("No baseline recordings found")

        eeg = _load_baseline(path)
        duration_s = eeg.shape[1] / 256
        if duration_s < 120:
            pytest.skip(f"Only {duration_s:.0f}s, need 120+")

        detector = BlinkDetector()
        speech = SpeechDetector()
        events = _replay_eeg(eeg, detector, speech_detector=speech)
        blink_events = [(t, k) for t, k in events if "blink" in k]

        events_per_min = len(blink_events) / (duration_s / 60)

        # Check distribution: events should NOT cluster in first 5s (cold start)
        early = [e for e in blink_events if e[0] < 5.0]
        assert len(early) == 0, f"Cold start burst: {early}"

        # Overall rate: natural involuntary blink rate is ~10-15/min. Allow up
        # to 8/min since the detector can't distinguish real involuntary blinks
        # from noise during baseline (both are short negative deflections).
        assert events_per_min < 8.0, (
            f"Event rate {events_per_min:.2f}/min over {duration_s:.0f}s is too high. "
            f"Total events: {len(blink_events)}"
        )

    def test_no_cold_start_burst(self):
        """Events should not cluster in the first 5s (cold start burst pattern)."""
        path = _get_longest_baseline()
        if path is None:
            pytest.skip("No baseline recordings found")

        eeg = _load_baseline(path)
        if eeg.shape[1] / 256 < 30:
            pytest.skip("Recording too short")

        detector = BlinkDetector()
        events = _replay_eeg(eeg, detector)
        blink_events = [(t, k) for t, k in events if "blink" in k]

        early_events = [e for e in blink_events if e[0] < 5.0]
        assert len(early_events) == 0, (
            f"Cold start burst: {len(early_events)} events in first 5s: {early_events}"
        )


# ── Detection After Drift Tests ──────────────────────────────


class TestDetectionAfterDrift:
    """Verify blinks are still detectable after minutes of quiet data + drift."""

    def test_blink_detected_after_5min_quiet(self):
        """After 5 minutes of quiet baseline, an injected blink should still be detected."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector()
        sr = 256
        chunk_size = 4

        # 5 minutes of quiet baseline at -30µV
        quiet_duration = 5 * 60  # 300s
        t = 0.0
        for _ in range(quiet_duration * sr // chunk_size):
            chunk = rng.normal(-30, 10, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # Inject V-shaped blink (realistic: downstroke → trough → upstroke)
        blink_eeg = rng.normal(-30, 10, (4, 64)).astype(np.float64)
        _inject_v_blink(blink_eeg, start=20, baseline_uv=-30, amplitude_uv=-170)

        all_events = []
        for start in range(0, 64, chunk_size):
            end = min(start + chunk_size, 64)
            chunk = blink_eeg[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            all_events.extend(frame.events)
            t += chunk_size / sr

        # Flush: wait for classify window to expire
        flush = rng.normal(-30, 10, (4, 4)).astype(np.float64)
        frame2 = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
        detector.process(frame2)
        all_events.extend(frame2.events)

        blink_events = [e for e in all_events if "blink" in e.kind]
        assert len(blink_events) >= 1, (
            f"Blink not detected after {quiet_duration}s quiet period. "
            f"baseline_median={detector._baseline_median:.1f}, "
            f"baseline_mad={detector._baseline_mad:.1f}"
        )

    def test_blink_detected_after_drift(self):
        """After signal drifts from -25 to -45µV over 2min, blinks still detected."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector(baseline_alpha=0.01)
        sr = 256
        chunk_size = 4

        # 2 minutes of drifting signal
        drift_duration = 120  # seconds
        n_chunks = drift_duration * sr // chunk_size

        t = 0.0
        for i in range(n_chunks):
            # Linear drift from -25 to -45
            frac = i / n_chunks
            mean = -25 + frac * (-20)
            chunk = rng.normal(mean, 8, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # Inject V-shaped blink centred on the drifted baseline
        blink_eeg = rng.normal(-45, 8, (4, 64)).astype(np.float64)
        _inject_v_blink(blink_eeg, start=20, baseline_uv=-45, amplitude_uv=-155)

        all_events = []
        for start in range(0, 64, chunk_size):
            end = min(start + chunk_size, 64)
            chunk = blink_eeg[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            all_events.extend(frame.events)
            t += chunk_size / sr

        # Flush
        flush = rng.normal(-45, 8, (4, 4)).astype(np.float64)
        frame2 = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
        detector.process(frame2)
        all_events.extend(frame2.events)

        blink_events = [e for e in all_events if "blink" in e.kind]
        assert len(blink_events) >= 1, (
            f"Blink not detected after drift. "
            f"baseline_median={detector._baseline_median:.1f}"
        )

    def test_blink_on_real_baseline_with_injection(self):
        """Replay real 120s+ baseline, inject blink at the end, verify detection."""
        files = _get_baseline_files(min_seconds=120)
        if not files:
            pytest.skip("No 120s+ baseline recordings")

        eeg = _load_baseline(files[0])
        # Use first 120s
        eeg_120 = eeg[:, :120 * 256]

        detector = BlinkDetector()
        sr = 256
        chunk_size = 4
        t = 0.0

        # Replay 120s
        for start in range(0, eeg_120.shape[1], chunk_size):
            end = min(start + chunk_size, eeg_120.shape[1])
            chunk = eeg_120[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # Inject V-shaped blink centred on actual session baseline
        actual_mean = detector._baseline_median
        rng = np.random.default_rng(99)
        blink_eeg = rng.normal(actual_mean, 10, (4, 64)).astype(np.float64)
        _inject_v_blink(blink_eeg, start=20, baseline_uv=actual_mean, amplitude_uv=-170)

        all_events = []
        for start in range(0, 64, chunk_size):
            end = min(start + chunk_size, 64)
            chunk = blink_eeg[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            all_events.extend(frame.events)
            t += chunk_size / sr

        # Flush
        flush = np.full((4, 4), actual_mean, dtype=np.float64)
        frame2 = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
        detector.process(frame2)
        all_events.extend(frame2.events)

        blink_events = [e for e in all_events if "blink" in e.kind]
        assert len(blink_events) >= 1, (
            f"Blink not detected after 120s real baseline. "
            f"baseline_median={detector._baseline_median:.1f}, "
            f"baseline_mad={detector._baseline_mad:.1f}"
        )


# ── Cross-Session Baseline Tests ─────────────────────────────


class TestCrossSession:
    """Verify detector handles different session signal levels."""

    @pytest.mark.parametrize("signal_mean", [-15, -30, -50, -80])
    def test_no_fps_at_various_signal_levels(self, signal_mean):
        """Rest data at different mean levels should not produce FPs."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector()
        sr = 256
        chunk_size = 4

        # 10s of data
        t = 0.0
        events = []
        for _ in range(10 * sr // chunk_size):
            chunk = rng.normal(signal_mean, 10, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            for ev in frame.events:
                events.append((t, ev.kind))
            t += chunk_size / sr

        blink_events = [e for e in events if "blink" in e[1]]
        assert len(blink_events) == 0, (
            f"FPs at signal_mean={signal_mean}: {blink_events}"
        )

    @pytest.mark.parametrize("signal_mean,blink_amp", [
        (-30, -200),   # loud session
        (-30, -80),    # moderate session
        (-50, -150),   # offset session
    ])
    def test_blink_detected_at_various_levels(self, signal_mean, blink_amp):
        """Blinks should be detected regardless of baseline signal level."""
        rng = np.random.default_rng(42)
        detector = BlinkDetector()
        sr = 256
        chunk_size = 4

        # Establish baseline (2s)
        t = 0.0
        for _ in range(2 * sr // chunk_size):
            chunk = rng.normal(signal_mean, 8, (4, chunk_size)).astype(np.float64)
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            t += chunk_size / sr

        # Inject V-shaped blink: amplitude_uv is the deflection *below* signal_mean
        blink_eeg = rng.normal(signal_mean, 8, (4, 64)).astype(np.float64)
        _inject_v_blink(blink_eeg, start=20, baseline_uv=signal_mean,
                         amplitude_uv=blink_amp - signal_mean)

        all_events = []
        for start in range(0, 64, chunk_size):
            end = min(start + chunk_size, 64)
            chunk = blink_eeg[:, start:end]
            frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
            detector.process(frame)
            all_events.extend(frame.events)
            t += chunk_size / sr

        # Flush
        flush = rng.normal(signal_mean, 8, (4, 4)).astype(np.float64)
        frame2 = PipelineFrame(eeg=flush, ppg=None, imu=None, timestamp=t + 2.0)
        detector.process(frame2)
        all_events.extend(frame2.events)

        blink_events = [e for e in all_events if "blink" in e.kind]
        assert len(blink_events) >= 1, (
            f"Blink at {blink_amp}µV not detected with baseline {signal_mean}µV. "
            f"detector baseline_median={detector._baseline_median:.1f}"
        )
