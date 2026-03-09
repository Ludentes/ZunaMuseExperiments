from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, Event, PipelineFrame


@dataclass
class ClenchResult:
    jaw_clench: bool


class BlinkDetector(Stage):
    name = "blink_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        z_threshold: float = 3.5,
        refractory_ms: float = 300,
        double_window_ms: float = 600,
        triple_window_ms: float = 900,
        window_size: int = 512,
    ):
        self.z_threshold = z_threshold
        self.refractory_ms = refractory_ms
        self.double_window_ms = double_window_ms
        self.triple_window_ms = triple_window_ms
        self.window_size = window_size
        self._buffer: np.ndarray | None = None
        self._last_peak_time: float = 0.0
        self._recent_peaks: deque[float] = deque(maxlen=10)

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        # Use average of AF7 (idx 1) and AF8 (idx 2)
        frontal = (frame.eeg[1] + frame.eeg[2]) / 2.0

        # Append to buffer
        if self._buffer is not None:
            self._buffer = np.concatenate([self._buffer, frontal])
            if len(self._buffer) > self.window_size:
                self._buffer = self._buffer[-self.window_size:]
        else:
            self._buffer = frontal.copy()

        if len(self._buffer) < 32:
            return

        now = frame.timestamp or time.time()

        # Detect peaks using z-score
        try:
            data = self._buffer.astype(np.float64)
            peaks = DataFilter.detect_peaks_z_score(
                data, lag=int(min(30, len(data) // 4)),
                threshold=self.z_threshold, influence=0.3,
            )
            new_start = max(0, len(data) - len(frontal))
            new_peaks = np.where(peaks[new_start:] != 0)[0]

            for _ in new_peaks:
                if (now - self._last_peak_time) * 1000 < self.refractory_ms:
                    continue
                self._last_peak_time = now
                self._recent_peaks.append(now)
        except Exception:
            return

        if not self._recent_peaks:
            return

        time_since_last = (now - self._recent_peaks[-1]) * 1000
        if time_since_last < self.refractory_ms:
            return

        cutoff_triple = now - self.triple_window_ms / 1000
        recent = [t for t in self._recent_peaks if t > cutoff_triple]
        count = len(recent)
        self._recent_peaks.clear()

        if count >= 3:
            frame.events.append(Event(
                kind="triple_blink", timestamp=now, confidence=0.8, channel="AF7+AF8",
            ))
        elif count == 2:
            frame.events.append(Event(
                kind="double_blink", timestamp=now, confidence=0.85, channel="AF7+AF8",
            ))
        elif count == 1:
            frame.events.append(Event(
                kind="single_blink", timestamp=now, confidence=0.9, channel="AF7+AF8",
            ))


class ClenchDetector(Stage):
    name = "clench_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        emg_lowcut: float = 20.0,
        emg_highcut: float = 45.0,
        threshold_uv: float = 50.0,
        min_duration_ms: float = 100,
    ):
        self.emg_lowcut = emg_lowcut
        self.emg_highcut = emg_highcut
        self.threshold_uv = threshold_uv
        self.min_duration_ms = min_duration_ms

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 32:
            return

        temporal = np.stack([frame.eeg[0], frame.eeg[3]])  # TP9, TP10
        sr = 256

        filtered = temporal.copy().astype(np.float64)
        for ch in range(2):
            try:
                DataFilter.perform_bandpass(
                    filtered[ch], sr, self.emg_lowcut, self.emg_highcut, 4, 0, 0.0,
                )
            except Exception:
                return

        envelope = np.abs(filtered)
        avg_envelope = np.mean(envelope, axis=0)

        above = avg_envelope > self.threshold_uv
        min_samples = int(self.min_duration_ms / 1000.0 * sr)

        if not np.any(above):
            frame.set(ClenchResult(jaw_clench=False))
            return

        n_above = int(np.sum(above))
        clenched = n_above >= min_samples

        frame.set(ClenchResult(jaw_clench=clenched))
        if clenched:
            now = frame.timestamp or time.time()
            frame.events.append(Event(
                kind="clench", timestamp=now, confidence=0.85,
                channel="TP9+TP10",
                metadata={"duration_samples": n_above},
            ))
