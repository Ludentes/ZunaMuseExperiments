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


def test_blink_detector_no_blink_in_noise():
    """Low-amplitude noise should not trigger blink detection."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 64)).astype(np.float64) * 20  # ±20 µV noise
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    detector = BlinkDetector()
    detector.process(frame)
    blink_events = [e for e in frame.events if "blink" in e.kind]
    assert len(blink_events) == 0


def test_blink_detector_detects_negative_deflection():
    """A -200 µV deflection on AF7+AF8 should trigger a single blink."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 256)).astype(np.float64) * 10  # ±10 µV background
    # Insert blink: large negative deflection on frontal channels
    eeg[1, 125:131] = -200.0
    eeg[2, 125:131] = -200.0

    now = time.time()
    detector = BlinkDetector(classify_window_ms=100, mf_threshold=0)

    # Frame with the blink — records pending blink
    frame1 = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=now)
    detector.process(frame1)

    # Frame after classify window expires — emits event
    calm_eeg = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame2 = PipelineFrame(eeg=calm_eeg, ppg=None, imu=None, timestamp=now + 0.2)
    detector.process(frame2)

    all_events = frame1.events + frame2.events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "single_blink"


def test_blink_detector_double_blink():
    """Two blinks within classify window → double_blink event."""
    rng = np.random.default_rng(42)
    now = time.time()
    detector = BlinkDetector(refractory_ms=200, classify_window_ms=800, mf_threshold=0)

    # First blink
    eeg1 = rng.standard_normal((4, 64)).astype(np.float64) * 10
    eeg1[1, 30:35] = -200.0
    eeg1[2, 30:35] = -200.0
    frame1 = PipelineFrame(eeg=eeg1, ppg=None, imu=None, timestamp=now)
    detector.process(frame1)

    # Second blink after refractory
    eeg2 = rng.standard_normal((4, 64)).astype(np.float64) * 10
    eeg2[1, 30:35] = -200.0
    eeg2[2, 30:35] = -200.0
    frame2 = PipelineFrame(eeg=eeg2, ppg=None, imu=None, timestamp=now + 0.4)
    detector.process(frame2)

    # After classify window
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame3 = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=now + 1.0)
    detector.process(frame3)

    all_events = frame1.events + frame2.events + frame3.events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "double_blink"


def test_blink_detector_refractory_prevents_double_count():
    """Two blinks within refractory period should count as one."""
    rng = np.random.default_rng(42)
    now = time.time()
    detector = BlinkDetector(refractory_ms=300, classify_window_ms=100, mf_threshold=0)

    # First blink
    eeg1 = rng.standard_normal((4, 64)).astype(np.float64) * 10
    eeg1[1, 30:35] = -200.0
    eeg1[2, 30:35] = -200.0
    frame1 = PipelineFrame(eeg=eeg1, ppg=None, imu=None, timestamp=now)
    detector.process(frame1)

    # Second blink within refractory (100ms < 300ms)
    eeg2 = rng.standard_normal((4, 64)).astype(np.float64) * 10
    eeg2[1, 30:35] = -200.0
    eeg2[2, 30:35] = -200.0
    frame2 = PipelineFrame(eeg=eeg2, ppg=None, imu=None, timestamp=now + 0.1)
    detector.process(frame2)

    # After classify window
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame3 = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=now + 0.3)
    detector.process(frame3)

    all_events = frame1.events + frame2.events + frame3.events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 1
    assert blink_events[0].kind == "single_blink"


def test_blink_detector_suppressed_by_speech():
    """Blink-like deflection during speech should be suppressed."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 64)).astype(np.float64) * 10
    eeg[1, 30:35] = -200.0
    eeg[2, 30:35] = -200.0

    now = time.time()
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=now)
    # Simulate speech detector having set speech_active
    frame.set(SpeechResult(speech_active=True))

    detector = BlinkDetector(classify_window_ms=100, mf_threshold=0)
    detector.process(frame)

    # After classify window
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame2 = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=now + 0.2)
    detector.process(frame2)

    all_events = frame.events + frame2.events
    assert len([e for e in all_events if "blink" in e.kind]) == 0


def test_blink_detector_adaptive_threshold():
    """After baseline is established, adaptive threshold should work."""
    rng = np.random.default_rng(42)
    now = time.time()
    detector = BlinkDetector(threshold_sd=4.0, classify_window_ms=100, mf_threshold=0)

    # Feed ~2s of calm baseline data to establish baseline
    for i in range(128):  # 128 chunks × 4 samples = 512 samples > 256 needed
        calm = rng.standard_normal((4, 4)).astype(np.float64) * 10
        frame = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=now + i * 0.016)
        detector.process(frame)

    assert detector._baseline_samples >= 128

    # A large deflection should still be detected
    blink_eeg = rng.standard_normal((4, 64)).astype(np.float64) * 10
    blink_eeg[1, 30:35] = -200.0
    blink_eeg[2, 30:35] = -200.0
    t_blink = now + 3.0
    frame_blink = PipelineFrame(eeg=blink_eeg, ppg=None, imu=None, timestamp=t_blink)
    detector.process(frame_blink)

    # After classify window
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame_after = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=t_blink + 0.2)
    detector.process(frame_after)

    all_events = frame_blink.events + frame_after.events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) >= 1


def test_blink_detector_rejects_broad_deflection():
    """A broad, slow deflection (speech-like) should be rejected by shape guard."""
    rng = np.random.default_rng(42)
    now = time.time()
    detector = BlinkDetector(classify_window_ms=100, max_deflection_ms=200)

    # Feed baseline
    for i in range(128):
        calm = rng.standard_normal((4, 4)).astype(np.float64) * 10
        frame = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=now + i * 0.016)
        detector.process(frame)

    # Create a broad deflection: 300ms below threshold (speech-like)
    broad = rng.standard_normal((4, 256)).astype(np.float64) * 10
    # Broad, sustained negative on frontal — 77 samples = 300ms at 256Hz
    broad[1, 50:127] = -120.0
    broad[2, 50:127] = -120.0
    t_broad = now + 3.0
    frame_broad = PipelineFrame(eeg=broad, ppg=None, imu=None, timestamp=t_broad)
    detector.process(frame_broad)

    # After classify window
    calm = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame_after = PipelineFrame(eeg=calm, ppg=None, imu=None, timestamp=t_broad + 0.2)
    detector.process(frame_after)

    all_events = frame_broad.events + frame_after.events
    blink_events = [e for e in all_events if "blink" in e.kind]
    assert len(blink_events) == 0


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
