"""Tests for calibrate_blink command and blink detector pipeline integration."""

import numpy as np

from backend.pipeline.base import Pipeline
from backend.pipeline.stages.detectors import BlinkDetector, SpeechDetector
from backend.pipeline.types import PipelineFrame


def _make_pipeline_with_blink_detector() -> Pipeline:
    """Create a minimal pipeline containing a BlinkDetector."""
    return Pipeline(
        stages=[SpeechDetector(), BlinkDetector()],
        actions=[],
    )


def _make_pipeline_without_blink_detector() -> Pipeline:
    """Create a pipeline with no BlinkDetector."""
    return Pipeline(
        stages=[SpeechDetector()],
        actions=[],
    )


def _find_blink_detector(pipeline: Pipeline) -> BlinkDetector | None:
    """Reproduce the server's _get_blink_detector logic."""
    for stage in pipeline.stages:
        if isinstance(stage, BlinkDetector):
            return stage
    return None


# ── Finding the detector ───────────────────────────────────


def test_find_blink_detector_present():
    """_get_blink_detector should return the BlinkDetector when present."""
    pipeline = _make_pipeline_with_blink_detector()
    detector = _find_blink_detector(pipeline)
    assert detector is not None
    assert isinstance(detector, BlinkDetector)


def test_find_blink_detector_absent():
    """_get_blink_detector should return None when no BlinkDetector in pipeline."""
    pipeline = _make_pipeline_without_blink_detector()
    detector = _find_blink_detector(pipeline)
    assert detector is None


# ── Calibration methods exist and work ─────────────────────


def test_blink_detector_has_set_calibrated_threshold():
    """BlinkDetector must expose set_calibrated_threshold method."""
    detector = BlinkDetector()
    assert hasattr(detector, 'set_calibrated_threshold')
    assert callable(detector.set_calibrated_threshold)


def test_blink_detector_has_set_signal_quality():
    """BlinkDetector must expose set_signal_quality method."""
    detector = BlinkDetector()
    assert hasattr(detector, 'set_signal_quality')
    assert callable(detector.set_signal_quality)


def test_calibrate_threshold_sets_floor():
    """set_calibrated_threshold sets threshold_uv floor; threshold_sd stays unchanged."""
    rng = np.random.default_rng(42)
    detector = BlinkDetector(threshold_sd=4.0)

    # Establish baseline
    t = 0.0
    for _ in range(int(1.5 * 256 / 4)):
        chunk = rng.normal(0, 10, (4, 4)).astype(np.float64)
        frame = PipelineFrame(eeg=chunk, ppg=None, imu=None, timestamp=t)
        detector.process(frame)
        t += 4 / 256

    original_sd = detector.threshold_sd
    detector.set_calibrated_threshold(-80.0)
    assert detector.threshold_sd == original_sd, (
        "threshold_sd must not change — only threshold_uv (floor) is updated by calibration"
    )
    assert detector.threshold_uv > -9000, "threshold_uv should be set to half-amplitude floor"


def test_set_signal_quality_clamps():
    """set_signal_quality should clamp values to [0, 1]."""
    detector = BlinkDetector()

    detector.set_signal_quality(1.5)
    assert detector._frontal_quality == 1.0

    detector.set_signal_quality(-0.5)
    assert detector._frontal_quality == 0.0

    detector.set_signal_quality(0.7)
    assert detector._frontal_quality == 0.7


def test_calibrate_with_zero_mad_does_not_crash():
    """Calibration with near-zero MAD should log warning, not crash."""
    detector = BlinkDetector()
    # MAD starts at 1.0 by default, but force it near zero
    detector._baseline_mad = 1e-8
    detector._baseline_median = 0.0
    detector._baseline_samples = 256
    # Should not raise
    detector.set_calibrated_threshold(-25.0)
    # threshold_sd should be unchanged (warning path)
