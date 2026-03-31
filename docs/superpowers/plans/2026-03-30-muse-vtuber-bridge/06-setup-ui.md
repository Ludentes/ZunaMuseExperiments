# Plan 6: Setup & Calibration UI

**Goal:** Web UI for headband fit check, Live2D avatar preview, and head tracking calibration. Backend streams to browser + VTS simultaneously.

**Depends on:** Plan 2 (head tracking) — done, Plan 5 (VTS) — done

**Spec:** `muse-vtuber/docs/superpowers/specs/2026-03-31-setup-ui-design.md`

## Reference: Existing Demo App

There is a **working demo frontend** in the parent project at `../zyphraexps/frontend/` that implements many of the same patterns we need. **Use it as a reference implementation** — cross-check your work against it. Key files:

| What we need | Reference file in `zyphraexps/frontend/src/` | What to reuse |
|---|---|---|
| WebSocket binary protocol | `lib/protocol.ts` | Frame format constants, `decodeBinaryFrame()`, `Metrics` type interface |
| WebSocket hook + reconnect | `hooks/useSensorStream.ts` | Connection logic, binary/JSON message routing, ref-based storage pattern |
| Signal quality display | `components/demo/CompactFit.tsx` | 4-dot per-channel display, color thresholds, fit status badge |
| Head pose display | `components/MotionPanel.tsx` | Pitch/roll/yaw rendering, color-coding by magnitude |
| VTuber page layout | `routes/vtuber.tsx` | Bias sliders (±45deg), recenter button, settle progress overlay, sidebar + canvas layout |
| Avatar animation | `components/vtuber/VTuberAvatar.tsx` | Blink easing (0→1→0 over 150ms), bone rotation split pattern |
| Head pose estimation | `lib/headPose.ts` | Madgwick + One Euro + yaw decay (already ported to Python in Plan 2) |
| One Euro filter | `lib/oneEuroFilter.ts` | Adaptive smoothing (already ported to Python in Plan 2) |
| Ring buffer utility | `lib/ringBuffer.ts` | Circular buffer for time-series data |

**Important differences** from the reference app:
- Reference uses **VRM (3D)** via Three.js + react-three-fiber. We use **Live2D (2D)** via PixiJS.
- Reference does head pose estimation **client-side** (JS Madgwick). We do it **server-side** (Python) and stream the result as JSON metrics. The frontend just displays values, no IMU processing.
- Reference uses the full binary protocol (EEG/PPG/IMU frames). We use **JSON-only** for V1 — the backend computes everything and sends metrics at ~30Hz.
- Reference has many pages (dashboard, demo, vtuber). We have **one page** — the setup/calibration tool.

**When implementing each task**, read the corresponding reference file first and adapt the patterns for our simpler architecture. Don't copy-paste blindly — our frontend is leaner (no R3F, no ring buffers for V1, no binary frame parsing).

---

### Task 1: Signal Quality Pipeline Stage

**Files:**
- Create: `src/muse_vtuber/pipeline/signal_quality.py`
- Create: `tests/test_signal_quality.py`

Per-channel signal quality metric. Runs at SLOW cadence.

- [ ] **Step 1: Write test**

`tests/test_signal_quality.py`:
```python
import numpy as np
import pytest

from muse_vtuber.pipeline.signal_quality import SignalQualityStage, SignalQualityResult
from muse_vtuber.pipeline.types import Cadence, PipelineFrame


def test_cadence_is_slow():
    stage = SignalQualityStage()
    assert stage.cadence == Cadence.SLOW


def test_good_signal():
    """Clean sine wave should score high."""
    stage = SignalQualityStage()
    t = np.linspace(0, 1, 256)
    # 10Hz sine, 50uV amplitude — clean EEG
    eeg = np.array([50 * np.sin(2 * np.pi * 10 * t)] * 4, dtype=np.float64)
    frame = PipelineFrame(eeg=eeg, imu=None, timestamp=0.0)
    stage.run(frame)
    result = frame.get(SignalQualityResult)
    assert result is not None
    assert all(q > 0.5 for q in result.channel_quality.values())
    assert result.fit_status == "good"


def test_noisy_signal():
    """High-frequency noise should score low."""
    stage = SignalQualityStage()
    rng = np.random.default_rng(42)
    # Pure high-frequency noise (>40Hz)
    eeg = rng.normal(0, 100, (4, 256))
    frame = PipelineFrame(eeg=eeg, imu=None, timestamp=0.0)
    stage.run(frame)
    result = frame.get(SignalQualityResult)
    assert result is not None
    assert all(q < 0.5 for q in result.channel_quality.values())


def test_flat_signal():
    """Zero variance (disconnected electrode) should score 0."""
    stage = SignalQualityStage()
    eeg = np.zeros((4, 256), dtype=np.float64)
    frame = PipelineFrame(eeg=eeg, imu=None, timestamp=0.0)
    stage.run(frame)
    result = frame.get(SignalQualityResult)
    assert result is not None
    assert all(q < 0.1 for q in result.channel_quality.values())
    assert result.fit_status == "poor"


def test_none_eeg_safe():
    stage = SignalQualityStage()
    frame = PipelineFrame(eeg=None, imu=None, timestamp=0.0)
    stage.run(frame)
    result = frame.get(SignalQualityResult)
    assert result is None
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd muse-vtuber && uv run pytest tests/test_signal_quality.py -v
```

- [ ] **Step 3: Implement**

`src/muse_vtuber/pipeline/signal_quality.py`:
```python
"""Per-channel EEG signal quality estimation.

Computes quality from the ratio of low-frequency (useful EEG) power to
high-frequency (noise/impedance) power. Flat-line detection for disconnected
electrodes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from brainflow.data_filter import DataFilter

from muse_vtuber.pipeline.types import CH_NAMES, Cadence, PipelineFrame, Stage

SAMPLE_RATE = 256
HF_CUTOFF = 40.0  # Hz — above this is mostly noise/muscle artifact


@dataclass
class SignalQualityResult:
    channel_quality: dict[str, float] = field(default_factory=dict)  # 0.0-1.0
    fit_status: str = "unknown"  # "good", "adjust", "poor"


class SignalQualityStage(Stage):
    cadence = Cadence.SLOW

    def run(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] < 64:
            return

        qualities: dict[str, float] = {}
        for i, name in enumerate(CH_NAMES):
            if i >= frame.eeg.shape[0]:
                break
            ch = frame.eeg[i].astype(np.float64)

            # Flat-line check
            if np.std(ch) < 0.5:
                qualities[name] = 0.0
                continue

            # Bandpass: compute power in EEG band (1-40Hz) vs total
            try:
                psd = DataFilter.get_psd_welch(
                    ch, nfft=min(256, len(ch)), overlap=128,
                    sampling_rate=SAMPLE_RATE, window=2,  # HAMMING
                )
                freqs = psd[1]
                powers = psd[0]

                eeg_mask = (freqs >= 1.0) & (freqs <= HF_CUTOFF)
                noise_mask = freqs > HF_CUTOFF

                eeg_power = np.sum(powers[eeg_mask]) if np.any(eeg_mask) else 0.0
                noise_power = np.sum(powers[noise_mask]) if np.any(noise_mask) else 1e-10
                total = eeg_power + noise_power

                quality = float(eeg_power / total) if total > 0 else 0.0
                qualities[name] = min(1.0, quality)
            except Exception:
                qualities[name] = 0.0

        # Fit status
        min_q = min(qualities.values()) if qualities else 0.0
        if min_q >= 0.5:
            fit_status = "good"
        elif min_q >= 0.2:
            fit_status = "adjust"
        else:
            fit_status = "poor"

        frame.set(SignalQualityResult(channel_quality=qualities, fit_status=fit_status))
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/pipeline/signal_quality.py tests/test_signal_quality.py
git commit -m "feat: signal quality pipeline stage for fit detection"
```

---

### Task 2: WebSocket Server

**Files:**
- Create: `src/muse_vtuber/server.py`
- Create: `tests/test_server.py`
- Modify: `src/muse_vtuber/main.py`
- Modify: `src/muse_vtuber/config.py`

WebSocket server that broadcasts JSON metrics + events to connected browsers. Runs in a separate thread.

- [ ] **Step 1: Write test**

`tests/test_server.py`:
```python
import asyncio
import json
import threading
import time

import pytest
import websockets


@pytest.fixture
def server_port():
    return 18765  # test port


@pytest.fixture
def ws_server(server_port):
    from muse_vtuber.server import SetupUIServer

    server = SetupUIServer(port=server_port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(0.3)  # wait for server to start
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_connect_and_receive_metrics(ws_server, server_port):
    async with websockets.connect(f"ws://localhost:{server_port}") as ws:
        ws_server.broadcast_metrics({
            "signal_quality": {"TP9": 0.9},
            "fit_status": "good",
            "head_pose": {"pitch": 0, "yaw": 0, "roll": 0},
            "settle_progress": 1.0,
            "initialized": True,
        })
        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        data = json.loads(msg)
        assert data["type"] == "metrics"
        assert data["signal_quality"]["TP9"] == 0.9


@pytest.mark.asyncio
async def test_receive_command(ws_server, server_port):
    async with websockets.connect(f"ws://localhost:{server_port}") as ws:
        await ws.send(json.dumps({"type": "recenter"}))
        # Give server time to process
        await asyncio.sleep(0.1)
        cmd = ws_server.poll_command()
        assert cmd is not None
        assert cmd["type"] == "recenter"


@pytest.mark.asyncio
async def test_broadcast_event(ws_server, server_port):
    async with websockets.connect(f"ws://localhost:{server_port}") as ws:
        ws_server.broadcast_event({
            "kind": "blink",
            "confidence": 0.95,
        })
        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        data = json.loads(msg)
        assert data["type"] == "bci_event"
        assert data["kind"] == "blink"
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement**

`src/muse_vtuber/server.py`:

Core design:
- `SetupUIServer` class with `run()` (blocking, call from thread) and `stop()`
- `broadcast_metrics(data: dict)` — wraps in `{"type": "metrics", ...}`, puts in broadcast queue
- `broadcast_event(data: dict)` — wraps in `{"type": "bci_event", ...}`, puts in broadcast queue
- `poll_command() -> dict | None` — non-blocking, returns command from frontend or None
- Internally: asyncio event loop, `websockets.serve`, set of connected clients
- Broadcast uses `asyncio.run_coroutine_threadsafe` to schedule from main thread
- Commands received from clients go into a `queue.Queue`

Optional: also serve static files (model directory) via a simple HTTP handler on a separate port or path.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Wire into main.py**

Add to `main.py`:
1. Import `SetupUIServer`
2. Start server thread if `config.ui_enabled`
3. In main loop: broadcast metrics every ~33ms (30Hz) and events on detection
4. Poll commands and apply recenter / set_bias
5. Add signal quality stage to pipeline

Add to `config.py`:
- `ui_enabled: bool = True`
- `ui_port: int = 8765`
- `model_path: str = ""`
- CLI flags: `--ui-port`, `--model`, `--no-ui`

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest -v
```

- [ ] **Step 7: Commit**

```bash
git add src/muse_vtuber/server.py src/muse_vtuber/main.py src/muse_vtuber/config.py \
        src/muse_vtuber/pipeline/signal_quality.py tests/test_server.py
git commit -m "feat: WebSocket server for setup UI — metrics broadcast + command handling"
```

---

### Task 3: Frontend Scaffold

**Files:** Create `frontend/` directory with Vite + React + TypeScript + Tailwind + shadcn/ui.

- [ ] **Step 1: Scaffold project**

```bash
cd muse-vtuber
pnpm create vite frontend -- --template react-ts
cd frontend
pnpm install
```

- [ ] **Step 2: Add Tailwind CSS 4**

```bash
pnpm add tailwindcss @tailwindcss/vite
```

Configure in `vite.config.ts` and `src/index.css`.

- [ ] **Step 3: Add shadcn/ui**

```bash
pnpm dlx shadcn@latest init
pnpm dlx shadcn@latest add slider button card badge
```

- [ ] **Step 4: Add Live2D dependencies**

```bash
pnpm add pixi.js@^8 @naari3/pixi-live2d-display
```

- [ ] **Step 5: Configure Vite proxy**

In `vite.config.ts`:
```typescript
server: {
  proxy: {
    '/ws': { target: 'ws://localhost:8765', ws: true },
    '/model': { target: 'http://localhost:8766' },
  }
}
```

- [ ] **Step 6: Verify dev server starts**

```bash
cd frontend && pnpm dev
```

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: frontend scaffold — Vite + React + Tailwind + shadcn + Live2D deps"
```

---

### Task 4: WebSocket Hook + Signal Quality UI

**Reference:** Read `zyphraexps/frontend/src/hooks/useSensorStream.ts` for WebSocket reconnect pattern, and `zyphraexps/frontend/src/components/demo/CompactFit.tsx` for signal quality display. Our version is simpler (JSON only, no binary frames).

**Files:**
- Create: `frontend/src/hooks/useMuseStream.ts`
- Create: `frontend/src/components/SignalQuality.tsx`
- Create: `frontend/src/components/ConnectionStatus.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Implement useMuseStream hook**

WebSocket connection with auto-reconnect. Parses JSON messages into typed state:
```typescript
interface MuseMetrics {
  signal_quality: Record<string, number>;
  fit_status: "good" | "adjust" | "poor" | "unknown";
  head_pose: { pitch: number; yaw: number; roll: number };
  settle_progress: number;
  initialized: boolean;
}

interface BciEvent {
  kind: string;
  confidence: number;
  timestamp: number;
}

function useMuseStream(url: string): {
  metrics: MuseMetrics | null;
  lastEvent: BciEvent | null;
  connected: boolean;
  send: (cmd: object) => void;
}
```

- [ ] **Step 2: Implement SignalQuality component**

4 horizontal bars (one per channel), color-coded green/yellow/red. Fit status badge.

- [ ] **Step 3: Implement ConnectionStatus component**

Green/red dot with label.

- [ ] **Step 4: Wire into App.tsx**

Left sidebar with SignalQuality + ConnectionStatus. Main area placeholder for avatar.

- [ ] **Step 5: Test manually**

Start backend: `uv run muse-vtuber --synthetic --debug`
Start frontend: `cd frontend && pnpm dev`
Verify connection + signal quality bars update.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: WebSocket hook + signal quality display"
```

---

### Task 5: Live2D Avatar Component

**Reference:** Read `zyphraexps/frontend/src/components/vtuber/VTuberAvatar.tsx` for animation patterns (blink easing 0→1→0 over 150ms, frame update loop). Our version drives Live2D parameters instead of VRM bones — simpler because Live2D takes Euler angles directly (no quaternion math needed client-side).

**Files:**
- Create: `frontend/src/components/Live2DAvatar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Implement Live2DAvatar**

PixiJS Application + Live2DModel loading. Accepts metrics as props, drives:
- `ParamAngleX` ← yaw (+ bias)
- `ParamAngleY` ← pitch (+ bias)
- `ParamAngleZ` ← roll (+ bias)
- `ParamEyeLOpen` / `ParamEyeROpen` ← 0 on blink, ease back to 1

Handles model load errors gracefully (show message if model path not configured).

- [ ] **Step 2: Wire into App.tsx**

Replace placeholder with Live2DAvatar. Pass metrics + lastEvent.

- [ ] **Step 3: Test with VTS model**

```bash
uv run muse-vtuber --synthetic --model "/path/to/akari_vts" --debug
# In another terminal:
cd frontend && pnpm dev
```

Verify Akari model renders and head moves.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat: Live2D avatar component — renders VTS model with BCI parameter driving"
```

---

### Task 6: Bias Controls + Recenter

**Reference:** Read `zyphraexps/frontend/src/routes/vtuber.tsx` — it has working bias sliders (±45deg, 1deg steps), recenter button, settle progress overlay, and the complete sidebar layout. Adapt the UI patterns and slider ranges from there. Also read `zyphraexps/frontend/src/components/MotionPanel.tsx` for head angle display formatting.

**Files:**
- Create: `frontend/src/components/BiasControls.tsx`
- Create: `frontend/src/components/HeadTrackingPanel.tsx`
- Create: `frontend/src/components/SettleOverlay.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `src/muse_vtuber/head_pose.py` (add bias fields)

- [ ] **Step 1: Add bias to HeadPoseEstimator**

```python
# head_pose.py — add to __init__:
self.bias_pitch: float = 0.0
self.bias_yaw: float = 0.0
self.bias_roll: float = 0.0
```

Update `get_euler_degrees()` to apply bias before returning.

- [ ] **Step 2: Handle commands in main.py**

Poll `server.poll_command()` each loop iteration. Handle:
- `{"type": "recenter"}` → call `head_pose.recenter()`
- `{"type": "set_bias", "pitch": N, "yaw": N, "roll": N}` → update bias fields

- [ ] **Step 3: Implement HeadTrackingPanel**

Displays live pitch/yaw/roll values from metrics.

- [ ] **Step 4: Implement BiasControls**

Three sliders (±45deg), Reset button (zero all), Recenter button.
Sends `set_bias` command on slider change, `recenter` on button click.

- [ ] **Step 5: Implement SettleOverlay**

Shows "Calibrating — hold still" with progress bar when `settle_progress < 1.0`.

- [ ] **Step 6: Wire into App.tsx**

Add HeadTrackingPanel, BiasControls to sidebar. SettleOverlay over avatar area.

- [ ] **Step 7: Test end-to-end**

Verify bias sliders change head position in both UI and VTS simultaneously.

- [ ] **Step 8: Commit**

```bash
git add src/muse_vtuber/head_pose.py src/muse_vtuber/main.py frontend/src/
git commit -m "feat: bias controls, recenter, settle overlay — setup UI complete"
```

---

### Task 7: Model Static File Server

**Files:**
- Modify: `src/muse_vtuber/server.py`

- [ ] **Step 1: Add HTTP static file serving**

When `config.model_path` is set, serve that directory on a separate HTTP port (8766) or as part of the WebSocket server using `websockets`' HTTP support. CORS headers required for Vite dev proxy.

- [ ] **Step 2: Test model loading**

```bash
uv run muse-vtuber --synthetic --model "/path/to/akari_vts" --debug
curl http://localhost:8766/akari.model3.json
```

- [ ] **Step 3: Commit**

```bash
git add src/muse_vtuber/server.py
git commit -m "feat: HTTP static file server for Live2D model directory"
```

---

### Done Criteria

- [ ] `uv run muse-vtuber --synthetic --model /path/to/akari_vts --debug` starts backend with WebSocket + model server
- [ ] `cd frontend && pnpm dev` shows setup UI at localhost:5173
- [ ] Signal quality bars update per-channel
- [ ] Live2D avatar head tracks with synthetic IMU data
- [ ] Bias sliders adjust tracking in both UI and VTS
- [ ] Recenter button resets head pose
- [ ] Settle progress overlay during calibration
- [ ] All backend tests pass

### Manual Verification

1. Start VTube Studio with API enabled
2. `uv run muse-vtuber --mac XX:XX --vts --model /path/to/akari_vts`
3. Open browser to localhost:5173
4. Check signal quality — verify headband fit
5. Move head — avatar follows in both browser and VTS
6. Adjust bias sliders — both avatars shift
7. Click Recenter — both reset
8. Stay still during settle — progress bar fills, then tracking activates
