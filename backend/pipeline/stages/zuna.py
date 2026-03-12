"""ZunaStage: real-time EEG superresolution via ZUNA diffusion model.

Buffers incoming 4ch Muse EEG, preprocesses, runs ZUNA inference on GPU,
and emits 23ch reconstructed EEG for downstream band power computation.

Usage: enabled via --zuna CLI flag. Requires CUDA GPU (~3.7GB VRAM).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import torch

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame

log = logging.getLogger(__name__)

# 23-channel output set: standard 10-20 positions
ZUNA_CH_NAMES = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T7", "C3", "Cz", "C4", "T8",
    "P7", "P3", "Pz", "P4", "P8",
    "O1", "O2",
    # Muse originals (kept in output)
    "TP9", "AF7", "AF8", "TP10",
]

# Channels to add beyond Muse 4ch (passed to ZUNA preprocessing)
# Use modern 10-20 names (T7=T3, T8=T4, P7=T5, P8=T6 — same positions in MNE)
CHANNELS_TO_ADD = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T7", "C3", "Cz", "C4", "T8",
    "P7", "P3", "Pz", "P4", "P8",
    "O1", "O2",
]


@dataclass
class ZunaResult:
    """Result type: 23ch reconstructed EEG from ZUNA."""
    eeg_23ch: np.ndarray  # (23, 1280) — 5s at 256Hz
    channel_names: list[str]


def load_zuna_model(device: str = "cuda"):
    """Load ZUNA model from HuggingFace cache."""
    import json

    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file as safe_load

    # Import ZUNA internals
    import sys
    import importlib
    zuna_pkg = importlib.util.find_spec("zuna")
    if zuna_pkg is None:
        raise ImportError("zuna package not installed")

    zuna_root = str(zuna_pkg.submodule_search_locations[0])
    lingua_root = f"{zuna_root}/inference/AY2l"
    if lingua_root not in sys.path:
        sys.path.insert(0, lingua_root)

    from lingua.args import dataclass_from_dict
    from apps.AY2latent_bci.transformer import EncoderDecoder, DecoderTransformerArgs

    REPO_ID = "Zyphra/ZUNA"

    log.info("Downloading ZUNA config from HuggingFace...")
    config_path = hf_hub_download(repo_id=REPO_ID, filename="config.json", token=False)
    with open(config_path) as f:
        cfg = json.load(f)
    model_args = dataclass_from_dict(DecoderTransformerArgs, cfg["model"])

    log.info("Downloading ZUNA weights from HuggingFace...")
    weights_path = hf_hub_download(
        repo_id=REPO_ID,
        filename="model-00001-of-00001.safetensors",
        token=False,
    )
    sd_raw = safe_load(weights_path, device="cpu")
    sd = {k.removeprefix("model."): v for k, v in sd_raw.items()}

    log.info("Loading ZUNA model to %s...", device)
    dev = torch.device(device)
    model = EncoderDecoder(model_args).to(dev)
    sd_on_dev = {k: v.to(dev) for k, v in sd.items()}
    model.load_state_dict(sd_on_dev, strict=True)
    model.eval()

    for p in model.parameters():
        p.requires_grad = False

    # Compile for speed if on CUDA
    if dev.type == "cuda":
        try:
            model.sample = torch.compile(model.sample)
            model.encoder = torch.compile(model.encoder)
            log.info("torch.compile applied to model.sample and model.encoder")
        except Exception:
            log.warning("torch.compile failed, running uncompiled")

    vram_mb = torch.cuda.memory_allocated(dev) / 1024**2 if dev.type == "cuda" else 0
    log.info("ZUNA loaded (%.0f MB VRAM)", vram_mb)

    return model, model_args, dev


@dataclass
class NormParams:
    """Z-score normalization parameters for reversing after ZUNA inference."""
    mean: float
    std: float


def preprocess_epoch(
    eeg_4ch: np.ndarray,
    sfreq: float = 256.0,
    skip_filtering: bool = False,
) -> tuple[np.ndarray, np.ndarray, NormParams]:
    """Preprocess a 4ch epoch for ZUNA inference.

    1. Notch filter (50Hz) + Highpass (0.5Hz) — skipped if already denoised
    2. Spherical spline interpolation (4ch → 23ch)
    3. Z-score normalize

    Args:
        eeg_4ch: (4, n_samples) raw EEG in µV
        sfreq: sampling rate
        skip_filtering: if True, skip notch/highpass (data already filtered)

    Returns:
        eeg_23ch: (23, n_samples) z-scored array
        chan_pos: (23, 3) channel positions in meters (MNE standard)
        norm: z-score params to reverse normalization after inference
    """
    import mne

    # Build MNE Raw from 4ch data
    ch_names = ["TP9", "AF7", "AF8", "TP10"]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types="eeg")
    raw = mne.io.RawArray(eeg_4ch * 1e-6, info, verbose=False)  # µV → V
    montage = mne.channels.make_standard_montage("standard_1020")
    raw.set_montage(montage)

    if not skip_filtering:
        raw.notch_filter(50.0, verbose=False)
        raw.filter(l_freq=0.5, h_freq=None, verbose=False)

    # Interpolate to 23ch: create 23ch Raw with 4ch data, mark 19 as bad, interpolate
    all_ch = ch_names + CHANNELS_TO_ADD
    full_montage = mne.channels.make_standard_montage("standard_1020")

    # Get channel positions for all 23 channels
    ch_pos_dict = full_montage.get_positions()["ch_pos"]
    chan_pos = np.array([ch_pos_dict[ch] for ch in all_ch], dtype=np.float32)

    # Build full 23ch Raw with zeros for missing channels, then interpolate
    data_4ch = raw.get_data()  # (4, n_samples) in V
    n_samples = data_4ch.shape[1]
    data_23ch = np.zeros((len(all_ch), n_samples), dtype=np.float64)
    for i, ch in enumerate(ch_names):
        idx = all_ch.index(ch)
        data_23ch[idx] = data_4ch[i]

    full_info = mne.create_info(ch_names=all_ch, sfreq=sfreq, ch_types="eeg")
    full_raw = mne.io.RawArray(data_23ch, full_info, verbose=False)
    full_raw.set_montage(full_montage)

    # Mark channels without real data as bad, then interpolate via public API
    full_raw.info["bads"] = CHANNELS_TO_ADD
    full_raw.interpolate_bads(verbose=False)

    data_23ch_v = full_raw.get_data()  # (23, n_samples) in V

    # Convert back to µV for downstream
    data_23ch_uv = data_23ch_v * 1e6

    # Z-score normalize (save params for un-z-scoring after inference)
    mean = float(data_23ch_uv.mean())
    std = float(data_23ch_uv.std())
    if std > 0:
        data_23ch_uv = (data_23ch_uv - mean) / std

    return data_23ch_uv.astype(np.float32), chan_pos, NormParams(mean=mean, std=std)


def build_model_input(
    eeg_normalized: np.ndarray,
    chan_pos: np.ndarray,
    device: torch.device,
    tf: int = 32,
    num_bins: int = 50,
) -> dict:
    """Build the model input tensors from preprocessed EEG.

    Args:
        eeg_normalized: (n_channels, n_samples) z-scored, divided by data_norm
        chan_pos: (n_channels, 3) channel positions in meters
        device: torch device
        tf: fine time points per token (from config)
        num_bins: discretization bins for channel positions

    Returns:
        dict with encoder_input, seq_lens, tok_idx tensors
    """
    n_channels, n_samples = eeg_normalized.shape
    tc = n_samples // tf  # coarse time chunks

    # Reshape: (n_ch, n_samples) → (n_ch * tc, tf)
    # use_coarse_time="B": keep same channels together
    eeg_tensor = torch.tensor(eeg_normalized, dtype=torch.float32)
    eeg_reshaped = eeg_tensor.reshape(n_channels, tc, tf).reshape(n_channels * tc, tf)

    seqlen = n_channels * tc

    # Channel positions: repeat for each coarse time chunk
    cp = torch.tensor(chan_pos, dtype=torch.float32)

    # Discretize channel positions to bins
    xyz_extremes = torch.tensor([[-0.12, -0.12, -0.12], [0.12, 0.12, 0.12]])
    xyz_min = xyz_extremes[0]
    xyz_max = xyz_extremes[1]
    cp_norm = (cp - xyz_min) / (xyz_max - xyz_min)
    cp_discrete = (cp_norm * num_bins).long().clamp(0, num_bins - 1)

    # Repeat for coarse time: each channel has tc entries
    cp_discrete_rep = cp_discrete.repeat_interleave(tc, dim=0)  # (seqlen, 3)

    # Coarse time indices
    tc_indices = torch.arange(tc).repeat(n_channels).reshape(seqlen, 1)

    # tok_idx: [1, seqlen, 4] = {x, y, z, tc}
    tok_idx = torch.cat([cp_discrete_rep, tc_indices], dim=1).unsqueeze(0)  # (1, seqlen, 4)

    # seq_lens
    seq_lens = torch.tensor([seqlen], dtype=torch.long)

    # Pad eeg_reshaped to input_dim=32 if tf < 32
    if tf < 32:
        pad = torch.zeros(seqlen, 32 - tf)
        encoder_input = torch.cat([eeg_reshaped, pad], dim=1)
    elif tf > 32:
        encoder_input = eeg_reshaped[:, :32]
    else:
        encoder_input = eeg_reshaped

    return {
        "encoder_input": encoder_input.unsqueeze(0).to(device),  # (1, seqlen, 32)
        "seq_lens": seq_lens.to(device),
        "tok_idx": tok_idx,  # stays on CPU per ZUNA convention
    }


def reconstruct_from_output(
    z: torch.Tensor,
    n_channels: int,
    tf: int = 32,
    data_norm: float = 10.0,
) -> np.ndarray:
    """Convert model output back to (n_channels, n_samples) array.

    Args:
        z: model output tensor (1, seqlen, 32) or (seqlen, 32)
        n_channels: number of channels
        tf: fine time points per token
        data_norm: denormalization factor

    Returns:
        (n_channels, n_samples) numpy array
    """
    if z.dim() == 3:
        z = z.squeeze(0)  # (seqlen, 32)

    if z.shape[0] % n_channels != 0:
        raise ValueError(
            f"Model output seqlen {z.shape[0]} is not divisible by n_channels {n_channels}"
        )

    # Denormalize
    z = z * data_norm

    # Take first tf columns (the actual signal, rest is padding)
    z_signal = z[:, :tf]  # (seqlen, tf)

    # Reshape back: (n_ch * tc, tf) → (n_ch, tc * tf)
    tc = z_signal.shape[0] // n_channels
    result = z_signal.reshape(n_channels, tc, tf).reshape(n_channels, tc * tf)

    return result.cpu().numpy()


class ZunaStage(Stage):
    """SLOW stage: buffer 5s of 4ch EEG, run ZUNA inference, emit 23ch.

    Accumulates EEG chunks until 5 seconds (1280 samples) are available,
    then runs preprocessing + ZUNA inference. Slides buffer by 1 second
    for 80% overlap, yielding 1Hz output cadence.
    """

    name = "zuna_stage"
    cadence = Cadence.SLOW

    def __init__(self, device: str = "cuda", diffusion_steps: int = 50):
        log.info("Initializing ZunaStage...")
        t0 = time.time()
        self.model, self.model_args, self.device = load_zuna_model(device)
        self.load_time = time.time() - t0
        log.info("ZunaStage ready (loaded in %.1fs)", self.load_time)
        log.info("First inference will be slow (~60-90s) due to torch.compile warmup")
        self.enabled = True  # can be toggled at runtime via WebSocket

        self.sfreq = 256
        self.epoch_samples = 1280  # 5s at 256Hz
        self.hop_samples = 256    # 1s hop → 1Hz output
        self.tf = 32              # fine time points per token
        self.num_bins = 50
        self.diffusion_steps = diffusion_steps

        # Read data_norm from model config if available, else default
        self.data_norm = getattr(self.model_args, "data_norm", 10.0)

        # Cap buffer at 2x epoch to prevent unbounded growth
        self._buffer_max = self.epoch_samples * 2
        self._buffer: np.ndarray | None = None  # (4, accumulated_samples)
        self._last_result: ZunaResult | None = None

    def process(self, frame: PipelineFrame) -> None:
        if not self.enabled:
            return
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        # Accumulate chunks
        if self._buffer is None:
            self._buffer = frame.eeg.copy()
        else:
            self._buffer = np.concatenate([self._buffer, frame.eeg], axis=1)

        # Cap buffer to prevent unbounded growth
        if self._buffer.shape[1] > self._buffer_max:
            self._buffer = self._buffer[:, -self._buffer_max:]

        # Not enough data yet
        if self._buffer.shape[1] < self.epoch_samples:
            # Emit last result if available (keeps heatmap alive between inferences)
            if self._last_result is not None:
                frame.set(self._last_result)
            return

        # Extract epoch and slide buffer
        epoch = self._buffer[:, :self.epoch_samples]
        self._buffer = self._buffer[:, self.hop_samples:]

        # Run inference
        try:
            t0 = time.time()
            result_23ch = self._run_inference(epoch)
            elapsed = time.time() - t0

            if elapsed > 5.0:
                log.warning("ZUNA inference took %.1fs (>5s), may cause lag", elapsed)
            else:
                log.debug("ZUNA inference: %.2fs, output shape %s", elapsed, result_23ch.shape)

            # Check enabled again — user may have toggled during inference
            if not self.enabled:
                return

            self._last_result = ZunaResult(
                eeg_23ch=result_23ch,
                channel_names=ZUNA_CH_NAMES,
            )
            frame.set(self._last_result)

            # Store 23ch as separate result — do NOT replace frame.eeg
            # Downstream stages (SignalQualityChecker, FAA) expect original 4ch layout

        except Exception:
            log.exception("ZUNA inference failed, falling back to 4ch")
            if self._last_result is not None:
                frame.set(self._last_result)

    def unload(self):
        """Release GPU memory by moving model to CPU and clearing caches."""
        if hasattr(self, "model") and self.model is not None:
            self.model.cpu()
            self.model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log.info("ZUNA model unloaded, GPU memory freed")

    def _run_inference(self, epoch_4ch: np.ndarray) -> np.ndarray:
        """Run full ZUNA pipeline on a 4ch epoch.

        Args:
            epoch_4ch: (4, 1280) raw EEG in µV

        Returns:
            (23, 1280) reconstructed EEG (z-scored, then denormalized)
        """
        # Preprocess: interpolate to 23ch + normalize
        # skip_filtering=True because WaveletDenoiser already ran upstream
        eeg_23ch, chan_pos, norm = preprocess_epoch(epoch_4ch, self.sfreq, skip_filtering=True)

        n_channels = eeg_23ch.shape[0]

        # Apply data_norm scaling (ZUNA expects std ≈ 0.1)
        eeg_scaled = eeg_23ch / self.data_norm

        # Build model input tensors
        model_input = build_model_input(
            eeg_scaled, chan_pos, self.device,
            tf=self.tf, num_bins=self.num_bins,
        )

        # Run diffusion sampling
        with torch.no_grad():
            z, _ = self.model.sample(
                encoder_input=model_input["encoder_input"],
                seq_lens=model_input["seq_lens"],
                tok_idx=model_input["tok_idx"],
                sample_steps=self.diffusion_steps,
                cfg=1.0,
            )

        # Reconstruct (n_channels, n_samples) from model output
        result = reconstruct_from_output(z, n_channels, tf=self.tf, data_norm=self.data_norm)

        # Reverse z-score normalization back to µV scale
        if norm.std > 0:
            result = result * norm.std + norm.mean

        return result
