import time
import numpy as np
from backend.acquisition import Acquisition
from backend.config import BoardConfig


def test_acquisition_synthetic_board():
    """Test acquisition with BrainFlow's synthetic board (no hardware needed)."""
    config = BoardConfig(board_id=-1, enable_ppg=False)  # -1 = SYNTHETIC_BOARD
    acq = Acquisition(config)
    acq.start()

    time.sleep(0.5)  # collect some data

    eeg = acq.get_eeg_data()
    assert eeg is not None
    assert eeg.shape[0] > 0  # has channels
    assert eeg.shape[1] > 0  # has samples

    acq.stop()


def test_acquisition_get_eeg_channels():
    config = BoardConfig(board_id=-1, enable_ppg=False)
    acq = Acquisition(config)
    channels = acq.eeg_channel_indices
    assert len(channels) > 0
    acq.stop()
