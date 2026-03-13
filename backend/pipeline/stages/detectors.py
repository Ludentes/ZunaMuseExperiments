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
    """Detect blinks via MAD-based adaptive threshold + shape guards.

    Detection pipeline:
    1. MAD-based adaptive threshold: frontal (AF7+AF8)/2 must exceed
       median - threshold_sd * 1.4826 * MAD (robust statistics, immune
       to outlier-induced drift). Rolling window of 256 chunk means.
    2. Sustained deflection: must cross threshold for multiple consecutive
       chunks (trailing-edge detection).
    3. Motion guard: reject if gyro pitch/yaw > 20 deg/s
    4. Bilateral correlation guard (disabled): AF7↔AF8 correlation
    5. Clench guard: reject if temporal/frontal HF ratio > max_hf_ratio
    6. Speech fusion: reject if SpeechDetector flagged speech_active
    7. Shape validation: duration check [50-200ms] + slope direction check
       (downstroke must go down, upstroke must go up — rejects plateaus).
       R² tent fitting computed for debug logging but not gated on (too
       strict for 4-sample streaming noise).
    8. Template matching (disabled): matched filter convolution
    9. Refractory + multi-blink classification window

    Evaluated on 342 trials (159 original + 183 office demo):
    Original data: F1=0.79 (P=0.87, R=0.72)
    All data: F1=0.64 (P=0.92, R=0.49)
    See docs/research/2026-03-13-advanced-blink-detection-methods-practical.md
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
        threshold_sd: float = 1.5,
        baseline_alpha: float = 0.01,
        refractory_ms: float = 100,
        classify_window_ms: float = 600,
        max_hf_ratio: float = 3.5,
        min_deflection_ms: float = 50.0,
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
        self.min_deflection_ms = min_deflection_ms
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
        # Adaptive baseline (rolling window + median/MAD)
        self._baseline_window: deque[float] = deque(maxlen=256)  # ~4s of chunk means at 64 chunks/s
        self._baseline_median: float = 0.0
        self._baseline_mad: float = 1.0
        self._baseline_samples: int = 0
        # Rolling buffers for shape validation and HF ratio
        self._frontal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._temporal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._af7_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._af8_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._buf_pos: int = 0
        self._buf_filled: bool = False
        # Sustained deflection counter: real blinks cross threshold for multiple consecutive chunks
        self._consecutive_crossed: int = 0

    def _update_baseline(self, chunk_mean: float, n_samples: int = 1) -> None:
        """Update rolling window baseline with median/MAD.

        Args:
            chunk_mean: Mean of the current chunk's frontal signal.
            n_samples: Number of samples in this chunk (for cold start counting).
        """
        self._baseline_samples += n_samples
        self._baseline_window.append(chunk_mean)

        if len(self._baseline_window) >= 8:  # need minimum data for meaningful statistics
            values = np.array(self._baseline_window)
            self._baseline_median = float(np.median(values))
            self._baseline_mad = float(np.median(np.abs(values - self._baseline_median)))
            if self._baseline_mad < 0.5:
                self._baseline_mad = 0.5  # floor to prevent zero-MAD in perfectly stable signals

    def _is_candidate(self, chunk_mean: float) -> bool:
        """Check if chunk_mean exceeds adaptive MAD-based threshold.

        Uses robust statistics: threshold = median - lambda * 1.4826 * MAD
        The 1.4826 factor converts MAD to a consistent estimator of SD
        for normal distributions.

        Suppresses detection during cold start (first 256 samples ~1s) while
        baseline is being established.
        """
        if self._baseline_samples < 256:
            return False  # cold start: accumulate baseline, don't detect

        robust_sd = 1.4826 * self._baseline_mad
        adaptive_thresh = self._baseline_median - self.threshold_sd * robust_sd
        return chunk_mean < adaptive_thresh

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
        """Validate blink shape using BLINKER-style R² tent fitting.

        A real blink has a characteristic tent shape: linear downstroke to peak,
        then linear upstroke back to baseline. We fit linear regressions to the
        inner 80% of each half and compute R². Good blinks have R² >= min_r2 on
        both halves.

        Also checks duration is within [min_deflection_ms, max_deflection_ms].

        Falls back to duration-only check if buffer is too small for R².

        Returns True if shape is blink-like.
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

        # Find the deepest point (blink peak is most negative)
        min_idx = int(np.argmin(buf))
        peak_val = float(buf[min_idx])
        half_amp = peak_val / 2.0

        # Find left boundary at half-amplitude
        left_idx = min_idx
        for i in range(min_idx - 1, -1, -1):
            if buf[i] >= half_amp:
                left_idx = i
                break
        else:
            left_idx = 0

        # Find right boundary at half-amplitude
        right_idx = min_idx
        for i in range(min_idx + 1, len(buf)):
            if buf[i] >= half_amp:
                right_idx = i
                break
        else:
            right_idx = len(buf) - 1

        # Duration check
        contiguous = right_idx - left_idx + 1
        dur_ms = contiguous / 256.0 * 1000.0

        if dur_ms < self.min_deflection_ms:
            self._log.debug("SHAPE: too brief %.0fms < %.0fms", dur_ms, self.min_deflection_ms)
            return False
        if dur_ms > self.max_deflection_ms:
            self._log.debug("SHAPE: too broad %.0fms > %.0fms", dur_ms, self.max_deflection_ms)
            return False

        # R² tent fitting: need at least 4 samples per half for meaningful regression
        downstroke = buf[left_idx:min_idx + 1]
        upstroke = buf[min_idx:right_idx + 1]

        if len(downstroke) < 4 or len(upstroke) < 4:
            return True  # too short for R², accept based on duration alone

        # Fit inner 80% of each half. Returns (R², slope).
        def r_squared_and_slope(segment: np.ndarray) -> tuple[float, float]:
            n = len(segment)
            start = int(n * 0.1)
            end = int(n * 0.9)
            if end - start < 3:
                return 1.0, 0.0  # too few points, accept
            inner = segment[start:end]
            x = np.arange(len(inner), dtype=np.float64)
            coeffs = np.polyfit(x, inner, 1)
            slope = float(coeffs[0])
            predicted = np.polyval(coeffs, x)
            ss_res = np.sum((inner - predicted) ** 2)
            ss_tot = np.sum((inner - np.mean(inner)) ** 2)
            if ss_tot < 1e-10:
                return 1.0, slope  # constant signal — high R² but check slope
            return float(1.0 - ss_res / ss_tot), slope

        r2_down, slope_down = r_squared_and_slope(downstroke)
        r2_up, slope_up = r_squared_and_slope(upstroke)

        # R² gating disabled — 4-sample streaming noise makes linear R² unreliable
        # (R²=0.7 rejected 32% of valid blinks). R² values still logged for analysis.

        # Slope direction check: downstroke must go down, upstroke must go up.
        # Flat plateaus have near-zero slope on both halves.
        blink_amplitude = abs(peak_val - float(np.mean([buf[left_idx], buf[right_idx]])))
        if blink_amplitude > 1.0:
            min_slope = blink_amplitude * 0.15 / max(len(downstroke), len(upstroke))
            if slope_down > -min_slope or slope_up < min_slope:
                self._log.debug(
                    "SHAPE slope: down=%.2f up=%.2f (min_mag=%.2f) → REJECT (plateau)",
                    slope_down, slope_up, min_slope)
                return False

        self._log.debug("SHAPE R²: down=%.2f up=%.2f slopes=%.2f/%.2f → ACCEPT",
                       r2_down, r2_up, slope_down, slope_up)
        return True

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

    def _try_emit_blink(self, frame: PipelineFrame, now: float) -> None:
        """Run guard layers and potentially register a blink candidate.

        Called on the trailing edge of a threshold-crossing streak, after
        the full blink waveform has been buffered.
        """
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

        # Guard 3: shape validation — reject non-tent-shaped deflections
        if not self._check_shape():
            self._log.debug("REJECTED by shape guard")
            return

        # Guard 4: matched filter — reject if template match is poor
        if not self._check_template():
            self._log.debug("REJECTED by template guard")
            return

        elapsed_ms = (now - self._last_blink_time) * 1000
        if elapsed_ms >= self.refractory_ms:
            self._last_blink_time = now
            self._pending_blinks.append(now)
            self._log.debug("ACCEPTED blink candidate (elapsed=%.0f ms)", elapsed_ms)
            if len(self._pending_blinks) == 1:
                self._classify_deadline = now + self.classify_window_ms / 1000
        else:
            self._log.debug("REJECTED by refractory (elapsed=%.0f ms < %.0f ms)", elapsed_ms, self.refractory_ms)

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

        chunk_val = float(np.mean(frontal))
        crossed = self._is_candidate(chunk_val)

        # Debug: log significant deflections even if they don't cross threshold
        if chunk_val < -40:
            sd = max(1.4826 * self._baseline_mad, 1.0) if self._baseline_samples >= 256 else 0
            adaptive = (self._baseline_median - self.threshold_sd * sd) if self._baseline_samples >= 256 else None
            self._log.debug(
                "deflection %.1f µV | baseline=%.1f sd=%.1f adaptive_thresh=%s | crossed=%s",
                chunk_val, self._baseline_median, sd,
                f"{adaptive:.1f}" if adaptive is not None else "N/A",
                crossed,
            )

        # Always update baseline using chunk MEAN (not min) if it's close to
        # current baseline. This tracks slow drift while ignoring blink spikes.
        # During blinks: chunk mean is very deviant → outside 3 robust SDs → no update.
        # During drift: chunk mean shifts gradually → within 3 robust SDs → updates.
        chunk_mean = chunk_val
        n_samp = len(frontal)
        if self._baseline_samples < 256:
            # During cold start, still reject extreme outliers once we have
            # enough data to know what "normal" looks like (after 64 samples)
            if self._baseline_samples < 64:
                self._update_baseline(chunk_mean, n_samp)
            else:
                robust_sd = 1.4826 * self._baseline_mad
                if abs(chunk_mean - self._baseline_median) < 5 * robust_sd:
                    self._update_baseline(chunk_mean, n_samp)
        else:
            robust_sd = 1.4826 * self._baseline_mad
            if abs(chunk_mean - self._baseline_median) < 3 * robust_sd:
                self._update_baseline(chunk_mean, n_samp)

        if crossed:
            self._consecutive_crossed += 1
        else:
            # Trailing-edge detection: validate when crossing streak ends.
            # This ensures the full blink waveform is in the buffer before
            # shape validation runs (which needs complete deflection width).
            if self._consecutive_crossed > 0:
                streak = self._consecutive_crossed
                self._consecutive_crossed = 0
                min_chunks = max(2, int(self.min_deflection_ms / 1000 * 256 / max(len(frontal), 1)))
                if streak >= min_chunks:
                    self._try_emit_blink(frame, now)

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
