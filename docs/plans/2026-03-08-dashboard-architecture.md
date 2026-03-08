# EEG Dashboard Architecture

**Date:** 2026-03-08
**Status:** Draft

---

## Overview

Real-time EEG experimentation dashboard for Muse 2. Two processes: a Python backend that acquires and processes data, and a browser-based frontend that visualizes it. Connected by a single WebSocket.

## Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Data acquisition | BrainFlow (compiled with `--ble`) | Native BLE on Linux, 40+ device support, built-in DSP |
| Backend | Python + `websockets` | Async, minimal, binary frame support |
| Transport | Single WebSocket (`ws://localhost:8765`) | Binary frames for EEG, JSON frames for metrics |
| Frontend framework | TanStack Start (SPA mode) | Type-safe routing, Vite-based, room to grow |
| Waveform rendering | webgl-plot | MIT, native WebGL, purpose-built for oscilloscope/waveform |
| UI | React + shadcn/ui | Standard component library, already in user's toolchain |
| Persistence | Filesystem (`.fif` files) + SQLite (optional) | No external database needed |

## Muse 2 Sensor Inventory

The Muse 2 exposes three data streams via BrainFlow presets:

### EEG (Default Preset) — 256 Hz, 8 rows
| Row | Content |
|-----|---------|
| 0 | Package number |
| 1 | TP9 (left ear) |
| 2 | AF7 (left forehead) |
| 3 | AF8 (right forehead) |
| 4 | TP10 (right ear) |
| 5 | Other (AUX/reference) |
| 6 | Timestamp |
| 7 | (marker) |

Electrode positions are standard 10-20. All four are in MNE's `standard_1020` montage. Units: microvolts (uV). 12-bit ADC, effective range roughly ±1000 uV.

### PPG (Ancillary Preset) — 64 Hz, 6 rows
| Row | Content |
|-----|---------|
| 0 | Package number |
| 1 | PPG channel 1 (IR) |
| 2 | PPG channel 2 (Red) |
| 3 | PPG channel 3 (Ambient) |
| 4 | Timestamp |
| 5 | (marker) |

The PPG sensor sits on the forehead between AF7/AF8. Three wavelengths: infrared (blood oxygen), red, and ambient light (for artifact correction). BrainFlow's `DataFilter.get_heart_rate()` computes HR from the IR channel. SpO2 estimation is also available via `DataFilter.get_oxygen_level()`.

**Requires activation:** Call `board.config_board("p50")` before `start_stream()` to enable PPG + 5th EEG channel.

### IMU (Auxiliary Preset) — 52 Hz, 9 rows
| Row | Content |
|-----|---------|
| 0 | Package number |
| 1 | Accel X |
| 2 | Accel Y |
| 3 | Accel Z |
| 4 | Gyro X |
| 5 | Gyro Y |
| 6 | Gyro Z |
| 7 | Timestamp |
| 8 | (marker) |

Accelerometer: m/s^2. Gyroscope: degrees/sec. The IMU is useful for:
- **Head movement detection**: jaw clench artifacts, head nods, posture changes
- **Motion artifact tagging**: flag EEG segments with concurrent head movement
- **Meditation stillness tracking**: quantify how still the user is during a session
- **Head pose estimation**: rough head orientation from accel + gyro fusion

### Derived Metrics (computed in Python, sent as JSON)

| Metric | Source | Update Rate | Description |
|--------|--------|-------------|-------------|
| Band powers (δ,θ,α,β,γ) | EEG | 1-4 Hz | PSD via BrainFlow `get_avg_band_powers()` |
| Theta/Beta ratio | EEG | 1-4 Hz | Attention index (higher = less focused) |
| Frontal Alpha Asymmetry | EEG | 1-4 Hz | `log(α_AF8) - log(α_AF7)` — approach/withdrawal |
| Signal quality (per ch) | EEG | 1-4 Hz | Railed %, std dev, line noise ratio → 0-1 score |
| Heart rate (BPM) | PPG IR | 1 Hz | BrainFlow `get_heart_rate()` on IR channel |
| SpO2 estimate | PPG IR+Red | 1 Hz | BrainFlow `get_oxygen_level()` |
| HRV (RMSSD) | PPG IR | 0.1 Hz | Root mean square of successive RR differences |
| Head movement | IMU | 4 Hz | Accel magnitude deviation from gravity vector |
| Head pose (pitch/roll) | IMU | 4 Hz | Complementary filter on accel + gyro |
| Motion artifact flag | IMU+EEG | 4 Hz | True when head movement exceeds threshold |
| Jaw clench detected | EEG+IMU | 4 Hz | High-amplitude burst on TP9/TP10 + accel spike |

## System Diagram

```
┌──────────────────────────────────────────────────┐
│ Python Backend (single process)                   │
│                                                   │
│  BrainFlow ──→ Ring Buffer ──→ WebSocket Server   │
│  (256Hz EEG)    (numpy)        (ws://localhost:8765)
│  (64Hz PPG)                         │             │
│  (52Hz IMU)                         │             │
│       │                             │             │
│       └──→ DSP Pipeline             │             │
│            - Band powers (δθαβγ)    │             │
│            - Heart rate (from PPG)  │             │
│            - Signal quality scores  │             │
│            - Fit detection          │             │
│                    │                │             │
│                    └──→ JSON frames (1-4Hz) ──┘   │
│                                                   │
│  File I/O:                                        │
│    - Record raw data → .fif (MNE format)          │
│    - Session metadata → sessions.json or SQLite   │
└───────────────────────────────────────────────────┘
                    │
          ws://localhost:8765
          (binary + JSON frames)
                    │
┌───────────────────────────────────────────────────┐
│ Browser (TanStack Start SPA)                       │
│                                                    │
│  useWebSocket (react-use-websocket)                │
│       │                                            │
│       ├── binary frames ──→ useRef buffer          │
│       │                        │                   │
│       │                  requestAnimationFrame      │
│       │                        │                   │
│       │                   webgl-plot canvas         │
│       │                   (4ch waveforms,           │
│       │                    imperative rendering)    │
│       │                                            │
│       └── JSON frames ──→ React state (1-4Hz)      │
│                               │                    │
│                    ┌──────────┼──────────┐         │
│                    ▼          ▼          ▼         │
│              Metrics UI   Fit Tool   Controls      │
│              (band pwr,   (contact   (record,      │
│               HR, ratios)  quality)   session)     │
│                                                    │
└────────────────────────────────────────────────────┘
```

## WebSocket Protocol

Single WebSocket, two message types distinguished by frame type:

### Binary frames (high frequency, ~16 batches/sec)

Each batch contains ~16 samples (256Hz / 16 = 16 samples per batch at ~60fps cadence).

```
Format: Float32Array, little-endian
Layout per sample: [TP9, AF7, AF8, TP10] (4 × float32 = 16 bytes)
Batch: N samples concatenated = N × 16 bytes

Total bandwidth: 256 samples/sec × 16 bytes = ~4 KB/sec
```

PPG and IMU data are interleaved in separate binary message types, distinguished by a 1-byte header prefix:

```
0x01 [EEG data...]     — 4 channels × N samples × float32
0x02 [PPG data...]     — 3 channels × N samples × float32
0x03 [IMU data...]     — 6 channels (accel+gyro) × N samples × float32
```

### JSON frames (low frequency, 1-4Hz)

```json
{
  "type": "metrics",
  "timestamp": 1709900000.123,
  "eeg": {
    "band_powers": {
      "delta": [12.3, 11.8, 10.5, 13.1],
      "theta": [8.1, 7.9, 8.4, 7.5],
      "alpha": [15.7, 14.2, 13.8, 16.1],
      "beta":  [6.2, 5.8, 6.1, 5.9],
      "gamma": [2.1, 1.9, 2.0, 2.2]
    },
    "theta_beta_ratio": [1.31, 1.36, 1.38, 1.27],
    "frontal_alpha_asymmetry": -0.03,
    "signal_quality": {
      "TP9":  0.95,
      "AF7":  0.82,
      "AF8":  0.78,
      "TP10": 0.91
    },
    "fit_status": "good"
  },
  "ppg": {
    "heart_rate_bpm": 72.5,
    "spo2_percent": 98.2,
    "hrv_rmssd_ms": 42.3
  },
  "imu": {
    "head_movement": 0.12,
    "head_pose": {"pitch": -5.2, "roll": 1.8},
    "motion_artifact": false,
    "jaw_clench": false
  },
  "session": {
    "recording": false,
    "duration_sec": 0,
    "filename": null
  }
}
```

### Commands (client → server, JSON)

```json
{"cmd": "start_recording", "filename": "session_001"}
{"cmd": "stop_recording"}
{"cmd": "set_filter", "highpass": 0.5, "lowpass": 45.0}
{"cmd": "enable_ppg", "enabled": true}
{"cmd": "get_sessions"}
```

## Frontend Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ ┌─── Fit Tool ────────────────────────────────────────────────┐  │
│ │  [HEAD DIAGRAM]   TP9: ████ 95%    AF7: ███░ 82%           │  │
│ │  (top-down view   AF8: ███░ 78%    TP10: ████ 91%          │  │
│ │   with colored    Status: Good — all electrodes in contact  │  │
│ │   electrodes)     Motion: Still  |  Jaw clench: No          │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─── EEG Waveforms (webgl-plot) ──────────────────────────────┐  │
│ │  TP9  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿  │  │
│ │  AF7  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿  │  │
│ │  AF8  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿  │  │
│ │  TP10 ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿  │  │
│ └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│ ┌─── Brain Metrics ──────┐  ┌─── Vitals ─────────────────────┐  │
│ │  Band Powers (avg)      │  │  HR: ♥ 72 bpm                 │  │
│ │  δ ████████████ 12.3    │  │  SpO2: 98.2%                  │  │
│ │  θ ████████     8.1     │  │  HRV (RMSSD): 42.3 ms         │  │
│ │  α ██████████████ 15.7  │  │                                │  │
│ │  β ██████       6.2     │  │  PPG Waveform (webgl-plot):    │  │
│ │  γ ██           2.1     │  │  IR  ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿   │  │
│ │                         │  │                                │  │
│ │  Ratios                 │  ├─── Motion ─────────────────────┤  │
│ │  θ/β: 1.31 (relaxed)   │  │  Head pose: pitch -5° roll 2°  │  │
│ │  FAA: -0.03 (neutral)   │  │  Movement: 0.12 (still)        │  │
│ └─────────────────────────┘  │  [artifact indicator bar]       │  │
│                               └────────────────────────────────┘  │
│                                                                  │
│ ┌─── Controls ────────────────────────────────────────────────┐  │
│ │  [● Record] [⏹ Stop]  |  Filter: 0.5-45 Hz  |  Window: 5s │  │
│ │  [PPG: ON] [IMU: ON]  |  Notch: 50Hz         |  Notes: ... │  │
│ └─────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Fit Tool

The fit tool is the first thing the user sees. It provides immediate feedback on electrode contact quality before running experiments.

**Signal quality scoring** (computed in Python):
- Compute per-channel metrics over a 1-second sliding window:
  - **Railed percentage**: samples hitting min/max ADC range (±1000 uV). >5% = bad contact.
  - **Standard deviation**: very low std (<2 uV) = no signal / not on head. Very high (>200 uV) = excessive artifact.
  - **60Hz/50Hz power ratio**: high line noise relative to total power = poor contact or dry electrode.
- Combine into a 0.0-1.0 quality score per channel.
- Overall fit status: `good` (all channels >0.7), `adjust` (1-2 channels <0.7), `poor` (3+ channels <0.7 or any channel railing).

**Visual feedback**:
- 4 colored bars (green/yellow/red) with percentage labels
- Head diagram showing electrode positions with color coding
- Text recommendation: "Adjust left ear sensor" / "Push headband down on forehead" / "All good"

### Waveform Panel

- 4 stacked channels, each a separate webgl-plot `WebglLine`
- Shared canvas for performance (single WebGL context)
- Ring buffer: 5 seconds × 256 samples = 1,280 points per channel
- Scrolls left continuously, new data appended on right
- Optional: amplitude scale indicator, channel labels
- Future: click to freeze/inspect a moment

### Brain Metrics Panel

- React components, updated via JSON frames at 1-4Hz
- Band power bars (delta through gamma) — averaged across channels or per-channel toggle
- Derived ratios: theta/beta (attention index), frontal alpha asymmetry (emotional valence)
- Color-coded interpretation labels: "focused", "relaxed", "neutral", "drowsy"
- All values computed in Python via BrainFlow `get_avg_band_powers()`, frontend just displays

### Vitals Panel

- **Heart rate**: BPM from PPG IR channel via `DataFilter.get_heart_rate()`
- **SpO2**: Estimated blood oxygen from IR+Red channels via `DataFilter.get_oxygen_level()`
- **HRV (RMSSD)**: Heart rate variability — computed from RR intervals over 30-60s window
- **PPG waveform**: Small webgl-plot trace showing the IR PPG signal (64Hz, ring buffer ~5s). Useful for verifying PPG sensor contact and seeing pulse wave morphology.

### Motion Panel

- **Head pose**: Pitch and roll angles from complementary filter on accel+gyro (52Hz)
- **Movement magnitude**: Deviation of accelerometer vector from gravity — 0 = perfectly still
- **Artifact indicator**: Bar that lights up when head movement exceeds threshold, signaling EEG contamination
- **Jaw clench detection**: High-amplitude burst on TP9/TP10 coinciding with accel spike

### Controls Panel

- Record / Stop recording (saves .fif to disk via Python, includes all active streams)
- Filter settings (highpass, lowpass, notch frequency)
- Window duration slider (2s / 5s / 10s for waveform display)
- Stream toggles: [PPG: ON/OFF] [IMU: ON/OFF]
- Notch filter: 50Hz / 60Hz / off
- Session notes (free text, saved with session metadata)

## Python Backend Structure

```
backend/
├── main.py              # Entry point, starts WS server + BrainFlow
├── acquisition.py       # BrainFlow connection, streaming, ring buffer
├── processing.py        # DSP: filters, band powers, quality scores, HR
├── protocol.py          # WebSocket message encoding/decoding
├── recording.py         # MNE .fif file writing, session metadata
└── config.py            # Board type, filter defaults, port settings
```

### Key design decisions

- **Single async process.** BrainFlow polling runs in a thread (it's blocking C++), data is pushed to an `asyncio.Queue`, and the WebSocket server consumes from the queue. No multiprocessing complexity.
- **BrainFlow does the heavy lifting.** Filters, FFT, band powers, heart rate — all available via `DataFilter`. No need for scipy/numpy DSP from scratch.
- **MNE only for file I/O.** Convert BrainFlow arrays to MNE `RawArray` only when saving recordings. Don't run MNE in the hot path.

## Frontend Structure

```
frontend/
├── app/
│   ├── routes/
│   │   ├── __root.tsx            # Layout shell
│   │   └── index.tsx             # Main dashboard (single page for now)
│   ├── components/
│   │   ├── FitTool.tsx           # Electrode contact quality + head diagram
│   │   ├── EEGWaveformPanel.tsx  # webgl-plot canvas for 4 EEG channels
│   │   ├── PPGWaveformPanel.tsx  # webgl-plot canvas for PPG IR trace
│   │   ├── BrainMetrics.tsx      # Band powers, ratios, interpretation
│   │   ├── VitalsPanel.tsx       # HR, SpO2, HRV
│   │   ├── MotionPanel.tsx       # Head pose, movement, artifact flag
│   │   └── ControlsPanel.tsx     # Record, filter, stream toggles
│   ├── hooks/
│   │   ├── useSensorStream.ts    # WebSocket + binary frame demux (EEG/PPG/IMU)
│   │   └── useMetrics.ts         # JSON frame parsing into React state
│   ├── lib/
│   │   ├── ringBuffer.ts         # Fixed-size typed array ring buffer
│   │   └── protocol.ts           # Message type constants, binary layout
│   └── router.tsx
├── package.json
└── vite.config.ts                # TanStack Start config, SPA mode
```

## Data Flow Summary

1. BrainFlow polls Muse 2 at 256Hz in a background thread
2. Raw samples go into a numpy ring buffer
3. Every ~16ms, a batch of samples is packed as binary and sent over WebSocket
4. Every ~250ms-1s, derived metrics are computed and sent as JSON
5. Browser receives binary → ref buffer → rAF → webgl-plot (no React renders)
6. Browser receives JSON → setState → React re-renders metrics/fit UI (1-4Hz, cheap)
7. User commands (record, filter, etc.) sent as JSON over same WebSocket
8. Python handles commands: starts/stops recording, adjusts filters, etc.

## Future Extensions (not in v1)

- ZUNA integration: button to run upsampling on recorded .fif files
- Session history page (TanStack Router adds value here)
- Experiment runner: stimulus presentation + EEG recording with markers
- 3D head model showing electrode positions (react-three-fiber)
- Export to CSV/EDF formats
- Multiple device support (connect 2+ Muse headbands)
