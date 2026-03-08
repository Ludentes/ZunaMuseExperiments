import numpy as np
from backend.processing import (
    compute_band_powers,
    compute_signal_quality,
    compute_fit_status,
    compute_head_movement,
    compute_head_pose,
)


def test_compute_band_powers():
    rng = np.random.default_rng(42)
    data = rng.standard_normal((4, 512)).astype(np.float32) * 50
    result = compute_band_powers(data, sampling_rate=256)
    assert "delta" in result
    assert "theta" in result
    assert "alpha" in result
    assert "beta" in result
    assert "gamma" in result
    assert len(result["alpha"]) == 4


def test_compute_signal_quality_good_signal():
    rng = np.random.default_rng(42)
    data = rng.standard_normal((4, 256)).astype(np.float32) * 30
    quality = compute_signal_quality(data)
    assert len(quality) == 4
    for q in quality.values():
        assert 0.0 <= q <= 1.0


def test_compute_signal_quality_railed_signal():
    data = np.full((4, 256), 999.0, dtype=np.float32)
    quality = compute_signal_quality(data)
    for q in quality.values():
        assert q < 0.3


def test_compute_fit_status():
    assert compute_fit_status({"TP9": 0.9, "AF7": 0.8, "AF8": 0.85, "TP10": 0.95}) == "good"
    assert compute_fit_status({"TP9": 0.9, "AF7": 0.3, "AF8": 0.85, "TP10": 0.95}) == "adjust"
    assert compute_fit_status({"TP9": 0.2, "AF7": 0.3, "AF8": 0.1, "TP10": 0.95}) == "poor"


def test_compute_head_movement():
    still = np.array([[0.0], [0.0], [9.81]], dtype=np.float32)
    assert compute_head_movement(still) < 0.1

    moving = np.array([[8.0], [6.0], [9.81]], dtype=np.float32)
    assert compute_head_movement(moving) > 0.3


def test_compute_head_pose():
    accel = np.array([[0.0], [0.0], [9.81]], dtype=np.float32)
    pitch, roll = compute_head_pose(accel)
    assert abs(pitch) < 2.0
    assert abs(roll) < 2.0
