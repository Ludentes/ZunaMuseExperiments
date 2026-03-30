# Plan 0: Repo Setup & Pipeline Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `muse-vtuber` repo with project scaffolding, pipeline framework, and BrainFlow hardware source.

**Architecture:** uv-managed Python project with src layout. Pipeline framework adapted from zyphraexps (Stage/Pipeline/PipelineFrame). BrainFlowSource wraps BrainFlow behind a BCISource protocol for testability.

**Tech Stack:** Python 3.12, uv, BrainFlow, numpy, scipy, python-osc, pytest

---

## Prerequisites & Testing Infrastructure

### System Requirements

| Tool | Version | Install | Purpose |
|------|---------|---------|---------|
| Python | ≥3.11 | System package manager | Runtime |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Python project manager |
| Git | Any | System package manager | Version control |
| Bluetooth | BLE 4.0+ | Built into most laptops | Muse 2 connection (manual testing only) |

### Automated Testing (No Hardware Needed)

All automated tests use **BrainFlow's synthetic board** (`board_id=-1`). This generates fake EEG/IMU data without any hardware connected. No Bluetooth, no Muse, no webcam required.

```bash
# Run all tests — works on any machine with Python + uv
cd muse-vtuber
uv run pytest -v
```

The synthetic board produces random noise that won't trigger blink/clench detectors reliably, but it validates:
- BrainFlow lifecycle (start → poll → stop)
- Pipeline stage execution order and error handling
- Data flow through the pipeline
- Output message formatting (VMC, OSC, VTS)
- Quaternion math (head pose, fusion, One Euro filter)

Blink/clench detector tests use **synthetic EEG signals** constructed in test fixtures (large negative deflections for blinks, 30Hz sinusoids for clench) — these don't rely on BrainFlow at all.

### Manual Testing — Tier 3 (EEG Addon)

**What you need:**
1. **Muse 2 headband** — Bluetooth BLE, paired via MAC address
2. **VSeeFace** — free VTuber app, download from https://www.vseeface.icu/

**VSeeFace setup (one-time):**
1. Download and extract VSeeFace (Windows only — runs under Wine on Linux but untested)
2. Launch VSeeFace — it includes a built-in model called **Vita** (no separate VRM download needed)
3. Go to **Settings → General Settings → scroll to "OSC/VMC receiver"**
4. **Enable** the VMC receiver
5. Set port to **39539** (our default output port)
6. Uncheck "Track face features" if you want Muse data to be the only input

**Test run:**
```bash
# With real Muse 2 (find MAC via: sudo hcitool lescan)
muse-vtuber --mac XX:XX:XX:XX:XX:XX --debug

# With synthetic data (no hardware — good for verifying VMC output)
muse-vtuber --synthetic --debug
```

**What to verify:**
- `--debug` output shows `Event: blink` when you blink
- VSeeFace VMC panel shows incoming blendshape values
- Blink your eyes → avatar blinks
- Clench jaw → `muse_clench` blendshape activates

### Manual Testing — Tier 1 (Head Tracking)

Same setup as Tier 3, but head tracking requires a **real Muse 2** (synthetic board doesn't generate meaningful IMU data).

**What to verify:**
- Turn head → avatar head follows (with noticeable smoothing delay)
- Stay still for 5+ seconds → yaw drift should decay toward center
- Head tracking is mediocre by design (6-axis IMU, no magnetometer) — see `docs/vtuber-demo-notes.md`

### Manual Testing — Tier 2 (Fusion)

**Additional requirement: OpenSeeFace** — standalone webcam face tracker.

**OpenSeeFace setup:**
1. Clone: `git clone https://github.com/emilianavt/OpenSeeFace`
2. Install deps: `pip install onnxruntime opencv-python pillow numpy`
3. Run: `python facetracker.py -c 0 -W 1280 -H 720 --discard-after 0 --scan-every 0 --no-3d-adapt 1 --max-feature-updates 900 --ip 127.0.0.1 --port 11573`
   - `-c 0` = webcam index 0
   - On Windows: use `Binary/facetracker.exe` instead (pre-compiled)

**Test run:**
```bash
# Start OpenSeeFace first (in separate terminal)
python facetracker.py -c 0 --port 11573

# Then start muse-vtuber with fusion
muse-vtuber --mac XX:XX:XX:XX:XX:XX --fusion --debug
```

**What to verify:**
- Log shows "Fusion enabled — listening for OpenSeeFace on port 11573"
- Head tracking is smoother and drift-free compared to IMU-only
- Cover webcam → tracking degrades to IMU-only (still works, drifts)
- Uncover webcam → drift corrects within ~1-2 seconds

### Manual Testing — VRChat OSC (Plan 4)

**What you need:** VRChat with an avatar that has BFiVRC parameters (or any OSC debugger like `oscdump` from liblo).

```bash
# Quick test without VRChat — use oscdump to see raw messages
pip install pyliblo3
oscdump 9000 &
muse-vtuber --synthetic --osc --debug
# Should see BFI/NeuroFB/FocusAvg, BFI/PwrBands/... messages
```

### Manual Testing — VTube Studio (Plan 5)

**What you need:** VTube Studio (Steam, ~$25 or free demo).

**Enable plugin API:**
1. Open VTube Studio
2. Go to main config (gear icon)
3. Enable **"Start API (Allow Plugins)"**
4. Default port: 8001

```bash
muse-vtuber --synthetic --vts --debug
# VTube Studio shows auth popup → approve "muse-vtuber"
# Check VTS parameter list → should see MuseBlink, MuseFocus, etc.
```

### Port Reference

| Service | Port | Protocol | Direction |
|---------|------|----------|-----------|
| VMC output | 39539 | UDP/OSC | muse-vtuber → VSeeFace/Warudo/VNyan |
| VRChat OSC | 9000 | UDP/OSC | muse-vtuber → VRChat/VNyan |
| VTube Studio | 8001 | WebSocket | muse-vtuber ↔ VTube Studio |
| OpenSeeFace | 11573 | UDP binary | OpenSeeFace → muse-vtuber |

---

### Task 1: Create repo and project scaffold

**Files:**
- Create: `muse-vtuber/pyproject.toml`
- Create: `muse-vtuber/src/muse_vtuber/__init__.py`
- Create: `muse-vtuber/tests/__init__.py`
- Create: `muse-vtuber/.gitignore`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p muse-vtuber/src/muse_vtuber/pipeline
mkdir -p muse-vtuber/src/muse_vtuber/outputs
mkdir -p muse-vtuber/tests
mkdir -p muse-vtuber/docs
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[project]
name = "muse-vtuber"
version = "0.1.0"
description = "Bridge BCI hardware to VTuber avatar software via VMC, OSC, and VTube Studio"
requires-python = ">=3.11"
dependencies = [
    "brainflow>=5.0",
    "numpy>=1.24",
    "scipy>=1.10",
    "python-osc>=1.8",
    "websockets>=12.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[project.scripts]
muse-vtuber = "muse_vtuber.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/muse_vtuber"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create __init__.py files**

`src/muse_vtuber/__init__.py`:
```python
"""Muse VTuber Bridge — BCI hardware to VTuber avatar software."""
```

`src/muse_vtuber/pipeline/__init__.py`:
```python
```

`src/muse_vtuber/outputs/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 5: Init git repo and install**

```bash
cd muse-vtuber
git init
uv sync --dev
```

- [ ] **Step 6: Verify install**

```bash
cd muse-vtuber
uv run python -c "import muse_vtuber; print('OK')"
```

Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: init project scaffold with uv"
```

---

### Task 2: Pipeline framework (types + base classes)

**Files:**
- Create: `src/muse_vtuber/pipeline/types.py`
- Create: `src/muse_vtuber/pipeline/base.py`
- Create: `tests/test_pipeline_base.py`

- [ ] **Step 1: Write tests for PipelineFrame**

`tests/test_pipeline_base.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.types import (
    BANDS,
    CH_NAMES,
    Cadence,
    Event,
    PipelineFrame,
)


def test_pipeline_frame_set_get():
    """Typed result storage and retrieval."""
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        value: float

    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    assert frame.get(FakeResult) is None

    frame.set(FakeResult(value=42.0))
    result = frame.get(FakeResult)
    assert result is not None
    assert result.value == 42.0


def test_pipeline_frame_events():
    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    assert frame.events == []

    frame.events.append(Event(kind="blink", timestamp=1.0, confidence=0.95))
    assert len(frame.events) == 1
    assert frame.events[0].kind == "blink"


def test_bands_defined():
    assert "alpha" in BANDS
    assert "beta" in BANDS
    assert "theta" in BANDS
    assert "delta" in BANDS
    assert "gamma" in BANDS
    for low, high in BANDS.values():
        assert low < high


def test_ch_names():
    assert CH_NAMES == ["TP9", "AF7", "AF8", "TP10"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_pipeline_base.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'muse_vtuber.pipeline.types'`

- [ ] **Step 3: Implement pipeline types**

`src/muse_vtuber/pipeline/types.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

import numpy as np

T = TypeVar("T")

BANDS: dict[str, tuple[float, float]] = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (7.5, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 44.0),
}

CH_NAMES: list[str] = ["TP9", "AF7", "AF8", "TP10"]

BAND_NAMES: list[str] = list(BANDS.keys())

# Hemisphere groupings for Muse 4-channel layout
LEFT_CHS: list[int] = [0, 1]   # TP9, AF7
RIGHT_CHS: list[int] = [2, 3]  # AF8, TP10
FRONTAL_CHS: list[int] = [1, 2]  # AF7, AF8
TEMPORAL_CHS: list[int] = [0, 3]  # TP9, TP10


class Cadence(Enum):
    FAST = "fast"   # every chunk (~16ms)
    SLOW = "slow"   # every ~1s window


@dataclass
class Event:
    kind: str
    timestamp: float
    confidence: float = 1.0
    channel: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineFrame:
    eeg: np.ndarray | None       # (n_channels, n_samples)
    imu: np.ndarray | None       # (6, n_samples) — accel[0:3] + gyro[3:6]
    timestamp: float
    _results: dict[str, Any] = field(default_factory=dict, repr=False)
    events: list[Event] = field(default_factory=list)

    def set(self, result: Any) -> None:
        """Store a result by its class name."""
        self._results[type(result).__name__] = result

    def get(self, cls: type[T]) -> T | None:
        """Retrieve a typed result, or None if not set."""
        return self._results.get(cls.__name__)

    def has(self, cls: type) -> bool:
        return cls.__name__ in self._results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd muse-vtuber
uv run pytest tests/test_pipeline_base.py -v
```

Expected: 4 passed

- [ ] **Step 5: Write tests for Pipeline runner**

Add to `tests/test_pipeline_base.py`:
```python
from muse_vtuber.pipeline.base import Pipeline, Stage


class CounterStage(Stage):
    name = "counter"
    cadence = Cadence.FAST

    def __init__(self):
        self.count = 0

    def process(self, frame: PipelineFrame) -> None:
        self.count += 1


class SlowStage(Stage):
    name = "slow"
    cadence = Cadence.SLOW

    def __init__(self):
        self.count = 0

    def process(self, frame: PipelineFrame) -> None:
        self.count += 1


class FailingStage(Stage):
    name = "failing"
    cadence = Cadence.FAST

    def process(self, frame: PipelineFrame) -> None:
        raise ValueError("boom")


def test_pipeline_runs_matching_cadence():
    fast = CounterStage()
    slow = SlowStage()
    pipeline = Pipeline(stages=[fast, slow])

    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    pipeline.run(Cadence.FAST, frame)
    assert fast.count == 1
    assert slow.count == 0

    pipeline.run(Cadence.SLOW, frame)
    assert fast.count == 1
    assert slow.count == 1


def test_pipeline_survives_stage_failure():
    failing = FailingStage()
    counter = CounterStage()
    pipeline = Pipeline(stages=[failing, counter])

    frame = PipelineFrame(eeg=None, imu=None, timestamp=1.0)
    pipeline.run(Cadence.FAST, frame)
    # Counter still ran despite failing stage before it
    assert counter.count == 1
```

- [ ] **Step 6: Implement Pipeline and Stage base**

`src/muse_vtuber/pipeline/base.py`:
```python
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from muse_vtuber.pipeline.types import Cadence, PipelineFrame

log = logging.getLogger("pipeline")


class Stage(ABC):
    name: str
    cadence: Cadence

    @abstractmethod
    def process(self, frame: PipelineFrame) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage]):
        self.stages = stages

    def run(self, cadence: Cadence, frame: PipelineFrame) -> None:
        for stage in self.stages:
            if stage.cadence != cadence:
                continue
            try:
                stage.process(frame)
            except Exception:
                log.exception("Stage %s failed", stage.name)
```

- [ ] **Step 7: Run all tests**

```bash
cd muse-vtuber
uv run pytest tests/test_pipeline_base.py -v
```

Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add src/muse_vtuber/pipeline/ tests/test_pipeline_base.py
git commit -m "feat: pipeline framework with Stage, Pipeline, PipelineFrame"
```

---

### Task 3: BrainFlow source with BCISource protocol

**Files:**
- Create: `src/muse_vtuber/source.py`
- Create: `tests/test_source.py`

- [ ] **Step 1: Write test for BCISource protocol and synthetic board**

`tests/test_source.py`:
```python
import numpy as np
import pytest

from muse_vtuber.source import BrainFlowSource, BCISource


def test_brainflow_source_implements_protocol():
    """BrainFlowSource satisfies BCISource protocol."""
    source = BrainFlowSource(board_id=-1)  # synthetic
    assert isinstance(source, BCISource)


def test_synthetic_board_lifecycle():
    """Start, poll, stop with BrainFlow synthetic board."""
    source = BrainFlowSource(board_id=-1)
    source.start()
    try:
        # Synthetic board generates data immediately
        import time
        time.sleep(0.1)  # let some data accumulate

        eeg = source.poll_eeg()
        assert eeg is not None
        assert eeg.ndim == 2
        assert eeg.shape[0] > 0  # has channels

        assert source.eeg_sample_rate > 0
    finally:
        source.stop()


def test_synthetic_board_imu():
    """Synthetic board may or may not have IMU — poll returns None if not."""
    source = BrainFlowSource(board_id=-1)
    source.start()
    try:
        import time
        time.sleep(0.1)
        # Synthetic board doesn't have IMU preset by default
        imu = source.poll_imu()
        # Either None (no IMU) or (6, n) array
        if imu is not None:
            assert imu.ndim == 2
            assert imu.shape[0] == 6
    finally:
        source.stop()


def test_board_id_from_string():
    """Board ID can be specified as a BrainFlow name string."""
    source = BrainFlowSource(board_id="SYNTHETIC_BOARD")
    assert source.board_id == -1


def test_poll_before_start_returns_none():
    source = BrainFlowSource(board_id=-1)
    assert source.poll_eeg() is None
    assert source.poll_imu() is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd muse-vtuber
uv run pytest tests/test_source.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement BrainFlowSource**

`src/muse_vtuber/source.py`:
```python
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import numpy as np
from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams, BrainFlowPresets

log = logging.getLogger("source")


@runtime_checkable
class BCISource(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def poll_eeg(self) -> np.ndarray | None: ...
    def poll_imu(self) -> np.ndarray | None: ...

    @property
    def eeg_sample_rate(self) -> int: ...

    @property
    def imu_sample_rate(self) -> int: ...

    @property
    def has_imu(self) -> bool: ...


def _resolve_board_id(board_id: int | str) -> int:
    """Resolve board_id from int or BrainFlow name string."""
    if isinstance(board_id, int):
        return board_id
    # Try as BoardIds enum name (e.g. "SYNTHETIC_BOARD", "MUSE_2_BOARD")
    name = board_id.upper().replace("-", "_")
    if not name.endswith("_BOARD"):
        name += "_BOARD"
    try:
        return BoardIds[name].value
    except KeyError:
        pass
    # Try direct int parse
    try:
        return int(board_id)
    except ValueError:
        raise ValueError(f"Unknown board_id: {board_id!r}. Use int or BrainFlow name like 'MUSE_2_BOARD'.")


class BrainFlowSource:
    """BrainFlow-backed BCI source. Implements BCISource protocol."""

    def __init__(
        self,
        board_id: int | str = -1,
        mac_address: str = "",
        serial_port: str = "",
    ):
        self.board_id = _resolve_board_id(board_id)
        params = BrainFlowInputParams()
        if mac_address:
            params.mac_address = mac_address
        if serial_port:
            params.serial_port = serial_port
        self._board = BoardShim(self.board_id, params)
        self._streaming = False
        self._eeg_channels: list[int] = []
        self._imu_channels: list[int] = []
        self._has_imu = False

    def start(self) -> None:
        self._board.prepare_session()
        # Discover channels
        self._eeg_channels = BoardShim.get_eeg_channels(self.board_id)

        # Try to enable IMU (auxiliary preset)
        try:
            accel = BoardShim.get_accel_channels(self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value)
            gyro = BoardShim.get_gyro_channels(self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value)
            if accel and gyro:
                self._imu_channels = accel + gyro
                self._has_imu = True
        except Exception:
            self._has_imu = False

        self._board.start_stream()
        self._streaming = True
        log.info("BrainFlow streaming started (board_id=%d)", self.board_id)

    def stop(self) -> None:
        if self._streaming:
            try:
                self._board.stop_stream()
            except Exception:
                log.warning("Error stopping stream", exc_info=True)
            self._streaming = False
        try:
            self._board.release_session()
        except Exception:
            log.warning("Error releasing session", exc_info=True)

    def poll_eeg(self) -> np.ndarray | None:
        if not self._streaming:
            return None
        data = self._board.get_board_data()
        if data.shape[1] == 0:
            return None
        return data[self._eeg_channels]

    def poll_imu(self) -> np.ndarray | None:
        if not self._streaming or not self._has_imu:
            return None
        try:
            data = self._board.get_board_data(preset=BrainFlowPresets.AUXILIARY_PRESET.value)
            if data.shape[1] == 0:
                return None
            return data[self._imu_channels]
        except Exception:
            return None

    @property
    def eeg_sample_rate(self) -> int:
        return BoardShim.get_sampling_rate(self.board_id)

    @property
    def imu_sample_rate(self) -> int:
        if not self._has_imu:
            return 0
        try:
            return BoardShim.get_sampling_rate(self.board_id, BrainFlowPresets.AUXILIARY_PRESET.value)
        except Exception:
            return 0

    @property
    def has_imu(self) -> bool:
        return self._has_imu
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_source.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/source.py tests/test_source.py
git commit -m "feat: BrainFlowSource with BCISource protocol"
```

---

### Done Criteria

- [x] `uv run pytest` passes all tests
- [x] `uv run python -c "from muse_vtuber.source import BrainFlowSource; print('OK')"` works
- [x] Pipeline framework (Stage, Pipeline, PipelineFrame) is importable and tested
- [x] BrainFlowSource starts/stops/polls with synthetic board
- [x] Board ID accepts both int and string names
