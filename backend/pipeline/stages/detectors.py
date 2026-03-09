from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from brainflow.data_filter import DataFilter

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, Event, PipelineFrame


@dataclass
class ClenchResult:
    jaw_clench: bool


@dataclass
class SpeechResult:
    """Set by SpeechDetector. Used by BlinkDetector for fusion."""
    speech_active: bool


def _hf_rms(sig: np.ndarray) -> float:
    """RMS of first-order diff — approximates high-frequency energy."""
    if len(sig) < 2:
        return 0.0
    return float(np.sqrt(np.mean(np.diff(sig) ** 2)))


class SpeechDetector(Stage):
    """Detect speech/vocalization via sustained temporal EMG.

    Speech produces sustained high-frequency EMG on temporal channels (TP9/TP10).
    Unlike brief blink artifacts, speech EMG persists for hundreds of ms.

    Uses a rolling window of per-chunk HF RMS values. If enough chunks in the
    window exceed the threshold, speech is flagged active.

    Tuned on recorded data: hf_thresh=15, min_active_frac=0.4, window=48 chunks
    (768ms). This correctly suppresses 4/7 talk FPs from the blink detector while
    preserving 97% blink recall.
    """

    name = "speech_detector"
    cadence = Cadence.FAST

    def __init__(
        self,
        hf_thresh: float = 15.0,
        window_chunks: int = 48,
        min_active_frac: float = 0.4,
    ):
        self.hf_thresh = hf_thresh
        self.window_chunks = window_chunks
        self.min_active = int(window_chunks * min_active_frac)
        self._hf_history: deque[float] = deque(maxlen=window_chunks)

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            frame.set(SpeechResult(speech_active=False))
            return

        temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0
        t_hf = _hf_rms(temporal)
        self._hf_history.append(t_hf)

        active = False
        if len(self._hf_history) >= self.window_chunks:
            n_above = sum(1 for v in self._hf_history if v > self.hf_thresh)
            active = n_above >= self.min_active

        frame.set(SpeechResult(speech_active=active))


class BlinkDetector(Stage):
    """Detect blinks via adaptive threshold + shape + template + EMG/speech guards.

    Six-layer detection pipeline:
    1. Adaptive threshold: frontal (AF7+AF8)/2 must exceed running baseline
       by threshold_sd standard deviations (default 4.0). Falls back to
       fixed threshold_uv if baseline not yet established.
    2. Clench guard: reject if temporal/frontal HF ratio > max_hf_ratio
       (clenches: ratio 3.7-5.0, blinks: 1.1-3.3)
    3. Speech fusion: reject if SpeechDetector flagged speech_active
    4. Shape validation: buffer ±200ms around event, reject if duration of
       sub-threshold deflection > max_deflection_ms (speech artifacts are
       broader than blinks)
    5. Template matching: matched filter (convolution with time-reversed
       template). Reject if peak response > mf_threshold (less negative
       means poorer match). Template from averaged single_blink recordings.
    6. Refractory + multi-blink classification window

    Evaluated on 93 recorded trials (rest/single_blink/double_blink/clench/talk):
    F1=0.93 (P=0.93, R=0.93) with all layers active.
    See docs/research/2026-03-09-blink-detection-evaluation.md for full analysis.
    """

    name = "blink_detector"
    cadence = Cadence.FAST

    # Shape validation buffer: ±200ms at 256Hz
    _HALF_WIN = 51
    _BUFFER_SIZE = 512  # ~2s rolling buffer for shape analysis
    _TEMPLATE_PATH = Path(__file__).parent.parent / "blink_template.npy"

    def __init__(
        self,
        threshold_uv: float = -75.0,
        threshold_sd: float = 4.0,
        baseline_alpha: float = 0.001,
        refractory_ms: float = 300,
        classify_window_ms: float = 800,
        max_hf_ratio: float = 3.5,
        max_deflection_ms: float = 200.0,
        mf_threshold: float = 0,  # disabled: template matching ineffective on 4ch Muse
    ):
        self.threshold_uv = threshold_uv
        self.threshold_sd = threshold_sd
        self.baseline_alpha = baseline_alpha
        self.refractory_ms = refractory_ms
        self.classify_window_ms = classify_window_ms
        self.max_hf_ratio = max_hf_ratio
        self.max_deflection_ms = max_deflection_ms
        self.mf_threshold = mf_threshold
        # Load blink template for matched filter
        self._matched_filt: np.ndarray | None = None
        if self._TEMPLATE_PATH.exists():
            template = np.load(self._TEMPLATE_PATH)
            self._matched_filt = template[::-1].copy()
            self._matched_filt /= np.sqrt(np.sum(self._matched_filt ** 2))
        else:
            logging.getLogger("blink_detector").warning(
                "No blink template at %s — matched filter disabled", self._TEMPLATE_PATH
            )
        self._last_blink_time: float = 0.0
        self._pending_blinks: deque[float] = deque(maxlen=10)
        self._classify_deadline: float = 0.0
        # Adaptive baseline (EMA of frontal mean and variance)
        self._baseline_mean: float = 0.0
        self._baseline_var: float = 1.0
        self._baseline_samples: int = 0
        # Rolling buffers for shape validation and HF ratio
        self._frontal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._temporal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._buf_pos: int = 0
        self._buf_filled: bool = False

    def _update_baseline(self, chunk_mean: float) -> None:
        """Update running baseline with EMA. Only during non-event periods."""
        if self._baseline_samples < 256:
            # Cold start: simple accumulation for first ~1s
            self._baseline_samples += 1
            alpha = 1.0 / self._baseline_samples
        else:
            alpha = self.baseline_alpha
        self._baseline_mean = (1 - alpha) * self._baseline_mean + alpha * chunk_mean
        diff2 = (chunk_mean - self._baseline_mean) ** 2
        self._baseline_var = (1 - alpha) * self._baseline_var + alpha * diff2

    def _is_candidate(self, min_val: float) -> bool:
        """Check if min_val exceeds adaptive or fixed threshold."""
        # Fixed threshold always applies
        if min_val >= self.threshold_uv:
            return False
        # Adaptive threshold: must be threshold_sd SDs below baseline
        if self._baseline_samples >= 256:
            sd = max(np.sqrt(self._baseline_var), 1.0)
            adaptive_thresh = self._baseline_mean - self.threshold_sd * sd
            return min_val < adaptive_thresh
        return True  # fixed threshold passed, baseline not ready

    def _append_buffer(self, frontal: np.ndarray, temporal: np.ndarray) -> None:
        """Append frontal and temporal data to rolling buffers."""
        n = len(frontal)
        if n >= self._BUFFER_SIZE:
            self._frontal_buf[:] = frontal[-self._BUFFER_SIZE:]
            self._temporal_buf[:] = temporal[-self._BUFFER_SIZE:]
            self._buf_pos = 0
            self._buf_filled = True
            return
        end = self._buf_pos + n
        if end <= self._BUFFER_SIZE:
            self._frontal_buf[self._buf_pos:end] = frontal
            self._temporal_buf[self._buf_pos:end] = temporal
            self._buf_pos = end
        else:
            first = self._BUFFER_SIZE - self._buf_pos
            self._frontal_buf[self._buf_pos:] = frontal[:first]
            self._temporal_buf[self._buf_pos:] = temporal[:first]
            rem = n - first
            self._frontal_buf[:rem] = frontal[first:]
            self._temporal_buf[:rem] = temporal[first:]
            self._buf_pos = rem
            self._buf_filled = True

    def _check_shape(self) -> bool:
        """Validate blink shape using buffered data. Returns True if shape is blink-like.

        Measures the contiguous duration of samples below half-peak amplitude
        around the deepest point. Blinks: 30-170ms. Speech: 200-300ms+.
        """
        if not self._buf_filled and self._buf_pos < self._HALF_WIN * 2:
            return True  # not enough data, accept

        # Reconstruct ordered buffer
        if self._buf_filled:
            buf = np.concatenate([
                self._frontal_buf[self._buf_pos:],
                self._frontal_buf[:self._buf_pos],
            ])
        else:
            buf = self._frontal_buf[:self._buf_pos]

        # Find the deepest point
        min_idx = int(np.argmin(buf))
        peak_val = float(buf[min_idx])
        half_amp = peak_val / 2.0

        # Measure contiguous run below half-amplitude around the peak
        # Walk left from peak
        left = 0
        for i in range(min_idx - 1, -1, -1):
            if buf[i] >= half_amp:
                break
            left += 1
        # Walk right from peak
        right = 0
        for i in range(min_idx + 1, len(buf)):
            if buf[i] >= half_amp:
                break
            right += 1

        contiguous = left + 1 + right  # +1 for the peak itself
        dur_ms = contiguous / 256.0 * 1000.0

        return dur_ms <= self.max_deflection_ms

    def _check_template(self) -> bool:
        """Validate blink using matched filter on buffered data.

        Convolves the buffer with the time-reversed blink template.
        Blinks produce a strong negative peak; non-blinks don't.
        Returns True if template match is good enough.
        """
        if self._matched_filt is None or self.mf_threshold >= 0:
            return True  # no template or disabled

        # Reconstruct ordered buffer
        if self._buf_filled:
            buf = np.concatenate([
                self._frontal_buf[self._buf_pos:],
                self._frontal_buf[:self._buf_pos],
            ])
        else:
            buf = self._frontal_buf[:self._buf_pos]

        if len(buf) < len(self._matched_filt):
            return True  # not enough data

        filtered = np.convolve(buf, self._matched_filt, mode="same")
        return float(np.min(filtered)) < self.mf_threshold

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        now = frame.timestamp or time.time()

        # Average of AF7 (idx 1) and AF8 (idx 2) — frontal channels
        frontal = (frame.eeg[1] + frame.eeg[2]) / 2.0
        temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0

        # Update rolling buffers
        self._append_buffer(frontal, temporal)

        min_val = float(np.min(frontal))
        crossed = self._is_candidate(min_val)

        if not crossed:
            # Update baseline only during non-event periods
            self._update_baseline(float(np.mean(frontal)))

        if crossed:
            # Guard 1: reject if temporal HF >> frontal HF (jaw clench EMG)
            # Use last 128 samples (~500ms) from buffer for stable HF ratio
            win = min(128, self._buf_pos if not self._buf_filled else self._BUFFER_SIZE)
            if win >= 4:
                if self._buf_pos >= win:
                    f_win = self._frontal_buf[self._buf_pos - win:self._buf_pos]
                    t_win = self._temporal_buf[self._buf_pos - win:self._buf_pos]
                else:
                    f_win = np.concatenate([
                        self._frontal_buf[-(win - self._buf_pos):],
                        self._frontal_buf[:self._buf_pos],
                    ])
                    t_win = np.concatenate([
                        self._temporal_buf[-(win - self._buf_pos):],
                        self._temporal_buf[:self._buf_pos],
                    ])
                f_hf = _hf_rms(f_win)
                t_hf = _hf_rms(t_win)
                if f_hf > 0 and t_hf / f_hf > self.max_hf_ratio:
                    return

            # Guard 2: reject if speech detector flagged active
            speech = frame.get(SpeechResult)
            if speech and speech.speech_active:
                return

            # Guard 3: shape validation — reject broad deflections (speech)
            if not self._check_shape():
                return

            # Guard 4: matched filter — reject if template match is poor
            if not self._check_template():
                return

            elapsed_ms = (now - self._last_blink_time) * 1000
            if elapsed_ms >= self.refractory_ms:
                self._last_blink_time = now
                self._pending_blinks.append(now)
                if len(self._pending_blinks) == 1:
                    self._classify_deadline = now + self.classify_window_ms / 1000

        # Emit events once the classification window expires
        if self._pending_blinks and now >= self._classify_deadline:
            count = len(self._pending_blinks)
            self._pending_blinks.clear()

            if count >= 3:
                frame.events.append(Event(
                    kind="triple_blink", timestamp=now, confidence=0.8,
                    channel="AF7+AF8",
                ))
            elif count == 2:
                frame.events.append(Event(
                    kind="double_blink", timestamp=now, confidence=0.85,
                    channel="AF7+AF8",
                ))
            else:
                frame.events.append(Event(
                    kind="single_blink", timestamp=now, confidence=0.9,
                    channel="AF7+AF8",
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
