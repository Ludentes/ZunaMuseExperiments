import numpy as np
from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.preprocessing import PreprocessingResult
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    BandPowerResult,
    SignalQualityChecker,
    SignalQualityResult,
    HeartRateExtractor,
    HeartRateResult,
    HeadMotionExtractor,
    HeadMotionResult,
)


def _make_eeg_frame(n_samples: int = 512) -> PipelineFrame:
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, n_samples)).astype(np.float64) * 50
    return PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)


def test_band_power_from_raw_eeg():
    frame = _make_eeg_frame(512)
    BandPowerExtractor().process(frame)
    bp = frame.get(BandPowerResult)
    assert bp is not None
    assert "alpha" in bp.band_powers
    assert len(bp.band_powers["alpha"]) == 4
    assert len(bp.theta_beta_ratio) == 4
    assert isinstance(bp.frontal_alpha_asymmetry, float)


def test_band_power_prefers_filtered():
    frame = _make_eeg_frame(512)
    filtered = frame.eeg.copy()
    frame.set(PreprocessingResult(eeg_filtered=filtered))
    BandPowerExtractor().process(frame)
    assert frame.get(BandPowerResult) is not None


def test_band_power_skips_short_data():
    frame = _make_eeg_frame(32)
    BandPowerExtractor().process(frame)
    assert frame.get(BandPowerResult) is None


def test_signal_quality_good():
    frame = _make_eeg_frame(256)
    SignalQualityChecker().process(frame)
    sq = frame.get(SignalQualityResult)
    assert sq is not None
    assert len(sq.quality) == 4
    assert sq.fit_status in ("good", "adjust", "poor")
    for q in sq.quality.values():
        assert 0.0 <= q <= 1.0


def test_signal_quality_railed():
    eeg = np.full((4, 256), 999.0)
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)
    SignalQualityChecker().process(frame)
    sq = frame.get(SignalQualityResult)
    assert sq is not None
    assert sq.fit_status == "poor"


def test_signal_quality_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    SignalQualityChecker().process(frame)
    assert frame.get(SignalQualityResult) is None


def test_heart_rate_needs_accumulation():
    rng = np.random.default_rng(42)
    ppg = rng.standard_normal((3, 128)).astype(np.float64)
    frame = PipelineFrame(eeg=None, ppg=ppg, imu=None, timestamp=0.0)
    stage = HeartRateExtractor()
    stage.process(frame)
    assert frame.get(HeartRateResult) is None


def test_heart_rate_accumulates():
    rng = np.random.default_rng(42)
    stage = HeartRateExtractor()
    for i in range(8):
        ppg = rng.standard_normal((3, 128)).astype(np.float64) * 1000
        frame = PipelineFrame(eeg=None, ppg=ppg, imu=None, timestamp=float(i))
        stage.process(frame)
    hr = frame.get(HeartRateResult)
    assert hr is not None
    assert isinstance(hr.heart_rate_bpm, float)


def test_heart_rate_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    HeartRateExtractor().process(frame)
    assert frame.get(HeartRateResult) is None


def test_head_motion_still():
    imu = np.array([
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 1.0, 1.0, 1.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ], dtype=np.float64)
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    hm = frame.get(HeadMotionResult)
    assert hm is not None
    assert hm.head_movement < 0.01
    assert not hm.motion_artifact


def test_head_motion_moving():
    imu = np.array([
        [0.0, 0.5, -0.3, 0.2],
        [0.0, 0.3, -0.1, 0.4],
        [1.0, 0.8, 1.2, 0.9],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 0.0],
    ], dtype=np.float64)
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    hm = frame.get(HeadMotionResult)
    assert hm is not None
    assert hm.head_movement > 0.1
    assert hm.motion_artifact


def test_head_motion_skips_none():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    assert frame.get(HeadMotionResult) is None


def test_head_motion_skips_single_sample():
    imu = np.zeros((6, 1))
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu, timestamp=0.0)
    HeadMotionExtractor().process(frame)
    assert frame.get(HeadMotionResult) is None


def test_concentration_scorer():
    frame = _make_eeg_frame(512)
    from backend.pipeline.stages.features import ConcentrationScorer, ConcentrationResult
    from backend.pipeline.stages.features import BandPowerExtractor
    # Need band powers first
    BandPowerExtractor().process(frame)
    scorer = ConcentrationScorer(use_raw_ratio=False)
    try:
        scorer.process(frame)
        cr = frame.get(ConcentrationResult)
        assert cr is not None
        assert 0.0 <= cr.concentration_score <= 1.0
        assert 0.0 <= cr.relaxation_score <= 1.0
    finally:
        scorer.release()


def test_concentration_raw_ratio_focused():
    """Low theta/beta ratio should produce high concentration."""
    from backend.pipeline.stages.features import ConcentrationScorer, ConcentrationResult
    frame = _make_eeg_frame(512)
    frame.set(BandPowerResult(
        band_powers={
            "delta": [100.0] * 4,
            "theta": [5.0, 5.0, 5.0, 5.0],
            "alpha": [10.0] * 4,
            "beta": [20.0, 20.0, 20.0, 20.0],
            "gamma": [5.0] * 4,
        },
        theta_beta_ratio=[0.25] * 4,
        frontal_alpha_asymmetry=0.0,
    ))
    scorer = ConcentrationScorer(use_raw_ratio=True)
    try:
        scorer.process(frame)
        cr = frame.get(ConcentrationResult)
        assert cr is not None
        assert cr.concentration_score > 0.6, f"Expected >0.6 for focused state, got {cr.concentration_score}"
    finally:
        scorer.release()


def test_concentration_raw_ratio_relaxed():
    """High theta/beta ratio should produce low concentration."""
    from backend.pipeline.stages.features import ConcentrationScorer, ConcentrationResult
    frame = _make_eeg_frame(512)
    frame.set(BandPowerResult(
        band_powers={
            "delta": [100.0] * 4,
            "theta": [40.0, 40.0, 40.0, 40.0],
            "alpha": [10.0] * 4,
            "beta": [5.0, 5.0, 5.0, 5.0],
            "gamma": [2.0] * 4,
        },
        theta_beta_ratio=[8.0] * 4,
        frontal_alpha_asymmetry=0.0,
    ))
    scorer = ConcentrationScorer(use_raw_ratio=True)
    try:
        scorer.process(frame)
        cr = frame.get(ConcentrationResult)
        assert cr is not None
        assert cr.concentration_score < 0.3, f"Expected <0.3 for relaxed state, got {cr.concentration_score}"
    finally:
        scorer.release()
