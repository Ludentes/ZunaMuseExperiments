from backend.pipeline.types import PipelineFrame
from backend.pipeline.stages.features import (
    BandPowerResult,
    SignalQualityResult,
    HeartRateResult,
    HeadMotionResult,
)
from backend.pipeline.stages.detectors import ClenchResult
from backend.pipeline.serialize import frame_to_metrics


def test_empty_frame_returns_empty():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    metrics = frame_to_metrics(frame)
    assert metrics == {}


def test_eeg_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(BandPowerResult(
        band_powers={"delta": [1.0, 2.0, 3.0, 4.0], "theta": [0.5]*4,
                     "alpha": [1.0]*4, "beta": [0.3]*4, "gamma": [0.1]*4},
        theta_beta_ratio=[1.5]*4,
        frontal_alpha_asymmetry=0.1,
    ))
    frame.set(SignalQualityResult(
        quality={"TP9": 0.9, "AF7": 0.8, "AF8": 0.85, "TP10": 0.95},
        fit_status="good",
    ))
    metrics = frame_to_metrics(frame)
    assert "eeg" in metrics
    assert metrics["eeg"]["band_powers"]["delta"] == [1.0, 2.0, 3.0, 4.0]
    assert metrics["eeg"]["fit_status"] == "good"
    assert metrics["eeg"]["signal_quality"]["TP9"] == 0.9


def test_ppg_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeartRateResult(heart_rate_bpm=72.0, spo2_percent=98.0, hrv_rmssd_ms=35.0))
    metrics = frame_to_metrics(frame)
    assert metrics["ppg"]["heart_rate_bpm"] == 72.0


def test_imu_metrics():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(5.0, -3.0), motion_artifact=False))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["head_movement"] == 0.02
    assert metrics["imu"]["head_pose"]["pitch"] == 5.0
    assert metrics["imu"]["motion_artifact"] is False


def test_imu_with_clench():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(0.0, 0.0), motion_artifact=False))
    frame.set(ClenchResult(jaw_clench=True))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["jaw_clench"] is True


def test_imu_jaw_clench_defaults_false():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadMotionResult(head_movement=0.02, head_pose=(0.0, 0.0), motion_artifact=False))
    metrics = frame_to_metrics(frame)
    assert metrics["imu"]["jaw_clench"] is False


from backend.pipeline.stages.features import EyesClosedResult


def test_serialize_eyes_closed_result():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(EyesClosedResult(eyes_closed=True, alpha_ratio=2.1, baseline_alpha=12.5))
    metrics = frame_to_metrics(frame)
    assert "eyes_closed" in metrics
    assert metrics["eyes_closed"]["active"] is True
    assert metrics["eyes_closed"]["alpha_ratio"] == 2.1


from backend.pipeline.stages.features import HeadbandStateResult


def test_serialize_headband_state_result():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HeadbandStateResult(state="ready", seconds_in_state=5.0))
    metrics = frame_to_metrics(frame)
    assert "headband" in metrics
    assert metrics["headband"]["state"] == "ready"
    assert metrics["headband"]["seconds_in_state"] == 5.0
