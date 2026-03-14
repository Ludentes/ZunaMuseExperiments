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

    Uses an adaptive baseline: tracks rolling median of temporal HF RMS, then
    flags speech when enough recent chunks exceed baseline × hf_ratio_thresh.
    This adapts to varying headband fit (poor temporal contact → high baseline HF).

    Tuned on recorded data: hf_ratio_thresh=2.0, min_active_frac=0.4, window=48
    chunks (768ms).
    """

    name = "speech_detector"
    cadence = Cadence.FAST
    _log = logging.getLogger("speech_detector")

    def __init__(
        self,
        hf_thresh: float = 15.0,
        hf_ratio_thresh: float = 2.0,
        window_chunks: int = 48,
        min_active_frac: float = 0.4,
    ):
        self.hf_thresh = hf_thresh
        self.hf_ratio_thresh = hf_ratio_thresh
        self.window_chunks = window_chunks
        self.min_active = int(window_chunks * min_active_frac)
        self._hf_history: deque[float] = deque(maxlen=window_chunks)
        # Adaptive baseline: rolling median of temporal HF values
        self._hf_baseline_history: deque[float] = deque(maxlen=256)
        self._hf_baseline: float = 0.0  # 0 = not yet established
        self._update_ctr: int = 0

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            frame.set(SpeechResult(speech_active=False))
            return

        temporal = (frame.eeg[0] + frame.eeg[3]) / 2.0
        t_hf = _hf_rms(temporal)
        self._hf_history.append(t_hf)

        # Use adaptive threshold when baseline is established, else absolute.
        # Adaptive threshold = max(baseline * ratio, absolute floor).
        # This way sessions with high temporal HF (poor fit) don't false-trigger
        # the speech guard constantly, while sessions with normal HF still work.
        if self._hf_baseline > 1.0:
            effective_thresh = max(self._hf_baseline * self.hf_ratio_thresh, self.hf_thresh)
        else:
            effective_thresh = self.hf_thresh

        active = False
        if len(self._hf_history) >= self.window_chunks:
            n_above = sum(1 for v in self._hf_history if v > effective_thresh)
            active = n_above >= self.min_active

        # Update baseline only during quiet periods (not while speech is active).
        # This prevents speech HF from contaminating the baseline upward.
        self._update_ctr += 1
        if self._update_ctr >= 8:
            self._update_ctr = 0
            if not active:
                self._hf_baseline_history.append(t_hf)
                if len(self._hf_baseline_history) >= 8:
                    self._hf_baseline = float(np.median(self._hf_baseline_history))

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
        threshold_uv: float = -9999.0,
        threshold_sd: float = 2.5,
        refractory_ms: float = 100,
        classify_window_ms: float = 600,
        max_hf_ratio: float = 3.5,
        min_deflection_ms: float = 50.0,
        max_deflection_ms: float = 200.0,
        mf_threshold: float = 0,  # disabled: template matching ineffective on 4ch Muse
        min_bilateral_corr: float = 0.0,  # disabled: unreliable with dry electrodes
    ):
        # threshold_uv: -9999 = disabled sentinel (use only adaptive).
        # Set by set_calibrated_threshold() or set_blink_threshold() to act as
        # a calibrated absolute floor that won't drift with MAD changes.
        self.threshold_uv = threshold_uv
        self.threshold_sd = threshold_sd
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
        self._pending_blinks: deque[tuple[float, float]] = deque(maxlen=10)
        self._classify_deadline: float = 0.0
        self._frontal_quality: float = 1.0
        self._last_blink_meta: dict = {}
        # Adaptive baseline (rolling window + median/MAD)
        self._baseline_window: deque[float] = deque(maxlen=256)  # ~4s of chunk means at 64 chunks/s
        self._baseline_median: float = 0.0
        self._baseline_mad: float = 1.0
        self._baseline_samples: int = 0
        # Per-channel baselines for AF7 and AF8 (independent, for asymmetric blink detection)
        self._af7_baseline_window: deque[float] = deque(maxlen=256)
        self._af7_baseline_median: float = 0.0
        self._af7_baseline_mad: float = 1.0
        self._af8_baseline_window: deque[float] = deque(maxlen=256)
        self._af8_baseline_median: float = 0.0
        self._af8_baseline_mad: float = 1.0
        # Rolling buffers for shape validation and HF ratio
        self._frontal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._temporal_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._af7_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._af8_buf: np.ndarray = np.zeros(self._BUFFER_SIZE)
        self._buf_pos: int = 0
        self._buf_filled: bool = False
        # Sustained deflection counter: real blinks cross threshold for multiple consecutive chunks
        self._consecutive_crossed: int = 0
        # Raw capture window for calibration (measures deflection independent of threshold)
        self._capture_active: bool = False
        self._capture_start: float = 0.0
        self._capture_duration: float = 0.7
        self._capture_samples: list[float] = []
        # Guard enable flags — togglable from the UI for debugging
        self.guard_motion: bool = True
        self.guard_bilateral: bool = True
        self.guard_clench: bool = True
        self.guard_speech: bool = True
        self.guard_shape: bool = True
        self.guard_template: bool = True
        # Rolling temporal HF baseline — used by clench guard to detect when temporal
        # EMG is elevated ABOVE its own normal level (rather than vs frontal HF, which
        # drops during smooth blink deflections and makes that ratio artificially high).
        # Updated every 8 chunks using a 32-sample sliding window (31 diffs) for stability,
        # instead of per-chunk 4-sample HF RMS (3 diffs, extremely noisy).
        self._temporal_hf_history: deque[float] = deque(maxlen=64)  # ~8s at 8 chunks/update
        self._temporal_hf_baseline: float = 15.0  # reasonable prior; refined in process()
        self._temporal_hf_update_ctr: int = 0

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

    def _update_channel_baselines(self, af7_mean: float, af8_mean: float) -> None:
        """Update per-channel rolling baselines with contamination guard.

        Mirrors _update_baseline but tracks AF7 and AF8 independently so
        the adaptive threshold can fire on whichever channel has better contact.
        Does NOT increment _baseline_samples (that counter is owned by _update_baseline).
        """
        for ch_mean, window, median_attr, mad_attr in (
            (af7_mean, self._af7_baseline_window, "_af7_baseline_median", "_af7_baseline_mad"),
            (af8_mean, self._af8_baseline_window, "_af8_baseline_median", "_af8_baseline_mad"),
        ):
            ch_median = getattr(self, median_attr)
            ch_mad = getattr(self, mad_attr)
            robust_sd = 1.4826 * ch_mad
            if len(window) < 8 or robust_sd < 1e-6 or abs(ch_mean - ch_median) < 3 * robust_sd:
                window.append(ch_mean)
                if len(window) >= 8:
                    vals = np.array(window)
                    new_med = float(np.median(vals))
                    new_mad = max(float(np.median(np.abs(vals - new_med))), 0.5)
                    setattr(self, median_attr, new_med)
                    setattr(self, mad_attr, new_mad)

    def set_signal_quality(self, frontal_quality: float) -> None:
        """Set frontal signal quality (0-1) to scale blink confidence."""
        self._frontal_quality = max(0.0, min(1.0, frontal_quality))

    def set_calibrated_threshold(self, median_peak_amplitude_uv: float) -> None:
        """Set a per-session half-amplitude floor from measured blink amplitude.

        Computes the half-amplitude point between the measured blink peak and the
        current baseline, and stores it as threshold_uv. In the adaptive threshold
        check, threshold_uv acts as a ceiling that prevents the effective threshold
        from becoming more negative than the calibrated half-amplitude — so that
        in noisy sessions with high MAD (where the adaptive alone would require an
        unreachably deep signal), the calibrated floor still triggers detection.

        Does NOT change threshold_sd, which would hurt recall for stable low-MAD
        sessions by making the adaptive threshold unnecessarily deep.

        Args:
            median_peak_amplitude_uv: Median peak amplitude from calibration (negative µV).
        """
        robust_sd = 1.4826 * self._baseline_mad
        if robust_sd < 1e-6:
            self._log.warning("Cannot calibrate: robust_sd near zero (baseline not established yet?)")
            return
        half_amp_uv = (median_peak_amplitude_uv + self._baseline_median) / 2.0
        peak_sds = abs(median_peak_amplitude_uv - self._baseline_median) / robust_sd
        old_effective_uv = self._baseline_median - self.threshold_sd * robust_sd
        self._log.info(
            "CALIBRATE: peak=%.1f µV is %.1f SDs from baseline (%.1f) | "
            "half-amplitude floor=%.1f µV",
            median_peak_amplitude_uv, peak_sds, self._baseline_median, half_amp_uv,
        )
        self._log.info(
            "CALIBRATE: threshold_sd unchanged (%.2f) | "
            "adaptive_thresh=%.1f µV | threshold_uv floor=%.1f µV",
            self.threshold_sd, old_effective_uv, half_amp_uv,
        )
        # Store half-amplitude as floor: max(adaptive, threshold_uv) picks the less
        # negative of the two, so threshold_uv only activates when the adaptive
        # drifts MORE negative (more restrictive) than the calibrated floor.
        self.threshold_uv = half_amp_uv

    def set_blink_threshold(
        self,
        threshold_sd: float | None = None,
        threshold_uv: float | None = None,
        max_hf_ratio: float | None = None,
    ) -> None:
        """Manually override blink detection thresholds from the UI.

        Args:
            threshold_sd: SD multiplier for adaptive threshold (1.0–5.0 typical).
            threshold_uv: Absolute µV floor (e.g., -45.0). Set to None to disable.
            max_hf_ratio: Temporal/frontal HF ratio cap for clench guard (3.5 default;
                higher = more permissive; set to 99 to effectively disable guard).
        """
        if threshold_sd is not None:
            old_sd = self.threshold_sd
            self.threshold_sd = max(1.0, float(threshold_sd))
            # Clear the calibrated absolute floor so the SD-based threshold
            # takes full effect — otherwise the floor can override the slider.
            old_uv = self.threshold_uv
            self.threshold_uv = -9999.0
            self._log.info("SET threshold_sd %.2f → %.2f (threshold_uv floor %.1f cleared)",
                           old_sd, self.threshold_sd, old_uv)
        if threshold_uv is not None:
            old_uv = self.threshold_uv
            self.threshold_uv = float(threshold_uv)
            self._log.info("SET threshold_uv %.1f → %.1f µV", old_uv, self.threshold_uv)
        if max_hf_ratio is not None:
            old_hf = self.max_hf_ratio
            self.max_hf_ratio = max(0.1, float(max_hf_ratio))
            self._log.info("SET max_hf_ratio %.1f → %.1f", old_hf, self.max_hf_ratio)

    def set_guards(self, guards: dict[str, bool]) -> None:
        """Enable/disable individual guard layers from the UI.

        Args:
            guards: Dict mapping guard name to enabled state.
                    Valid keys: motion, bilateral, clench, speech, shape, template.
        """
        for name, enabled in guards.items():
            attr = f"guard_{name}"
            if hasattr(self, attr):
                old = getattr(self, attr)
                setattr(self, attr, bool(enabled))
                self._log.info("GUARD %s: %s → %s", name, old, bool(enabled))
            else:
                self._log.warning("Unknown guard: %s", name)

    def get_guard_states(self) -> dict[str, bool]:
        """Return current enable state of all guards."""
        return {
            "motion": self.guard_motion,
            "bilateral": self.guard_bilateral,
            "clench": self.guard_clench,
            "speech": self.guard_speech,
            "shape": self.guard_shape,
            "template": self.guard_template,
        }

    def start_blink_capture(self, duration_s: float = 0.7) -> None:
        """Open a raw capture window to measure blink amplitude independent of threshold.

        Collects all frontal samples for `duration_s` seconds, then the result
        is available via `get_capture_result()`. Used for calibration so we can
        measure what the user's blink actually looks like before the detector is tuned.
        """
        self._capture_start = time.time()
        self._capture_duration = duration_s
        self._capture_samples = []
        self._capture_active = True
        self._log.info("Blink capture window opened (%.1fs)", duration_s)

    def get_capture_result(self) -> dict | None:
        """Return capture result if the window is complete, else None.

        Returns dict with amplitude_uv and half_amplitude_uv (both negative for blinks).
        Returns None if capture is still in progress or no capture was started.
        """
        if not self._capture_active:
            return None
        if time.time() - self._capture_start < self._capture_duration:
            return None  # still in window
        self._capture_active = False
        if not self._capture_samples:
            self._log.warning("Blink capture: no samples collected — pipeline may not be running")
            return {"amplitude_uv": 0.0, "half_amplitude_uv": 0.0, "baseline_stable": False}
        samples = self._capture_samples
        peak_val = float(min(samples))
        baseline_stable = self._baseline_samples >= 128
        # Half-amplitude relative to baseline (midpoint from baseline to peak).
        # When baseline is not stable, fall back to absolute peak/2 (less accurate).
        if baseline_stable:
            half_amp = (peak_val + self._baseline_median) / 2.0
        else:
            half_amp = peak_val / 2.0
        robust_sd = 1.4826 * self._baseline_mad
        current_thresh = self._baseline_median - self.threshold_sd * robust_sd
        sds_from_baseline = abs(peak_val - self._baseline_median) / robust_sd if robust_sd > 0 else 0
        would_detect = peak_val < current_thresh
        self._log.info(
            "CAPTURE result: peak=%.1f µV, half=%.1f µV (%d samples) | "
            "baseline=%.1f (stable=%s), robust_sd=%.1f, current_thresh=%.1f µV (%.1f SD) | "
            "peak is %.1f SDs from baseline → would_detect=%s",
            peak_val, half_amp, len(samples),
            self._baseline_median, baseline_stable, robust_sd, current_thresh, self.threshold_sd,
            sds_from_baseline, would_detect,
        )
        return {
            "amplitude_uv": round(peak_val, 1),
            "half_amplitude_uv": round(half_amp, 1),
            "baseline_stable": baseline_stable,
        }

    def _is_candidate(self, af7_mean: float, af8_mean: float) -> bool:
        """Check if either frontal channel exceeds its adaptive MAD-based threshold."""
        if self._baseline_samples < 128:
            return False  # cold start: accumulate baseline, don't detect

        def _channel_thresh(median: float, mad: float) -> float:
            robust_sd = 1.4826 * mad
            adaptive_thresh = median - self.threshold_sd * robust_sd
            if self.threshold_uv > -9000:
                return max(adaptive_thresh, self.threshold_uv)
            return adaptive_thresh

        af7_thresh = _channel_thresh(self._af7_baseline_median, self._af7_baseline_mad)
        af8_thresh = _channel_thresh(self._af8_baseline_median, self._af8_baseline_mad)
        af7_crossed = af7_mean < af7_thresh
        af8_crossed = af8_mean < af8_thresh
        crossed = af7_crossed or af8_crossed

        # Log every threshold crossing or near-miss for diagnostic tracing
        if crossed or af7_mean < af7_thresh + 5.0 or af8_mean < af8_thresh + 5.0:
            self._log.debug(
                "CANDIDATE af7=%.1f(thr=%.1f %s) af8=%.1f(thr=%.1f %s) → %s",
                af7_mean, af7_thresh, "X" if af7_crossed else ".",
                af8_mean, af8_thresh, "X" if af8_crossed else ".",
                "CROSSED" if crossed else "near-miss",
            )
        return crossed

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

    def _check_shape(self) -> tuple[bool, dict]:
        """Validate blink shape using BLINKER-style R² tent fitting.

        A real blink has a characteristic tent shape: linear downstroke to peak,
        then linear upstroke back to baseline. We fit linear regressions to the
        inner 80% of each half and compute R². Good blinks have R² >= min_r2 on
        both halves.

        Also checks duration is within [min_deflection_ms, max_deflection_ms].

        Falls back to duration-only check if buffer is too small for R².

        Returns (is_blink_like, metadata_dict).
        """
        if not self._buf_filled and self._buf_pos < self._HALF_WIN * 2:
            return True, {}  # not enough data, accept

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
        # Half-amplitude relative to baseline (midpoint between peak and baseline).
        # When baseline is not stable, fall back to peak/2 (less accurate).
        if self._baseline_samples >= 128:
            half_amp = (peak_val + self._baseline_median) / 2.0
        else:
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

        # Secondary peak: real blinks produce a positive overshoot ~50-150ms after trough.
        # Check buf[right_idx+1 : right_idx+40] (≈150ms at 256Hz). Acts as confidence
        # booster only (not a gate — would miss blinks at end of buffer).
        secondary_peak = False
        sp_end = right_idx + 40
        if sp_end < len(buf):
            after_right = buf[right_idx + 1:sp_end]
            if len(after_right) >= 5 and float(np.max(after_right)) > self._baseline_median + 2.0:
                secondary_peak = True

        # Duration check
        contiguous = right_idx - left_idx + 1
        dur_ms = contiguous / 256.0 * 1000.0

        if dur_ms < self.min_deflection_ms:
            self._log.info("REJECTED by shape guard: too brief %.0fms < %.0fms", dur_ms, self.min_deflection_ms)
            return False, {}
        if dur_ms > self.max_deflection_ms:
            self._log.info("REJECTED by shape guard: too broad %.0fms > %.0fms", dur_ms, self.max_deflection_ms)
            return False, {}

        # R² tent fitting: need at least 4 samples per half for meaningful regression
        downstroke = buf[left_idx:min_idx + 1]
        upstroke = buf[min_idx:right_idx + 1]

        if len(downstroke) < 4 or len(upstroke) < 4:
            meta = {
                "amplitude_uv": round(peak_val, 1),
                "half_amplitude_uv": round(half_amp, 1),
                "onset_slope": 0.0,
                "duration_ms": round(dur_ms, 1),
                "secondary_peak": secondary_peak,
            }
            return True, meta  # too short for R², accept based on duration alone

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
                self._log.info(
                    "REJECTED by shape guard: slope down=%.2f up=%.2f min_mag=%.2f (plateau)",
                    slope_down, slope_up, min_slope)
                return False, {}

        meta = {
            "amplitude_uv": round(peak_val, 1),
            "half_amplitude_uv": round(half_amp, 1),
            "onset_slope": round(slope_down, 2),
            "duration_ms": round(dur_ms, 1),
            "secondary_peak": secondary_peak,
        }
        self._log.debug("SHAPE R²: down=%.2f up=%.2f slopes=%.2f/%.2f → ACCEPT",
                       r2_down, r2_up, slope_down, slope_up)
        return True, meta

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
        the full blink waveform has been buffered. All rejections log at INFO
        for diagnostic tracing ("why was my blink not detected?").
        """
        def _reject(guard: str, detail: str = "") -> None:
            self._log.info("REJECTED by %s guard%s", guard, f": {detail}" if detail else "")
            frame.events.append(Event(
                kind="blink_rejected", timestamp=now, confidence=0.0,
                channel="AF7+AF8",
                metadata={"guard": guard, "detail": detail},
            ))

        # Guard 0: reject if head is moving (nod/shake causes EEG artifact)
        if self.guard_motion and frame.imu is not None and frame.imu.shape[0] > 5 and frame.imu.shape[1] > 0:
            gyro_pitch_peak = float(np.max(np.abs(frame.imu[4])))
            gyro_yaw_peak = float(np.max(np.abs(frame.imu[5])))
            if gyro_pitch_peak > 20.0 or gyro_yaw_peak > 20.0:
                _reject("motion", f"pitch={gyro_pitch_peak:.1f} yaw={gyro_yaw_peak:.1f}")
                return

        # Guard 0.5: bilateral correlation — real blinks correlate AF7↔AF8
        if self.guard_bilateral and self.min_bilateral_corr > 0:
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
                    _reject("bilateral", f"corr={corr:.2f}" if not np.isnan(corr) else "corr=NaN")
                    return

        # Guard 1: reject if temporal HF is elevated above its own rolling baseline (jaw clench EMG)
        win = min(128, self._buf_pos if not self._buf_filled else self._BUFFER_SIZE)
        if self.guard_clench and win >= 4:
            if self._buf_pos >= win:
                t_win = self._temporal_buf[self._buf_pos - win:self._buf_pos]
            else:
                t_win = np.concatenate([
                    self._temporal_buf[-(win - self._buf_pos):],
                    self._temporal_buf[:self._buf_pos],
                ])
            t_hf = _hf_rms(t_win)
            temporal_baseline = max(self._temporal_hf_baseline, 1.0)
            hf_ratio = t_hf / temporal_baseline
            effective_max_hf_ratio = self.max_hf_ratio * (2.0 - self._frontal_quality)
            if hf_ratio > effective_max_hf_ratio:
                _reject("clench", f"ratio={hf_ratio:.2f} max={effective_max_hf_ratio:.2f}")
                return

        # Guard 2: reject if speech detector flagged active
        speech = frame.get(SpeechResult)
        if self.guard_speech and speech and speech.speech_active:
            _reject("speech")
            return

        # Guard 3: shape validation — reject non-tent-shaped deflections
        if self.guard_shape:
            shape_ok, blink_meta = self._check_shape()
        else:
            shape_ok, blink_meta = True, {}
        if not shape_ok:
            # _check_shape logs details; emit rejection event
            frame.events.append(Event(
                kind="blink_rejected", timestamp=now, confidence=0.0,
                channel="AF7+AF8",
                metadata={"guard": "shape"},
            ))
            return
        self._last_blink_meta = blink_meta

        # Guard 4: matched filter — reject if template match is poor
        if self.guard_template and not self._check_template():
            _reject("template")
            return

        elapsed_ms = (now - self._last_blink_time) * 1000
        if elapsed_ms >= self.refractory_ms:
            self._last_blink_time = now
            amp = blink_meta.get("amplitude_uv", 0.0) if blink_meta else 0.0
            dur = blink_meta.get("duration_ms", 0.0) if blink_meta else 0.0
            self._pending_blinks.append((now, amp))
            self._log.info("ACCEPTED blink: amp=%.1fµV dur=%.0fms elapsed=%.0fms",
                           amp, dur, elapsed_ms)
            if len(self._pending_blinks) == 1:
                self._classify_deadline = now + self.classify_window_ms / 1000
        else:
            self._log.info("REJECTED by refractory: elapsed=%.0fms < %.0fms",
                           elapsed_ms, self.refractory_ms)

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

        # Track temporal HF baseline using 32-sample sliding window every 8 chunks.
        # Larger window (31 diffs) reduces noise ~10x vs per-chunk (3 diffs).
        self._temporal_hf_update_ctr += 1
        if self._temporal_hf_update_ctr >= 8:
            self._temporal_hf_update_ctr = 0
            win = min(32, self._buf_pos if not self._buf_filled else self._BUFFER_SIZE)
            if win >= 8:
                if self._buf_pos >= win:
                    t_seg = self._temporal_buf[self._buf_pos - win:self._buf_pos]
                else:
                    t_seg = np.concatenate([
                        self._temporal_buf[-(win - self._buf_pos):],
                        self._temporal_buf[:self._buf_pos],
                    ])
                t_hf_val = _hf_rms(t_seg)
                # Contamination guard: reject if HF is >3x baseline (clench/speech)
                if len(self._temporal_hf_history) < 8 or t_hf_val < 3.0 * self._temporal_hf_baseline:
                    self._temporal_hf_history.append(t_hf_val)
                    if len(self._temporal_hf_history) >= 8:
                        self._temporal_hf_baseline = float(np.median(self._temporal_hf_history))

        af7_mean = float(np.mean(af7))
        af8_mean = float(np.mean(af8))
        chunk_val = (af7_mean + af8_mean) / 2.0
        crossed = self._is_candidate(af7_mean, af8_mean)

        # Collect raw samples during calibration capture window
        if self._capture_active and (time.time() - self._capture_start) < self._capture_duration:
            self._capture_samples.extend(frontal.tolist())

        # Debug: log significant deflections even if they don't cross threshold
        if chunk_val < -40:
            sd = max(1.4826 * self._baseline_mad, 1.0) if self._baseline_samples >= 128 else 0
            adaptive = (self._baseline_median - self.threshold_sd * sd) if self._baseline_samples >= 128 else None
            self._log.debug(
                "deflection %.1f µV | baseline=%.1f sd=%.1f adaptive_thresh=%s | crossed=%s",
                chunk_val, self._baseline_median, sd,
                f"{adaptive:.1f}" if adaptive is not None else "N/A",
                crossed,
            )

        # Always update baseline using chunk MEAN if not contaminated by artifact.
        # Guard uses chunk MIN (not mean) so that blink-contaminated chunks are
        # rejected even when the chunk mean stays within 3 SDs of baseline.
        # Blink mean ≈ 1-2 SDs below baseline (4-sample chunk; only 1-2 samples
        # are in the dip) → mean-based guard leaks blinks in → baseline drifts
        # negative over long sessions → threshold becomes unreachable.
        # Update baseline using chunk MEAN if it's close to current baseline.
        # Blinks are rejected because their chunk_mean is typically 2-4 SDs deviant.
        # Edge chunks (rising/falling slopes of blinks) may sneak through at 1-2 SDs,
        # but with a 256-entry median window these contaminate <5% of entries —
        # not enough to shift the median significantly. The main defence against
        # long-session drift is threshold_uv as an absolute floor (set by calibration)
        # so MAD changes cannot raise the effective threshold above the calibrated point.
        chunk_mean = chunk_val
        n_samp = len(frontal)
        # Update per-channel baselines alongside the combined baseline
        self._update_channel_baselines(af7_mean, af8_mean)
        if self._baseline_samples < 128:
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
            if self._consecutive_crossed > 0:
                streak = self._consecutive_crossed
                self._consecutive_crossed = 0
                min_chunks = max(2, int(self.min_deflection_ms / 1000 * 256 / max(len(frontal), 1)))
                if streak >= min_chunks:
                    self._log.info(
                        "TRAILING_EDGE streak=%d (min=%d) t=%.3f → running guards",
                        streak, min_chunks, now,
                    )
                    self._try_emit_blink(frame, now)
                else:
                    self._log.debug(
                        "TRAILING_EDGE streak=%d < min=%d → too short, skipped",
                        streak, min_chunks,
                    )

        # Emit events once the classification window expires
        if self._pending_blinks and now >= self._classify_deadline:
            count = len(self._pending_blinks)
            deepest_amp = min(amp for _, amp in self._pending_blinks)
            self._pending_blinks.clear()
            self._log.debug("EMITTING: %d blink(s) in window (deepest=%.1f µV)", count, deepest_amp)

            emit_meta = self._last_blink_meta or {}
            has_secondary = emit_meta.get("secondary_peak", False)

            if count >= 2:
                base_conf = min(1.0, 0.85 + (0.05 if has_secondary else 0.0))
                frame.events.append(Event(
                    kind="double_blink", timestamp=now,
                    confidence=round(base_conf * self._frontal_quality, 2),
                    channel="AF7+AF8",
                    metadata=emit_meta,
                ))
            else:
                base_conf = min(1.0, 0.9 + (0.05 if has_secondary else 0.0))
                frame.events.append(Event(
                    kind="single_blink", timestamp=now,
                    confidence=round(base_conf * self._frontal_quality, 2),
                    channel="AF7+AF8",
                    metadata=emit_meta,
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
