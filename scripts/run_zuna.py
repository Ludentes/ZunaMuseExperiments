#!/usr/bin/env python3
"""Run ZUNA pipeline on recorded Muse 2 EEG data.

Usage:
    # Run on a single .fif file
    python scripts/run_zuna.py recordings/rest/rest_20260308_123456_raw.fif

    # Run on all .fif files in a directory
    python scripts/run_zuna.py recordings/rest/

    # Use CPU (default: GPU 0)
    python scripts/run_zuna.py recordings/rest/ --cpu

    # Custom target channels (default: 19 standard 10-20)
    python scripts/run_zuna.py recordings/rest/ --channels 32

Output goes to recordings/<label>/zuna_output/
"""
import argparse
import shutil
from pathlib import Path


# Channels to ADD beyond our 4 Muse channels (TP9, AF7, AF8, TP10).
# ZUNA's preprocessing adds these via spherical spline interpolation,
# then the diffusion model reconstructs them from context.
# Standard 10-20 minus our existing 4 = 15 new virtual channels.
CHANNELS_TO_ADD_19 = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T3", "C3", "Cz", "C4", "T4",
    "T5", "P3", "Pz", "P4", "T6",
    "O1", "O2",
]


def run_pipeline(input_path: str, gpu_device: int, target_channels: int | list[str]):
    from zuna import preprocessing, inference, pt_to_fif, compare_plot_pipeline

    input_path = Path(input_path)

    if input_path.is_file():
        # Single file — copy to a temp input dir
        work_dir = input_path.parent / "zuna_work"
        fif_input = work_dir / "0_fif_input"
        fif_input.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, fif_input / input_path.name)
    else:
        work_dir = input_path / "zuna_work"
        fif_input = input_path  # directory of .fif files

    # Working directories
    preprocessed_fif = str(work_dir / "1_fif_filter")
    pt_input = str(work_dir / "2_pt_input")
    pt_output = str(work_dir / "3_pt_output")
    fif_output = str(work_dir / "4_fif_output")
    figures = str(work_dir / "FIGURES")

    for d in [preprocessed_fif, pt_input, pt_output, fif_output, figures]:
        Path(d).mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Preprocessing {fif_input} ...")
    preprocessing(
        input_dir=str(fif_input),
        output_dir=pt_input,
        apply_notch_filter=True,
        apply_highpass_filter=True,
        apply_average_reference=False,  # Only 4 channels, avg ref not meaningful
        target_channel_count=target_channels,
        bad_channels=[],  # No bad channels to exclude
        preprocessed_fif_dir=preprocessed_fif,
    )

    gpu_str = str(gpu_device) if gpu_device >= 0 else ""
    print(f"[2/4] Running ZUNA inference (device={'GPU '+str(gpu_device) if gpu_device >= 0 else 'CPU'}) ...")
    inference(
        input_dir=pt_input,
        output_dir=pt_output,
        gpu_device=gpu_str,
        tokens_per_batch=100000,
        data_norm=10.0,
        diffusion_cfg=1.0,
        diffusion_sample_steps=50,
        plot_eeg_signal_samples=True,
        inference_figures_dir=figures,
    )

    print("[3/4] Converting back to .fif ...")
    pt_to_fif(
        input_dir=pt_output,
        output_dir=fif_output,
    )

    print("[4/4] Generating comparison plots ...")
    compare_plot_pipeline(
        input_dir=str(fif_input),
        fif_input_dir=preprocessed_fif,
        fif_output_dir=fif_output,
        pt_input_dir=pt_input,
        pt_output_dir=pt_output,
        output_dir=figures,
        plot_pt=True,
        plot_fif=True,
        num_samples=2,
    )

    print(f"\nDone!")
    print(f"  Reconstructed .fif files: {fif_output}/")
    print(f"  Comparison plots:         {figures}/")
    print(f"\nTo inspect in Python:")
    print(f"  import mne")
    print(f"  raw = mne.io.read_raw_fif('{fif_output}/<file>.fif', preload=True)")
    print(f"  raw.plot()")


def main():
    parser = argparse.ArgumentParser(description="Run ZUNA on Muse 2 recordings")
    parser.add_argument("input", help="Path to .fif file or directory of .fif files")
    parser.add_argument("--cpu", action="store_true", help="Use CPU instead of GPU")
    parser.add_argument("--gpu", type=int, default=0, help="GPU device index (default: 0)")
    parser.add_argument("--channels", type=int, default=19,
                        help="Target channel count for reconstruction (default: 19)")
    args = parser.parse_args()

    gpu_device = -1 if args.cpu else args.gpu

    if args.channels == 19:
        target: int | list[str] = CHANNELS_TO_ADD_19
    else:
        target = args.channels  # int = greedy N-channel selection

    run_pipeline(args.input, gpu_device, target)


if __name__ == "__main__":
    main()
