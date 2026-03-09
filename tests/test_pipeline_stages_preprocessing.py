import numpy as np
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.stages.preprocessing import (
    BandPassFilter,
    WaveletDenoiser,
    PreprocessingResult,
)


def _make_eeg_frame(n_samples: int = 512) -> PipelineFrame:
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, n_samples)).astype(np.float64) * 50
    return PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=0.0)


def test_bandpass_filter_produces_result():
    stage = BandPassFilter()
    assert stage.cadence == Cadence.SLOW
    frame = _make_eeg_frame(512)
    stage.process(frame)
    result = frame.get(PreprocessingResult)
    assert result is not None
    assert result.eeg_filtered.shape == (4, 512)


def test_bandpass_filter_does_not_mutate_input():
    frame = _make_eeg_frame(512)
    original = frame.eeg.copy()
    BandPassFilter().process(frame)
    np.testing.assert_array_equal(frame.eeg, original)


def test_bandpass_filter_skips_insufficient_data():
    frame = _make_eeg_frame(8)  # too few samples
    BandPassFilter().process(frame)
    assert frame.get(PreprocessingResult) is None


def test_bandpass_filter_skips_none_eeg():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    BandPassFilter().process(frame)
    assert frame.get(PreprocessingResult) is None


def test_wavelet_denoiser_produces_result():
    stage = WaveletDenoiser()
    assert stage.cadence == Cadence.SLOW
    frame = _make_eeg_frame(512)
    stage.process(frame)
    result = frame.get(PreprocessingResult)
    assert result is not None
    assert result.eeg_filtered.shape == (4, 512)
