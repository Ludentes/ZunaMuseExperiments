"""Tests for EyesClosedDetector pipeline stage."""
import time

import numpy as np

from backend.pipeline.stages.features import BandPowerResult
from backend.pipeline.types import PipelineFrame


def _make_frame_with_alpha(frontal_alpha: float, other_alpha: float = 10.0) -> PipelineFrame:
    """Build a PipelineFrame with BandPowerResult pre-populated."""
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
    base_time = 1000.0
    # Establish baseline with normal alpha
    for i in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)
    baseline = frame.get(EyesClosedResult).baseline_alpha

    # Send high alpha (3x baseline) for >1.5s (4 ticks at 0.5s = 2s)
    for i in range(4):
        frame = _make_frame_with_alpha(frontal_alpha=baseline * 3.0)
        frame.timestamp = base_time + 5.0 + i * 0.5
        stage.process(frame)
    result = frame.get(EyesClosedResult)
    assert result.eyes_closed is True


def test_hysteresis_prevents_flicker():
    """Once eyes_closed, should stay closed until alpha drops below lower threshold."""
    from backend.pipeline.stages.features import EyesClosedDetector, EyesClosedResult
    stage = EyesClosedDetector()
    base_time = 1000.0
    # Establish baseline
    for i in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)

    # Trigger eyes closed (3x baseline for 2s)
    for i in range(4):
        frame = _make_frame_with_alpha(frontal_alpha=30.0)
        frame.timestamp = base_time + 5.0 + i * 0.5
        stage.process(frame)
    assert frame.get(EyesClosedResult).eyes_closed is True

    # Alpha drops to 1.5x baseline -- between thresholds, should stay closed
    frame = _make_frame_with_alpha(frontal_alpha=15.0)
    frame.timestamp = base_time + 8.0
    stage.process(frame)
    assert frame.get(EyesClosedResult).eyes_closed is True

    # Alpha drops below 1.3x baseline -- should open
    frame = _make_frame_with_alpha(frontal_alpha=8.0)
    frame.timestamp = base_time + 9.0
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
    base_time = 1000.0
    for i in range(10):
        frame = _make_frame_with_alpha(frontal_alpha=10.0)
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)
    # Double the alpha
    frame = _make_frame_with_alpha(frontal_alpha=20.0)
    frame.timestamp = base_time + 6.0
    stage.process(frame)
    result = frame.get(EyesClosedResult)
    assert result is not None
    assert result.alpha_ratio > 1.5  # should be ~2.0
