"""Translate pipeline results to the WebSocket JSON format the frontend expects.

This is the ONLY place that maps stage results → dashboard JSON keys.
When adding a new stage whose output should appear on the dashboard,
add one `if` block here.
"""
from __future__ import annotations

from backend.pipeline.stages.detectors import ClenchResult
from backend.pipeline.stages.features import (
    BandPowerResult,
    HeadMotionResult,
    HeartRateResult,
    SignalQualityResult,
)
from backend.pipeline.types import PipelineFrame


def frame_to_metrics(frame: PipelineFrame) -> dict:
    metrics: dict = {}

    bp = frame.get(BandPowerResult)
    sq = frame.get(SignalQualityResult)
    if bp or sq:
        eeg: dict = {}
        if bp:
            eeg["band_powers"] = bp.band_powers
            eeg["theta_beta_ratio"] = bp.theta_beta_ratio
            eeg["frontal_alpha_asymmetry"] = bp.frontal_alpha_asymmetry
        if sq:
            eeg["signal_quality"] = sq.quality
            eeg["fit_status"] = sq.fit_status
        metrics["eeg"] = eeg

    hr = frame.get(HeartRateResult)
    if hr:
        metrics["ppg"] = {
            "heart_rate_bpm": hr.heart_rate_bpm,
            "spo2_percent": hr.spo2_percent,
            "hrv_rmssd_ms": hr.hrv_rmssd_ms,
        }

    hm = frame.get(HeadMotionResult)
    if hm:
        cl = frame.get(ClenchResult)
        metrics["imu"] = {
            "head_movement": hm.head_movement,
            "head_pose": {"pitch": hm.head_pose[0], "roll": hm.head_pose[1]},
            "motion_artifact": hm.motion_artifact,
            "jaw_clench": cl.jaw_clench if cl else False,
        }

    return metrics
