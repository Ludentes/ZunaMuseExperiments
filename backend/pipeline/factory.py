"""Pipeline assembly.

To swap a stage: change one line.
To add a stage: append one line + write the stage file.
"""
from __future__ import annotations

from backend.pipeline.actions.log import LogAction
from backend.pipeline.base import Pipeline
from backend.pipeline.stages.detectors import BlinkDetector, ClenchDetector, SpeechDetector
from backend.pipeline.stages.features import (
    BandPowerExtractor,
    ConcentrationScorer,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
from backend.pipeline.stages.preprocessing import WaveletDenoiser


def create_default_pipeline() -> Pipeline:
    stages = [
        # SLOW — spectral features, vitals
        WaveletDenoiser(),
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
        # FAST — event detection (SpeechDetector must precede BlinkDetector)
        SpeechDetector(),
        BlinkDetector(),
        # ClenchDetector(),  # disabled: needs tuning on real data
    ]
    actions = [
        LogAction(),
    ]
    return Pipeline(stages, actions)
