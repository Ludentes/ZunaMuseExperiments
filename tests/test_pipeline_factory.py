from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.base import Pipeline
from backend.pipeline.types import Cadence


def test_create_default_pipeline():
    pipeline = create_default_pipeline()
    assert isinstance(pipeline, Pipeline)
    slow_stages = [s for s in pipeline.stages if s.cadence == Cadence.SLOW]
    fast_stages = [s for s in pipeline.stages if s.cadence == Cadence.FAST]
    assert len(slow_stages) >= 4  # bandpass, bandpower, signal_quality, head_motion
    assert len(fast_stages) >= 2  # speech_detector, blink_detector
    assert len(pipeline.actions) >= 1  # at least LogAction


def test_factory_includes_eyes_closed_detector():
    pipeline = create_default_pipeline()
    names = [s.name for s in pipeline.stages]
    assert "eyes_closed_detector" in names
    bp_idx = names.index("band_power_extractor")
    ec_idx = names.index("eyes_closed_detector")
    assert ec_idx > bp_idx
