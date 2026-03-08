# Research: BrainFlow Deep Dive

**Date:** 2026-03-07
**Sources:** 20+ sources (key ones listed at end)

---

## Executive Summary

BrainFlow is an MIT-licensed, C++-core biosignal SDK supporting 40+ devices across 9 programming languages and 4+ operating systems. Created by Andrey Parfenov (ex-Intel, ex-Nvidia) in 2018 as a personal project, it became the de facto hardware abstraction layer for consumer and research EEG/EMG/ECG after partnering with OpenBCI. The project is actively maintained (v5.21.0 released Feb 2026, 1.6k GitHub stars, 21 open issues) but development velocity has slowed — roughly 4 releases per year, mostly adding new boards. Funding is modest ($26.6k total via Open Collective, 90% from OpenBCI). The architecture is solid: a C++ core with plain C interface, language bindings via dynamic library loading, and a clean board abstraction that makes adding new devices straightforward. For Muse 2 on Linux, native BLE works but may require compiling from source with `--ble` flag.

---

## Key Findings

### 1. What BrainFlow Is

BrainFlow is a library for acquiring, parsing, and analyzing biosensor data — EEG, EMG, ECG, PPG, EDA, accelerometer, gyroscope, and more. Its core value proposition is **device abstraction**: write your application once, switch hardware without changing code. The same API is available in Python, C++, Java, C#, Julia, MATLAB, R, TypeScript, and Rust [1].

The library consists of three independent modules that can be used separately:

- **BoardShim** — Data acquisition. Session management (prepare/start/stop/release), real-time data retrieval, board configuration, marker insertion, and multi-stream support.
- **DataFilter** — Signal processing. Bandpass/highpass/lowpass/bandstop filters (Butterworth, Chebyshev, Bessel with zero-phase variants), FFT/IFFT, 45 wavelet families, ICA, CSP, PSD computation, band power extraction, peak detection, PPG-derived heart rate and SpO2, and file I/O [2].
- **MLModel** — Machine learning inference. Ships with pre-trained classifiers for "mindfulness" and "restfulness" metrics. Supports loading custom models via ONNX Runtime or dynamic libraries [2].

Data comes back as 2D numpy arrays (in Python) where rows are channels and columns are samples. Channel indices are queryable: `get_eeg_channels()`, `get_ppg_channels()`, `get_accel_channels()`, etc. [2]

### 2. Architecture & Source Code

The codebase is ~46.6% C++, 13.5% C, 9.8% Python, 9.2% C#, 5.7% Java, 3.8% Rust, and the remainder split across other bindings [3]. The architecture follows a clear pattern:

**Core (C/C++):** All board communication, signal processing, and ML inference is implemented once in C++ and exposed through a plain C interface via shared libraries (`.so`/`.dll`/`.dylib`). This was a deliberate design choice by Parfenov, drawing on his experience at Nvidia building C++ libraries with Python bindings [4].

**Board abstraction:** Each supported device inherits from a base `Board` class and implements its communication protocol. Data is stored in a shared `DataBuffer`. Helper base classes exist for common patterns: `_DynLibBoard` (dynamic library boards), `BLELibBoard` (BLE devices) [5].

**Bindings:** Each language binding loads the shared library at runtime and wraps the C functions in idiomatic APIs. Adding a new board automatically makes it available across all 9 languages — you only write C++ once [5].

**Build system:** CMake with a Python build script (`tools/build.py`). Supports cross-compilation for Windows, Linux, macOS, Android, and Raspberry Pi. BLE support on Linux requires compiling with `--ble` flag and `libdbus-1-dev` installed [5].

**Testing:** CI/CD pipelines with device emulators in the cloud. The synthetic board and playback board enable testing without hardware. CppCheck for static analysis. The project treats compiler warnings as errors [5].

**Code style:** clang-format enforced, snake_case for methods/variables, camelCase for classes. Brackets required even for single-line conditionals [5].

### 3. Who Is Behind It

**Creator/maintainer:** Andrey Parfenov (GitHub: Andrey1994). Russian-born software engineer with stints at Intel, Nvidia, and the University of Innsbruck. Started BrainFlow in June 2018 after buying an OpenBCI Cyton board and being frustrated by the existing SDKs. Built the first version in ~2 months of personal time. OpenBCI noticed and hired him as a contractor by May 2019 [4].

**Core team:** 26 contributors with commit access, including daniellasry (OpenBCI), retiutut, matthijscox, mesca, and others [6]. In practice, Parfenov appears to be the dominant contributor.

**Partnership:** OpenBCI is the primary partner and financial backer. The relationship is symbiotic — BrainFlow provides the SDK layer that OpenBCI's hardware ecosystem needs, and OpenBCI provides funding and hardware for testing [6].

**Funding:** Modest. $26,630 total raised via Open Collective, of which $23,549 (89%) came from OpenBCI. Current balance is $22,549 (very low expenses at $559 total). Yearly budget is $4,000. Three recurring monthly backers at $5+. No venture funding, no grants [7]. Parfenov also offers paid consulting services through the project [8].

**Governance:** Essentially a benevolent-dictator model. Parfenov has final say on merges. The project has clear contribution guidelines but no formal governance structure.

### 4. Project Activity & Health

**GitHub metrics (March 2026):**
- 1.6k stars, 385 forks
- 21 open issues, 2 open PRs (very clean issue tracker)
- 1,409+ commits
- MIT license [3]

**Release cadence (recent):**
- v5.21.0 — Feb 28, 2026 (Neuropawn board support)
- v5.20.1 — Jan 25, 2026 (IronBCI fixes)
- v5.20.0 — Jan 17, 2026 (IronBCI support)
- v5.19.0 — Oct 9, 2025 (Galea fixes)
- v5.18.1 — Aug 6, 2024 (CI fixes)
- v5.18.0 — May 31, 2024 (C# improvements)
- v5.16.0 — Jan 15, 2024 (Ant Neuro impedance) [9]

The pattern: **~4 releases/year**, primarily adding new board support or fixing device-specific issues. No major architectural changes or feature additions in the past 2 years. The project is in **maintenance mode** — stable and functional, but not rapidly evolving.

**Community:** Slack workspace (OpenBrainTalk) with #askhelp and #brainapps channels [10]. GitHub issues are the primary support channel. No Discord. Documentation is on ReadTheDocs and is comprehensive but could use better getting-started guides (acknowledged in roadmap) [11].

### 5. Supported Devices — Complete List

BrainFlow supports **40+ board configurations** across these manufacturers:

**OpenBCI (8 configs):**
- Cyton (8ch, serial USB, 250Hz)
- Cyton + Daisy (16ch, serial USB)
- Ganglion (4ch, serial via BLED112 dongle)
- Ganglion Native (4ch, native BLE)
- Cyton/CytonDaisy/Ganglion + WiFi Shield variants
- Galea (8ch EEG + EMG/EOG, WiFi/BT)

**Muse (6 configs):**
- Muse 2 — native BLE (4+1ch, 256Hz) — **your device**
- Muse S — native BLE (4+1ch, 256Hz)
- Muse 2016 — native BLE (4ch, 256Hz)
- Muse 2/S/2016 BLED variants (via BLED112 dongle)

**NeuroMD (5 configs):**
- BrainBit (4ch EEG, BLE native or BLED)
- Callibri EEG/EMG/ECG (BLE native)

**G.Tec:**
- Unicorn (8ch, proprietary BLE dongle)

**Neurosity (3 configs):**
- Notion 1 (4ch), Notion 2 (4ch), Crown (8ch) — BLE broadcast

**Ant Neuro (14 configs):**
- EE-211 through EE-511 (2–32 channels, USB/BT)

**Mentalab (2 configs):**
- Explore 4ch, Explore 8ch — native BLE

**FreeEEG (2 configs):**
- FreeEEG32 (32ch, serial USB)
- FreeEEG128 (128ch, serial USB)

**Others:**
- OYMotion gForce Pro/Dual (EMG armbands, BLE)
- EmotiBit (accel/gyro/PPG/EDA, UDP broadcast)
- PiEEG (8ch, SPI — Raspberry Pi only)
- NeuroPawn Knight/Knight IMU (8ch, serial USB)
- BioListener (variable ch, UDP server)
- IronBCI32 (32ch, serial USB)
- Enophone (4ch EEG headphones, BLE)
- BrainAlive (8ch, native BLE)

**Utility boards:**
- Synthetic Board (generated test data)
- Playback File Board (replay recorded sessions)
- Streaming Board (multicast UDP consumer) [12]

### 6. Muse 2 on Linux — Specifics

Two paths are available:

**Native BLE (recommended):** `BoardIds.MUSE_2_BOARD`. Requires:
- `libdbus-1-dev` package installed
- BrainFlow compiled from source with `python3 tools/build.py --ble`
- Platforms: Windows 10+, macOS 10.15+, Linux, Raspberry Pi
- Known issues on macOS 12.0–12.2 (fixed in 12.3+)
- Optional 5th EEG channel enabled via `board.config_board("p50")`
- PPG data available via ancillary preset (also requires `config_board("p50")`)

**BLED112 dongle:** `BoardIds.MUSE_2_BLED_BOARD`. Works out of the box on all platforms without compilation, but requires purchasing a $20-30 BLED112 USB dongle.

In both cases, you get 4 EEG channels (TP9, AF7, AF8, TP10) at 256Hz, plus optional accelerometer, gyroscope, and PPG streams via BrainFlow presets [12].

### 7. Signal Processing & ML — What's Built In

The DataFilter API is surprisingly comprehensive for a data acquisition library:

**Filtering:** Butterworth, Chebyshev Type I, Bessel filters — all available as lowpass, highpass, bandpass, bandstop. Zero-phase variants available. Environmental noise removal (50Hz, 60Hz, or both). Rolling filters with configurable aggregation [2].

**Transforms:** FFT/IFFT, 45 wavelet families (Haar, Daubechies db1–db20, Biorthogonal, Coiflet, Symlet), wavelet denoising (VisuShrink, SureShrink), downsampling [2].

**Analysis:** Power spectral density, band power extraction (average and custom bands), Common Spatial Patterns (CSP), Independent Component Analysis (ICA), peak detection (z-score based), signal detrending [2].

**Physiological:** Heart rate and SpO2 from PPG data, railed percentage calculation [2].

**ML:** Pre-trained classifiers for mindfulness and restfulness metrics. Custom model loading via ONNX Runtime (bring your own model) or dynamic libraries. Band power features → regression classifier pipeline [2].

**What's missing:** No real-time epoch management, no event-related potential averaging, no source localization, no advanced artifact rejection (beyond ICA). For these, you'd pair BrainFlow with MNE-Python.

### 8. Roadmap & Direction

The official roadmap [11] lists these priorities (no timelines):

1. **More devices** — Medical-grade and consumer devices, acquired or via partnerships
2. **More platforms** — iOS support, expanded Android/RPi compatibility
3. **More languages** — JavaScript bindings (TypeScript exists but is less mature)
4. **Signal processing** — ICA-based denoising improvements, additional ML classifiers, P300 classification at API level, user model loading via ONNX
5. **Documentation** — Learning paths for different user backgrounds, better getting-started guides
6. **Game engine integration** — Third-party application and game engine support

The trajectory is clear: BrainFlow aims to be the **universal hardware abstraction layer** for biosensors. Not a full BCI application framework — just the reliable data acquisition and basic processing layer that everything else builds on.

### 9. Strengths

- **Device breadth:** 40+ boards across price segments, from $30 Muse to research-grade Ant Neuro
- **Language breadth:** 9 languages with identical API — rare in this space
- **Clean architecture:** C++ core + C interface + bindings is a proven pattern (cf. SQLite, libcurl)
- **Low issue count:** 21 open issues for a project of this scope is impressive
- **MIT license:** No restrictions on commercial use
- **Signal processing included:** Don't need a separate library for basic filtering and feature extraction
- **Synthetic board:** Can develop and test without hardware
- **Maintainer quality:** Parfenov clearly knows what he's doing (Intel/Nvidia background)

### 10. Weaknesses & Risks

- **Bus factor of ~1:** Parfenov is the dominant contributor. If he steps away, the project could stagnate quickly.
- **Funding is thin:** $4k/year budget, 89% from one sponsor (OpenBCI). No diversified funding.
- **Development velocity declining:** Releases are mostly board additions, not feature development. The ML and signal processing modules haven't seen major updates.
- **BLE on Linux is painful:** Requires source compilation with `--ble` flag, `libdbus-1-dev`, and can be flaky depending on BlueZ version. This is the main friction point for your Muse 2 setup.
- **TypeScript binding is immature:** Listed as supported but less battle-tested than Python/C++/C#. If you want to build in TypeScript, web-muse or muse-js may be more practical for the Muse specifically.
- **No real-time pipeline framework:** BrainFlow gives you data and tools, but you assemble the pipeline yourself. No built-in concept of epochs, triggers, feedback loops, or event-driven processing. For that, you need TimeFlux, NeuroPype, or custom code.
- **Documentation could be better:** Acknowledged in the roadmap. Getting started is straightforward, but intermediate topics (custom board integration, advanced signal processing) require reading source code.
- **Bluetooth remains the weakest link:** Different BLE stacks across OSes, different board protocols, platform-specific quirks. This is inherent to the problem space but it's where most user issues arise.

---

## Comparison: BrainFlow vs Alternatives for Muse 2

| Aspect | BrainFlow | muselsl | web-muse | NeuroSkill |
|--------|-----------|---------|----------|------------|
| **Language** | Python/C++/9 total | Python | TypeScript | Rust (app) + TS CLI |
| **Muse 2 support** | Native BLE + BLED | Native BLE (bleak) | Web Bluetooth | Native BLE |
| **Linux setup** | Compile from source | pip install | Browser (Chrome) | Experimental |
| **Signal processing** | Built-in (filters, FFT, wavelets, ICA) | None (just streaming) | Basic utilities | 70+ metrics, GPU-accelerated |
| **ML** | Mindfulness/restfulness + ONNX | None | None | ZUNA embeddings, sleep staging |
| **Real-time** | Raw streaming, you build pipeline | Raw streaming | Raw streaming | Full dashboard, WebSocket API |
| **Multi-device** | 40+ boards | Muse only | Muse only | Muse + OpenBCI |
| **Maintenance** | Active (v5.21, Feb 2026) | Dormant | Active but small | Active |
| **Best for** | Multi-device apps, custom pipelines | Quick Muse-only scripts | Browser-based BCI | Turnkey analysis + ZUNA |

---

## Open Questions

- **BrainFlow + ZUNA integration:** No one has documented a BrainFlow → MNE → ZUNA pipeline yet. The conversion from BrainFlow's numpy arrays to MNE RawArray is straightforward but untested in published examples.
- **Linux BLE reliability:** Multiple sources mention issues with BLE on Linux. The v4.9.3 fix (SimpleBLE update) helped, but BlueZ version and kernel support still matter. Worth testing early in your setup.
- **TypeScript binding maturity:** The TS binding exists but I couldn't find significant community usage or examples beyond basics. For Muse-specific TypeScript work, web-muse is likely more practical.
- **Parfenov's continued involvement:** No public statements about future plans. The project's health depends heavily on his continued interest.
- **ONNX model ecosystem:** The ONNX integration for custom ML models is documented but I found no community-shared models or a model zoo. You'd be training your own.

---

## Sources

[1] BrainFlow official site. https://brainflow.org/
[2] BrainFlow User API documentation. https://brainflow.readthedocs.io/en/stable/UserAPI.html
[3] BrainFlow GitHub repository. https://github.com/brainflow-dev/brainflow
[4] Q&A with BrainFlow Creator Andrey Parfenov — OpenBCI Community. https://openbci.com/community/brainflowqa/
[5] BrainFlow Developer documentation. https://brainflow.readthedocs.io/en/stable/BrainFlowDev.html
[6] BrainFlow Partners, Sponsors, and Contributors. https://brainflow.readthedocs.io/en/stable/Partners.html
[7] BrainFlow Open Collective. https://opencollective.com/brainflow
[8] BrainFlow Consulting services. https://brainflow.org/paid_software_development/
[9] BrainFlow GitHub Releases. https://github.com/brainflow-dev/brainflow/releases
[10] OpenBrainTalk Slack — BrainFlow community. https://brainflow.org/2020-03-23-slack/
[11] BrainFlow Roadmap. https://brainflow.org/roadmap/
[12] BrainFlow Supported Boards. https://brainflow.readthedocs.io/en/stable/SupportedBoards.html
[13] BrainFlow History and Review. https://brainflow.org/2021-07-30-history/
[14] BrainFlow Features. https://brainflow.org/features/
[15] BrainFlow installation / build instructions. https://brainflow.readthedocs.io/en/stable/BuildBrainFlow.html
[16] BrainFlow 4.9.3 — Linux Muse fix. https://brainflow.org/2022-05-16-muse-linux/
[17] BrainFlow 4.7.0 — Native BLE release. https://brainflow.org/2021-11-01-new-release/
[18] DeepWiki — BrainFlow architecture. https://deepwiki.com/brainflow-dev/brainflow/5-installation-and-building
