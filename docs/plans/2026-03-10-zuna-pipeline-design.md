# ZUNA Real-Time Pipeline Design

**Date:** 2026-03-10

---

## Overview

Integrate ZUNA v0.1.1 (380M param diffusion model, 4ch → 23ch EEG superresolution) into the existing single-process Python backend. The model loads once at startup and runs inference on 5-second chunks as data streams in. No separate process, no IPC, no Docker — just a PyTorch model living in the same process as BrainFlow.

When `--zuna` flag is not passed (or no GPU available), the backend sends 4ch band powers and the frontend does browser-side spherical spline interpolation for the heatmap. This is the fallback and default.

---

## Architecture

### Single Process

```
python -m backend.main --mac "XX:XX:XX:XX:XX:XX" --zuna

One process:
  BrainFlow (BLE)
    → existing pipeline stages (blink/clench/speech detectors)
    → ZunaStage (buffers 5s, calls model.sample(), emits 23ch)
    → BandPowerStage (computes per-channel band powers, emits 1Hz JSON)
    → WebSocket server
```

Without `--zuna`:

```
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"

  BrainFlow (BLE)
    → existing pipeline stages
    → BandPowerStage (4ch band powers, 1Hz)
    → WebSocket server
```

### Why Single Process

- **Zero IPC overhead** — `model.sample()` is a function call
- **One thing to start, one thing to restart** — no service orchestration
- **Clean extraction seam** — if we ever need to split (cloud GPU, multiple backends), the `ZunaStage` boundary is the natural cut point
- **BLE stays on host** — no Docker Bluetooth passthrough headaches
- **YAGNI** — one machine, one GPU, one user

---

## Pipeline Stages

### ZunaStage

New stage in `backend/pipeline/stages/`. Plugs into the existing pipeline architecture.

**Lifecycle:**

1. **Init (`--zuna` flag):** Load model weights from HuggingFace cache (`Zyphra/ZUNA`), move to CUDA. ~30s cold start, ~3s warm start (weights cached). Log VRAM usage.
2. **Accumulate:** Buffer incoming 4ch EEG chunks until 5 seconds (1280 samples at 256Hz) are available.
3. **Preprocess:** Notch filter (50/60Hz) → highpass (0.1Hz) → spherical spline interpolation 4ch → 23ch (initial estimate).
4. **Inference:** Call `model.sample(encoder_input, seq_lens, tok_idx)` on GPU. Normalize input by dividing by 10.0 (ZUNA expects std≈0.1), denormalize output by multiplying by 10.0.
5. **Emit:** Pass 23×1280 array downstream to BandPowerStage.
6. **Overlap:** Slide buffer by 1 second (256 samples), keeping 4 seconds of context for the next inference. This gives 1Hz output cadence with 80% overlap.

**Threading:** Inference runs on a background thread to avoid blocking the WebSocket event loop. The pipeline already handles async stage execution.

**Failure handling:** If inference fails or takes >5s, skip that chunk and log a warning. Frontend continues with the last good data or falls back to 4ch.

```python
class ZunaStage:
    def __init__(self, device="cuda"):
        self.model = load_zuna_model(device)  # EncoderDecoder from Zyphra/ZUNA
        self.buffer = np.zeros((4, 0))        # accumulator
        self.sfreq = 256
        self.epoch_samples = 1280             # 5s × 256Hz
        self.hop_samples = 256                # 1s hop → 1Hz output

    def process(self, chunk_4ch: np.ndarray) -> Optional[np.ndarray]:
        self.buffer = np.hstack([self.buffer, chunk_4ch])
        if self.buffer.shape[1] < self.epoch_samples:
            return None  # still accumulating

        epoch = self.buffer[:, :self.epoch_samples]
        self.buffer = self.buffer[:, self.hop_samples:]  # slide by 1s

        preprocessed = self._preprocess(epoch)       # notch + hp + spline 4→23
        result_23ch = self._inference(preprocessed)  # model.sample()
        return result_23ch  # 23 × 1280
```

### BandPowerStage

Computes per-channel band powers and sends as JSON over WebSocket.

**Input:** Either 4×1280 (no ZUNA) or 23×1280 (with ZUNA) array.

**Output:** `band_powers` JSON message at 1Hz.

```python
class BandPowerStage:
    BANDS = {
        "delta": (1, 4),
        "theta": (4, 8),
        "alpha": (8, 13),
        "beta":  (13, 30),
        "gamma": (30, 50),
    }

    def process(self, data: np.ndarray, channel_names: list[str]) -> dict:
        powers = {}
        for i, name in enumerate(channel_names):
            psd = welch(data[i], fs=256)
            powers[name] = {
                band: band_power(psd, lo, hi)
                for band, (lo, hi) in self.BANDS.items()
            }
        return {
            "type": "band_powers",
            "mode": "23ch" if len(channel_names) > 4 else "4ch",
            "channels": powers,
            "timestamp": time.time(),
        }
```

---

## ZUNA Model Loading

Extract the minimum needed from ZUNA's internals to load and call the model without subprocess/torchrun overhead.

```python
import torch
from zuna.inference.AY2l.lingua.apps.AY2latent_bci.transformer import (
    EncoderDecoder, ModelArgs
)
from huggingface_hub import snapshot_download

def load_zuna_model(device="cuda") -> EncoderDecoder:
    model_path = snapshot_download("Zyphra/ZUNA")

    # Load config and build model
    args = ModelArgs(...)  # from model's config
    model = EncoderDecoder(args).to(device)

    # Load weights from safetensors
    state_dict = load_safetensors(model_path)
    model.load_state_dict(state_dict)
    model.eval()

    return model
```

**VRAM:** ~3.7GB for the 380M param model. RTX 5090 has 32GB — plenty of headroom.

**Warm start:** After first load, HuggingFace cache + PyTorch CUDA context are warm. Subsequent starts take ~3s instead of ~30s.

---

## Preprocessing

Reuse ZUNA's own preprocessing functions where possible. The key steps:

1. **Notch filter** (50Hz or 60Hz depending on locale)
2. **Highpass filter** (0.1Hz, removes DC drift)
3. **Spherical spline interpolation** (4ch → 23ch initial estimate using MNE)
4. **Normalize** (divide by 10.0 — ZUNA expects std≈0.1)

After inference:

5. **Denormalize** (multiply by 10.0)

The spline interpolation creates a smooth 23ch estimate from 4 sensors. ZUNA's diffusion model then refines this estimate, adding realistic spatial detail that pure interpolation cannot produce. This is where the value comes from — the model has learned EEG spatial statistics from training data.

---

## WebSocket Protocol

### New Message: `band_powers` (1Hz)

```json
{
  "type": "band_powers",
  "mode": "4ch",
  "channels": {
    "TP9":  {"delta": 4.1, "theta": 5.2, "alpha": 12.1, "beta": 8.3, "gamma": 2.1},
    "AF7":  {"delta": 3.8, "theta": 4.9, "alpha": 6.5, "beta": 7.1, "gamma": 1.8},
    "AF8":  {"delta": 3.5, "theta": 5.1, "alpha": 5.9, "beta": 6.8, "gamma": 1.9},
    "TP10": {"delta": 4.3, "theta": 5.5, "alpha": 13.2, "beta": 9.1, "gamma": 2.3}
  },
  "timestamp": 1710000000.0
}
```

With ZUNA (`mode: "23ch"`): same format, 23 channel entries (Fp1, Fp2, F3, F4, ..., O1, O2).

Frontend handles both identically — more channels = more interpolation points = sharper heatmap gradients.

---

## CLI Interface

```bash
# Development (no hardware, no ZUNA)
python -m backend.main --synthetic

# With Muse, no ZUNA (4ch band powers, browser interpolation)
python -m backend.main --mac "XX:XX:XX:XX:XX:XX"

# With Muse + ZUNA (23ch band powers, GPU inference)
python -m backend.main --mac "XX:XX:XX:XX:XX:XX" --zuna

# Synthetic + ZUNA (testing ZUNA pipeline without hardware)
python -m backend.main --synthetic --zuna
```

`--zuna` flag:
- Checks for CUDA availability, warns and falls back to 4ch if no GPU
- Downloads model on first run (~1.5GB from HuggingFace)
- Adds ~30s to startup (first run) or ~3s (cached)
- Increases VRAM usage by ~3.7GB

---

## Startup Sequence

```
1. Parse args (--mac/--synthetic, --zuna)
2. Initialize BrainFlow board
3. If --zuna:
   a. Check CUDA availability
   b. Download model if not cached
   c. Load model to GPU (~3-30s)
   d. Initialize ZunaStage
   e. Log: "ZUNA loaded (3.7GB VRAM, 23ch mode)"
4. Initialize BandPowerStage (4ch or 23ch depending on ZUNA)
5. Initialize existing pipeline stages (detectors)
6. Start WebSocket server on :8765
7. Begin acquisition loop
```

---

## Deployment

### Development
Run directly in terminal. No process manager needed.

### Always-On (demo, headless)
Systemd service unit:

```ini
[Unit]
Description=Zyphra EEG Backend
After=bluetooth.target network.target

[Service]
ExecStart=/usr/bin/python -m backend.main --mac "XX:XX:XX:XX:XX:XX" --zuna
WorkingDirectory=/home/newub/w/zyphraexps
Restart=on-failure
RestartSec=5
Environment=PYTHONPATH=/home/newub/w/zyphraexps

[Install]
WantedBy=multi-user.target
```

### Frontend
Same as today: `cd frontend && pnpm dev` for development, or build static files and serve with nginx.

---

## Development Order

1. **BandPowerStage (4ch)** — compute and send band powers from raw Muse data. Test with existing dashboard.
2. **Frontend BrainHeatmap** — React Three Fiber component consuming band_powers messages (per heatmap design doc).
3. **ZunaStage** — load model, buffer, preprocess, inference. Wire into pipeline behind `--zuna` flag.
4. **Integration test** — run with `--synthetic --zuna`, verify 23ch band_powers arrive and heatmap renders.
5. **Live test** — run with Muse + ZUNA, validate against known effects (alpha blocking, meditation vs math).

Steps 1-2 can proceed in parallel. Step 3 requires reading ZUNA internals carefully. Steps 4-5 are validation.

---

## Fallback Behavior

| Scenario | Band powers mode | Heatmap quality |
|----------|-----------------|-----------------|
| `--zuna` + GPU available | 23ch | Sharp spatial gradients |
| `--zuna` + no GPU | 4ch (warn at startup) | Blobby but functional |
| No `--zuna` flag | 4ch | Blobby but functional |
| ZUNA inference fails mid-session | Last good 23ch, then 4ch | Graceful degradation |

The frontend never needs to know about failures — it just renders whatever band_powers it receives.
