import numpy as np
from backend.pipeline.types import PipelineFrame, CH_NAMES
from backend.pipeline.stages.features import BandPowerResult
from backend.pipeline.stages.band_power_broadcaster import (
    BandPowerBroadcaster,
    BandPowerMessage,
)


def test_band_power_broadcaster_produces_message():
    """BandPowerBroadcaster reads BandPowerResult and produces BandPowerMessage."""
    stage = BandPowerBroadcaster()
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=1.0)

    # Simulate upstream BandPowerResult
    bp = BandPowerResult(
        band_powers={
            "delta": [4.1, 3.8, 3.5, 4.3],
            "theta": [5.2, 4.9, 5.1, 5.5],
            "alpha": [12.1, 6.5, 5.9, 13.2],
            "beta": [8.3, 7.1, 6.8, 9.1],
            "gamma": [2.1, 1.8, 1.9, 2.3],
        },
        theta_beta_ratio=[0.63, 0.69, 0.75, 0.60],
        frontal_alpha_asymmetry=0.1,
    )
    frame.set(bp)

    stage.process(frame)

    msg = frame.get(BandPowerMessage)
    assert msg is not None
    assert msg.mode == "4ch"
    assert "TP9" in msg.channels
    assert "AF7" in msg.channels
    assert "AF8" in msg.channels
    assert "TP10" in msg.channels
    assert msg.channels["TP9"]["delta"] == 4.1
    assert msg.channels["AF7"]["theta"] == 4.9
    assert msg.channels["TP10"]["gamma"] == 2.3


def test_band_power_broadcaster_skips_without_upstream():
    """No BandPowerResult upstream → no BandPowerMessage."""
    stage = BandPowerBroadcaster()
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=1.0)
    stage.process(frame)
    assert frame.get(BandPowerMessage) is None
