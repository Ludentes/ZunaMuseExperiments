from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.base import Pipeline
from backend.pipeline.types import Cadence


def test_create_default_pipeline():
    pipeline = create_default_pipeline()
    assert isinstance(pipeline, Pipeline)
    slow_stages = [s for s in pipeline.stages if s.cadence == Cadence.SLOW]
    fast_stages = [s for s in pipeline.stages if s.cadence == Cadence.FAST]
    assert len(slow_stages) >= 4  # bandpass, bandpower, signal_quality, head_motion
    assert len(fast_stages) >= 2  # blink, clench
    assert len(pipeline.actions) >= 1  # at least LogAction
