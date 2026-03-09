from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from brainflow.data_filter import DataFilter, DetrendOperations, WindowOperations

from backend.pipeline.base import Stage
from backend.pipeline.stages.preprocessing import PreprocessingResult
from backend.pipeline.types import BANDS, BAND_NAMES, CH_NAMES, Cadence, PipelineFrame


RAIL_THRESHOLD = 995.0  # µV


@dataclass
class BandPowerResult:
    band_powers: dict[str, list[float]]
    theta_beta_ratio: list[float]
    frontal_alpha_asymmetry: float


@dataclass
class SignalQualityResult:
    quality: dict[str, float]
    fit_status: str


@dataclass
class HeartRateResult:
    heart_rate_bpm: float
    spo2_percent: float
    hrv_rmssd_ms: float


@dataclass
class HeadMotionResult:
    head_movement: float
    head_pose: tuple[float, float]
    motion_artifact: bool


class BandPowerExtractor(Stage):
    name = "band_power_extractor"
    cadence = Cadence.SLOW

    def __init__(self, bands: dict[str, tuple[float, float]] | None = None):
        self.bands = bands or BANDS

    def process(self, frame: PipelineFrame) -> None:
        prep = frame.get(PreprocessingResult)
        eeg = prep.eeg_filtered if prep else frame.eeg
        if eeg is None:
            return

        sampling_rate = 256
        nfft = DataFilter.get_nearest_power_of_two(sampling_rate)
        if eeg.shape[1] < nfft:
            return

        band_powers: dict[str, list[float]] = {b: [] for b in BAND_NAMES}

        for ch_idx in range(eeg.shape[0]):
            channel_data = eeg[ch_idx].astype(np.float64).copy()
            try:
                DataFilter.detrend(channel_data, DetrendOperations.LINEAR.value)
                psd = DataFilter.get_psd_welch(
                    channel_data, nfft, nfft // 2,
                    sampling_rate, WindowOperations.HANNING.value,
                )
                for band_name in BAND_NAMES:
                    low, high = self.bands[band_name]
                    power = DataFilter.get_band_power(psd, low, high)
                    band_powers[band_name].append(round(float(power), 2))
            except Exception:
                for band_name in BAND_NAMES:
                    band_powers[band_name].append(0.0)

        # Theta/beta ratio
        theta_beta = []
        for i in range(len(band_powers.get("theta", []))):
            theta = band_powers["theta"][i]
            beta = band_powers["beta"][i]
            theta_beta.append(round(theta / beta, 2) if beta > 0 else 0.0)

        # Frontal alpha asymmetry
        alpha = band_powers.get("alpha", [0, 0, 0, 0])
        if len(alpha) >= 4:
            af7_alpha = max(alpha[1], 1e-10)
            af8_alpha = max(alpha[2], 1e-10)
            faa = round(math.log(af8_alpha) - math.log(af7_alpha), 3)
        else:
            faa = 0.0

        frame.set(BandPowerResult(
            band_powers=band_powers,
            theta_beta_ratio=theta_beta,
            frontal_alpha_asymmetry=faa,
        ))


class SignalQualityChecker(Stage):
    name = "signal_quality_checker"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        quality = {}
        for i, name in enumerate(CH_NAMES[:frame.eeg.shape[0]]):
            channel = frame.eeg[i]
            n = len(channel)
            railed = float(np.sum(np.abs(channel) > RAIL_THRESHOLD)) / n
            railed_score = max(0.0, 1.0 - railed * 10)
            std = float(np.std(channel))
            if std < 2.0:
                std_score = 0.2
            elif std > 200.0:
                std_score = 0.3
            else:
                std_score = 1.0
            quality[name] = round(min(railed_score, std_score), 2)

        poor_count = sum(1 for q in quality.values() if q < 0.7)
        if poor_count == 0:
            fit = "good"
        elif poor_count <= 2:
            fit = "adjust"
        else:
            fit = "poor"

        frame.set(SignalQualityResult(quality=quality, fit_status=fit))


class HeartRateExtractor(Stage):
    name = "heart_rate_extractor"
    cadence = Cadence.SLOW

    def __init__(self):
        self._ppg_accumulator: np.ndarray | None = None
        self._max_samples = 1280  # 20s at 64Hz

    def process(self, frame: PipelineFrame) -> None:
        if frame.ppg is None:
            return

        # Accumulate PPG across ticks
        if self._ppg_accumulator is not None:
            self._ppg_accumulator = np.concatenate(
                [self._ppg_accumulator, frame.ppg], axis=1
            )
        else:
            self._ppg_accumulator = frame.ppg.copy()

        if self._ppg_accumulator.shape[1] > self._max_samples:
            self._ppg_accumulator = self._ppg_accumulator[:, -self._max_samples:]

        if self._ppg_accumulator.shape[1] < 1024:
            return

        ppg = self._ppg_accumulator
        ppg_ir = ppg[1].astype(np.float64)
        ppg_red = ppg[0].astype(np.float64)

        try:
            hr = float(DataFilter.get_heart_rate(ppg_ir, ppg_red, 64, 1024))
        except Exception:
            hr = 0.0

        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg_ir, ppg_red, 64))
        except Exception:
            spo2 = 0.0

        # HRV RMSSD from peak detection
        hrv_rmssd = 0.0
        try:
            ppg_filt = ppg_ir.copy()
            DataFilter.detrend(ppg_filt, DetrendOperations.LINEAR.value)
            DataFilter.perform_bandpass(ppg_filt, 64, 0.5, 4.0, 4, 0, 0.0)
            diff = np.diff(ppg_filt)
            peaks = []
            for i in range(1, len(diff)):
                if diff[i - 1] > 0 and diff[i] <= 0:
                    peaks.append(i)
            if len(peaks) >= 3:
                rr_intervals = np.diff(peaks) / 64.0 * 1000.0
                rr_intervals = rr_intervals[(rr_intervals > 300) & (rr_intervals < 2000)]
                if len(rr_intervals) >= 2:
                    successive_diffs = np.diff(rr_intervals)
                    hrv_rmssd = float(np.sqrt(np.mean(successive_diffs ** 2)))
        except Exception:
            hrv_rmssd = 0.0

        frame.set(HeartRateResult(
            heart_rate_bpm=round(hr, 1),
            spo2_percent=round(spo2, 1),
            hrv_rmssd_ms=round(hrv_rmssd, 1),
        ))


class HeadMotionExtractor(Stage):
    name = "head_motion_extractor"
    cadence = Cadence.SLOW

    def process(self, frame: PipelineFrame) -> None:
        if frame.imu is None or frame.imu.shape[1] < 2:
            return

        accel = frame.imu[:3]

        # Movement: RMS of per-axis std-dev
        std_per_axis = np.std(accel, axis=1)
        movement = round(float(np.sqrt(np.mean(std_per_axis ** 2))), 4)

        # Pose: pitch/roll from mean accel
        mean_accel = np.mean(accel, axis=1)
        ax, ay, az = float(mean_accel[0]), float(mean_accel[1]), float(mean_accel[2])
        pitch = round(math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2))), 1)
        roll = round(math.degrees(math.atan2(ay, math.sqrt(ax**2 + az**2))), 1)

        frame.set(HeadMotionResult(
            head_movement=movement,
            head_pose=(pitch, roll),
            motion_artifact=movement > 0.05,
        ))


@dataclass
class ConcentrationResult:
    concentration_score: float   # 0.0 - 1.0 (from MINDFULNESS model)
    relaxation_score: float      # 0.0 - 1.0 (from RESTFULNESS model)


class ConcentrationScorer(Stage):
    name = "concentration_scorer"
    cadence = Cadence.SLOW

    def __init__(self):
        from brainflow.ml_model import MLModel, BrainFlowModelParams, BrainFlowMetrics, BrainFlowClassifiers
        mind_params = BrainFlowModelParams(BrainFlowMetrics.MINDFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
        rest_params = BrainFlowModelParams(BrainFlowMetrics.RESTFULNESS, BrainFlowClassifiers.DEFAULT_CLASSIFIER)
        self._mindfulness = MLModel(mind_params)
        self._restfulness = MLModel(rest_params)
        # BrainFlow MLModel is process-global; release first to avoid
        # ANOTHER_CLASSIFIER_IS_PREPARED_ERROR when re-creating the stage.
        try:
            self._mindfulness.release()
        except Exception:
            pass
        self._mindfulness.prepare()
        try:
            self._restfulness.release()
        except Exception:
            pass
        self._restfulness.prepare()

    def release(self):
        """Release BrainFlow ML models (call on shutdown)."""
        try:
            self._mindfulness.release()
        except Exception:
            pass
        try:
            self._restfulness.release()
        except Exception:
            pass

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        # MLModel expects normalized band powers as input
        # get_custom_band_powers returns relative powers, but we have absolute
        # Use our band powers and normalize them
        band_names_ordered = ["delta", "theta", "alpha", "beta", "gamma"]
        total = 0.0
        sums = []
        for b in band_names_ordered:
            s = sum(bp.band_powers.get(b, [0.0]))
            sums.append(s)
            total += s

        if total <= 0:
            return

        features = np.array([s / total for s in sums], dtype=np.float64)

        try:
            result = self._mindfulness.predict(features)
            concentration = float(result.item() if hasattr(result, 'item') else result)
        except Exception:
            concentration = 0.0

        try:
            result = self._restfulness.predict(features)
            relaxation = float(result.item() if hasattr(result, 'item') else result)
        except Exception:
            relaxation = 0.0

        frame.set(ConcentrationResult(
            concentration_score=round(concentration, 3),
            relaxation_score=round(relaxation, 3),
        ))
