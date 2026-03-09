#!/usr/bin/env python3
"""Connect to the EEG backend WebSocket, capture data, and validate ranges.

Usage:
    python scripts/diagnose_data.py [--seconds 15] [--url ws://localhost:8765]

Captures binary frames + metrics JSON, then prints a diagnostic report
showing whether values fall within expected Muse 2 ranges.
"""
import argparse
import asyncio
import json
import struct
import sys
import numpy as np
import websockets

MSG_EEG = 0x01
MSG_PPG = 0x02
MSG_IMU = 0x03
MSG_NAMES = {MSG_EEG: "EEG", MSG_PPG: "PPG", MSG_IMU: "IMU"}

# Expected ranges for Muse 2
EXPECTED = {
    "eeg_amplitude_uv": (1, 200),        # typical resting EEG in µV (RMS)
    "delta_power": (0.1, 500),            # µV² — varies widely
    "theta_power": (0.1, 300),
    "alpha_power": (0.1, 300),            # higher with eyes closed
    "beta_power": (0.05, 100),
    "gamma_power": (0.01, 50),
    "heart_rate_bpm": (40, 180),
    "spo2_percent": (85, 100),
    "accel_magnitude_g": (0.8, 1.2),      # ~1g when still
    "pitch_deg": (-90, 90),
    "roll_deg": (-90, 90),
}


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


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def check(label: str, value, expected_range, unit=""):
    lo, hi = expected_range
    ok = lo <= value <= hi
    status = "✓" if ok else "✗"
    color = "\033[92m" if ok else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {label}: {value:.3f} {unit}  (expected {lo}–{hi})")
    return ok


async def capture(url: str, duration: float):
    eeg_frames = []
    ppg_frames = []
    imu_frames = []
    metrics_list = []
    frame_counts = {MSG_EEG: 0, MSG_PPG: 0, MSG_IMU: 0}

    print(f"Connecting to {url} ...")
    async with websockets.connect(url) as ws:
        print(f"Connected. Capturing for {duration}s ...\n")
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
                ft = frame["type"]
                frame_counts[ft] = frame_counts.get(ft, 0) + 1
                if ft == MSG_EEG:
                    eeg_frames.append(frame["data"])
                elif ft == MSG_PPG:
                    ppg_frames.append(frame["data"])
                elif ft == MSG_IMU:
                    imu_frames.append(frame["data"])

                # Progress dot
                total = sum(frame_counts.values())
                if total % 50 == 0:
                    elapsed = duration - (deadline - asyncio.get_event_loop().time())
                    print(f"  ... {elapsed:.0f}s  EEG={frame_counts[MSG_EEG]} PPG={frame_counts[MSG_PPG]} IMU={frame_counts[MSG_IMU]} frames", end="\r")
            else:
                try:
                    m = json.loads(msg)
                    if m.get("type") == "metrics":
                        metrics_list.append(m)
                except json.JSONDecodeError:
                    pass

    print()
    return eeg_frames, ppg_frames, imu_frames, metrics_list, frame_counts


def analyze_eeg(frames):
    if not frames:
        print("  No EEG data received!")
        return
    all_data = np.concatenate(frames, axis=1)  # (channels, total_samples)
    n_ch, n_samples = all_data.shape
    print(f"  Channels: {n_ch}, Total samples: {n_samples} ({n_samples/256:.1f}s at 256Hz)")
    print()

    ch_names = ["TP9", "AF7", "AF8", "TP10"]
    all_ok = True
    for i in range(min(n_ch, 4)):
        ch = all_data[i]
        rms = float(np.sqrt(np.mean(ch ** 2)))
        std = float(np.std(ch))
        mn, mx = float(np.min(ch)), float(np.max(ch))
        print(f"  {ch_names[i]:5s}  mean={np.mean(ch):8.2f}  std={std:8.2f}  rms={rms:8.2f}  min={mn:8.2f}  max={mx:8.2f} µV")
        ok = check(f"  {ch_names[i]} RMS amplitude", rms, EXPECTED["eeg_amplitude_uv"], "µV")
        all_ok = all_ok and ok
    return all_ok


def analyze_ppg(frames):
    if not frames:
        print("  No PPG data received!")
        return
    all_data = np.concatenate(frames, axis=1)
    n_ch, n_samples = all_data.shape
    print(f"  Channels: {n_ch}, Total samples: {n_samples} ({n_samples/64:.1f}s at 64Hz)")
    print()

    ch_names = ["Red", "IR", "Ambient"]
    for i in range(min(n_ch, 3)):
        ch = all_data[i]
        print(f"  {ch_names[i]:8s}  mean={np.mean(ch):12.2f}  std={np.std(ch):10.2f}  min={np.min(ch):12.2f}  max={np.max(ch):12.2f}")


def analyze_imu(frames):
    if not frames:
        print("  No IMU data received!")
        return
    all_data = np.concatenate(frames, axis=1)
    n_ch, n_samples = all_data.shape
    print(f"  Channels: {n_ch}, Total samples: {n_samples} ({n_samples/52:.1f}s at 52Hz)")
    print()

    ch_names = ["AccX", "AccY", "AccZ", "GyrX", "GyrY", "GyrZ"]
    for i in range(min(n_ch, 6)):
        ch = all_data[i]
        print(f"  {ch_names[i]:5s}  mean={np.mean(ch):8.4f}  std={np.std(ch):8.4f}  min={np.min(ch):8.4f}  max={np.max(ch):8.4f}")

    if n_ch >= 3:
        accel = all_data[:3]
        mag = np.sqrt(np.sum(accel ** 2, axis=0))
        mean_mag = float(np.mean(mag))
        print()
        check("Accel magnitude", mean_mag, EXPECTED["accel_magnitude_g"], "g")


def analyze_metrics(metrics_list):
    if not metrics_list:
        print("  No metrics received! (needs ~16s for PPG, ~2s for EEG)")
        return

    print(f"  Received {len(metrics_list)} metrics messages\n")

    for i, m in enumerate(metrics_list):
        print(f"  --- Metrics #{i+1} ---")
        if "eeg" in m:
            eeg = m["eeg"]
            bp = eeg.get("band_powers", {})
            print(f"    Band powers:")
            for band in ["delta", "theta", "alpha", "beta", "gamma"]:
                vals = bp.get(band, [])
                if vals:
                    avg = np.mean(vals)
                    check(f"    {band:6s} (avg)", avg, EXPECTED.get(f"{band}_power", (0, 999)))
                    print(f"           per-channel: {vals}")

            tbr = eeg.get("theta_beta_ratio", [])
            if tbr:
                print(f"    Theta/Beta ratio: {tbr}  (avg={np.mean(tbr):.2f}, >2.5 = unfocused)")

            faa = eeg.get("frontal_alpha_asymmetry", 0)
            print(f"    Frontal alpha asymmetry: {faa:.3f}  (+ve = approach)")

            sq = eeg.get("signal_quality", {})
            fit = eeg.get("fit_status", "?")
            print(f"    Signal quality: {sq}  fit={fit}")

        if "ppg" in m:
            ppg = m["ppg"]
            hr = ppg.get("heart_rate_bpm", 0)
            spo2 = ppg.get("spo2_percent", 0)
            hrv = ppg.get("hrv_rmssd_ms", 0)
            if hr > 0:
                check("    Heart rate", hr, EXPECTED["heart_rate_bpm"], "bpm")
            else:
                print(f"    ✗ Heart rate: {hr} (not computed yet)")
            if spo2 > 0:
                check("    SpO2", spo2, EXPECTED["spo2_percent"], "%")
            else:
                print(f"    ✗ SpO2: {spo2} (not computed yet)")
            print(f"    HRV RMSSD: {hrv:.1f} ms")

        if "imu" in m:
            imu = m["imu"]
            pitch = imu.get("head_pose", {}).get("pitch", 0)
            roll = imu.get("head_pose", {}).get("roll", 0)
            movement = imu.get("head_movement", 0)
            artifact = imu.get("motion_artifact", False)
            print(f"    Head pose: pitch={pitch}° roll={roll}°  movement={movement}  artifact={artifact}")

        print()


async def main():
    parser = argparse.ArgumentParser(description="EEG data diagnostic")
    parser.add_argument("--seconds", type=float, default=20,
                        help="Capture duration (default 20s, need ≥16s for PPG)")
    parser.add_argument("--url", default="ws://localhost:8765")
    args = parser.parse_args()

    eeg_frames, ppg_frames, imu_frames, metrics_list, counts = await capture(args.url, args.seconds)

    print_header("FRAME SUMMARY")
    for ft, name in MSG_NAMES.items():
        print(f"  {name}: {counts.get(ft, 0)} frames")

    print_header("EEG RAW DATA ANALYSIS")
    analyze_eeg(eeg_frames)

    print_header("PPG RAW DATA ANALYSIS")
    analyze_ppg(ppg_frames)

    print_header("IMU RAW DATA ANALYSIS")
    analyze_imu(imu_frames)

    print_header("METRICS ANALYSIS (computed by backend)")
    analyze_metrics(metrics_list)

    print_header("DONE")
    print("  Green ✓ = within expected range")
    print("  Red ✗ = outside expected range (may indicate pipeline issue)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
