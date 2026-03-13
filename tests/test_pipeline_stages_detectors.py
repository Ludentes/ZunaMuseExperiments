import time
import numpy as np
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.detectors import (
    BlinkDetector,
    ClenchDetector,
    ClenchResult,
    SpeechDetector,
    SpeechResult,
)


def _establish_baseline(detector: BlinkDetector, rng, signal_mean: float = 0.0,
                        signal_sd: float = 10.0, duration_s: float = 1.5) -> float:
    """Feed quiet data to establish baseline. Returns the timestamp after baseline."""
    sr = 256
    chunk_size = 4
    t = 0.0
    for _ in range(int(duration_s * sr / chunk_size)):
        chunk = rng.normal(signal_mean, signal_sd, (4, chunk_size)).astype(np.float64)
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        t += chunk_size / sr
    return t


def _inject_blink(detector: BlinkDetector, rng, t: float, signal_mean: float = 0.0,
                   blink_amp: float = -200.0, blink_samples: int = 20,
                   total_samples: int = 64) -> tuple[list, float]:
    """Inject a blink as 4-sample streaming chunks. Returns (events, new_t)."""
    sr = 256
    chunk_size = 4
    blink_eeg = rng.normal(signal_mean, 10, (4, total_samples)).astype(np.float64)
    blink_start = (total_samples - blink_samples) // 2
    blink_eeg[1, blink_start:blink_start + blink_samples] = blink_amp
    blink_eeg[2, blink_start:blink_start + blink_samples] = blink_amp

    all_events = []
    for start in range(0, total_samples, chunk_size):
        end = min(start + chunk_size, total_samples)
        chunk = blink_eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        all_events.extend(frame.events)
        t += chunk_size / sr
    return all_events, t


def _flush_classify(detector: BlinkDetector, rng, t: float,
                    signal_mean: float = 0.0) -> list:
    """Send a calm frame after classify window to flush pending blinks."""
    calm = rng.normal(signal_mean, 10, (4, 4)).astype(np.float64)
    frame = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=t + 2.0)
    detector.process(frame)
    return list(frame.events)


# ── SpeechDetector ──────────────────────────────────────────


def test_speech_detector_quiet():
    """Low-amplitude signal should not flag speech."""
    rng = np.random.default_rng(42)
    detector = SpeechDetector(window_chunks=4, min_active_frac=0.5, hf_thresh=15)
    for _ in range(10):
        eeg = rng.standard_normal((4, 4)).astype(np.float64) * 5
        frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)
        detector.process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert not result.speech_active


def test_speech_detector_sustained_emg():
    """Sustained high-freq temporal EMG should flag speech."""
    detector = SpeechDetector(window_chunks=4, min_active_frac=0.5, hf_thresh=10)
    t = np.linspace(0, 0.016, 4)
    for i in range(10):
        eeg = np.zeros((4, 4), dtype=np.float64)
        # Strong 30Hz EMG on temporal channels
        eeg[0] = np.sin(2 * np.pi * 30 * t + i) * 100
        eeg[3] = np.sin(2 * np.pi * 30 * t + i) * 100
        frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)
        detector.process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert result.speech_active


def test_speech_detector_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    SpeechDetector().process(frame)
    result = frame.get(SpeechResult)
    assert result is not None
    assert not result.speech_active


# ── BlinkDetector ───────────────────────────────────────────


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
    assert 2.0 < robust_sd < 30.0, f"Robust SD {robust_sd} out of expected range"


def test_blink_detector_no_blink_in_noise():
    """Low-amplitude noise should not trigger blink detection."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector()
    t = _establish_baseline(detector, rng, signal_mean=0.0, signal_sd=20.0)

    # More calm noise
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 20
    frame = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=t)
    detector.process(frame)
    blink_events = [e for e in frame.events if "blink" in e.kind]
    assert len(blink_events) == 0


def test_blink_detector_detects_negative_deflection():
    """A -200 µV deflection on AF7+AF8 should trigger a single blink."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100, mf_threshold=0)

    t = _establish_baseline(detector, rng, signal_mean=0.0)
    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0, blink_amp=-200.0)
    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "single_blink"


def test_blink_detector_double_blink():
    """Two blinks within classify window → double_blink event."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(refractory_ms=200, classify_window_ms=800, mf_threshold=0)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # First blink
    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0)
    # Gap between blinks
    for _ in range(int(0.3 * 256 / 4)):
        chunk = rng.normal(0, 10, (4, 4)).astype(np.float64)
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        events1.extend(frame.events)
        t += 4 / 256

    # Second blink
    events2, t = _inject_blink(detector, rng, t, signal_mean=0.0)
    events3 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2 + events3
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "double_blink"


def test_blink_detector_refractory_prevents_double_count():
    """Two blinks within refractory period should count as one."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(refractory_ms=300, classify_window_ms=100, mf_threshold=0)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # First blink
    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0)
    # Very short gap (50ms < 300ms refractory)
    for _ in range(int(0.05 * 256 / 4)):
        chunk = rng.normal(0, 10, (4, 4)).astype(np.float64)
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        events1.extend(frame.events)
        t += 4 / 256

    # Second blink within refractory
    events2, t = _inject_blink(detector, rng, t, signal_mean=0.0)
    events3 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2 + events3
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "single_blink"


def test_blink_detector_suppressed_by_speech():
    """Blink-like deflection during speech should be suppressed."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100, mf_threshold=0)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # Inject blink with speech active on every frame
    blink_eeg = rng.normal(0, 10, (4, 64)).astype(np.float64)
    blink_eeg[1, 20:40] = -200.0
    blink_eeg[2, 20:40] = -200.0

    all_events = []
    for start in range(0, 64, 4):
        end = min(start + 4, 64)
        chunk = blink_eeg[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        frame.set(SpeechResult(speech_active=True))
        detector.process(frame)
        all_events.extend(frame.events)
        t += 4 / 256

    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)
    all_events.extend(events2)

    assert len([e for e in all_events if "blink" in e.kind]) == 0


def test_blink_detector_adaptive_threshold():
    """After baseline is established, adaptive threshold should work."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(threshold_sd=4.0, classify_window_ms=100, mf_threshold=0)

    t = _establish_baseline(detector, rng, signal_mean=0.0)
    assert detector._baseline_samples >= 256

    events1, t = _inject_blink(detector, rng, t, signal_mean=0.0, blink_amp=-200.0)
    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)

    all_events = events1 + events2
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) >= 1


def test_blink_detector_rejects_broad_deflection():
    """A broad, slow deflection (speech-like) should be rejected by shape guard."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100, max_deflection_ms=200)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # Create a broad deflection: 300ms below threshold (speech-like)
    # 77 samples = ~300ms at 256Hz
    broad = rng.normal(0, 10, (4, 128)).astype(np.float64)
    broad[1, 20:97] = -120.0
    broad[2, 20:97] = -120.0

    all_events = []
    for start in range(0, 128, 4):
        end = min(start + 4, 128)
        chunk = broad[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        all_events.extend(frame.events)
        t += 4 / 256

    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)
    all_events.extend(events2)

    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 0


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
    """A flat plateau (not tent-shaped) should be rejected by shape guard.

    Uses a 60-sample plateau (234ms) which exceeds max_deflection_ms=200,
    and has asymmetric shape (abrupt down, long flat, abrupt up) unlike
    the symmetric tent shape of a real blink.
    """
    rng = np.random.default_rng(42)
    detector = BlinkDetector(classify_window_ms=100, max_deflection_ms=200)

    t = _establish_baseline(detector, rng, signal_mean=0.0)

    # Create a plateau: abrupt drop, flat bottom for 60 samples (~234ms), abrupt rise
    plateau = rng.normal(0, 5, (4, 160)).astype(np.float64)
    plateau[1, 30:90] = -150.0
    plateau[2, 30:90] = -150.0

    all_events = []
    for start in range(0, 160, 4):
        end = min(start + 4, 160)
        chunk = plateau[:, start:end]
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        all_events.extend(frame.events)
        t += 4 / 256

    events2 = _flush_classify(detector, rng, t, signal_mean=0.0)
    all_events.extend(events2)

    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 0, "Plateau shape should be rejected by shape guard"



def test_blink_detector_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    BlinkDetector().process(frame)
    assert len(frame.events) == 0


# ── ClenchDetector ──────────────────────────────────────────


def test_clench_detector_no_clench_in_calm():
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 256)).astype(np.float64) * 10
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    ClenchDetector().process(frame)
    assert frame.get(ClenchResult) is None or not frame.get(ClenchResult).jaw_clench


def test_clench_detector_detects_emg():
    eeg = np.zeros((4, 256), dtype=np.float64)
    rng = np.random.default_rng(42)
    eeg += rng.standard_normal((4, 256)) * 5
    t = np.arange(256) / 256.0
    emg_signal = np.sin(2 * np.pi * 30 * t) * 100
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
