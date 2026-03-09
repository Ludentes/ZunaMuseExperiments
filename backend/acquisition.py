import logging
import time

import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BrainFlowPresets

from backend.config import BoardConfig

log = logging.getLogger("acquisition")


class Acquisition:
    """Manages BrainFlow board connection and data retrieval.

    Handles connection retries, stream drop detection, and graceful reconnection.
    A connected, well-fitted Muse is a valuable resource — we never crash on
    transient BLE failures.
    """

    def __init__(self, config: BoardConfig, max_retries: int = 5, retry_backoff: float = 2.0):
        self.config = config
        self.board_id = config.board_id
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._params = self._build_params(config)
        self.board = BoardShim(self.board_id, self._params)
        self._streaming = False
        self._last_data_time: float = 0.0
        self._consecutive_empty: int = 0

    @staticmethod
    def _build_params(config: BoardConfig) -> BrainFlowInputParams:
        params = BrainFlowInputParams()
        if config.serial_port:
            params.serial_port = config.serial_port
        if config.mac_address:
            params.mac_address = config.mac_address
        return params

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def eeg_channel_indices(self) -> list[int]:
        return BoardShim.get_eeg_channels(self.board_id)

    @property
    def eeg_sampling_rate(self) -> int:
        return BoardShim.get_sampling_rate(self.board_id)

    @property
    def ppg_channel_indices(self) -> list[int]:
        try:
            return BoardShim.get_ppg_channels(
                self.board_id, BrainFlowPresets.ANCILLARY_PRESET.value
            )
        except Exception:
            return []

    @property
    def ppg_sampling_rate(self) -> int:
        try:
            return BoardShim.get_sampling_rate(
                self.board_id, BrainFlowPresets.ANCILLARY_PRESET.value
            )
        except Exception:
            return 0

    @property
    def accel_channel_indices(self) -> list[int]:
        try:
            return BoardShim.get_accel_channels(
                self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value
            )
        except Exception:
            return []

    @property
    def gyro_channel_indices(self) -> list[int]:
        try:
            return BoardShim.get_gyro_channels(
                self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value
            )
        except Exception:
            return []

    @property
    def imu_sampling_rate(self) -> int:
        try:
            return BoardShim.get_sampling_rate(
                self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value
            )
        except Exception:
            return 0

    def start(self):
        """Connect to board with retries. Raises after max_retries exhausted."""
        for attempt in range(1, self.max_retries + 1):
            try:
                # Release any stale session from a previous crash
                if self.board.is_prepared():
                    log.warning("Stale session found — releasing before reconnect")
                    try:
                        self.board.stop_stream()
                    except Exception:
                        pass
                    self.board.release_session()

                log.info("Connecting to board %d (attempt %d/%d)...",
                         self.board_id, attempt, self.max_retries)
                self.board.prepare_session()
                if self.config.enable_ppg:
                    try:
                        self.board.config_board("p50")
                    except Exception:
                        pass
                self.board.start_stream()
                self._streaming = True
                self._last_data_time = time.time()
                self._consecutive_empty = 0
                log.info("Board %d connected and streaming", self.board_id)
                return
            except Exception as e:
                log.warning("Connection attempt %d/%d failed: %s",
                            attempt, self.max_retries, e)
                # Clean up partial state
                try:
                    if self.board.is_prepared():
                        self.board.release_session()
                except Exception:
                    pass
                if attempt < self.max_retries:
                    wait = self.retry_backoff * attempt
                    log.info("Retrying in %.1fs...", wait)
                    time.sleep(wait)
                else:
                    raise

    def stop(self):
        """Gracefully stop streaming and release BLE session."""
        if self._streaming:
            try:
                self.board.stop_stream()
            except Exception as e:
                log.warning("stop_stream error (non-fatal): %s", e)
            self._streaming = False
        if self.board.is_prepared():
            try:
                self.board.release_session()
            except Exception as e:
                log.warning("release_session error (non-fatal): %s", e)

    def reconnect(self) -> bool:
        """Attempt to reconnect after a stream drop. Returns True on success."""
        log.warning("Attempting reconnect...")
        self.stop()
        # Fresh BoardShim — BrainFlow doesn't always recover from a dropped BLE link
        self.board = BoardShim(self.board_id, self._params)
        try:
            self.start()
            return True
        except Exception as e:
            log.error("Reconnect failed: %s", e)
            return False

    @property
    def seconds_since_last_data(self) -> float:
        """Seconds since we last received any data. 0 if never connected."""
        if self._last_data_time == 0:
            return 0.0
        return time.time() - self._last_data_time

    @property
    def stream_healthy(self) -> bool:
        """True if data arrived recently (within 5s)."""
        if not self._streaming:
            return False
        return self.seconds_since_last_data < 5.0

    def get_eeg_data(self) -> np.ndarray | None:
        """Get latest EEG data. Returns (n_channels, n_samples) or None."""
        try:
            data = self.board.get_board_data()
        except Exception as e:
            log.warning("get_board_data failed: %s", e)
            self._consecutive_empty += 1
            return None
        if data.shape[1] == 0:
            self._consecutive_empty += 1
            return None
        self._last_data_time = time.time()
        self._consecutive_empty = 0
        channels = self.eeg_channel_indices
        return data[channels, :].astype(np.float32)

    def get_ppg_data(self) -> np.ndarray | None:
        """Get latest PPG data. Returns (3, n_samples) or None."""
        try:
            data = self.board.get_board_data(
                preset=BrainFlowPresets.ANCILLARY_PRESET.value
            )
            if data.shape[1] == 0:
                return None
            channels = self.ppg_channel_indices
            return data[channels, :].astype(np.float32)
        except Exception:
            return None

    def get_imu_data(self) -> np.ndarray | None:
        """Get latest IMU data. Returns (6, n_samples) or None."""
        try:
            data = self.board.get_board_data(
                preset=BrainFlowPresets.AUXILIARY_PRESET.value
            )
            if data.shape[1] == 0:
                return None
            accel = self.accel_channel_indices
            gyro = self.gyro_channel_indices
            channels = accel + gyro
            return data[channels, :].astype(np.float32)
        except Exception:
            return None
