from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter, NoiseTypes, WaveletTypes

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame


@dataclass
class PreprocessingResult:
    eeg_filtered: np.ndarray


class BandPassFilter(Stage):
    name = "bandpass_filter"
    cadence = Cadence.SLOW

    def __init__(
        self,
        lowcut: float = 1.0,
        highcut: float = 45.0,
        notch: NoiseTypes | None = NoiseTypes.FIFTY,
        order: int = 4,
        filter_type: int = 0,
    ):
        self.lowcut = lowcut
        self.highcut = highcut
        self.notch = notch
        self.order = order
        self.filter_type = filter_type

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < self.order * 3:
            return

        filtered = frame.eeg.copy().astype(np.float64)
        sr = 256  # Muse 2 EEG sample rate

        for ch in range(filtered.shape[0]):
            if self.notch is not None:
                DataFilter.remove_environmental_noise(
                    filtered[ch], sr, self.notch,
                )
            DataFilter.perform_bandpass(
                filtered[ch], sr, self.lowcut, self.highcut,
                self.order, self.filter_type, 0.0,
            )

        frame.set(PreprocessingResult(eeg_filtered=filtered))


class WaveletDenoiser(Stage):
    name = "wavelet_denoiser"
    cadence = Cadence.SLOW

    def __init__(
        self, wavelet: WaveletTypes = WaveletTypes.DB4, decomp_level: int = 4,
    ):
        self.wavelet = wavelet
        self.decomp_level = decomp_level

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 16:
            return

        filtered = frame.eeg.copy().astype(np.float64)
        for ch in range(filtered.shape[0]):
            DataFilter.perform_wavelet_denoising(
                filtered[ch], self.wavelet, self.decomp_level,
            )

        frame.set(PreprocessingResult(eeg_filtered=filtered))
