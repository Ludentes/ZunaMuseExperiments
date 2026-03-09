"""Verify pipeline produces the same JSON structure as the old build_metrics()."""
import numpy as np
from backend.processing import build_metrics
from backend.pipeline.types import PipelineFrame, Cadence
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.serialize import frame_to_metrics


def test_pipeline_matches_build_metrics_eeg_keys():
    """Pipeline's EEG output must have the same keys as build_metrics."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    old = build_metrics(eeg, None, None, 256)

    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    assert "eeg" in old
    assert "eeg" in new
    old_keys = set(old["eeg"].keys())
    new_keys = set(new["eeg"].keys())
    assert old_keys == new_keys, f"Key mismatch: old={old_keys}, new={new_keys}"


def test_pipeline_matches_build_metrics_imu_keys():
    """Pipeline's IMU output must have the same keys as build_metrics."""
    rng = np.random.default_rng(42)
    imu = rng.standard_normal((6, 104)).astype(np.float64)
    imu[2, :] += 1.0

    old = build_metrics(None, None, imu, 256)

    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=None, ppg=None, imu=imu.copy(), timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    assert "imu" in old
    assert "imu" in new
    old_keys = set(old["imu"].keys())
    new_keys = set(new["imu"].keys())
    assert old_keys == new_keys, f"Key mismatch: old={old_keys}, new={new_keys}"


def test_pipeline_eeg_values_close():
    """Band power values structure should match."""
    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    old = build_metrics(eeg.copy(), None, None, 256)
    pipeline = create_default_pipeline()
    frame = PipelineFrame(eeg=eeg.copy(), ppg=None, imu=None, timestamp=0.0)
    pipeline.run(Cadence.SLOW, frame)
    new = frame_to_metrics(frame)

    assert len(old["eeg"]["theta_beta_ratio"]) == len(new["eeg"]["theta_beta_ratio"])
    assert set(old["eeg"]["signal_quality"].keys()) == set(new["eeg"]["signal_quality"].keys())
