# ZyphraExps

BCI experimentation platform: Muse 2 EEG headband → Python backend (BrainFlow + WebSocket) → React frontend (TanStack Start SPA).

## Prerequisites

- Python 3.12+
- Node 22+, pnpm
- [BrainFlow](https://brainflow.readthedocs.io/) (`pip install brainflow`)
- Muse 2 headband (or use `--synthetic` for simulated data)
- Linux with Bluetooth/bluez (for real hardware only)

## Quick Setup

```bash
./setup.sh
```

Or manually:

```bash
pip install -r backend/requirements.txt
pip install brainflow
cd frontend && pnpm install
```

## Running

### Terminal 1: Backend

```bash
# Without hardware (synthetic board — generates fake EEG)
python -m backend.main --synthetic

# With Muse hardware
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"
```

Backend starts a WebSocket server on `ws://localhost:8765`.

### Terminal 2: Frontend

```bash
cd frontend
pnpm dev
```

- **Dashboard**: http://localhost:3000 — live EEG waveforms, recording controls, metrics
- **EUTERPE Demo**: http://localhost:3000/demo — brain-to-light control demo with event log

### BrainFlow + Muse 2 Setup

```bash
sudo systemctl start bluetooth
bluetoothctl scan on        # power on Muse, look for "Muse-XXXX"
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"
```

## Architecture

```
backend/
├── main.py            # EEGServer — WebSocket streaming, recording, commands
├── acquisition.py     # BrainFlow board wrapper with reconnection
├── config.py          # Board, filter, server configuration
└── pipeline/          # Pluggable real-time processing stages
    ├── factory.py     # Pipeline assembly
    └── stages/
        ├── detectors.py      # BlinkDetector, NodDetector, SpeechDetector, ClenchDetector
        ├── features.py       # Band powers, concentration, signal quality, eyes-closed
        └── preprocessing.py  # Wavelet denoising

frontend/
├── src/
│   ├── routes/
│   │   ├── index.tsx          # Dashboard with live waveforms
│   │   └── demo.tsx           # EUTERPE demo page
│   ├── components/
│   │   ├── BrainHeatmap.tsx   # 3D brain visualization (R3F)
│   │   ├── RecordingPanel.tsx # Cued protocol recording UI
│   │   └── demo/              # Demo-specific components
│   ├── hooks/
│   │   ├── useSensorStream.ts # WebSocket data hook
│   │   ├── useMetrics.ts      # Metrics polling
│   │   └── useEvents.ts       # BCI event polling
│   └── lib/
│       ├── protocol.ts        # Binary frame decoder
│       └── ringBuffer.ts      # Circular buffer for waveforms

scripts/
├── eval_blink_detector.py     # Detector evaluation harness
├── analyze_blink_params.py    # Blink parameter sweep
├── analyze_nod_imu.py         # IMU nod analysis
├── experiment.py              # Experiment tracking
└── run_zuna.py                # ZUNA signal reconstruction

recordings/                    # Saved trials (.npz + .fif) — not in git
experiments/                   # Tracked experiment runs
docs/research/                 # Research notes and findings
```

## BCI Event Detection

| Event | Method | Accuracy | Input |
|-------|--------|----------|-------|
| single_blink | Adaptive threshold + 5 guards | F1=0.88 | EEG (AF7+AF8) |
| double_blink | Refractory + classify window | ~70% | EEG (AF7+AF8) |
| nod_yes | Gyro pitch threshold (40 deg/s) | 100% | IMU gyroscope |
| nod_no | Gyro yaw threshold (100 deg/s) | 100% | IMU gyroscope |
| eyes_closed | Alpha power ratio | ~90% | EEG (all channels) |
| concentration | Theta/beta ratio | ~75% | EEG (AF7+AF8) |

## Protocol

- **Sensor data**: Binary WebSocket frames (1B type + 2B channels + 2B samples + float32 data)
- **Metrics**: JSON messages over the same WebSocket (band powers, HR, concentration, etc.)
- **BCI events**: JSON `{"type": "bci_event", "kind": "single_blink", "confidence": 0.9, ...}`

## Muse 2 Channels

| Stream | Channels | Sample Rate |
|--------|----------|-------------|
| EEG    | TP9, AF7, AF8, TP10 | 256 Hz |
| PPG    | Red, IR, Ambient | 64 Hz |
| IMU    | Accel XYZ + Gyro XYZ | 52 Hz |

## Recording

The dashboard has a cued protocol recorder: countdown → beep cue → record → rest → repeat. Recordings save to `recordings/<label>/` as `.npz` (raw numpy) and `.fif` (MNE format with standard_1020 montage).

Available protocols: baseline, rest, single/double blink, clench, eyebrow raise/furrow, talk, eyes closed/open, nod yes/no, head still, meditation, mental math.

## Tests

```bash
python -m pytest tests/ -v
```

## Hardware Safety

- **Never kill the server while Muse is connected** — forces BLE disconnect, may require Muse power cycle + `sudo systemctl restart bluetooth`
- Use `--synthetic` for development without hardware
