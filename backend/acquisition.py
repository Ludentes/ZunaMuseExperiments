import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BrainFlowPresets

from backend.config import BoardConfig


class Acquisition:
    """Manages BrainFlow board connection and data retrieval."""

    def __init__(self, config: BoardConfig):
        self.config = config
        self.board_id = config.board_id
        params = BrainFlowInputParams()
        if config.serial_port:
            params.serial_port = config.serial_port
        if config.mac_address:
            params.mac_address = config.mac_address
        self.board = BoardShim(self.board_id, params)
        self._streaming = False

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
        self.board.prepare_session()
        if self.config.enable_ppg:
            try:
                self.board.config_board("p50")
            except Exception:
                pass  # not all boards support this
        self.board.start_stream()
        self._streaming = True

    def stop(self):
        if self._streaming:
            self.board.stop_stream()
            self.board.release_session()
            self._streaming = False

    def get_eeg_data(self) -> np.ndarray | None:
        """Get latest EEG data. Returns (n_channels, n_samples) or None."""
        data = self.board.get_board_data()
        if data.shape[1] == 0:
            return None
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
