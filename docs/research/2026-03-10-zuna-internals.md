# ZUNA v0.1.1 Internals Reference

**Date:** 2026-03-10

## Package Location

`/home/newub/miniconda3/lib/python3.12/site-packages/zuna/`

## Key Files

| File | Purpose |
|------|---------|
| `zuna/__init__.py` | Public API: `preprocessing()`, `inference()`, `pt_to_fif()` |
| `zuna/pipeline.py` | `inference()` wrapper |
| `zuna/preprocessing/batch.py` | `preprocessing()` function |
| `zuna/preprocessing/processor.py` | `EEGProcessor` class |
| `zuna/preprocessing/normalizer.py` | Z-score normalization |
| `zuna/preprocessing/filtering.py` | `Filter` class (resample, highpass, notch, CAR) |
| `zuna/preprocessing/interpolation.py` | Channel upsampling/interpolation |
| `zuna/inference/AY2l/lingua/apps/AY2latent_bci/transformer.py` | `EncoderDecoder` model, `sample()` method |
| `zuna/inference/AY2l/lingua/apps/AY2latent_bci/eeg_eval.py` | CLI inference entry point |
| `zuna/inference/AY2l/lingua/apps/AY2latent_bci/eeg_data.py` | Dataset, `chop_and_reshape_signals()` |
| `zuna/inference/AY2l/lingua/apps/AY2latent_bci/configs/config_infer.yaml` | Inference config |

## Model Loading

```python
import json
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file as safe_load

# Add ZUNA's lingua to path
import sys
zuna_root = "/path/to/zuna"
sys.path.insert(0, f"{zuna_root}/inference/AY2l")
from lingua.args import dataclass_from_dict
from apps.AY2latent_bci.transformer import EncoderDecoder, DecoderTransformerArgs

REPO_ID = "Zyphra/ZUNA"
config_path = hf_hub_download(repo_id=REPO_ID, filename="config.json", token=False)
with open(config_path) as f:
    cfg = json.load(f)
model_args = dataclass_from_dict(DecoderTransformerArgs, cfg["model"])

weights_path = hf_hub_download(repo_id=REPO_ID, filename="model-00001-of-00001.safetensors", token=False)
sd_raw = safe_load(weights_path, device="cpu")
sd = {k.removeprefix("model."): v for k, v in sd_raw.items()}

model = EncoderDecoder(model_args).to("cuda")
model.load_state_dict({k: v.to("cuda") for k, v in sd.items()}, strict=True)
model.eval()
```

## model.sample() Signature

```python
@torch.no_grad()
def sample(
    self,
    encoder_input: torch.Tensor,  # [B, seqlen, 32] or [seqlen, 32]
    seq_lens: torch.Tensor,       # [B] sequence lengths
    tok_idx: torch.Tensor,        # [1, seqlen, 4] for 4D-RoPE {x,y,z,tc}
    sample_steps: int = 50,       # diffusion steps
    cfg: float = 1.0,             # classifier-free guidance (1.0 = none)
) -> Tuple[torch.Tensor, List[torch.Tensor]]:
    # Returns (z_final, intermediate_steps)
```

## Data Flow: 4ch → model input

### 1. Preprocessing
- Resample → 256 Hz
- Highpass → 0.5 Hz
- Notch filter (optional)
- Spherical spline interpolation: 4ch → 23ch
- Z-score normalize: `(data - mean) / std`

### 2. Token construction (`chop_and_reshape_signals` with `use_coarse_time="B"`)

Given `(n_channels, 1280)` and `tf=32`:
- `tc = 1280 / 32 = 40` coarse time chunks
- `seqlen = n_channels × tc` (e.g., 23 × 40 = 920)
- Reshape: `(n_ch, 1280) → (n_ch, 40, 32) → (920, 32)`
- Same channels kept together: [ch0_tc0, ch0_tc1, ..., ch0_tc39, ch1_tc0, ...]

### 3. Position encoding (4D-RoPE)

`tok_idx` shape: `[1, seqlen, 4]` = `{x_discrete, y_discrete, z_discrete, tc}`

Channel position discretization:
- `xyz_extremes = [[-0.12, -0.12, -0.12], [0.12, 0.12, 0.12]]` (config: `"twelves"`)
- `num_bins = 50`
- `cp_norm = (chan_pos - xyz_min) / (xyz_max - xyz_min)`
- `cp_discrete = (cp_norm * 50).long().clamp(0, 49)`
- Each channel's discrete position is repeated for all tc entries
- `tc` indices: `torch.arange(tc).repeat(n_channels).reshape(seqlen, 1)`

### 4. Data normalization

```python
data_norm = 10.0
eeg_signal = eeg_signal / data_norm  # before model
output = model_output * data_norm    # after model
```

Also `data_clip = 1.0`: `eeg_signal.clamp(-1.0, 1.0)` after norm.

### 5. Reconstruction

```python
z_signal = z[:, :tf]  # (seqlen, 32) → take first tf=32 columns
result = z_signal.reshape(n_channels, tc, tf).reshape(n_channels, tc * tf)
# → (23, 1280)
```

## Key Config Values

```yaml
# Model
input_dim: 32
encoder_input_dim: 32
encoder_output_dim: 32
num_fine_time_pts: 32        # tf — fine time points per token
rope_dim: 4                  # 4D positional encoding
tok_idx_type: "{x,y,z,tc}"
stft_global_sigma: 0.1       # noise std for diffusion

# Data
data_norm: 10.0              # normalization divisor
data_clip: 1.0               # clip after norm
seq_len: 1280                # 5s at 256Hz
num_fine_time_pts: 32        # matches model
num_bins_discretize_xyz_chan_pos: 50
chan_pos_xyz_extremes_type: "twelves"  # [-0.12, 0.12]
use_coarse_time: "B"         # channels-together ordering
```

## Preprocessing Pipeline (EEGProcessor)

```
Raw EEG → resample(256Hz) → highpass(0.5Hz) → [CAR] → [notch]
  → z-score normalize → epoch(5s) → per-epoch z-score
  → channel upsample (spline interpolation) → save .pt
```

Normalization params stored in metadata for reversibility via `pt_to_fif`.

## Performance

- RTX 5090: ~0.57× real-time (5s epoch in ~2.8s)
- ~3.7 GB VRAM
- Cold start: ~30s (first HF download), warm: ~3s
- `torch.compile` applied to `model.sample` and `model.encoder` for speedup
