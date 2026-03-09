# ZUNA Capabilities Research

**Date:** 2026-03-08
**Sources:** arxiv 2602.18478, GitHub Zyphra/zuna, HuggingFace Zyphra/ZUNA, Zyphra blog, BrainAccess review, MarkTechPost

---

## What ZUNA Actually Is

ZUNA is a 380M-parameter masked diffusion autoencoder for scalp EEG. It is a **signal-level reconstruction model** — EEG in, better EEG out. It does NOT decode mental states, classify intentions, or produce text.

The "thought-to-text" framing in Zyphra's PR is aspirational — the idea is that better signal quality is a prerequisite for future downstream decoding. Zyphra explicitly states they are "not there yet."

## Concrete Capabilities

### 1. Denoising
Outputs cleaner versions of channels it has seen. The model was trained with heavy channel-dropout (randomly dropping 90% of channels, replacing with zeros, then reconstructing). Denoising is a byproduct of the reconstruction objective.

No specific dB improvement numbers vs traditional bandpass filtering published. Comparisons are against **spherical spline interpolation**, not traditional filtering.

### 2. Channel Superresolution (core capability)
Reconstruct missing/virtual channels from a subset of real channels:
- At 75%+ channel dropout: significantly outperforms spherical spline interpolation
- At 90% dropout (e.g., 25 real → 250 virtual): maintains high fidelity while spline degrades sharply
- Uses 4D rotary positional encoding (x, y, z, t) — handles arbitrary electrode layouts without retraining
- Trained on data with 2-256 channels per recording

**For Muse 2 (4 channels):** Would attempt to reconstruct virtual channels at standard 10-20 positions. This is ~96% dropout — the extreme edge of training distribution. Quality at this extreme is unknown.

### 3. What It Does NOT Do
- Does NOT classify mental states
- Does NOT decode text or intentions
- Does NOT do real-time processing
- Does NOT output anything other than reconstructed EEG signals

## API (pip install zuna, v0.1.1)

Four-step pipeline, all batch/offline:

```python
from zuna import preprocessing, inference, pt_to_fif, compare_plot_pipeline
```

### Step 1: Preprocessing (.fif → .pt)
```python
preprocessing(
    input_dir="path/to/fif/files",
    output_dir="path/to/working/2_pt_input",
    apply_notch_filter=False,
    apply_highpass_filter=True,        # 0.5 Hz
    apply_average_reference=True,
    target_channel_count=['C3', 'C4', 'Pz'],  # channels to ADD via spline interpolation
    bad_channels=['Cz'],               # zero out known bad channels
    preprocessed_fif_dir="path/to/working/1_fif_filter",
)
```

Fixed parameters (match pretrained model): 256 Hz, 5-second epochs, 64 epochs per file batch.

`target_channel_count` controls upsampling:
- `None` — keep original channels only
- `int` (e.g., 40) — greedy selection to N channels from 10-05 montage
- `list[str]` (e.g., `['C3', 'C4']`) — add these specific channels

### Step 2: Inference (.pt → .pt)
```python
inference(
    input_dir="path/to/working/2_pt_input",
    output_dir="path/to/working/3_pt_output",
    gpu_device=0,                      # 0 for GPU, "" for CPU
    tokens_per_batch=100000,
    data_norm=10.0,                    # normalization (ZUNA expects std=0.1)
    diffusion_cfg=1.0,                 # classifier-free guidance (1.0 = none)
    diffusion_sample_steps=50,         # diffusion steps per epoch
    plot_eeg_signal_samples=False,
    inference_figures_dir="./FIGURES",
)
```

Model weights auto-download from HuggingFace on first run.

### Step 3: Reconstruction (.pt → .fif)
```python
pt_to_fif(
    input_dir="path/to/working/3_pt_output",
    output_dir="path/to/working/4_fif_output",
)
```

### Step 4: Visualization (optional)
```python
compare_plot_pipeline(
    input_dir="path/to/original/fif/files",
    fif_input_dir="path/to/working/1_fif_filter",
    fif_output_dir="path/to/working/4_fif_output",
    pt_input_dir="path/to/working/2_pt_input",
    pt_output_dir="path/to/working/3_pt_output",
    output_dir="path/to/working/FIGURES",
    plot_pt=True,
    plot_fif=True,
    num_samples=2,
)
```

## Performance / Latency

- 380M parameters — "lightweight" for a foundation model
- Runs on consumer GPU, "decently on CPU"
- **Not real-time**: diffusion process with 50 sampling steps per 5-second epoch. Inherently batch/offline.
- `tokens_per_batch` is tunable for GPU utilization
- No published ms/epoch benchmark numbers

## Input Requirements

- MNE `.fif` format with valid scalp montage (3D channel positions)
- Files without montages are skipped
- Standard montages work: `standard_1020`, `standard_1005`
- Our Muse channels (TP9, AF7, AF8, TP10) are all in `standard_1020`

## Dependencies
numpy, scipy, mne, torch, joblib, omegaconf, sentencepiece, tiktoken, transformers, huggingface-hub, einops, vector-quantize-pytorch, wandb, lm-eval, and others. Apache 2.0 license.

## Our Integration

- Installed: `pip install zuna` (v0.1.1)
- Script: `scripts/run_zuna.py` wraps the pipeline for our recordings
- Recording system saves `.fif` with `standard_1020` montage and MNE annotations for cue events
- Default reconstruction: 4 Muse channels → 23 channels (4 real + 19 standard 10-20 virtual)

## Open Questions

1. **Quality at 96% dropout**: Nobody has published ZUNA results with only 4 input channels. We would be the first to test this. Reconstruction quality is likely poor compared to starting with 32+ channels.
2. **Does superresolution improve downstream classification?** E.g., if ZUNA reconstructs virtual C3/C4 channels from our 4 Muse channels, can we do motor imagery classification on the virtual channels? Unknown.
3. **Real-time feasibility**: 50 diffusion steps per 5s epoch makes streaming impossible. Could reduce steps (quality tradeoff) or pipeline with buffering, but fundamentally offline.
4. **Denoising value vs bandpass**: Is ZUNA's denoising meaningfully better than `perform_wavelet_denoising` from BrainFlow for our use case? Needs empirical testing.

## Sources

- [arxiv paper](https://arxiv.org/abs/2602.18478) — "Flexible EEG Superresolution with Position-Aware Diffusion Autoencoders"
- [GitHub — Zyphra/zuna](https://github.com/Zyphra/zuna)
- [HuggingFace — Zyphra/ZUNA](https://huggingface.co/Zyphra/ZUNA)
- [Zyphra blog post](https://www.zyphra.com/post/zuna)
- [BrainAccess review](https://www.brainaccess.ai/zuna-a-foundation-model-built-for-real-world-eeg/)
- [MarkTechPost coverage](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)
- [PR Newswire announcement](https://www.prnewswire.com/news-releases/zyphra-releases-zuna---bci-foundation-model-advancing-towards-thought-to-text-302691176.html)
- [Zyphra LinkedIn post](https://www.linkedin.com/posts/zyphra_today-were-releasing-zuna-our-first-bci-activity-7429879992215384064-uuHs)
