from dataclasses import dataclass, field
from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame, CH_NAMES
from backend.pipeline.stages.features import BandPowerResult

BAND_NAMES = ["delta", "theta", "alpha", "beta", "gamma"]


@dataclass
class BandPowerMessage:
    """Result type: per-channel band powers formatted for WebSocket."""
    mode: str  # "4ch" or "23ch"
    channels: dict[str, dict[str, float]] = field(default_factory=dict)


class BandPowerBroadcaster(Stage):
    """SLOW. Reads BandPowerResult, reformats as per-channel dict for heatmap."""

    name = "band_power_broadcaster"
    cadence = Cadence.SLOW

    def __init__(self, channel_names: list[str] | None = None):
        self.channel_names = channel_names or list(CH_NAMES)

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        channels = {}
        for i, ch_name in enumerate(self.channel_names):
            channels[ch_name] = {
                band: bp.band_powers[band][i]
                for band in BAND_NAMES
                if band in bp.band_powers and i < len(bp.band_powers[band])
            }

        mode = "4ch" if len(self.channel_names) <= 4 else "23ch"
        frame.set(BandPowerMessage(mode=mode, channels=channels))
