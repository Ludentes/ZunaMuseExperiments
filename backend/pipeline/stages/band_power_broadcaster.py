import logging
from dataclasses import dataclass, field

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame, CH_NAMES, BAND_NAMES
from backend.pipeline.stages.features import BandPowerResult

log = logging.getLogger(__name__)


@dataclass
class BandPowerMessage:
    """Result type: per-channel band powers formatted for WebSocket."""
    mode: str  # "4ch" or "23ch"
    channels: dict[str, dict[str, float]] = field(default_factory=dict)


class BandPowerBroadcaster(Stage):
    """SLOW. Reads BandPowerResult, reformats as per-channel dict for heatmap.

    Applies EMA smoothing to reduce frame-to-frame jitter from non-overlapping
    2s PSD windows. Without this, band powers jump wildly every 2s.
    """

    name = "band_power_broadcaster"
    cadence = Cadence.SLOW

    def __init__(
        self,
        channel_names: list[str] | None = None,
        ema_alpha: float = 0.3,
    ):
        self.channel_names = channel_names or list(CH_NAMES)
        self.ema_alpha = ema_alpha
        # EMA state: {ch_name: {band: smoothed_value}}
        self._smoothed: dict[str, dict[str, float]] = {}

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        channels = {}
        for i, ch_name in enumerate(self.channel_names):
            raw_vals = {
                band: bp.band_powers[band][i]
                for band in BAND_NAMES
                if band in bp.band_powers and i < len(bp.band_powers[band])
            }

            # EMA smooth each band per channel
            if ch_name not in self._smoothed:
                self._smoothed[ch_name] = dict(raw_vals)
            else:
                prev = self._smoothed[ch_name]
                for band, val in raw_vals.items():
                    old = prev.get(band, val)
                    prev[band] = self.ema_alpha * val + (1 - self.ema_alpha) * old
                    raw_vals[band] = round(prev[band], 2)

            channels[ch_name] = raw_vals

        mode = "4ch" if len(self.channel_names) <= 4 else "23ch"
        frame.set(BandPowerMessage(mode=mode, channels=channels))

        # Log for debugging jerkiness
        if channels:
            sample_ch = next(iter(channels))
            sample = channels[sample_ch]
            log.info(
                "band_powers [%s] α=%.1f θ=%.1f β=%.1f (smoothed, ema=%.1f)",
                sample_ch,
                sample.get("alpha", 0),
                sample.get("theta", 0),
                sample.get("beta", 0),
                self.ema_alpha,
            )
