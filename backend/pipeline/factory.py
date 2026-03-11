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
    EyesClosedDetector,
    HeadbandStateTracker,
    HeadMotionExtractor,
    HeartRateExtractor,
    SignalQualityChecker,
)
from backend.pipeline.stages.band_power_broadcaster import BandPowerBroadcaster
from backend.pipeline.stages.preprocessing import WaveletDenoiser


def create_default_pipeline(
    zuna_enabled: bool = False,
    zuna_device: str = "cuda",
    zuna_diffusion_steps: int = 50,
) -> Pipeline:
    stages: list = [
        # SLOW — spectral features, vitals
        WaveletDenoiser(),
    ]

    # ZUNA: insert before band power extraction so it can replace 4ch with 23ch
    if zuna_enabled:
        from backend.pipeline.stages.zuna import ZunaStage
        stages.append(ZunaStage(device=zuna_device, diffusion_steps=zuna_diffusion_steps))

    stages.extend([
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeadbandStateTracker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
        EyesClosedDetector(),
        BandPowerBroadcaster(),
        # FAST — event detection (SpeechDetector must precede BlinkDetector)
        SpeechDetector(),
        BlinkDetector(),
        # ClenchDetector(),  # disabled: needs tuning on real data
    ])
    actions = [
        LogAction(),
    ]
    return Pipeline(stages, actions)
