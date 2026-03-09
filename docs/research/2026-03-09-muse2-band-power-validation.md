# Research: Muse 2 Band Power — Device vs SDK Computation & Cross-Validation

**Date:** 2026-03-09
**Sources:** 12 sources, key ones listed below

---

## Executive Summary

The Muse 2 headband does **not** compute band powers on-device. The hardware streams only raw EEG samples (12-bit, 256Hz) over BLE via GATT characteristics. Band power computation (FFT → PSD → frequency band integration) happens entirely **client-side** — either in the libmuse SDK, Mind Monitor app, or your own code. This means there is no "ground truth" Muse-computed band power to compare against. BrainFlow also provides only raw EEG (channels 1-4) with no pre-computed metrics. Cross-validation must therefore compare **our algorithm against the documented Muse SDK algorithm**, not against device output.

## Key Findings

### 1. Band Powers Are Computed Client-Side, Not On-Device

The Muse BLE protocol, as documented by Alexandre Barachant's reverse-engineering work [1], shows the headband streams raw EEG in packets containing "a 16-bit timestamp followed by 12 12-bit data samples" per electrode. There are no GATT characteristics for band powers.

The muse-lsl library [2], which directly subscribes to Muse BLE characteristics, receives only: raw EEG, accelerometer, gyroscope, and PPG (Muse 2). It has "no mention of band power computation or subscription to computed band power BLE characteristics" [2]. Band powers in muse-lsl's neurofeedback example are computed locally via FFT with a Hamming window [3].

The libmuse SDK (InteraXon's official library) exposes `MuseDataPacketType` enums including `ALPHA_ABSOLUTE`, `BETA_ABSOLUTE`, `THETA_ABSOLUTE`, `DELTA_ABSOLUTE`, `GAMMA_ABSOLUTE` and their relative/score variants [4]. However, these are computed by the SDK library running on the phone/computer from the raw EEG data it receives over BLE — not received pre-computed from the device. This is confirmed by the fact that muse-lsl achieves the same results using only raw EEG BLE subscriptions.

Mind Monitor computes band powers itself from raw EEG at 256Hz, outputting absolute brainwave values at 10Hz [5]. The developer confirmed it doesn't receive pre-computed values from the device.

### 2. BrainFlow Exposes Only Raw Sensor Data

BrainFlow's Muse 2 board descriptor (board_id=38) confirms:

| Preset | Channels | Data |
|--------|----------|------|
| DEFAULT | [1,2,3,4] EEG + [5] other | Raw EEG at 256Hz. Channel 5 = optional 5th EEG (via `config_board("p50")`) |
| AUXILIARY | [1,2,3] accel + [4,5,6] gyro | IMU at 52Hz |
| ANCILLARY | [1,2,3] PPG | PPG at 64Hz |

No band power channels exist in any preset. BrainFlow provides `DataFilter.get_psd_welch()` and `DataFilter.get_band_power()` as separate signal processing utilities — these compute from raw data, not from device output.

### 3. The Muse SDK Algorithm (Documented)

Based on archived InteraXon developer documentation [6] and Mind Monitor's technical manual [5]:

- **Method**: Hamming-windowed FFT → Power Spectral Density (PSD)
- **Absolute band power**: `log10(PSD)` integrated over the frequency band
- **Frequency bands**: Delta 1-4Hz, Theta 4-8Hz, Alpha 7.5-13Hz, Beta 13-30Hz, Gamma 30-44Hz
- **Relative band power**: Single band's absolute power ÷ sum of all bands' absolute powers
- **Score**: Rolling average mapped to [0, 1] scale
- **Update rate**: ~10Hz

Note: Alpha range is 7.5-13Hz (not 8-13Hz as sometimes cited). Gamma caps at 44Hz (not 50Hz). These differ slightly from standard neuroscience definitions.

### 4. Cross-Validation Strategy

Since there's no device-side "ground truth," validation options are:

**Option A — Algorithm comparison (recommended)**:
1. Record raw EEG via BrainFlow
2. Compute band powers using our current method (`get_psd_welch` + `get_band_power`)
3. Compute band powers using the documented Muse SDK algorithm (Hamming FFT, log10 PSD, their exact frequency ranges)
4. Compare values — they should be very close (differences only from windowing parameters)

**Option B — Mind Monitor comparison**:
1. Stream Muse data to Mind Monitor simultaneously (not possible — BLE allows only one connection)
2. Alternative: Record with Mind Monitor, export CSV, then record same session with BrainFlow. Compare band powers offline. Impractical due to non-simultaneous recording.

**Option C — Known signal validation**:
1. Record resting eyes-closed EEG (strong alpha peak expected at 8-12Hz)
2. Verify alpha band shows clear dominant power
3. Record eyes-open (alpha should drop significantly)
4. This validates the pipeline is computing bands correctly without needing Muse's own values

### 5. BLE Limitation: Single Connection Only

"Interaxon unfortunately only let one app at a time connect to the Muse" [5]. This is a fundamental BLE limitation — the Muse accepts one active BLE connection. You cannot simultaneously connect BrainFlow and Mind Monitor (or libmuse) to compare real-time outputs.

This eliminates the dual-connection approach entirely.

## Comparison: Our Pipeline vs. Muse SDK Algorithm

| Parameter | Our Pipeline (BrainFlow) | Muse SDK (libmuse) |
|-----------|--------------------------|---------------------|
| Input | Raw EEG from BLE | Raw EEG from BLE |
| PSD method | Welch's method (overlapping windows) | Hamming-windowed FFT |
| Band ranges | delta 1-4, theta 4-8, alpha 8-13, beta 13-30, gamma 30-50 | delta 1-4, theta 4-8, alpha **7.5-13**, beta 13-30, gamma 30-**44** |
| Output scale | µV² (linear power) | **log10** of PSD |
| Update rate | Every 2s (our metrics loop) | ~10Hz |
| Computation location | Python (BrainFlow DataFilter) | Native SDK (C/C++ in libmuse) |

Key differences: Our alpha starts at 8Hz (Muse uses 7.5Hz), our gamma goes to 50Hz (Muse uses 44Hz), and we output linear µV² while Muse outputs log10. These are cosmetic and can be aligned.

## Recommendation

**Don't chase "Muse's own" band powers** — they don't exist at the hardware level. Instead:

1. **Match the Muse SDK frequency ranges** (7.5-13Hz for alpha, 30-44Hz for gamma) if you want comparable numbers
2. **Use Option C (eyes-open/closed alpha test)** for quick validation — it's the gold standard "does our FFT work" test
3. **Optionally implement log10 scaling** to match Muse absolute band power scale for comparison with published Muse research
4. **Use `get_custom_band_powers`** from BrainFlow which lets you specify exact frequency ranges

## Open Questions

- The `other_channels[5]` in BrainFlow's DEFAULT preset — likely the optional 5th EEG channel (AUX/Fpz), but not documented clearly. Needs empirical verification.
- Whether BrainFlow's Welch PSD vs Muse SDK's single-window Hamming FFT produces meaningfully different band powers for 2-second windows. Likely very similar.

## Sources

[1] Barachant, A. "Reverse-Engineering Muse EEG headband Bluetooth protocol". https://alexandre.barachant.org/blog/2017/01/27/reverse-engineering-muse-eeg-headband-bluetooth-protocol.html (Retrieved: 2026-03-09)
[2] alexandrebarachant/muse-lsl GitHub repository. https://github.com/alexandrebarachant/muse-lsl (Retrieved: 2026-03-09)
[3] muse-lsl neurofeedback example. https://github.com/alexandrebarachant/muse-lsl/blob/master/examples/neurofeedback.py (Retrieved: 2026-03-09)
[4] LibMuse 6.0.3 MuseDataPacketType enum. https://siddhantattavar.com/libmuse/ (Retrieved: 2026-03-09)
[5] Mind Monitor Technical Manual & FAQ. https://www.mind-monitor.com/Technical_Manual.php / https://www.mind-monitor.com/FAQ.php (Retrieved: 2026-03-09)
[6] InteraXon Developer Docs (archived). https://mind-monitor.com/OnlineHelp.php?page=absolute_band_powers (Retrieved: 2026-03-09)
[7] Guerdan, L. "How to Decode Mental States With a Commercial EEG Headband". https://lukeguerdan.com/blog/2019/muse-neurofeedback/ (Retrieved: 2026-03-09)
[8] BrainFlow Supported Boards documentation. https://brainflow.readthedocs.io/en/stable/SupportedBoards.html (Retrieved: 2026-03-09)
[9] Muse Forum: Accessing Alpha and Beta values in LibMuse. http://forum.choosemuse.com/t/accessing-alpha-and-beta-values-in-libmuse-android/416 (Retrieved: 2026-03-09)
[10] SiddhantAttavar/libmuse (unofficial). https://github.com/SiddhantAttavar/libmuse (Retrieved: 2026-03-09)
[11] Mind Monitor Forum: From Raw to Absolute Band Powers. https://musemonitor.com/forums/viewtopic.php?t=1651 (Retrieved: 2026-03-09)
[12] BrainFlow Band Power Notebook. https://brainflow.readthedocs.io/en/stable/notebooks/band_power.html (Retrieved: 2026-03-09)
