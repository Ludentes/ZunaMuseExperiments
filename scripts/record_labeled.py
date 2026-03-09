#!/usr/bin/env python3
"""Record labeled EEG samples from Muse 2 via the WebSocket backend.

Usage:
    python scripts/record_labeled.py --label blink --duration 10 --trials 5
    python scripts/record_labeled.py --label clench --duration 10 --trials 5
    python scripts/record_labeled.py --label rest --duration 10 --trials 5
    python scripts/record_labeled.py --label talk --duration 10 --trials 5

Each trial records `duration` seconds of EEG data and saves it as:
    recordings/<label>/<label>_<trial>_<timestamp>.npz

Also saves MNE-compatible .fif files for ZUNA processing.
"""
import argparse
import asyncio
import json
import struct
import time
from pathlib import Path

import numpy as np
import websockets

MSG_EEG = 0x01
MSG_PPG = 0x02
MSG_IMU = 0x03

CH_NAMES = ["TP9", "AF7", "AF8", "TP10"]
SFREQ = 256


def decode_binary_frame(data: bytes):
    if len(data) < 5:
        return None
    msg_type = data[0]
    channels = struct.unpack_from("<H", data, 1)[0]
    samples = struct.unpack_from("<H", data, 3)[0]
    expected_len = 5 + channels * samples * 4
    if len(data) < expected_len:
        return None
    values = np.frombuffer(data[5:5 + channels * samples * 4], dtype=np.float32)
    values = values.reshape(channels, samples)
    return {"type": msg_type, "channels": channels, "samples": samples, "data": values}


async def record_trial(url: str, duration: float, label: str, trial_num: int, out_dir: Path):
    eeg_frames = []
    ppg_frames = []
    imu_frames = []

    async with websockets.connect(url) as ws:
        print(f"\n  Recording trial {trial_num} ({label}) for {duration}s ...")
        print(f"  >>> Perform '{label}' action NOW <<<")

        deadline = asyncio.get_event_loop().time() + duration
        while asyncio.get_event_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if isinstance(msg, bytes):
                frame = decode_binary_frame(msg)
                if frame is None:
                    continue
                if frame["type"] == MSG_EEG:
                    eeg_frames.append(frame["data"])
                elif frame["type"] == MSG_PPG:
                    ppg_frames.append(frame["data"])
                elif frame["type"] == MSG_IMU:
                    imu_frames.append(frame["data"])

    if not eeg_frames:
        print("  WARNING: No EEG data received!")
        return None

    eeg = np.concatenate(eeg_frames, axis=1)
    ppg = np.concatenate(ppg_frames, axis=1) if ppg_frames else np.array([])
    imu = np.concatenate(imu_frames, axis=1) if imu_frames else np.array([])

    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"{label}_{trial_num:02d}_{ts}"

    # Save as numpy archive
    npz_path = out_dir / f"{fname}.npz"
    np.savez(npz_path, eeg=eeg, ppg=ppg, imu=imu,
             label=label, trial=trial_num,
             ch_names=CH_NAMES, sfreq=SFREQ)
    print(f"  Saved: {npz_path} — EEG shape {eeg.shape} ({eeg.shape[1]/SFREQ:.1f}s)")

    # Save as MNE .fif for ZUNA
    try:
        import mne
        info = mne.create_info(ch_names=CH_NAMES, sfreq=SFREQ, ch_types="eeg")
        # BrainFlow returns µV, MNE expects V
        eeg_volts = eeg.astype(np.float64) * 1e-6
        raw = mne.io.RawArray(eeg_volts, info, verbose=False)
        montage = mne.channels.make_standard_montage("standard_1020")
        raw.set_montage(montage)
        fif_path = out_dir / f"{fname}_raw.fif"
        raw.save(fif_path, overwrite=True, verbose=False)
        print(f"  Saved: {fif_path} (MNE .fif for ZUNA)")
    except ImportError:
        print("  (MNE not installed — skipping .fif export)")

    return npz_path


async def main():
    parser = argparse.ArgumentParser(description="Record labeled EEG samples")
    parser.add_argument("--label", required=True,
                        help="Label for this recording (e.g., blink, clench, rest, talk)")
    parser.add_argument("--duration", type=float, default=10,
                        help="Duration per trial in seconds (default: 10)")
    parser.add_argument("--trials", type=int, default=5,
                        help="Number of trials (default: 5)")
    parser.add_argument("--pause", type=float, default=3,
                        help="Pause between trials in seconds (default: 3)")
    parser.add_argument("--url", default="ws://localhost:8765")
    args = parser.parse_args()

    out_dir = Path("recordings") / args.label
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Recording {args.trials} trials of '{args.label}', {args.duration}s each")
    print(f"Output: {out_dir}/")
    print(f"Pause between trials: {args.pause}s")

    for trial in range(1, args.trials + 1):
        if trial > 1:
            print(f"\n  Pause {args.pause}s — relax ...")
            await asyncio.sleep(args.pause)

        # Countdown
        for i in range(3, 0, -1):
            print(f"  Starting in {i}...")
            await asyncio.sleep(1)

        await record_trial(args.url, args.duration, args.label, trial, out_dir)

    print(f"\nDone! {args.trials} trials saved to {out_dir}/")
    print(f"\nTo record other conditions:")
    print(f"  python scripts/record_labeled.py --label rest --duration {args.duration} --trials {args.trials}")
    print(f"  python scripts/record_labeled.py --label clench --duration {args.duration} --trials {args.trials}")
    print(f"  python scripts/record_labeled.py --label talk --duration {args.duration} --trials {args.trials}")


if __name__ == "__main__":
    asyncio.run(main())
