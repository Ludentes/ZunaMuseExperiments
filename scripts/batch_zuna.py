#!/usr/bin/env python3
"""Batch ZUNA superresolution for all recordings.

Concatenates all raw trials per label, runs ZUNA once per label.
Output: recordings/<label>/zuna_concat_raw.fif (original concatenated)
        recordings/<label>/zuna_output_raw.fif (ZUNA reconstructed 23ch)

Usage:
    PYTHONPATH=. python scripts/batch_zuna.py
    PYTHONPATH=. python scripts/batch_zuna.py --labels eyes_closed eyes_open meditation
    PYTHONPATH=. python scripts/batch_zuna.py --cpu
"""
import argparse
import atexit
import os
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import mne
import numpy as np

mne.set_log_level("ERROR")

# Persistent triton cache to avoid ~90s recompilation per ZUNA run
TRITON_CACHE = Path.home() / ".cache" / "triton_zuna"
TRITON_CACHE.mkdir(parents=True, exist_ok=True)
os.environ["TRITON_CACHE_DIR"] = str(TRITON_CACHE)

RECORDINGS = Path("/home/newub/w/zyphraexps/recordings")

CHANNELS_TO_ADD_19 = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6",
    "O1", "O2",
]

# Min duration for ZUNA (needs 5s epochs)
MIN_DURATION_S = 5.0


def find_raw_fifs(label: str) -> list[Path]:
    """Find all *_raw.fif files for a label."""
    base = RECORDINGS / label
    return sorted(base.rglob("*_raw.fif"))


def concat_and_filter(files: list[Path], label: str) -> mne.io.Raw | None:
    """Concatenate raw files, filter to EEG channels only."""
    raws = []
    for f in files:
        try:
            raw = mne.io.read_raw_fif(str(f), preload=True, verbose=False)
            # Keep only EEG channels (drop PPG, IMU markers)
            eeg_picks = mne.pick_types(raw.info, eeg=True)
            if len(eeg_picks) == 0:
                continue
            raw.pick(eeg_picks)
            raws.append(raw)
        except Exception as e:
            print(f"    SKIP {f.name}: {e}")
    if not raws:
        return None
    combined = mne.concatenate_raws(raws)
    # Remove BAD boundary annotations from concatenation — they cause
    # MNE's make_fixed_length_epochs to drop all epochs when trials < epoch_duration
    bad_idx = [i for i, a in enumerate(combined.annotations)
               if a["description"].startswith("BAD")]
    if bad_idx:
        combined.annotations.delete(bad_idx)
    return combined


def run_zuna_on_raw(raw: mne.io.Raw, label: str, gpu_device: int) -> mne.io.Raw | None:
    """Run ZUNA pipeline on a Raw object."""
    from zuna import preprocessing, inference, pt_to_fif

    work_dir = Path(f"/tmp/zuna_batch_{label}")
    if work_dir.exists():
        shutil.rmtree(work_dir)

    fif_input = work_dir / "0_fif_input"
    fif_input.mkdir(parents=True)
    input_path = fif_input / f"{label}_raw.fif"
    raw.save(str(input_path), overwrite=True, verbose=False)

    pt_input = str(work_dir / "2_pt_input")
    pt_output = str(work_dir / "3_pt_output")
    fif_output = str(work_dir / "4_fif_output")
    preprocessed = str(work_dir / "1_fif_filter")
    figs = str(work_dir / "figs")
    for d in [pt_input, pt_output, fif_output, preprocessed, figs]:
        Path(d).mkdir(parents=True, exist_ok=True)

    gpu_str = str(gpu_device) if gpu_device >= 0 else ""

    preprocessing(
        input_dir=str(fif_input),
        output_dir=pt_input,
        apply_notch_filter=True,
        apply_highpass_filter=True,
        apply_average_reference=False,
        target_channel_count=CHANNELS_TO_ADD_19,
        bad_channels=[],
        preprocessed_fif_dir=preprocessed,
    )

    # Check if preprocessing produced any epochs
    pt_files = list(Path(pt_input).glob("*.pt"))
    if not pt_files:
        print(f"    No epochs after preprocessing — skipping inference")
        return None

    inference(
        input_dir=pt_input,
        output_dir=pt_output,
        gpu_device=gpu_str,
        tokens_per_batch=100000,
        data_norm=10.0,
        diffusion_cfg=1.0,
        diffusion_sample_steps=50,
        plot_eeg_signal_samples=False,
        inference_figures_dir=figs,
    )

    pt_to_fif(input_dir=pt_output, output_dir=fif_output)

    out_files = sorted(Path(fif_output).glob("*.fif"))
    if not out_files:
        print(f"    ERROR: ZUNA produced no output")
        return None
    return mne.io.read_raw_fif(str(out_files[0]), preload=True, verbose=False)


def main():
    parser = argparse.ArgumentParser(description="Batch ZUNA on all recordings")
    parser.add_argument("--labels", nargs="+", help="Only process these labels")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip labels that already have zuna_output_raw.fif")
    args = parser.parse_args()

    gpu_device = -1 if args.cpu else args.gpu

    # Discover all labels
    all_labels = sorted([
        d.name for d in RECORDINGS.iterdir()
        if d.is_dir() and list(d.rglob("*_raw.fif"))
    ])

    if args.labels:
        labels = [l for l in args.labels if l in all_labels]
    else:
        labels = all_labels

    print(f"Processing {len(labels)} labels on {'CPU' if gpu_device < 0 else f'GPU {gpu_device}'}")
    print(f"Labels: {', '.join(labels)}\n")

    results = {}
    total_t0 = time.time()

    for i, label in enumerate(labels):
        output_path = RECORDINGS / label / "zuna_output_raw.fif"
        concat_path = RECORDINGS / label / "zuna_concat_raw.fif"

        failed_marker = RECORDINGS / label / ".zuna_failed"
        if args.skip_existing and output_path.exists():
            print(f"[{i+1}/{len(labels)}] {label}: SKIP (exists)")
            continue
        if args.skip_existing and failed_marker.exists():
            print(f"[{i+1}/{len(labels)}] {label}: SKIP (previously failed)")
            continue

        files = find_raw_fifs(label)
        print(f"[{i+1}/{len(labels)}] {label}: {len(files)} raw files")

        raw = concat_and_filter(files, label)
        if raw is None:
            print(f"    No valid EEG data, skipping")
            results[label] = "no_data"
            continue

        duration = raw.times[-1]
        print(f"    Concatenated: {duration:.1f}s, {raw.info['nchan']}ch")

        if duration < MIN_DURATION_S:
            print(f"    Too short ({duration:.1f}s < {MIN_DURATION_S}s), skipping")
            results[label] = "too_short"
            continue

        # Save concatenated original
        raw.save(str(concat_path), overwrite=True, verbose=False)

        # Run ZUNA
        t0 = time.time()
        try:
            zuna_raw = run_zuna_on_raw(raw, label, gpu_device)
        except Exception as e:
            print(f"    ZUNA FAILED: {e}")
            results[label] = f"error: {e}"
            failed_marker.write_text(str(e))
            continue
        elapsed = time.time() - t0

        if zuna_raw is None:
            results[label] = "no_output"
            failed_marker.write_text("no output from ZUNA")
            continue

        # Save output
        zuna_raw.save(str(output_path), overwrite=True, verbose=False)
        print(f"    Done: {zuna_raw.info['nchan']}ch, {zuna_raw.times[-1]:.1f}s ({elapsed:.1f}s)")
        results[label] = f"ok ({elapsed:.1f}s)"

    total_elapsed = time.time() - total_t0
    print(f"\n{'='*60}")
    print(f"BATCH COMPLETE ({total_elapsed:.0f}s total)")
    print(f"{'='*60}")
    for label, status in sorted(results.items()):
        print(f"  {label:25s} {status}")


if __name__ == "__main__":
    main()
