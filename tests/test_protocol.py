import numpy as np
from backend.protocol import (
    MSG_EEG, MSG_PPG, MSG_IMU,
    encode_binary_frame,
    decode_binary_frame,
    encode_metrics,
)


def test_encode_decode_eeg_roundtrip():
    data = np.random.randn(4, 16).astype(np.float32)
    encoded = encode_binary_frame(MSG_EEG, data)
    assert isinstance(encoded, bytes)
    assert encoded[0] == MSG_EEG
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_EEG
    np.testing.assert_array_almost_equal(decoded, data)


def test_encode_decode_ppg_roundtrip():
    data = np.random.randn(3, 8).astype(np.float32)
    encoded = encode_binary_frame(MSG_PPG, data)
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_PPG
    assert decoded.shape == (3, 8)


def test_encode_decode_imu_roundtrip():
    data = np.random.randn(6, 4).astype(np.float32)
    encoded = encode_binary_frame(MSG_IMU, data)
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_IMU
    assert decoded.shape == (6, 4)


def test_binary_frame_header_format():
    data = np.zeros((4, 1), dtype=np.float32)
    encoded = encode_binary_frame(MSG_EEG, data)
    assert encoded[0] == MSG_EEG
    assert len(encoded) == 1 + 2 + 2 + (4 * 1 * 4)  # header + data


def test_encode_metrics():
    metrics = {
        "eeg": {"band_powers": {"alpha": [1.0, 2.0, 3.0, 4.0]}},
        "ppg": {"heart_rate_bpm": 72.5},
    }
    result = encode_metrics(metrics)
    assert isinstance(result, str)
    import json
    parsed = json.loads(result)
    assert parsed["type"] == "metrics"
    assert "timestamp" in parsed
    assert parsed["eeg"]["band_powers"]["alpha"] == [1.0, 2.0, 3.0, 4.0]
