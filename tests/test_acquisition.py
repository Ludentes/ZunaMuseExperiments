import time
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


def test_acquisition_stream_health():
    """Test stream health monitoring."""
    config = BoardConfig(board_id=-1, enable_ppg=False)
    acq = Acquisition(config)
    acq.start()

    time.sleep(0.3)
    acq.get_eeg_data()  # trigger data fetch to set _last_data_time

    assert acq.is_streaming
    assert acq.stream_healthy
    assert acq.seconds_since_last_data < 2.0

    acq.stop()
    assert not acq.is_streaming


def test_acquisition_reconnect():
    """Test reconnect creates fresh session."""
    config = BoardConfig(board_id=-1, enable_ppg=False)
    acq = Acquisition(config)
    acq.start()

    time.sleep(0.3)
    eeg1 = acq.get_eeg_data()
    assert eeg1 is not None

    # Reconnect should succeed on synthetic board
    success = acq.reconnect()
    assert success
    assert acq.is_streaming

    time.sleep(0.3)
    eeg2 = acq.get_eeg_data()
    assert eeg2 is not None

    acq.stop()


def test_acquisition_graceful_stop():
    """Stop should not raise even if called multiple times."""
    config = BoardConfig(board_id=-1, enable_ppg=False)
    acq = Acquisition(config)
    acq.start()
    acq.stop()
    acq.stop()  # second stop should be safe
