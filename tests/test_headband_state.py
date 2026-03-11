"""Tests for HeadbandStateTracker pipeline stage.

State machine:
  fitting --(good fit 3s)--> ready
  ready   --(poor fit 1.5s)-> headband_off
  headband_off --(non-poor)--> fitting
"""
import time
import numpy as np

from backend.pipeline.stages.features import SignalQualityResult
from backend.pipeline.types import PipelineFrame


def _make_quality_frame(fit_status: str, qualities: dict[str, float] | None = None) -> PipelineFrame:
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=time.time())
    if qualities is None:
        if fit_status == "good":
            qualities = {"TP9": 0.9, "AF7": 0.9, "AF8": 0.9, "TP10": 0.9}
        elif fit_status == "adjust":
            qualities = {"TP9": 0.5, "AF7": 0.9, "AF8": 0.9, "TP10": 0.5}
        else:
            qualities = {"TP9": 0.1, "AF7": 0.1, "AF8": 0.1, "TP10": 0.1}
    frame.set(SignalQualityResult(quality=qualities, fit_status=fit_status))
    return frame


def test_headband_state_result_import():
    from backend.pipeline.stages.features import HeadbandStateResult
    r = HeadbandStateResult(state="ready", seconds_in_state=5.0)
    assert r.state == "ready"


def test_headband_state_tracker_import():
    from backend.pipeline.stages.features import HeadbandStateTracker
    stage = HeadbandStateTracker()
    assert stage.name == "headband_state_tracker"
    assert stage.cadence.value == "slow"


def test_starts_in_fitting():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    frame = _make_quality_frame("good")
    stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result is not None
    assert result.state == "fitting"


def test_transitions_to_ready_after_stable():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    base_time = 1000.0
    for i in range(8):  # 4s of good fit
        frame = _make_quality_frame("good")
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "ready"


def test_transitions_to_off_on_all_rail():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    base_time = 1000.0
    # First reach ready
    for i in range(8):
        frame = _make_quality_frame("good")
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)
    assert frame.get(HeadbandStateResult).state == "ready"

    # All channels go poor
    for i in range(4):  # 2s poor > 1.5s threshold
        frame = _make_quality_frame("poor")
        frame.timestamp = base_time + 5.0 + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "headband_off"


def test_off_to_fitting_on_signal_return():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    base_time = 1000.0
    # Force into headband_off
    stage._state = "headband_off"
    stage._state_entered = base_time

    # Signal returns
    frame = _make_quality_frame("adjust")
    frame.timestamp = base_time + 5.0
    stage.process(frame)
    assert frame.get(HeadbandStateResult).state == "fitting"


def test_adjust_does_not_become_ready():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    base_time = 1000.0
    for i in range(10):
        frame = _make_quality_frame("adjust")
        frame.timestamp = base_time + i * 0.5
        stage.process(frame)
    result = frame.get(HeadbandStateResult)
    assert result.state == "fitting"


def test_skips_without_quality():
    from backend.pipeline.stages.features import HeadbandStateTracker, HeadbandStateResult
    stage = HeadbandStateTracker()
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=0.0)
    stage.process(frame)
    assert frame.get(HeadbandStateResult) is None
