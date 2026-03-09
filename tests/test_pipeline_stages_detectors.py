import time
import numpy as np
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.detectors import (
    BlinkDetector,
    ClenchDetector,
    ClenchResult,
)


def test_blink_detector_no_blink_in_noise():
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 64)).astype(np.float64) * 20
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    detector = BlinkDetector()
    detector.process(frame)
    blink_events = [e for e in frame.events if "blink" in e.kind]
    assert len(blink_events) == 0


def test_blink_detector_detects_spike():
    eeg = np.zeros((4, 256), dtype=np.float64)
    rng = np.random.default_rng(42)
    eeg += rng.standard_normal((4, 256)) * 10
    eeg[1, 125:131] = -500.0
    eeg[2, 125:131] = -500.0

    now = time.time()
    detector = BlinkDetector()
    # First frame: spike is detected, peak is recorded
    frame1 = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=now)
    detector.process(frame1)

    # Second frame after refractory period: triggers event emission
    calm_eeg = rng.standard_normal((4, 64)).astype(np.float64) * 10
    frame2 = PipelineFrame(eeg=calm_eeg, ppg=None, imu=None, timestamp=now + 0.5)
    detector.process(frame2)

    all_events = frame1.events + frame2.events
    blink_events = [e for e in all_events if "blink" in e.kind]
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
