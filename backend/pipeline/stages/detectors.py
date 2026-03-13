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
    _log = logging.getLogger("blink_detector")

    # Shape validation buffer: ±200ms at 256Hz
    _HALF_WIN = 51
    _BUFFER_SIZE = 512  # ~2s rolling buffer for shape analysis
    _TEMPLATE_PATH = Path(__file__).parent.parent / "blink_template.npy"

    def __init__(
        self,
        threshold_uv: float = -50.0,
        threshold_sd: float = 2.0,
        baseline_alpha: float = 0.001,
        refractory_ms: float = 100,
        classify_window_ms: float = 600,
        max_hf_ratio: float = 3.5,
        max_deflection_ms: float = 200.0,
        mf_threshold: float = 0,  # disabled: template matching ineffective on 4ch Muse
        min_bilateral_corr: float = 0.0,  # disabled: unreliable with dry electrodes
    ):
        self.threshold_uv = threshold_uv
        self.threshold_sd = threshold_sd
        self.baseline_alpha = baseline_alpha
        self.refractory_ms = refractory_ms
        self.classify_window_ms = classify_window_ms
        self.max_hf_ratio = max_hf_ratio
        self.max_deflection_ms = max_deflection_ms
        self.mf_threshold = mf_threshold
        self.min_bilateral_corr = min_bilateral_corr
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
        self._af7_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._af8_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
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
        """Check if min_val exceeds adaptive or fixed threshold.

        Once adaptive baseline is established (~1s), use ONLY adaptive.
        Fixed threshold is only used during cold start.
        """
        if self._baseline_samples >= 256:
            # Adaptive: threshold_sd SDs below running baseline
            sd = max(np.sqrt(self._baseline_var), 1.0)
            adaptive_thresh = self._baseline_mean - self.threshold_sd * sd
            return min_val < adaptive_thresh
        # Cold start: use fixed threshold until baseline is ready
        return min_val < self.threshold_uv

    def _append_buffer(self, frontal: np.ndarray, temporal: np.ndarray,
                       af7: np.ndarray, af8: np.ndarray) -> None:
        """Append frontal, temporal, and per-channel data to rolling buffers."""
        n = len(frontal)
        if n >= self._BUFFER_SIZE:
            self._frontal_buf[:] = frontal[-self._BUFFER_SIZE:]
            self._temporal_buf[:] = temporal[-self._BUFFER_SIZE:]
            self._af7_buf[:] = af7[-self._BUFFER_SIZE:]
            self._af8_buf[:] = af8[-self._BUFFER_SIZE:]
            self._buf_pos = 0
            self._buf_filled = True
            return
        end = self._buf_pos + n
        if end <= self._BUFFER_SIZE:
            self._frontal_buf[self._buf_pos:end] = frontal
            self._temporal_buf[self._buf_pos:end] = temporal
            self._af7_buf[self._buf_pos:end] = af7
            self._af8_buf[self._buf_pos:end] = af8
            self._buf_pos = end
        else:
            first = self._BUFFER_SIZE - self._buf_pos
            self._frontal_buf[self._buf_pos:] = frontal[:first]
            self._temporal_buf[self._buf_pos:] = temporal[:first]
            self._af7_buf[self._buf_pos:] = af7[:first]
            self._af8_buf[self._buf_pos:] = af8[:first]
            rem = n - first
            self._frontal_buf[:rem] = frontal[first:]
            self._temporal_buf[:rem] = temporal[first:]
            self._af7_buf[:rem] = af7[first:]
            self._af8_buf[:rem] = af8[first:]
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
        af7 = frame.eeg[1].astype(np.float64)
        af8 = frame.eeg[2].astype(np.float64)
        frontal = (af7 + af8) / 2.0
        temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0

        # Update rolling buffers
        self._append_buffer(frontal, temporal, af7, af8)

        min_val = float(np.min(frontal))
        crossed = self._is_candidate(min_val)

        # Debug: log significant deflections even if they don't cross threshold
        if min_val < -30:
            sd = max(np.sqrt(self._baseline_var), 1.0) if self._baseline_samples >= 256 else 0
            adaptive = (self._baseline_mean - self.threshold_sd * sd) if self._baseline_samples >= 256 else None
            self._log.debug(
                "deflection %.1f µV | baseline=%.1f sd=%.1f adaptive_thresh=%s fixed_thresh=%.1f | crossed=%s",
                min_val, self._baseline_mean, sd,
                f"{adaptive:.1f}" if adaptive is not None else "N/A",
                self.threshold_uv, crossed,
            )

        if not crossed:
            # Update baseline only during non-event periods
            self._update_baseline(float(np.mean(frontal)))

        if crossed:
            # Guard 0: reject if head is moving (nod/shake causes EEG artifact)
            if frame.imu is not None and frame.imu.shape[0] > 5 and frame.imu.shape[1] > 0:
                gyro_pitch_peak = float(np.max(np.abs(frame.imu[4])))
                gyro_yaw_peak = float(np.max(np.abs(frame.imu[5])))
                if gyro_pitch_peak > 20.0 or gyro_yaw_peak > 20.0:
                    self._log.debug("REJECTED by motion guard: pitch=%.1f yaw=%.1f deg/s", gyro_pitch_peak, gyro_yaw_peak)
                    return

            # Guard 0.5: bilateral correlation — real blinks correlate AF7↔AF8
            if self.min_bilateral_corr > 0:
                win = min(64, self._buf_pos if not self._buf_filled else self._BUFFER_SIZE)
                if win >= 16:
                    if self._buf_pos >= win:
                        a7 = self._af7_buf[self._buf_pos - win:self._buf_pos]
                        a8 = self._af8_buf[self._buf_pos - win:self._buf_pos]
                    else:
                        a7 = np.concatenate([
                            self._af7_buf[-(win - self._buf_pos):],
                            self._af7_buf[:self._buf_pos],
                        ])
                        a8 = np.concatenate([
                            self._af8_buf[-(win - self._buf_pos):],
                            self._af8_buf[:self._buf_pos],
                        ])
                    corr = np.corrcoef(a7, a8)[0, 1]
                    if np.isnan(corr) or corr < self.min_bilateral_corr:
                        self._log.debug("REJECTED by bilateral guard: corr=%.2f (min=%.1f)",
                                       corr if not np.isnan(corr) else 0, self.min_bilateral_corr)
                        return

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
                hf_ratio = t_hf / f_hf if f_hf > 0 else 0
                if f_hf > 0 and hf_ratio > self.max_hf_ratio:
                    self._log.debug("REJECTED by clench guard: HF ratio=%.2f (max=%.1f)", hf_ratio, self.max_hf_ratio)
                    return

            # Guard 2: reject if speech detector flagged active
            speech = frame.get(SpeechResult)
            if speech and speech.speech_active:
                self._log.debug("REJECTED by speech guard")
                return

            # Guard 3: shape validation — reject broad deflections (speech)
            if not self._check_shape():
                self._log.debug("REJECTED by shape guard (deflection too broad)")
                return

            # Guard 4: matched filter — reject if template match is poor
            if not self._check_template():
                self._log.debug("REJECTED by template guard")
                return

            elapsed_ms = (now - self._last_blink_time) * 1000
            if elapsed_ms >= self.refractory_ms:
                self._last_blink_time = now
                self._pending_blinks.append(now)
                self._log.debug("ACCEPTED blink candidate (min=%.1f µV, elapsed=%.0f ms)", min_val, elapsed_ms)
                if len(self._pending_blinks) == 1:
                    self._classify_deadline = now + self.classify_window_ms / 1000
            else:
                self._log.debug("REJECTED by refractory (elapsed=%.0f ms < %.0f ms)", elapsed_ms, self.refractory_ms)

        # Emit events once the classification window expires
        if self._pending_blinks and now >= self._classify_deadline:
            count = len(self._pending_blinks)
            self._pending_blinks.clear()
            self._log.debug("EMITTING: %d blink(s) in window", count)

            if count >= 2:
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


class NodDetector(Stage):
    """Detect head nods (yes) and shakes (no) from IMU gyroscope data.

    Uses gyro_pitch (ch4) for nod-yes and gyro_yaw (ch5) for head-shake-no.
    Thresholds derived from 20 nod_yes + 20 nod_no + 10 head_still recordings.

    Gyro pitch: nod_yes median=156 deg/s, nod_no median=19, still max=2.4
    Gyro yaw:   nod_no  median=176 deg/s, nod_yes median=52, still max=1.3
    """

    name = "nod_detector"
    cadence = Cadence.FAST

    # IMU channel indices (BrainFlow Muse 2)
    GYRO_PITCH = 4  # nod up/down
    GYRO_YAW = 5    # shake left/right

    def __init__(
        self,
        pitch_threshold: float = 40.0,   # deg/s — nod yes (100% TP, 0% FP on training data)
        yaw_threshold: float = 100.0,    # deg/s — head shake no (100% TP, 0% FP)
        refractory_ms: float = 1000,     # min time between nod events (nods have down+up = 2 peaks)
    ):
        self.pitch_threshold = pitch_threshold
        self.yaw_threshold = yaw_threshold
        self.refractory_ms = refractory_ms
        self._last_nod_time: float = 0.0
        # Buffer for baseline subtraction (running mean)
        self._pitch_baseline: float = 0.0
        self._yaw_baseline: float = 0.0
        self._baseline_samples: int = 0

    def _update_baseline(self, pitch_mean: float, yaw_mean: float) -> None:
        self._baseline_samples += 1
        if self._baseline_samples < 52:  # ~1s cold start
            alpha = 1.0 / self._baseline_samples
        else:
            alpha = 0.01
        self._pitch_baseline = (1 - alpha) * self._pitch_baseline + alpha * pitch_mean
        self._yaw_baseline = (1 - alpha) * self._yaw_baseline + alpha * yaw_mean

    def process(self, frame: PipelineFrame) -> None:
        if frame.imu is None or frame.imu.shape[1] == 0:
            return
        if frame.imu.shape[0] <= self.GYRO_YAW:
            return

        now = frame.timestamp or time.time()

        pitch = frame.imu[self.GYRO_PITCH]
        yaw = frame.imu[self.GYRO_YAW]

        # Subtract running baseline
        pitch_centered = pitch - self._pitch_baseline
        yaw_centered = yaw - self._yaw_baseline

        pitch_peak = float(np.max(np.abs(pitch_centered)))
        yaw_peak = float(np.max(np.abs(yaw_centered)))

        # Update baseline only during quiet periods
        if pitch_peak < self.pitch_threshold * 0.5 and yaw_peak < self.yaw_threshold * 0.5:
            self._update_baseline(float(np.mean(pitch)), float(np.mean(yaw)))

        elapsed_ms = (now - self._last_nod_time) * 1000
        if elapsed_ms < self.refractory_ms:
            return

        # Detect nod (pitch dominates yaw)
        if pitch_peak >= self.pitch_threshold and pitch_peak > yaw_peak:
            self._last_nod_time = now
            confidence = min(0.95, 0.7 + 0.25 * (pitch_peak / self.pitch_threshold - 1))
            frame.events.append(Event(
                kind="nod_yes", timestamp=now, confidence=round(confidence, 2),
                channel="gyro_pitch",
                metadata={"peak_dps": round(pitch_peak, 1)},
            ))
        # Detect head shake (yaw dominates pitch)
        elif yaw_peak >= self.yaw_threshold and yaw_peak > pitch_peak:
            self._last_nod_time = now
            confidence = min(0.95, 0.7 + 0.25 * (yaw_peak / self.yaw_threshold - 1))
            frame.events.append(Event(
                kind="nod_no", timestamp=now, confidence=round(confidence, 2),
                channel="gyro_yaw",
                metadata={"peak_dps": round(yaw_peak, 1)},
            ))
