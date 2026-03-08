# Research: Muse 2 Programmatic Usage & BCI Applications with ZUNA

**Date:** 2026-03-07
**Sources:** 25+ sources (key ones listed below)

---

## Executive Summary

The Muse 2 has a mature ecosystem for programmatic access across Python, TypeScript, and browsers. **BrainFlow** (native BLE, no dongle since v4.7) and **muselsl** (LSL-based, bleak backend) are the two primary Python paths; **muse-js** and its maintained fork **web-muse** provide Web Bluetooth access from browsers and Node.js. For real-time processing, **NeuroSkill** stands out as a free, open-source desktop app that already integrates ZUNA embeddings, 70+ brain metrics, and a WebSocket API — purpose-built for Muse 2/S and OpenBCI. ZUNA itself is pip-installable and converts 4-channel Muse data into virtual high-density EEG through denoising and channel upsampling, unlocking applications that normally require research-grade hardware. Practical projects range from neurofeedback and attention detection (high feasibility) through motor imagery and P300 classification (moderate) to thought-to-text (experimental, frontier).

---

## Part 1: Muse 2 Programmatic Access

### 1.1 Python Libraries

**BrainFlow** is the most versatile option. Since v4.7.0, it supports Muse 2 via native BLE with no dongle required on Windows, macOS, and Linux [1]. On Linux, you need `libdbus-1-dev` and may need to compile from source with `--ble` flag [2]. The API is clean: `BoardIds.MUSE_2_BOARD`, `prepare_session()`, `start_stream()`, `get_board_data()`. BrainFlow provides 3 presets: default (EEG), auxiliary (gyro/accel), and ancillary (PPG) [2]. It also bundles signal processing functions (filters, transforms, ML classifiers) making it a one-stop SDK.

```python
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds

params = BrainFlowInputParams()
board = BoardShim(BoardIds.MUSE_2_BOARD.value, params)
board.prepare_session()
board.start_stream()
data = board.get_board_data()  # numpy array
board.stop_stream()
board.release_session()
```

**muselsl** is the classic option, streaming Muse data over Lab Streaming Layer (LSL) [3]. Uses the `bleak` Bluetooth backend by default, works on Linux without a dongle. The main concern is maintenance — the repo hasn't seen significant updates, and some users report issues with newer Python versions. Still works for basic streaming.

**uvicMuse** is a third alternative that works on Linux/macOS without a dongle and supports UDP streaming in addition to LSL [4]. Less widely used but fills the gap for users who want native BLE on Linux without BrainFlow's compilation step.

**Recommendation for Linux:** BrainFlow (if you're okay building from source) or muselsl (simpler setup, just `pip install muselsl`). BrainFlow is more actively maintained and has richer signal processing built in.

### 1.2 TypeScript / JavaScript / Browser

**muse-js** [5] is the original Web Bluetooth library for Muse devices (Muse 1, 2, S). Written in TypeScript, uses RxJS observables for EEG, PPG, accelerometer, gyro streams. However, it is **no longer actively maintained**.

**web-muse** [6] is a modern, maintained fork/alternative that explicitly targets Muse 2 and Muse S. Key advantages over muse-js:
- Active development (14+ commits, recent activity)
- Built-in React hooks (`useEEG()`, `EEGProvider`)
- Mock mode for development without hardware
- Signal processing utilities included
- Real-time 256 Hz streaming

```typescript
import { connectMuse } from 'web-muse';
const muse = await connectMuse();
// Access muse.eeg for raw EEG buffers
```

**MuseJS** (Respiire) [7] is another vanilla JS library with zero dependencies, targeting Muse 2/S via Web Bluetooth. Minimal but functional.

**Browser compatibility:** Chrome, Edge, Opera, Samsung Internet. **No Safari/iOS** — Web Bluetooth is not supported there.

### 1.3 Real-Time Processing Frameworks

**NeuroSkill** [8] deserves special attention. It's a free (GPL-3.0), open-source desktop app that:
- Connects directly to Muse 2/S and OpenBCI boards
- Computes **70+ brain metrics** at ~4 Hz (band powers, FAA, TBR, entropy, HRV, consciousness indices)
- GPU-accelerated signal processing via wgpu compute shaders (~125 ms latency)
- **Integrates ZUNA** for neural embeddings (32-dim vectors every 5 seconds, HNSW-indexed)
- Automatic sleep staging (Wake/N1/N2/N3/REM per AASM)
- **WebSocket API** with 3 event streams and 9 commands — perfect for building custom apps on top
- **CLI tool** (TypeScript) wrapping the full WebSocket API with `--json` mode
- Local-only, no cloud, no accounts
- macOS primary, Linux experimental (requires BlueZ)

**TimeFlux** [9] is a Python framework for real-time biosignal processing. MIT-licensed, modular (DSP nodes, UI nodes as separate packages), graph-based pipeline definition. Works with LSL streams, so compatible with Muse via muselsl.

**OpenViBE** [10] is a mature C++ platform for BCI design with visual pipeline editor. Supports LSL input, so Muse data can flow in. Has Python scripting support but is primarily a GUI application.

**PyNoetic** [11] is a newer Python framework covering the full BCI pipeline: stimulus presentation, recording, preprocessing, feature extraction, classification (EEGNet, SVM, Random Forest, etc.), and real-time feedback. GUI-based "no-code" pipeline builder. No explicit Muse support but compatible via LSL.

### 1.4 Streaming Architecture Summary

```
Muse 2 (BLE)
├── BrainFlow (Python/C++/Java/C#) → numpy arrays → MNE / ZUNA / custom
├── muselsl (Python) → LSL stream → pylsl / MNE-LSL / TimeFlux
├── uvicMuse (Python) → LSL or UDP stream
├── web-muse / muse-js (TypeScript) → Web Bluetooth → browser app
└── NeuroSkill (desktop app) → WebSocket API → any language
```

---

## Part 2: From Brainwaves to Applications

### 2.1 What Can You Do with 4-Channel Consumer EEG?

The Muse 2 has electrodes at TP9, AF7, AF8, TP10 — frontal and temporal positions. This limits what's detectable but still enables several practical applications:

**High feasibility (proven with Muse 2):**
- **Neurofeedback** — Alpha/beta/theta band training for relaxation, focus, meditation. The classic Muse use case. Alpha power at TP9/TP10 reliably tracks relaxation state [12].
- **Attention/focus detection** — Beta/theta ratio (β/θ) is a robust index of concentration. Random Forest on frequency bands achieves ~91% accuracy; GRU on raw signals reaches ~96% [13].
- **Meditation state classification** — Distinguishing meditation vs. mind-wandering using frontal alpha asymmetry and temporal alpha power.
- **Sleep staging** — NeuroSkill already does this with Muse 2, classifying Wake/N1/N2/N3/REM [8].
- **Blink/artifact detection** — Eye blinks produce large, distinctive signals on AF7/AF8. Can be used as binary control (short blink vs long blink) for IoT devices [14].
- **ERP detection** — N400 and P300 components are measurable with Muse, though signal quality is lower than research-grade [15].

**Moderate feasibility (demonstrated but limited):**
- **Motor imagery classification** — SVM on Muse data achieves ~70% accuracy for left/right imagery [16]. Limited by electrode placement (no motor cortex coverage at C3/C4).
- **SSVEP (Steady-State Visual Evoked Potentials)** — Consumer-grade EEG achieves ~87% accuracy with Random Forest in 6-command drone control [17]. Muse's frontal/temporal placement is suboptimal for SSVEP (which is strongest at occipital sites) but still detectable.
- **Emotion classification** — Frontal alpha asymmetry (FAA) between AF7/AF8 correlates with valence (approach/avoidance). Theta/beta ratio correlates with arousal.

**Low feasibility / frontier (requires ZUNA or better hardware):**
- **Thought-to-text** — ZUNA is "advancing towards" this but it's not yet consumer-ready. Current state requires high-density EEG (64-256 channels) and controlled conditions [18]. With ZUNA upsampling, this becomes an active research direction.
- **Fine-grained cognitive state decoding** — Distinguishing specific mental tasks (mental math vs. spatial navigation vs. language).

### 2.2 What ZUNA Unlocks

ZUNA is a 380M-parameter diffusion autoencoder that takes sparse EEG and produces dense, denoised output [19]. For Muse 2 specifically:

**Denoising:** Consumer EEG is noisy (muscle artifacts, eye blinks, poor electrode contact). ZUNA's denoising was trained on ~2M channel-hours and significantly outperforms standard methods (spherical spline interpolation) especially when many channels are missing or corrupted [19].

**Channel upsampling:** This is the key capability. ZUNA can take your 4 channels (TP9, AF7, AF8, TP10) and predict what signals would look like at other standard 10-20 positions — effectively generating virtual channels. The model uses 4D rotary position embeddings (x, y, z, t) so it understands spatial relationships between electrode positions [19].

**What this means practically:**
- Downstream classifiers trained on 32-channel or 64-channel data could potentially work on ZUNA-upsampled Muse data
- Motor imagery becomes more viable if ZUNA can reliably reconstruct C3/C4 signals from surrounding positions
- Research datasets (which assume many channels) become accessible for transfer learning
- Signal quality approaches research-grade for the channels that exist, and provides reasonable estimates for positions in between

**Important caveats:**
- ZUNA is doing *prediction*, not magic — information content is fundamentally limited by 4 physical sensors
- Upsampled channels are model estimates, not measurements
- The model is released for **research use only**, not clinical/medical applications
- Real-time inference latency hasn't been benchmarked for consumer GPU scenarios (the pipeline operates on 5-second epochs)

### 2.3 ZUNA Pipeline (Concrete)

```bash
pip install zuna
```

```python
from zuna import preprocessing, inference, pt_to_fif

# 1. Preprocess .fif files (resample to 256Hz, filter, epoch into 5s segments)
preprocessing(
    input_dir="path/to/fif/files",
    output_dir="working/2_pt_input"
)

# 2. Run inference (denoising + upsampling)
inference(
    input_dir="working/2_pt_input",
    output_dir="working/3_pt_output",
    gpu_device=0,              # use "" for CPU
    tokens_per_batch=100000,
    data_norm=10.0,
    diffusion_cfg=1.0,         # 1.0 = no classifier-free guidance
    diffusion_sample_steps=50
)

# 3. Convert back to .fif
pt_to_fif(
    input_dir="working/3_pt_output",
    output_dir="working/4_fif_output"
)
```

Full tutorial: `tutorials/run_zuna_pipeline.py` in the repo. Google Colab notebook also available [20].

### 2.4 BCI Frameworks Comparison

| Framework | Language | Real-time | GUI | Muse Support | License | Best For |
|-----------|----------|-----------|-----|-------------|---------|----------|
| **NeuroSkill** | Rust/TS | Yes (4Hz) | Yes | Native | GPL-3.0 | Turnkey Muse analysis + ZUNA |
| **BrainFlow** | C++/Python/etc | Yes | No | Native | MIT | Data acquisition + basic processing |
| **TimeFlux** | Python | Yes | Basic | Via LSL | MIT | Custom real-time pipelines |
| **MNE-Python** | Python | No (offline) | Basic | Via import | BSD-3 | Offline analysis, preprocessing |
| **PyNoetic** | Python | Yes | Yes | Via LSL | GPL | Full BCI pipeline, no-code |
| **OpenViBE** | C++ | Yes | Yes | Via LSL | AGPL | Visual BCI design |
| **BCI2000** | C++ | Yes | Yes | Via LSL | GPL | Clinical/research BCI |
| **NeuroPype** | Python | Yes | Yes | Via LSL | Commercial | Enterprise BCI/neuroimaging |

### 2.5 Practical Project Ideas (Ranked by Feasibility)

**Tier 1 — Weekend projects (proven, well-documented):**

1. **Real-time meditation/relaxation neurofeedback** — Stream Muse 2 EEG → compute alpha power → audio/visual feedback. Use BrainFlow or muselsl + a simple Python/web UI. Dozens of tutorials exist.

2. **Focus tracker** — Beta/theta ratio dashboard. Build with NeuroSkill's WebSocket API or BrainFlow + a web frontend via web-muse.

3. **Sleep monitor** — Use NeuroSkill's built-in sleep staging. Wear Muse S/2 overnight, get automatic Wake/N1/N2/N3/REM classification.

4. **Blink-controlled interface** — Detect eye blinks on AF7/AF8, use as binary input for controlling smart home devices or triggering actions.

**Tier 2 — Week-long projects (requires ML pipeline):**

5. **Mental state classifier** — Record labeled sessions (focused work, relaxation, meditation, mind-wandering), extract frequency-band features, train Random Forest / SVM / EEGNet. Expected accuracy: 85-95% for 2-3 classes.

6. **ZUNA-enhanced EEG analysis** — Record Muse data → convert to .fif → run through ZUNA → analyze upsampled output. Compare raw vs. ZUNA-enhanced spectral features. Validate whether upsampled channels are useful.

7. **Emotion detection prototype** — Use frontal alpha asymmetry (AF7 vs AF8) + theta/beta ratio as features. Combine with self-reported emotional state labels. This is genuinely useful for personal mood tracking.

8. **ERP (P300) speller prototype** — Present oddball stimuli, detect P300 at frontal/temporal sites. Classification accuracy will be modest (~70%) but it's a compelling BCI demo.

**Tier 3 — Multi-week research projects (frontier):**

9. **ZUNA + downstream decoder** — Use ZUNA to upsample Muse data to 32 channels, then apply classifiers trained on public 32-channel datasets (e.g., MOABB benchmarks). Test whether ZUNA bridging improves cross-hardware transfer learning.

10. **Real-time ZUNA pipeline** — Build a streaming system: Muse → BrainFlow → 5s buffer → ZUNA inference → feature extraction → real-time classification. The challenge is latency (5s epochs + inference time).

11. **Thought-to-text exploration** — Highly experimental with 4 channels. Use ZUNA upsampling + language model decoding. This is the long-term vision Zyphra is building toward, but don't expect reliable results yet.

---

## Part 3: Recommended Stack for Your Setup

Given: Linux, Python + TypeScript proficiency, Muse 2, interest in ZUNA.

### Data Acquisition
- **Primary:** BrainFlow (Python) — richest API, native BLE on Linux
- **Alternative:** muselsl — simpler setup if BrainFlow compilation is painful
- **For web UIs:** web-muse (TypeScript, Web Bluetooth)

### Processing & Analysis
- **Real-time metrics:** NeuroSkill (if macOS available) or custom with BrainFlow + MNE
- **Offline analysis:** MNE-Python
- **ZUNA integration:** `pip install zuna` for upsampling/denoising

### Application Layer
- **Quick prototypes:** Python (BrainFlow → matplotlib/dash/streamlit)
- **Web dashboards:** TypeScript + web-muse + React
- **Neurofeedback:** BrainFlow → compute band powers → WebSocket → browser UI

### Suggested First Steps
1. Get BrainFlow streaming from Muse 2 on Linux
2. Record a few minutes of data, convert to MNE .fif format
3. Run through ZUNA pipeline, compare raw vs. enhanced
4. Build a simple real-time alpha/beta dashboard
5. Gradually add ML classification for mental states

---

## Open Questions

- **ZUNA real-time latency**: No published benchmarks for inference speed on consumer GPUs. The 5-second epoch window sets a minimum latency floor, but GPU inference time on top of that is unknown.
- **ZUNA upsampling quality at 4 channels**: The model works with 2-256 channels, but how well virtual channels at motor cortex positions (C3/C4) are predicted from only frontal/temporal data hasn't been independently validated.
- **NeuroSkill Linux support**: Listed as "experimental" — may require troubleshooting with BlueZ.
- **muselsl maintenance status**: The core repo appears dormant. BrainFlow is a safer long-term bet.
- **Web Bluetooth on Linux**: Chrome on Linux supports Web Bluetooth but can be flaky with BLE devices. Worth testing early.

---

## Sources

[1] BrainFlow 4.7.0 Release — Native BLE for Muse 2/S. https://brainflow.org/2021-11-01-new-release/
[2] BrainFlow Supported Boards — Muse 2. https://brainflow.readthedocs.io/en/stable/SupportedBoards.html
[3] muselsl — GitHub. https://github.com/alexandrebarachant/muse-lsl
[4] Krigolson Lab — Working with MUSE (uvicMuse). https://www.krigolsonlab.com/working-with-muse.html
[5] muse-js — GitHub (Web Bluetooth). https://github.com/urish/muse-js
[6] web-muse — Modern maintained alternative. https://github.com/itayinbarr/web-muse/
[7] MuseJS — Vanilla JS for Muse 2/S. https://github.com/Respiire/MuseJS
[8] NeuroSkill — Open-source EEG analysis for Muse & OpenBCI. https://neuroskill.com/
[9] TimeFlux — Real-time biosignal processing. https://timeflux.io/assets/pdf/Timeflux_GBCIC2019.pdf
[10] NeuroTechX awesome-bci — Curated BCI resources. https://github.com/NeuroTechX/awesome-bci
[11] PyNoetic — Modular Python BCI framework. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0327791
[12] Luke Guerdan — Decoding Mental States with Muse. https://lukeguerdan.com/blog/2019/muse-neurofeedback/
[13] Evelyn Teng — Decoding Focus with Python and AI. https://medium.com/@evelynqyteng/decoding-focus-categorizing-eeg-signals-with-python-and-ai-046cb7035653
[14] IoT control with Muse blink detection. https://www.sciencedirect.com/science/article/pii/S240584402030270X
[15] Muse N400/P300 utility study. https://pmc.ncbi.nlm.nih.gov/articles/PMC11679084/
[16] Muse Motor Imagery Classification — GitHub. https://github.com/vinayakr99/Muse-MotorImageryClassification
[17] SSVEP BCI drone navigation with consumer EEG. https://ijeeemi.org/index.php/ijeeemi/article/view/295
[18] Zyphra ZUNA press release. https://www.prnewswire.com/news-releases/zyphra-releases-zuna---bci-foundation-model-advancing-towards-thought-to-text-302691176.html
[19] Zyphra ZUNA — Technical blog post. https://www.zyphra.com/post/zuna
[20] ZUNA GitHub repository. https://github.com/Zyphra/zuna
[21] ZUNA on Hugging Face. https://huggingface.co/Zyphra/ZUNA
[22] ZUNA arxiv paper. https://arxiv.org/html/2602.18478
[23] BrainFlow Linux Muse fix (v4.9.3). https://brainflow.org/2022-05-16-muse-linux/
[24] BCI frameworks review (PMC). https://pmc.ncbi.nlm.nih.gov/articles/PMC11861396/
[25] Consumer EEG signal quality comparison. https://pmc.ncbi.nlm.nih.gov/articles/PMC11679099/
