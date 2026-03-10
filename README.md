# ZyphraExps

BCI experimentation platform: Muse 2 EEG headband → Python backend (BrainFlow + WebSocket) → React frontend (TanStack Start SPA).

## Prerequisites

- Python 3.12+
- Node 22+, pnpm
- [BrainFlow](https://brainflow.readthedocs.io/) (`pip install brainflow`)
- Muse 2 headband (or use `--synthetic` for simulated data)

## Quickstart

### Terminal 1: Backend

```bash
pip install -r backend/requirements.txt

# With Muse hardware (requires bluez + BLE adapter)
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"  # your Muse MAC

# Without hardware (synthetic board — BrainFlow generates fake EEG)
python -m backend.main --synthetic
```

Backend starts a WebSocket server on `ws://localhost:8765`.

### BrainFlow Setup

BrainFlow handles all hardware communication. For Muse 2 on Linux:

```bash
pip install brainflow

# Ensure bluetooth is running
sudo systemctl start bluetooth

# Find your Muse MAC address (power on Muse, then scan)
bluetoothctl scan on
# Look for "Muse-XXXX", note the MAC address

# Start backend with your MAC
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"
```

BrainFlow uses board_id=38 (`MUSE_2_BOARD`). The `--synthetic` flag uses board_id=-1 (synthetic board) which generates realistic EEG waveforms without hardware.

### Terminal 2: Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:3000 — live EEG waveforms, recording controls, real-time metrics.

## Architecture

```
backend/
├── main.py            # EEGServer — WebSocket streaming, recording, command handling
├── acquisition.py     # BrainFlow board wrapper with connection resilience
├── config.py          # Board, filter, server configuration
└── pipeline/          # Pluggable real-time processing stages
    ├── factory.py     # Pipeline assembly
    └── stages/
        └── detectors.py  # BlinkDetector v5 (F1=0.95), SpeechDetector, ClenchDetector

frontend/
├── src/
│   ├── routes/index.tsx           # Dashboard with live waveforms
│   └── components/
│       ├── RecordingPanel.tsx     # Cued protocol recording UI
│       ├── WaveformDisplay.tsx    # Canvas 2D waveform rendering
│       └── MetricsPanel.tsx       # Band powers, heart rate, concentration

scripts/
├── eval_blink_detector.py  # Detector evaluation harness
├── eval_zuna_alpha.py      # ZUNA superresolution evaluation
├── run_zuna.py             # ZUNA signal reconstruction pipeline
├── experiment.py           # Experiment tracking (config/results/artifacts)
└── diagnose_data.py        # Recording quality diagnostics

recordings/               # Saved trials (.npz + .fif)
experiments/              # Tracked experiment runs + registry.csv
docs/research/            # Research notes and validated findings
```

## Protocol

- **Sensor data**: Binary WebSocket frames (1B type + 2B channels + 2B samples + float32 data)
- **Metrics/events**: JSON messages over the same WebSocket

## Muse 2 Channels

| Stream | Channels | Sample Rate |
|--------|----------|-------------|
| EEG    | TP9, AF7, AF8, TP10 | 256 Hz |
| PPG    | Red, IR, Ambient | 64 Hz |
| IMU    | Accel XYZ + Gyro XYZ | 52 Hz |

## Recording

The dashboard has a cued protocol recorder: countdown → beep cue → record → rest → repeat. Recordings save to `recordings/<label>/` as `.npz` (raw numpy) and `.fif` (MNE format with standard_1020 montage).

Available protocols: baseline, rest, single/double/triple blink, clench, eyebrow raise/furrow, talk, eyes closed/open.

## Running Tests

```bash
python -m pytest tests/ -v
```

## Hardware Notes

- **Never kill the server while Muse is connected** — forces BLE disconnect, may require Muse power cycle + `sudo systemctl restart bluetooth`
- Use `--synthetic` for development without hardware
- BrainFlow board_id=38 (MUSE_2_BOARD)
