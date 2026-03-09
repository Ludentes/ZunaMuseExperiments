"""Pipeline assembly.

To swap a stage: change one line.
To add a stage: append one line + write the stage file.
"""
from __future__ import annotations

from backend.pipeline.actions.log import LogAction
from backend.pipeline.base import Pipeline
from backend.pipeline.stages.detectors import BlinkDetector, ClenchDetector
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
from backend.pipeline.stages.preprocessing import BandPassFilter


def create_default_pipeline() -> Pipeline:
    stages = [
        # SLOW — spectral features, vitals
        BandPassFilter(lowcut=1.0, highcut=45.0),
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        # FAST — event detection
        BlinkDetector(),
        ClenchDetector(),
    ]
    actions = [
        LogAction(),
    ]
    return Pipeline(stages, actions)
