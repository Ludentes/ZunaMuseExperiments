# EEG Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time EEG dashboard for Muse 2 with Python backend (BrainFlow + websockets) and TanStack Start SPA frontend (React + webgl-plot + shadcn/ui).

**Architecture:** Python backend acquires all sensor data (EEG 256Hz, PPG 64Hz, IMU 52Hz) via BrainFlow, computes derived metrics, and streams everything over a single WebSocket. Browser frontend displays waveforms via WebGL (bypassing React render cycle) and metrics via React state updates at 1-4Hz. See `docs/plans/2026-03-08-dashboard-architecture.md` for full spec.

**Tech Stack:** Python 3.12, BrainFlow (compiled with --ble), websockets, numpy, MNE | TanStack Start (SPA mode), React, shadcn/ui, webgl-plot, react-use-websocket, pnpm

---

## Phase 1: Python Backend — Data Acquisition + WebSocket

### Task 1: Project scaffolding + config

**Files:**
- Create: `backend/config.py`
- Create: `backend/__init__.py`
- Create: `backend/requirements.txt`

**Step 1: Create backend directory and requirements**

```bash
mkdir -p backend
```

`backend/requirements.txt`:
```
websockets>=14.0
numpy>=1.26
mne>=1.7
```

**Step 2: Write config module**

`backend/config.py`:
```python
from dataclasses import dataclass, field


@dataclass
class BoardConfig:
    board_id: int = 38  # MUSE_2_BOARD
    serial_port: str = ""
    mac_address: str = ""
    enable_ppg: bool = True  # send "p50" to enable PPG + 5th EEG ch


@dataclass
class FilterConfig:
    highpass: float = 0.5
    lowpass: float = 45.0
    notch: float = 50.0  # 0 to disable


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 8765
    eeg_batch_interval: float = 0.0625  # 16ms (~60fps)
    metrics_interval: float = 0.5  # 2Hz
    recording_dir: str = "recordings"


@dataclass
class Config:
    board: BoardConfig = field(default_factory=BoardConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
```

**Step 3: Create empty init**

`backend/__init__.py`: empty file

**Step 4: Install dependencies**

```bash
cd /home/newub/w/zyphraexps && pip install websockets numpy mne
```

**Step 5: Verify imports**

```bash
python3 -c "from backend.config import Config; c = Config(); print(f'Board: {c.board.board_id}, Port: {c.server.port}')"
```

Expected: `Board: 38, Port: 8765`

**Step 6: Commit**

```bash
git init && git add backend/ && git commit -m "feat: add backend config module"
```

---

### Task 2: Protocol — binary frame encoding + JSON messages

**Files:**
- Create: `backend/protocol.py`
- Create: `tests/test_protocol.py`

**Step 1: Write the failing test**

`tests/__init__.py`: empty file

`tests/test_protocol.py`:
```python
import numpy as np
from backend.protocol import (
    MSG_EEG, MSG_PPG, MSG_IMU,
    encode_binary_frame,
    decode_binary_frame,
    encode_metrics,
)


def test_encode_decode_eeg_roundtrip():
    data = np.random.randn(4, 16).astype(np.float32)  # 4 channels, 16 samples
    encoded = encode_binary_frame(MSG_EEG, data)
    assert isinstance(encoded, bytes)
    assert encoded[0] == MSG_EEG
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_EEG
    np.testing.assert_array_almost_equal(decoded, data)


def test_encode_decode_ppg_roundtrip():
    data = np.random.randn(3, 8).astype(np.float32)  # 3 channels, 8 samples
    encoded = encode_binary_frame(MSG_PPG, data)
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_PPG
    assert decoded.shape == (3, 8)


def test_encode_decode_imu_roundtrip():
    data = np.random.randn(6, 4).astype(np.float32)  # 6 channels, 4 samples
    encoded = encode_binary_frame(MSG_IMU, data)
    msg_type, decoded = decode_binary_frame(encoded)
    assert msg_type == MSG_IMU
    assert decoded.shape == (6, 4)


def test_binary_frame_header_format():
    data = np.zeros((4, 1), dtype=np.float32)
    encoded = encode_binary_frame(MSG_EEG, data)
    # byte 0: message type
    # bytes 1-2: num channels (uint16 LE)
    # bytes 3-4: num samples (uint16 LE)
    # rest: float32 data
    assert encoded[0] == MSG_EEG
    assert len(encoded) == 1 + 2 + 2 + (4 * 1 * 4)


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
```

**Step 2: Run test to verify it fails**

```bash
cd /home/newub/w/zyphraexps && python3 -m pytest tests/test_protocol.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.protocol'`

**Step 3: Write implementation**

`backend/protocol.py`:
```python
import json
import struct
import time
import numpy as np

MSG_EEG: int = 0x01
MSG_PPG: int = 0x02
MSG_IMU: int = 0x03

# Header: 1 byte type + 2 bytes num_channels + 2 bytes num_samples
_HEADER_SIZE = 5
_HEADER_STRUCT = struct.Struct("<BHH")


def encode_binary_frame(msg_type: int, data: np.ndarray) -> bytes:
    """Encode a numpy array (channels × samples) into a binary WebSocket frame.

    Format: [type:u8][num_channels:u16le][num_samples:u16le][data:f32le...]
    """
    num_channels, num_samples = data.shape
    header = _HEADER_STRUCT.pack(msg_type, num_channels, num_samples)
    return header + data.astype(np.float32).tobytes()


def decode_binary_frame(raw: bytes) -> tuple[int, np.ndarray]:
    """Decode a binary WebSocket frame back into (msg_type, numpy array)."""
    msg_type, num_channels, num_samples = _HEADER_STRUCT.unpack_from(raw, 0)
    data = np.frombuffer(raw, dtype=np.float32, offset=_HEADER_SIZE)
    return msg_type, data.reshape(num_channels, num_samples)


def encode_metrics(metrics: dict) -> str:
    """Wrap metrics dict in a JSON envelope with type and timestamp."""
    envelope = {"type": "metrics", "timestamp": time.time()}
    envelope.update(metrics)
    return json.dumps(envelope)
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_protocol.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add backend/protocol.py tests/ && git commit -m "feat: add binary frame protocol with encode/decode"
```

---

### Task 3: Acquisition module — BrainFlow wrapper

**Files:**
- Create: `backend/acquisition.py`
- Create: `tests/test_acquisition.py`

**Step 1: Write the failing test (uses BrainFlow synthetic board)**

`tests/test_acquisition.py`:
```python
import asyncio
import numpy as np
from backend.acquisition import Acquisition
from backend.config import BoardConfig


def test_acquisition_synthetic_board():
    """Test acquisition with BrainFlow's synthetic board (no hardware needed)."""
    config = BoardConfig(board_id=-1, enable_ppg=False)  # -1 = SYNTHETIC_BOARD
    acq = Acquisition(config)
    acq.start()

    import time
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
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_acquisition.py -v
```
Expected: FAIL — `cannot import name 'Acquisition'`

**Step 3: Write implementation**

`backend/acquisition.py`:
```python
import numpy as np
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BrainFlowPresets
from brainflow.data_filter import DataFilter

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
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_acquisition.py -v
```
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add backend/acquisition.py tests/test_acquisition.py && git commit -m "feat: add BrainFlow acquisition wrapper"
```

---

### Task 4: Processing module — DSP + derived metrics

**Files:**
- Create: `backend/processing.py`
- Create: `tests/test_processing.py`

**Step 1: Write the failing test**

`tests/test_processing.py`:
```python
import numpy as np
from backend.processing import (
    compute_band_powers,
    compute_signal_quality,
    compute_fit_status,
    compute_head_movement,
    compute_head_pose,
)


def test_compute_band_powers():
    # Generate 2 seconds of synthetic EEG at 256Hz
    rng = np.random.default_rng(42)
    data = rng.standard_normal((4, 512)).astype(np.float32) * 50
    result = compute_band_powers(data, sampling_rate=256)
    assert "delta" in result
    assert "theta" in result
    assert "alpha" in result
    assert "beta" in result
    assert "gamma" in result
    assert len(result["alpha"]) == 4  # one value per channel


def test_compute_signal_quality_good_signal():
    rng = np.random.default_rng(42)
    data = rng.standard_normal((4, 256)).astype(np.float32) * 30  # reasonable range
    quality = compute_signal_quality(data)
    assert len(quality) == 4
    for q in quality.values():
        assert 0.0 <= q <= 1.0


def test_compute_signal_quality_railed_signal():
    data = np.full((4, 256), 999.0, dtype=np.float32)  # railed
    quality = compute_signal_quality(data)
    for q in quality.values():
        assert q < 0.3  # poor quality


def test_compute_fit_status():
    assert compute_fit_status({"TP9": 0.9, "AF7": 0.8, "AF8": 0.85, "TP10": 0.95}) == "good"
    assert compute_fit_status({"TP9": 0.9, "AF7": 0.3, "AF8": 0.85, "TP10": 0.95}) == "adjust"
    assert compute_fit_status({"TP9": 0.2, "AF7": 0.3, "AF8": 0.1, "TP10": 0.95}) == "poor"


def test_compute_head_movement():
    # Perfectly still: accel = [0, 0, 9.81] (gravity only)
    still = np.array([[0.0], [0.0], [9.81]], dtype=np.float32)
    assert compute_head_movement(still) < 0.1

    # Moving: significant deviation from gravity
    moving = np.array([[5.0], [3.0], [9.81]], dtype=np.float32)
    assert compute_head_movement(moving) > 0.3


def test_compute_head_pose():
    # Level head: accel = [0, 0, 9.81]
    accel = np.array([[0.0], [0.0], [9.81]], dtype=np.float32)
    pitch, roll = compute_head_pose(accel)
    assert abs(pitch) < 2.0  # roughly level
    assert abs(roll) < 2.0
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_processing.py -v
```
Expected: FAIL

**Step 3: Write implementation**

`backend/processing.py`:
```python
import math
import numpy as np
from brainflow.data_filter import DataFilter

CH_NAMES = ["TP9", "AF7", "AF8", "TP10"]
BAND_NAMES = ["delta", "theta", "alpha", "beta", "gamma"]

# Band frequency ranges (Hz)
BANDS = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}

GRAVITY = 9.81
RAIL_THRESHOLD = 995.0  # uV, close to ±1000


def compute_band_powers(
    eeg: np.ndarray, sampling_rate: int = 256
) -> dict[str, list[float]]:
    """Compute average band powers per channel.

    Args:
        eeg: (n_channels, n_samples) array
        sampling_rate: Hz

    Returns:
        Dict with band names as keys, lists of per-channel power as values.
    """
    result = {band: [] for band in BAND_NAMES}
    for ch_idx in range(eeg.shape[0]):
        channel_data = eeg[ch_idx].copy()
        try:
            bands = DataFilter.get_avg_band_powers(
                DataFilter.get_psd_welch(
                    channel_data,
                    256,  # nfft
                    256 // 2,  # overlap
                    sampling_rate,
                    2,  # hamming window
                )
            )
            # bands[0] = [delta, theta, alpha, beta, gamma] powers
            for i, band_name in enumerate(BAND_NAMES):
                result[band_name].append(float(bands[0][i]))
        except Exception:
            for band_name in BAND_NAMES:
                result[band_name].append(0.0)
    return result


def compute_signal_quality(
    eeg: np.ndarray,
) -> dict[str, float]:
    """Compute 0-1 signal quality score per channel.

    Checks: railed %, std dev range, flatline detection.
    """
    quality = {}
    for i, name in enumerate(CH_NAMES[: eeg.shape[0]]):
        channel = eeg[i]
        n = len(channel)
        if n == 0:
            quality[name] = 0.0
            continue

        # Railed percentage
        railed = np.sum(np.abs(channel) > RAIL_THRESHOLD) / n
        railed_score = max(0.0, 1.0 - railed * 10)  # >10% railed = 0

        # Std dev check
        std = float(np.std(channel))
        if std < 2.0:
            std_score = 0.2  # flatline / not on head
        elif std > 200.0:
            std_score = 0.3  # excessive artifact
        else:
            std_score = 1.0

        quality[name] = round(min(railed_score, std_score), 2)
    return quality


def compute_fit_status(quality: dict[str, float]) -> str:
    """Determine overall headband fit from per-channel quality scores."""
    poor_count = sum(1 for q in quality.values() if q < 0.7)
    if poor_count == 0:
        return "good"
    elif poor_count <= 2:
        return "adjust"
    else:
        return "poor"


def compute_theta_beta_ratio(band_powers: dict[str, list[float]]) -> list[float]:
    """Compute theta/beta ratio per channel. Higher = less focused."""
    ratios = []
    for i in range(len(band_powers.get("theta", []))):
        theta = band_powers["theta"][i]
        beta = band_powers["beta"][i]
        ratios.append(round(theta / beta, 2) if beta > 0 else 0.0)
    return ratios


def compute_frontal_alpha_asymmetry(band_powers: dict[str, list[float]]) -> float:
    """Compute FAA = log(alpha_AF8) - log(alpha_AF7).

    Positive = more left-frontal alpha = approach/positive valence.
    """
    alpha = band_powers.get("alpha", [0, 0, 0, 0])
    if len(alpha) < 4:
        return 0.0
    af7_alpha = max(alpha[1], 1e-10)  # index 1 = AF7
    af8_alpha = max(alpha[2], 1e-10)  # index 2 = AF8
    return round(math.log(af8_alpha) - math.log(af7_alpha), 3)


def compute_head_movement(accel: np.ndarray) -> float:
    """Compute head movement magnitude from accelerometer.

    Returns deviation of accel vector from gravity (0 = still).
    """
    # Mean acceleration vector across samples
    mean_accel = np.mean(accel, axis=1)  # (3,)
    magnitude = float(np.linalg.norm(mean_accel))
    deviation = abs(magnitude - GRAVITY) / GRAVITY
    return round(deviation, 3)


def compute_head_pose(accel: np.ndarray) -> tuple[float, float]:
    """Compute pitch and roll from accelerometer (degrees).

    Simple tilt estimation from gravity vector.
    """
    mean_accel = np.mean(accel, axis=1)
    ax, ay, az = float(mean_accel[0]), float(mean_accel[1]), float(mean_accel[2])
    pitch = math.degrees(math.atan2(ax, math.sqrt(ay**2 + az**2)))
    roll = math.degrees(math.atan2(ay, math.sqrt(ax**2 + az**2)))
    return round(pitch, 1), round(roll, 1)


def build_metrics(
    eeg: np.ndarray | None,
    ppg: np.ndarray | None,
    imu: np.ndarray | None,
    sampling_rate: int = 256,
) -> dict:
    """Build the full metrics JSON payload from sensor data."""
    metrics: dict = {}

    if eeg is not None and eeg.shape[1] >= 256:
        band_powers = compute_band_powers(eeg, sampling_rate)
        quality = compute_signal_quality(eeg)
        metrics["eeg"] = {
            "band_powers": band_powers,
            "theta_beta_ratio": compute_theta_beta_ratio(band_powers),
            "frontal_alpha_asymmetry": compute_frontal_alpha_asymmetry(band_powers),
            "signal_quality": quality,
            "fit_status": compute_fit_status(quality),
        }

    if ppg is not None and ppg.shape[1] >= 64:
        try:
            hr = float(DataFilter.get_heart_rate(ppg[0], 64, 64, 3))
        except Exception:
            hr = 0.0
        try:
            spo2 = float(DataFilter.get_oxygen_level(ppg[:2], 64, 10))
        except Exception:
            spo2 = 0.0
        metrics["ppg"] = {
            "heart_rate_bpm": round(hr, 1),
            "spo2_percent": round(spo2, 1),
            "hrv_rmssd_ms": 0.0,  # TODO: implement RR interval extraction
        }

    if imu is not None and imu.shape[1] > 0:
        accel = imu[:3]  # first 3 rows = accel
        movement = compute_head_movement(accel)
        pitch, roll = compute_head_pose(accel)
        metrics["imu"] = {
            "head_movement": movement,
            "head_pose": {"pitch": pitch, "roll": roll},
            "motion_artifact": movement > 0.3,
            "jaw_clench": False,  # TODO: combine EEG + accel detection
        }

    return metrics
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_processing.py -v
```
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add backend/processing.py tests/test_processing.py && git commit -m "feat: add DSP processing module with band powers, quality, IMU metrics"
```

---

### Task 5: WebSocket server — main entry point

**Files:**
- Create: `backend/main.py`

**Step 1: Write the server**

`backend/main.py`:
```python
import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import websockets

from backend.acquisition import Acquisition
from backend.config import Config
from backend.processing import build_metrics
from backend.protocol import (
    MSG_EEG, MSG_PPG, MSG_IMU,
    encode_binary_frame,
    encode_metrics,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eeg-server")


class EEGServer:
    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.acq: Acquisition | None = None
        self.clients: set[websockets.WebSocketServerProtocol] = set()
        self._running = False
        self._ppg_enabled = self.config.board.enable_ppg
        self._imu_enabled = True
        self._recording = False
        self._eeg_buffer = []
        self._ppg_buffer = []
        self._imu_buffer = []

    async def start(self):
        self.acq = Acquisition(self.config.board)
        self.acq.start()
        self._running = True
        log.info(
            "BrainFlow started — board %d, EEG %dHz",
            self.config.board.board_id,
            self.acq.eeg_sampling_rate,
        )

        async with websockets.serve(
            self._handle_client,
            self.config.server.host,
            self.config.server.port,
        ):
            log.info("WebSocket server on ws://%s:%d", self.config.server.host, self.config.server.port)
            await asyncio.gather(
                self._stream_loop(),
                self._metrics_loop(),
                asyncio.Future(),  # run forever
            )

    async def _handle_client(self, ws):
        self.clients.add(ws)
        log.info("Client connected (%d total)", len(self.clients))
        try:
            async for message in ws:
                await self._handle_command(ws, message)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log.info("Client disconnected (%d total)", len(self.clients))

    async def _handle_command(self, ws, message: str):
        try:
            cmd = json.loads(message)
        except json.JSONDecodeError:
            return

        action = cmd.get("cmd")
        if action == "enable_ppg":
            self._ppg_enabled = cmd.get("enabled", True)
        elif action == "enable_imu":
            self._imu_enabled = cmd.get("enabled", True)
        elif action == "set_filter":
            self.config.filter.highpass = cmd.get("highpass", self.config.filter.highpass)
            self.config.filter.lowpass = cmd.get("lowpass", self.config.filter.lowpass)
            self.config.filter.notch = cmd.get("notch", self.config.filter.notch)
        elif action == "start_recording":
            self._recording = True
            log.info("Recording started")
        elif action == "stop_recording":
            self._recording = False
            log.info("Recording stopped")

    async def _broadcast_binary(self, data: bytes):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _broadcast_text(self, data: str):
        if not self.clients:
            return
        websockets.broadcast(self.clients, data)

    async def _stream_loop(self):
        """Poll BrainFlow and broadcast binary frames at ~60fps."""
        interval = self.config.server.eeg_batch_interval
        while self._running:
            if self.acq is None:
                await asyncio.sleep(interval)
                continue

            eeg = self.acq.get_eeg_data()
            if eeg is not None and eeg.shape[1] > 0:
                self._eeg_buffer.append(eeg)
                await self._broadcast_binary(encode_binary_frame(MSG_EEG, eeg))

            if self._ppg_enabled:
                ppg = self.acq.get_ppg_data()
                if ppg is not None and ppg.shape[1] > 0:
                    self._ppg_buffer.append(ppg)
                    await self._broadcast_binary(encode_binary_frame(MSG_PPG, ppg))

            if self._imu_enabled:
                imu = self.acq.get_imu_data()
                if imu is not None and imu.shape[1] > 0:
                    self._imu_buffer.append(imu)
                    await self._broadcast_binary(encode_binary_frame(MSG_IMU, imu))

            await asyncio.sleep(interval)

    async def _metrics_loop(self):
        """Compute and broadcast derived metrics at configured rate."""
        interval = self.config.server.metrics_interval
        while self._running:
            await asyncio.sleep(interval)

            # Concatenate buffered data for metrics computation
            eeg = (
                np.concatenate(self._eeg_buffer, axis=1)
                if self._eeg_buffer
                else None
            )
            ppg = (
                np.concatenate(self._ppg_buffer, axis=1)
                if self._ppg_buffer
                else None
            )
            imu = (
                np.concatenate(self._imu_buffer, axis=1)
                if self._imu_buffer
                else None
            )

            # Clear buffers
            self._eeg_buffer.clear()
            self._ppg_buffer.clear()
            self._imu_buffer.clear()

            sr = self.acq.eeg_sampling_rate if self.acq else 256
            metrics = build_metrics(eeg, ppg, imu, sr)
            if metrics:
                await self._broadcast_text(encode_metrics(metrics))

    def shutdown(self):
        self._running = False
        if self.acq:
            self.acq.stop()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EEG Dashboard Backend")
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic board (no hardware needed)",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    config = Config()
    config.server.port = args.port
    if args.synthetic:
        config.board.board_id = -1  # SYNTHETIC_BOARD
        config.board.enable_ppg = False

    server = EEGServer(config)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        log.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
```

**Step 2: Test with synthetic board**

```bash
python3 -m backend.main --synthetic --port 8765
```

In another terminal:
```bash
python3 -c "
import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8765') as ws:
        for i in range(10):
            msg = await ws.recv()
            if isinstance(msg, bytes):
                print(f'Binary frame: {len(msg)} bytes, type=0x{msg[0]:02x}')
            else:
                data = json.loads(msg)
                print(f'JSON: type={data[\"type\"]}, keys={list(data.keys())}')
asyncio.run(test())
"
```

Expected: Mix of binary frames (0x01 EEG) and JSON metrics messages

**Step 3: Commit**

```bash
git add backend/main.py && git commit -m "feat: add WebSocket server with streaming and metrics broadcast"
```

---

## Phase 2: Frontend — TanStack Start SPA

### Task 6: Scaffold TanStack Start project

**Step 1: Create the frontend app**

```bash
cd /home/newub/w/zyphraexps && pnpm create @tanstack/start frontend
```

Follow prompts: React, TypeScript, SPA mode.

**Step 2: Install dependencies**

```bash
cd /home/newub/w/zyphraexps/frontend && pnpm add react-use-websocket webgl-plot && pnpm add -D @types/node
```

**Step 3: Install shadcn/ui**

```bash
cd /home/newub/w/zyphraexps/frontend && pnpm dlx shadcn@latest init
```

Choose: New York style, dark theme, slate color.

**Step 4: Add shadcn components we'll need**

```bash
pnpm dlx shadcn@latest add button card badge slider switch separator
```

**Step 5: Verify dev server runs**

```bash
pnpm dev
```

Visit http://localhost:3000 — should see TanStack Start default page.

**Step 6: Commit**

```bash
cd /home/newub/w/zyphraexps && git add frontend/ && git commit -m "feat: scaffold TanStack Start SPA with shadcn/ui and webgl-plot"
```

---

### Task 7: Protocol + ring buffer (TypeScript)

**Files:**
- Create: `frontend/app/lib/protocol.ts`
- Create: `frontend/app/lib/ringBuffer.ts`

**Step 1: Write protocol constants and decoder**

`frontend/app/lib/protocol.ts`:
```typescript
export const MSG_EEG = 0x01;
export const MSG_PPG = 0x02;
export const MSG_IMU = 0x03;

export const EEG_CHANNELS = 4;
export const PPG_CHANNELS = 3;
export const IMU_CHANNELS = 6;

export const CHANNEL_NAMES = ["TP9", "AF7", "AF8", "TP10"] as const;

export interface DecodedFrame {
  type: number;
  channels: number;
  samples: number;
  data: Float32Array; // flat: channels × samples, row-major
}

export function decodeBinaryFrame(buffer: ArrayBuffer): DecodedFrame {
  const view = new DataView(buffer);
  const type = view.getUint8(0);
  const channels = view.getUint16(1, true); // little-endian
  const samples = view.getUint16(3, true);
  const data = new Float32Array(buffer, 5); // offset past 5-byte header
  return { type, channels, samples, data };
}

/** Extract one channel from a decoded frame (row-major layout). */
export function getChannel(frame: DecodedFrame, channelIndex: number): Float32Array {
  const offset = channelIndex * frame.samples;
  return frame.data.subarray(offset, offset + frame.samples);
}

export interface Metrics {
  type: "metrics";
  timestamp: number;
  eeg?: {
    band_powers: Record<string, number[]>;
    theta_beta_ratio: number[];
    frontal_alpha_asymmetry: number;
    signal_quality: Record<string, number>;
    fit_status: "good" | "adjust" | "poor";
  };
  ppg?: {
    heart_rate_bpm: number;
    spo2_percent: number;
    hrv_rmssd_ms: number;
  };
  imu?: {
    head_movement: number;
    head_pose: { pitch: number; roll: number };
    motion_artifact: boolean;
    jaw_clench: boolean;
  };
  session?: {
    recording: boolean;
    duration_sec: number;
    filename: string | null;
  };
}
```

**Step 2: Write ring buffer**

`frontend/app/lib/ringBuffer.ts`:
```typescript
/**
 * Fixed-size ring buffer backed by Float32Array.
 * Used for waveform display — new samples overwrite oldest.
 */
export class RingBuffer {
  private buffer: Float32Array;
  private writePos: number = 0;
  private _filled: boolean = false;

  constructor(public readonly capacity: number) {
    this.buffer = new Float32Array(capacity);
  }

  /** Push new samples into the buffer. */
  push(samples: Float32Array | number[]): void {
    for (let i = 0; i < samples.length; i++) {
      this.buffer[this.writePos] = samples[i];
      this.writePos = (this.writePos + 1) % this.capacity;
      if (this.writePos === 0) this._filled = true;
    }
  }

  /** Get the buffer contents in chronological order (oldest first). */
  getOrdered(): Float32Array {
    if (!this._filled) {
      return this.buffer.subarray(0, this.writePos);
    }
    const result = new Float32Array(this.capacity);
    const tail = this.capacity - this.writePos;
    result.set(this.buffer.subarray(this.writePos), 0);
    result.set(this.buffer.subarray(0, this.writePos), tail);
    return result;
  }

  /** Number of samples currently stored. */
  get length(): number {
    return this._filled ? this.capacity : this.writePos;
  }

  clear(): void {
    this.buffer.fill(0);
    this.writePos = 0;
    this._filled = false;
  }
}
```

**Step 3: Commit**

```bash
git add frontend/app/lib/ && git commit -m "feat: add WS protocol decoder and ring buffer"
```

---

### Task 8: WebSocket hook — useSensorStream

**Files:**
- Create: `frontend/app/hooks/useSensorStream.ts`
- Create: `frontend/app/hooks/useMetrics.ts`

**Step 1: Write the sensor stream hook**

`frontend/app/hooks/useSensorStream.ts`:
```typescript
import { useCallback, useEffect, useRef } from "react";
import useWebSocket, { ReadyState } from "react-use-websocket";
import {
  MSG_EEG, MSG_PPG, MSG_IMU,
  EEG_CHANNELS, PPG_CHANNELS, IMU_CHANNELS,
  decodeBinaryFrame,
  getChannel,
} from "../lib/protocol";
import { RingBuffer } from "../lib/ringBuffer";

const WS_URL = "ws://localhost:8765";

// 5 seconds of data per channel
const EEG_BUFFER_SIZE = 256 * 5;   // 1280 samples
const PPG_BUFFER_SIZE = 64 * 5;    // 320 samples

export interface SensorBuffers {
  eeg: RingBuffer[];    // 4 channels
  ppg: RingBuffer[];    // 3 channels (IR, Red, Ambient)
}

export function useSensorStream() {
  const buffersRef = useRef<SensorBuffers>({
    eeg: Array.from({ length: EEG_CHANNELS }, () => new RingBuffer(EEG_BUFFER_SIZE)),
    ppg: Array.from({ length: PPG_CHANNELS }, () => new RingBuffer(PPG_BUFFER_SIZE)),
  });

  const metricsRef = useRef<string | null>(null);

  const { readyState, sendJsonMessage } = useWebSocket(WS_URL, {
    onMessage: (event) => {
      if (event.data instanceof Blob) {
        // Binary frame — read into ArrayBuffer
        event.data.arrayBuffer().then((buffer) => {
          const frame = decodeBinaryFrame(buffer);
          const buffers = buffersRef.current;

          if (frame.type === MSG_EEG) {
            for (let ch = 0; ch < Math.min(frame.channels, EEG_CHANNELS); ch++) {
              buffers.eeg[ch].push(getChannel(frame, ch));
            }
          } else if (frame.type === MSG_PPG) {
            for (let ch = 0; ch < Math.min(frame.channels, PPG_CHANNELS); ch++) {
              buffers.ppg[ch].push(getChannel(frame, ch));
            }
          }
          // IMU: not buffered for waveform, only used via metrics JSON
        });
      } else {
        // JSON frame (metrics)
        metricsRef.current = event.data;
      }
    },
    shouldReconnect: () => true,
    reconnectInterval: 2000,
  });

  const sendCommand = useCallback(
    (cmd: Record<string, unknown>) => {
      sendJsonMessage(cmd);
    },
    [sendJsonMessage],
  );

  return {
    buffers: buffersRef,
    metricsRef,
    readyState,
    isConnected: readyState === ReadyState.OPEN,
    sendCommand,
  };
}
```

**Step 2: Write the metrics hook**

`frontend/app/hooks/useMetrics.ts`:
```typescript
import { useEffect, useRef, useState } from "react";
import type { Metrics } from "../lib/protocol";

/**
 * Polls a metricsRef (set by useSensorStream) at a fixed rate
 * and updates React state. This limits React re-renders to the poll rate.
 */
export function useMetrics(
  metricsRef: React.RefObject<string | null>,
  pollRateMs: number = 250,
) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      const raw = metricsRef.current;
      if (raw) {
        try {
          setMetrics(JSON.parse(raw));
        } catch {
          // ignore parse errors
        }
      }
    }, pollRateMs);
    return () => clearInterval(interval);
  }, [metricsRef, pollRateMs]);

  return metrics;
}
```

**Step 3: Commit**

```bash
git add frontend/app/hooks/ && git commit -m "feat: add WebSocket sensor stream and metrics hooks"
```

---

### Task 9: EEG Waveform panel (webgl-plot)

**Files:**
- Create: `frontend/app/components/EEGWaveformPanel.tsx`

**Step 1: Write the component**

This is the performance-critical component. It uses webgl-plot imperatively via refs, completely bypassing React's render cycle for the waveform data.

`frontend/app/components/EEGWaveformPanel.tsx`:
```typescript
import { useEffect, useRef } from "react";
import { WebglPlot, WebglLine, ColorRGBA } from "webgl-plot";
import type { SensorBuffers } from "../hooks/useSensorStream";
import { CHANNEL_NAMES, EEG_CHANNELS } from "../lib/protocol";

const COLORS: ColorRGBA[] = [
  new ColorRGBA(0.35, 0.8, 0.95, 1),   // TP9  — cyan
  new ColorRGBA(0.95, 0.6, 0.3, 1),    // AF7  — orange
  new ColorRGBA(0.6, 0.95, 0.4, 1),    // AF8  — green
  new ColorRGBA(0.85, 0.4, 0.95, 1),   // TP10 — purple
];

const SAMPLES_PER_CHANNEL = 256 * 5; // 5 seconds at 256Hz

interface Props {
  buffersRef: React.RefObject<SensorBuffers>;
}

export function EEGWaveformPanel({ buffersRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wglRef = useRef<WebglPlot | null>(null);
  const linesRef = useRef<WebglLine[]>([]);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Initialize WebGL plot
    const wgl = new WebglPlot(canvas);
    wglRef.current = wgl;

    // Create one line per EEG channel, stacked vertically
    const lines: WebglLine[] = [];
    for (let ch = 0; ch < EEG_CHANNELS; ch++) {
      const line = new WebglLine(COLORS[ch], SAMPLES_PER_CHANNEL);
      line.arrangeX();

      // Stack channels vertically: offset Y position
      const yOffset = 0.75 - ch * 0.5; // spread across [-1, 1]
      line.offsetY = yOffset;
      line.scaleY = 0.002; // scale microvolts to WebGL coordinates

      wgl.addLine(line);
      lines.push(line);
    }
    linesRef.current = lines;

    // Animation loop — reads from ring buffers, updates WebGL
    const animate = () => {
      const buffers = buffersRef.current;
      if (buffers) {
        for (let ch = 0; ch < EEG_CHANNELS; ch++) {
          const data = buffers.eeg[ch].getOrdered();
          const line = lines[ch];
          for (let i = 0; i < Math.min(data.length, SAMPLES_PER_CHANNEL); i++) {
            line.setY(i, data[i]);
          }
        }
      }
      wgl.update();
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafRef.current);
      // webgl-plot doesn't have a destroy method, but the canvas will be cleaned up
    };
  }, [buffersRef]);

  return (
    <div className="relative w-full">
      {/* Channel labels */}
      <div className="absolute left-2 top-0 bottom-0 flex flex-col justify-around pointer-events-none z-10">
        {CHANNEL_NAMES.map((name, i) => (
          <span
            key={name}
            className="text-xs font-mono opacity-70"
            style={{ color: `rgba(${COLORS[i].r * 255}, ${COLORS[i].g * 255}, ${COLORS[i].b * 255}, 0.9)` }}
          >
            {name}
          </span>
        ))}
      </div>
      <canvas
        ref={canvasRef}
        className="w-full h-64 bg-black/50 rounded-md border border-white/10"
      />
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/app/components/EEGWaveformPanel.tsx && git commit -m "feat: add EEG waveform panel with webgl-plot"
```

---

### Task 10: Remaining UI components (Fit Tool, Metrics, Vitals, Motion, Controls)

**Files:**
- Create: `frontend/app/components/FitTool.tsx`
- Create: `frontend/app/components/BrainMetrics.tsx`
- Create: `frontend/app/components/VitalsPanel.tsx`
- Create: `frontend/app/components/MotionPanel.tsx`
- Create: `frontend/app/components/ControlsPanel.tsx`
- Create: `frontend/app/components/PPGWaveformPanel.tsx`

These are standard React components consuming the `Metrics` state at 1-4Hz. No performance concerns — just display data.

**Note:** The frontend-design skill is handling the visual design and exact implementation of these components. This plan only specifies the data contract. Each component receives the relevant slice of the `Metrics` type and renders it. See the architecture doc for the JSON schema.

**Step 1: Create placeholder components with correct props interfaces**

Each component should accept its relevant metrics slice and render placeholder content. The frontend-design output will replace the placeholder markup.

**Step 2: Commit**

```bash
git add frontend/app/components/ && git commit -m "feat: add metrics display components (fit, brain, vitals, motion, controls)"
```

---

### Task 11: Dashboard page — wire everything together

**Files:**
- Modify: `frontend/app/routes/index.tsx`

**Step 1: Wire up the dashboard**

`frontend/app/routes/index.tsx`:
```typescript
import { createFileRoute } from "@tanstack/react-router";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { EEGWaveformPanel } from "../components/EEGWaveformPanel";
import { PPGWaveformPanel } from "../components/PPGWaveformPanel";
import { FitTool } from "../components/FitTool";
import { BrainMetrics } from "../components/BrainMetrics";
import { VitalsPanel } from "../components/VitalsPanel";
import { MotionPanel } from "../components/MotionPanel";
import { ControlsPanel } from "../components/ControlsPanel";
import { Badge } from "@/components/ui/badge";

export const Route = createFileRoute("/")({
  component: Dashboard,
});

function Dashboard() {
  const { buffers, metricsRef, isConnected, sendCommand } = useSensorStream();
  const metrics = useMetrics(metricsRef);

  return (
    <div className="min-h-screen bg-background text-foreground p-4 space-y-4">
      {/* Connection status */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-mono font-semibold tracking-tight">
          EEG Dashboard
        </h1>
        <Badge variant={isConnected ? "default" : "destructive"}>
          {isConnected ? "Connected" : "Disconnected"}
        </Badge>
      </div>

      {/* Fit Tool */}
      <FitTool
        signalQuality={metrics?.eeg?.signal_quality}
        fitStatus={metrics?.eeg?.fit_status}
        motionArtifact={metrics?.imu?.motion_artifact}
        jawClench={metrics?.imu?.jaw_clench}
      />

      {/* EEG Waveforms */}
      <EEGWaveformPanel buffersRef={buffers} />

      {/* Bottom panels: metrics + vitals/motion side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <BrainMetrics
          bandPowers={metrics?.eeg?.band_powers}
          thetaBetaRatio={metrics?.eeg?.theta_beta_ratio}
          faa={metrics?.eeg?.frontal_alpha_asymmetry}
        />
        <div className="space-y-4">
          <VitalsPanel
            heartRate={metrics?.ppg?.heart_rate_bpm}
            spo2={metrics?.ppg?.spo2_percent}
            hrv={metrics?.ppg?.hrv_rmssd_ms}
            buffersRef={buffers}
          />
          <MotionPanel
            headMovement={metrics?.imu?.head_movement}
            headPose={metrics?.imu?.head_pose}
            motionArtifact={metrics?.imu?.motion_artifact}
            jawClench={metrics?.imu?.jaw_clench}
          />
        </div>
      </div>

      {/* Controls */}
      <ControlsPanel
        isConnected={isConnected}
        isRecording={metrics?.session?.recording ?? false}
        duration={metrics?.session?.duration_sec ?? 0}
        sendCommand={sendCommand}
      />
    </div>
  );
}
```

**Step 2: Test end-to-end**

Terminal 1:
```bash
cd /home/newub/w/zyphraexps && python3 -m backend.main --synthetic
```

Terminal 2:
```bash
cd /home/newub/w/zyphraexps/frontend && pnpm dev
```

Visit http://localhost:3000 — should see waveforms streaming and metrics updating.

**Step 3: Commit**

```bash
git add frontend/app/routes/index.tsx && git commit -m "feat: wire up dashboard page with all panels"
```

---

## Phase 3: Polish + Real Hardware

### Task 12: Test with actual Muse 2

**Step 1: Start backend with real hardware**

```bash
cd /home/newub/w/zyphraexps && python3 -m backend.main
```

**Step 2: Put on Muse 2, verify:**
- [ ] All 4 EEG channels show waveforms
- [ ] Fit tool shows green on all channels
- [ ] Band powers update
- [ ] HR displays (if PPG enabled)
- [ ] Head movement responds to tilting

**Step 3: Tune signal quality thresholds**

Adjust `RAIL_THRESHOLD`, std dev ranges in `backend/processing.py` based on real Muse 2 signal characteristics.

---

### Task 13: Recording support

**Files:**
- Create: `backend/recording.py`

**Step 1: Write the recording module**

`backend/recording.py`:
```python
import os
import time
import numpy as np
import mne

from backend.config import ServerConfig


class Recorder:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._eeg_data: list[np.ndarray] = []
        self._recording = False
        self._filename: str = ""
        os.makedirs(config.recording_dir, exist_ok=True)

    def start(self, filename: str | None = None):
        self._filename = filename or f"session_{int(time.time())}"
        self._eeg_data.clear()
        self._recording = True

    def stop(self) -> str | None:
        if not self._recording:
            return None
        self._recording = False
        if not self._eeg_data:
            return None

        data = np.concatenate(self._eeg_data, axis=1)
        info = mne.create_info(
            ch_names=["TP9", "AF7", "AF8", "TP10"],
            sfreq=256.0,
            ch_types="eeg",
        )
        raw = mne.io.RawArray(data * 1e-6, info)  # convert uV to V for MNE
        montage = mne.channels.make_standard_montage("standard_1020")
        raw.set_montage(montage)

        filepath = os.path.join(self.config.recording_dir, f"{self._filename}.fif")
        raw.save(filepath, overwrite=True)
        return filepath

    def append(self, eeg: np.ndarray):
        if self._recording:
            self._eeg_data.append(eeg.copy())

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration_sec(self) -> float:
        if not self._eeg_data:
            return 0.0
        total_samples = sum(d.shape[1] for d in self._eeg_data)
        return total_samples / 256.0
```

**Step 2: Integrate into `main.py`** — add `Recorder` instance, call `recorder.append(eeg)` in stream loop, handle start/stop commands.

**Step 3: Test: record 10 seconds, verify .fif file is valid**

```bash
python3 -c "
import mne
raw = mne.io.read_raw_fif('recordings/session_test.fif', preload=True)
print(raw.info)
print(f'Duration: {raw.times[-1]:.1f}s, Channels: {raw.ch_names}')
"
```

**Step 4: Commit**

```bash
git add backend/recording.py && git commit -m "feat: add MNE .fif recording support"
```

---

## Summary

| Phase | Tasks | What you get |
|-------|-------|--------------|
| **Phase 1** | Tasks 1-5 | Python backend streaming all sensors over WebSocket |
| **Phase 2** | Tasks 6-11 | Working dashboard with waveforms, metrics, controls |
| **Phase 3** | Tasks 12-13 | Real Muse 2 validation + recording to .fif |

Each task produces something testable. The synthetic board (`--synthetic` flag) lets you develop the full stack without the Muse 2 plugged in.
