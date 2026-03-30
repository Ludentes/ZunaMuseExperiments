# Design: Muse VTuber Bridge

**Date:** 2026-03-30
**Status:** Draft

## Purpose

Standalone Python app that bridges BCI hardware (Muse 2 primarily, any BrainFlow-supported device) to VTuber avatar software via VMC protocol, VRChat OSC, and VTube Studio WebSocket API.

Three operating tiers in one app:
1. **Camera-free** — IMU head tracking + EEG expressions (Muse only, no webcam)
2. **Fusion** — IMU + OpenSeeFace webcam fusion + EEG expressions (better than either alone)
3. **EEG addon** — blink, clench, focus, relaxation as blendshapes/parameters (always active)

## Success Criteria

1. User installs, connects Muse, sees EEG blink in VSeeFace within 5 minutes
2. Head tracking works in camera-free mode (with known drift limitations)
3. Fusion mode measurably improves tracking vs webcam-only or IMU-only
4. Compatible with VSeeFace, Warudo, VNyan (VMC), VRChat (OSC), VTube Studio (WebSocket)

## Architecture

### Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Main Process                          │
│                                                          │
│  ┌──────────┐    ┌───────────┐    ┌──────────────────┐  │
│  │ BrainFlow│    │ Processing│    │ Output Sinks     │  │
│  │ Thread   │───▶│ Pipeline  │───▶│  ├─ VMC (UDP)    │  │
│  │          │    │           │    │  ├─ OSC (UDP)    │  │
│  └──────────┘    │  EEG:     │    │  └─ VTS (WS)    │  │
│                  │   blink   │    └──────────────────┘  │
│  ┌──────────┐    │   clench  │                          │
│  │ OSF UDP  │───▶│   focus   │    ┌──────────────────┐  │
│  │ Receiver │    │   relax   │    │ Config / CLI     │  │
│  │(optional)│    │           │    └──────────────────┘  │
│  └──────────┘    │  IMU:     │                          │
│                  │   head    │                          │
│                  │   pose    │                          │
│                  │           │                          │
│                  │  Fusion:  │                          │
│                  │   comp.   │                          │
│                  │   filter  │                          │
│                  └───────────┘                          │
└─────────────────────────────────────────────────────────┘
```

### Runtime Model

Single process, asyncio event loop. BrainFlow is synchronous — polled in a dedicated thread that pushes data chunks onto an `asyncio.Queue`. The main loop consumes the queue, runs the processing pipeline, and distributes results to output sinks.

OpenSeeFace UDP receiver (optional, for fusion mode) is an asyncio UDP protocol that feeds webcam pose into the fusion module.

### Component Breakdown

#### 1. `source.py` — Hardware Abstraction

```python
class BCISource(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def poll_eeg(self) -> np.ndarray | None: ...   # (n_ch, n_samples)
    def poll_imu(self) -> np.ndarray | None: ...   # (6, n_samples) accel+gyro
    @property
    def eeg_sample_rate(self) -> int: ...
    @property
    def imu_sample_rate(self) -> int: ...
    @property
    def has_imu(self) -> bool: ...
```

`BrainFlowSource` implements this, adapted from zyphraexps `Acquisition`. Handles connection retries, stream health monitoring, reconnection. Configurable board_id (numeric or BrainFlow name string like `muse_2_board`) + MAC address. Resolves string names via `BoardIds[name.upper()]` with fallback to int parsing.

#### 2. `pipeline/` — EEG Processing

Adapted from zyphraexps pipeline. Simplified — no recording, no PPG, no ZUNA.

**Stages:**
- `SpeechDetector` — guards blink detector from speech EMG false positives
- `BlinkDetector` — EEG-based blink detection (TP9/TP10 temporal channels)
- `ClenchDetector` — jaw clench detection
- `BandPowerStage` — computes alpha/beta/theta/gamma/delta power per hemisphere (left=TP9+AF7, right=AF8+TP10) and average. EMA smoothing with configurable decay, **artifact-gated**: when blink/clench/speech is active, EMA target freezes to last clean value to prevent contamination.
- `FocusRelaxStage` — derives focus and relaxation from band power ratios, per hemisphere and average:
  - Focus: `tanh(1.1 * log(beta / theta))` → [-1, 1] (matches BrainFlowsIntoVRChat formula for VRChat OSC compatibility)
  - Relaxation: `tanh(1.1 * log(alpha / theta))` → [-1, 1]
  - Outputs: FocusLeft, FocusRight, FocusAvg, RelaxLeft, RelaxRight, RelaxAvg
  - Unsigned variants (0-1) also provided for animation constraints

**Data flow:** `PipelineFrame(eeg, imu, timestamp)` → stages mutate frame → frame carries events + results.

The pipeline cadence model (FAST/SLOW) carries over: blink/clench run on every chunk (FAST, ~16ms), band power/focus run on accumulated windows (SLOW, ~1s).

#### 3. `head_pose.py` — IMU Head Tracking

Port of zyphraexps `frontend/src/lib/headPose.ts` to Python.

- Madgwick AHRS filter (via `ahrs` Python package or custom ~100 lines)
- Axis remap: Muse frame → standard frame (confirmed empirically in demo)
- Gyro deadzone (2 deg/s), still detection (5 deg/s threshold)
- Velocity-gated yaw decay (30%/s still, 2%/s moving)
- One Euro quaternion filter for adaptive smoothing
- Recenter (store home orientation, compute relative)
- Output: quaternion relative to home pose

Key constants from demo testing:
```
GYRO_DEADZONE = 2.0       # deg/s
STILL_THRESHOLD = 5.0     # deg/s
YAW_DECAY_STILL = 0.3     # per second
YAW_DECAY_MOVING = 0.02   # per second
SETTLE_FRAMES = 260       # ~5s at 52Hz
MADGWICK_BETA = 0.8       # high — prioritize responsiveness
ONE_EURO_MIN_CUTOFF = 0.3
ONE_EURO_BETA = 1.5
```

#### 4. `fusion.py` — IMU + Webcam Complementary Filter

Quaternion complementary filter running at IMU rate (52Hz):

```python
class ComplementaryFusion:
    def __init__(self, alpha: float = 0.96):
        self.alpha = alpha
        self.q_fused: Quaternion = Quaternion.identity()

    def update_imu(self, q_imu: Quaternion) -> Quaternion:
        """Called at 52Hz. Pure IMU prediction."""
        self.q_fused = q_imu
        return self.q_fused

    def update_webcam(self, q_webcam: Quaternion, confidence: float) -> Quaternion:
        """Called at ~30fps when OpenSeeFace data arrives."""
        alpha = self._adaptive_alpha(confidence)
        self.q_fused = slerp(q_webcam, self.q_fused, alpha)
        return self.q_fused

    def _adaptive_alpha(self, confidence: float) -> float:
        # High confidence → trust webcam more (lower alpha)
        # Low confidence → trust IMU more (higher alpha)
        return self.alpha + (1.0 - self.alpha) * (1.0 - confidence)
```

When OpenSeeFace is not connected, fusion degrades to pure IMU (Tier 1). When connected, IMU provides smooth inter-frame motion, webcam corrects drift every ~33ms.

#### 5. `openseeface.py` — OpenSeeFace UDP Receiver

Parses OpenSeeFace's binary UDP protocol. Extracts:
- Head rotation (quaternion)
- Face detection confidence
- Optionally: blendshapes (eye, mouth) for pass-through

Listens on configurable port (default: 11573, OpenSeeFace's default output port). Asyncio UDP protocol.

#### 6. `outputs/vmc.py` — VMC Protocol Output

VMC over UDP using `python-osc`. Implements 5 message types directly (no python-vmcp dependency — it's marked "Unstable"):

```python
# Head tracking
/VMC/Ext/Bone/Pos "Head" (pos.x pos.y pos.z) (q.x q.y q.z q.w)
/VMC/Ext/Bone/Pos "Neck" (pos.x pos.y pos.z) (q.x q.y q.z q.w)

# EEG expressions as blendshapes
/VMC/Ext/Blend/Val "blink" 0.0-1.0
/VMC/Ext/Blend/Val "muse_focus" 0.0-1.0
/VMC/Ext/Blend/Val "muse_relaxation" 0.0-1.0
/VMC/Ext/Blend/Val "muse_clench" 0.0-1.0
/VMC/Ext/Blend/Apply

# Status
/VMC/Ext/OK 1
/VMC/Ext/T <relative_time>
```

Sends to configurable IP:port (default: 127.0.0.1:39539).

**Bone naming:** Uses Unity `HumanBodyBones` names as required by VMC spec. Head rotation split 60/40 between Neck and Head bones (same as demo).

**Blendshape naming:** Standard VRM blendshapes where applicable (`blink`). Custom names prefixed with `muse_` for EEG-specific values. VTuber apps will show these as available blend inputs.

#### 7. `outputs/osc_vrchat.py` — VRChat OSC Output

Partial compatibility with BrainFlowsIntoVRChat parameter format. Sends the most-used subset:

```python
# Neurofeedback (signed -1 to 1)
/avatar/parameters/BFI/NeuroFB/FocusLeft     float
/avatar/parameters/BFI/NeuroFB/FocusRight    float
/avatar/parameters/BFI/NeuroFB/FocusAvg      float
/avatar/parameters/BFI/NeuroFB/RelaxLeft     float
/avatar/parameters/BFI/NeuroFB/RelaxRight    float
/avatar/parameters/BFI/NeuroFB/RelaxAvg      float
# Unsigned variants (0 to 1) for animation
/avatar/parameters/BFI/NeuroFB/FocusAvg+     float
/avatar/parameters/BFI/NeuroFB/RelaxAvg+     float
# Power bands per hemisphere (0 to 1)
/avatar/parameters/BFI/PwrBands/Left/Alpha   float
/avatar/parameters/BFI/PwrBands/Right/Alpha  float
/avatar/parameters/BFI/PwrBands/Avg/Alpha    float
# ... same for Delta, Theta, Beta, Gamma
# Status / info
/avatar/parameters/BFI/Info/DeviceConnected  bool
/avatar/parameters/BFI/Info/SecondsSinceLastUpdate float
/avatar/parameters/BFI/Info/BatteryLevel     float  # if available
```

**Not implemented (vs full BFiVRC):** HR, SpO2, respiration, ML intent classification, HueShift addon. Documented in README.

Sends to 127.0.0.1:9000 (VRChat default). Also works with VNyan (accepts VRChat OSC since v1.3.2).

#### 8. `outputs/vts.py` — VTube Studio Plugin (Phase 2)

WebSocket client connecting to VTube Studio on port 8001. Follows VTS authentication flow (token request → user approval popup → persistent token). Creates custom parameters:

- `MuseBlink` (0-1)
- `MuseFocus` (0-1)
- `MuseRelaxation` (0-1)
- `MuseClench` (0-1)

Injects values at pipeline rate. Users bind these to Live2D model parameters in VTube Studio's UI.

Uses `websockets` library (already well-maintained, async-native). No pyvts dependency — the auth flow + parameter injection is ~80 lines.

#### 9. `config.py` — Configuration

TOML config file (`~/.config/muse-vtuber/config.toml` or CLI flags):

```toml
[device]
board_id = "muse_2_board"  # BrainFlow name or numeric ID (38)
mac_address = ""            # auto-discover if empty

[processing]
ema_decay = 0.04           # EMA smoothing for neurofeedback (lower = smoother)
window_seconds = 1.0       # PSD computation window

[outputs.vmc]
enabled = true
host = "127.0.0.1"
port = 39539

[outputs.osc]
enabled = false        # off by default, enable for VRChat
host = "127.0.0.1"
port = 9000

[outputs.vts]
enabled = false        # off by default, enable for VTube Studio
port = 8001

[fusion]
enabled = false        # auto-enables if OpenSeeFace detected
openseeface_port = 11573
alpha = 0.96

[head_tracking]
enabled = true
madgwick_beta = 0.8
smoothing_min_cutoff = 0.3
smoothing_beta = 1.5
```

CLI overrides: `muse-vtuber --board-id muse_2_board --mac XX:XX:XX:XX:XX:XX --vmc-port 39539 --debug`

The `--debug` flag logs all output messages to terminal (essential for troubleshooting without a GUI).

#### 10. `main.py` — Entry Point

```python
async def main():
    config = load_config()
    source = BrainFlowSource(config.device)
    pipeline = create_pipeline(config)
    head_pose = HeadPoseEstimator(config.head_tracking)
    fusion = ComplementaryFusion(config.fusion.alpha) if config.fusion.enabled else None
    outputs = create_outputs(config)

    # Start BrainFlow in thread
    source.start()
    poll_task = asyncio.create_task(poll_brainflow(source, queue))

    # Start OpenSeeFace listener if fusion enabled
    if fusion:
        osf_task = asyncio.create_task(listen_openseeface(config.fusion, fusion))

    # Main loop
    async for eeg, imu in data_stream(queue):
        frame = PipelineFrame(eeg=eeg, imu=imu, timestamp=time.time())
        pipeline.run(Cadence.FAST, frame)

        # Head pose from IMU
        if imu is not None and head_pose:
            q = head_pose.update(imu)
            if fusion:
                q = fusion.update_imu(q)

        # Distribute to outputs
        for output in outputs:
            output.send(frame, q)
```

### Repo Structure

```
muse-vtuber/
├── pyproject.toml
├── README.md
├── src/
│   └── muse_vtuber/
│       ├── __init__.py
│       ├── main.py              # entry point, async loop
│       ├── config.py            # TOML config + CLI args
│       ├── source.py            # BCISource protocol + BrainFlowSource
│       ├── head_pose.py         # Madgwick + drift countermeasures + One Euro
│       ├── fusion.py            # quaternion complementary filter
│       ├── openseeface.py       # UDP receiver + binary parser
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── base.py          # Stage, Pipeline, PipelineFrame
│       │   ├── blink.py         # BlinkDetector (from zyphraexps)
│       │   ├── clench.py        # ClenchDetector
│       │   ├── speech.py        # SpeechDetector (blink guard)
│       │   ├── band_power.py    # frequency band computation
│       │   └── focus.py         # focus/relaxation from bands
│       └── outputs/
│           ├── __init__.py
│           ├── vmc.py           # VMC protocol over python-osc
│           ├── osc_vrchat.py    # VRChat-compatible OSC
│           └── vts.py           # VTube Studio WebSocket plugin
├── tests/
│   ├── test_head_pose.py
│   ├── test_fusion.py
│   ├── test_vmc_output.py
│   └── test_pipeline.py
└── docs/
    └── setup.md
```

### Dependencies

```toml
[project]
dependencies = [
    "brainflow>=5.0",
    "numpy>=1.24",
    "scipy>=1.10",
    "python-osc>=1.8",      # VMC + VRChat OSC output
    "websockets>=12.0",      # VTube Studio plugin
    "tomli>=2.0; python_version < '3.11'",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio"]
```

No heavy dependencies beyond BrainFlow. Total: ~6 packages. No opencv, no mediapipe (fusion uses OpenSeeFace externally).

### Error Handling

- **BLE disconnect:** BrainFlowSource retries with backoff (from zyphraexps pattern). Outputs send identity quaternion / zero blendshapes during disconnect. Reconnect resumes automatically.
- **OpenSeeFace not running:** Fusion falls back to IMU-only. No error, just logs "OpenSeeFace not detected, running in camera-free mode."
- **VTube Studio not running:** VTS output retries connection periodically (every 5s). Other outputs unaffected.
- **VMC receiver not listening:** UDP sends are fire-and-forget. No error possible.

### Testing Strategy

- **Unit tests:** HeadPoseEstimator (quaternion math, axis mapping, drift decay), ComplementaryFusion (slerp, adaptive alpha, degradation), VMC output (message format), pipeline stages (blink/clench with recorded data)
- **Integration test:** BrainFlowSource with synthetic board (board_id=-1), full pipeline → VMC output → verify OSC messages
- **Manual test:** Connect real Muse → VSeeFace with VMC receiver → verify blink/head/focus on avatar

### What's NOT in Scope

- GUI (CLI only for v1, GUI is a future concern)
- Direct webcam access (we use OpenSeeFace, not MediaPipe)
- PPG / heart rate / SpO2
- Full body tracking
- Model rendering (that's the VTuber app's job)
- OBS integration (not needed — VTuber app → OBS capture)
