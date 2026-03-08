Short version: there is very strong evidence that Muse 2 will work with ZUNA, but there is (as of Feb 2026) no official “Muse 2 + ZUNA” tutorial. ZUNA is explicitly designed to accept data from low‑channel consumer headsets via MNE, and Muse 2 has well‑documented ways to stream raw EEG into MNE/BrainFlow. So compatibility is architectural, not vendor‑certified.

Below is:

1. Evidence that a 4‑channel Muse 2 fits ZUNA’s supported device class  
2. Evidence that Muse 2 raw data can be brought into MNE/Python in the right shape  
3. A concrete step‑by‑step pipeline from Muse 2 → Python/MNE → ZUNA

***

## 1. What ZUNA expects

**ZUNA’s design goals and input format**

From Zyphra’s own material and the ZUNA paper/model card:

- ZUNA is a 380M‑parameter diffusion autoencoder trained to **reconstruct, denoise, and upsample scalp EEG**. [arxiv](https://www.arxiv.org/abs/2602.18478)  
- It was trained on an aggregated corpus of **208 public datasets with ~2 million channel‑hours**, with **channel counts ranging from 2 to 256** per recording. [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)
- The architecture tokenizes EEG into short windows and uses a **4D rotary positional encoding over (x, y, z, t)**, i.e. it only cares about electrode 3D position and time index, not any fixed channel layout. [pawanpatra](https://pawanpatra.com/exploring-zyphras-zuna-a-deep-dive-into-the-380m-parameter-bci-foundation-model-for-eeg-data/)
- Zyphra and the paper emphasize that ZUNA **“scales seamlessly from consumer headsets to 256‑electrode research systems, with no retraining.”** [linkedin](https://www.linkedin.com/posts/zyphra_today-were-releasing-zuna-our-first-bci-activity-7429879992215384064-uuHs)
- The preprocessing in their training pipeline standardized everything to **256 Hz** using **MNE‑Python**. [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)
- The current README / commits say **“ZUNA expects EEG in MNE‑Python format (.fif) with a valid scalp montage”** and provide an MNE‑compatible preprocessing/inference stack, installable via `pip install zuna`. [huggingface](https://huggingface.co/api/resolve-cache/models/Zyphra/ZUNA/8eedc87bc4d10eae9d428ad43b7aa55a12eb0a35/README.md?download=true&etag=%22de70024cd7522c1d239f46ab17c514c445993b81%22)

Taken together:

- Any EEG that you can represent as an MNE `Raw` object or `.fif` file with:
  - known sampling rate (ideally 256 Hz)  
  - channel names with known 10–20 positions or explicit 3D coordinates  
  - standard EEG units  
  satisfies ZUNA’s input requirements. There is no dependency on a particular hardware brand.

Muse 2 clearly fits in the “consumer headset with 2–8 channels at ~256 Hz” bucket ZUNA was designed to upsample from.

***

## 2. What Muse 2 provides (technically)

**Muse 2 hardware and signal**

Vendor specs + independent docs show that Muse 2 has: [choosemuse](https://choosemuse.com/products/muse-2)

- **Electrode positions**: 4 dry EEG electrodes at **TP9, AF7, AF8, TP10**, plus a reference at FPz (CMS/DRL). These are standard 10–20 locations; MNE has them in the built‑in `standard_1020` montage.
- **Sample rate**: **256 Hz**.
- **Resolution**: **12‑bit** per sample.
- 4 EEG channels + up to 2 amplified AUX channels (not always exposed by all software). [m.media-amazon](https://m.media-amazon.com/images/I/61ntS2R+KmL.pdf)

The scoping review on consumer EEG explicitly notes **interaXon Muse records at 256 Hz from AF7, AF8, TP9, TP10** and reports its use in experimental and clinical work. [pmc.ncbi.nlm.nih](https://pmc.ncbi.nlm.nih.gov/articles/PMC10917334/)

These properties line up almost perfectly with ZUNA’s training regime (256 Hz, standard 10–20 coordinates, low‑channel consumer devices). [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)

**Muse 2 → Python raw data**

There is well‑tested tooling to get full‑rate raw EEG from Muse 2 into Python:

- **`muselsl` / Muse‑LSL**  
  - Python package that streams **raw Muse data over LSL**; explicitly supports Muse 2 / Muse S. [github](https://github.com/alexandrebarachant/muse-lsl)  
  - Typical workflow: `muselsl stream` to create an LSL stream; then a separate Python process reads that stream and records data or feeds it to analysis.
- **BlueMuse + custom LSL tools**  
  - Guides for “Collect Real‑Time Data from Muse 2 EEG With Markers” on Windows use BlueMuse (GUI) to create an LSL stream and a Python script (via `pylsl`) to capture raw Muse 2 data (all four channels, at full sampling) into NumPy/CSV. [shaum](https://shaum.pro/collect-real-time-data-from-muse-2-eeg-with-markers-windows-ad60466cbcff)
- **BrainFlow**  
  - BrainFlow added support for **Muse 2 and Muse S** back in v4.3.0, initially via BLED112 dongle. [brainflow](https://brainflow.org/2021-06-22-muse-bled/)  
  - v4.7.0 introduced **native BLE support (no dongle)**, with boards `MUSE_2_BOARD` and `MUSE_S_BOARD` for Windows/macOS/Linux, including example code. [brainflow](https://brainflow.org/2021-11-01-new-release/)  
  - Example code for Muse 2: connect as `BoardIds.MUSE_2_BOARD`, collect samples for N seconds, store to Pandas/CSV. [cheongpark.tistory](https://cheongpark.tistory.com/99)
- These pipelines give you **raw numeric time‑series** for TP9 / AF7 / AF8 / TP10 with precise timestamps at 256 Hz that you can feed into MNE.

So: Muse 2 gives you 4 channels at 256 Hz in standard 10–20 positions, and you can access that raw signal programmatically in Python via LSL or BrainFlow. [shaum](https://shaum.pro/collect-real-time-data-from-muse-2-eeg-with-markers-windows-ad60466cbcff)

***

## 3. Bridging the two: why this is enough “proof”

Putting the pieces together:

- ZUNA only requires **“EEG in MNE‑Python format (.fif) with a valid scalp montage”** and is explicitly designed to **generalize across arbitrary hardware, channel counts and Electrode layouts, including consumer headsets**. [linkedin](https://www.linkedin.com/posts/zyphra_today-were-releasing-zuna-our-first-bci-activity-7429879992215384064-uuHs)
- Muse 2 produces **standard 4‑channel 10–20 EEG at 256 Hz**, which:
  - is a supported channel count (≥2) [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)
  - matches ZUNA’s standardized sample rate [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)
  - uses electrode names that MNE knows how to position in 3D [pmc.ncbi.nlm.nih](https://pmc.ncbi.nlm.nih.gov/articles/PMC10917334/)
- There are battle‑tested paths from **Muse 2 → LSL/BrainFlow → Python** that yield arrays or CSVs you can load into MNE as `RawArray` and then save to `.fif`. [shaum](https://shaum.pro/collect-real-time-data-from-muse-2-eeg-with-markers-windows-ad60466cbcff)

What is *not* available yet is an official sentence like *“we have validated ZUNA on Muse 2 data”* from Zyphra. Instead, all the evidence is architectural and ecosystem‑level: ZUNA is device‑agnostic by design, and Muse 2 is a normal, low‑channel EEG device that matches the expected sampling rate and coordinate system and can be ingested via MNE.

Given your skill level, that is generally sufficient to treat “Muse 2 + ZUNA” as compatible, with the only real work being plumbing (streaming, MNE conversion, calling the ZUNA API).

***

## 4. Step‑by‑step: Muse 2 → MNE → ZUNA on a home lab

Below is a concrete path that stays in Python and MNE. It uses `muselsl` (LSL) because it’s simple and cross‑platform; BrainFlow is an alternative if you prefer.

### 4.1. Hardware & OS

You will need:

- Muse 2 headset, charged and paired via Bluetooth 4.x/5.x.
- A machine with:
  - BLE support (built‑in or via dongle).
  - Linux (your usual dev environment), macOS, or Windows.
  - Python 3.10+.
  - For ZUNA: ideally a GPU box (e.g. RTX 4070‑class with ≥12 GB VRAM), but CPU will work for small tests. [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)

### 4.2. Set up Python env

Create a fresh environment (conda/mamba or venv) and install the key libs:

```bash
# example with conda
conda create -n eeg python=3.11
conda activate eeg

pip install mne muselsl pylsl numpy scipy
pip install brainflow  # optional alternative to muselsl
pip install zuna       # ZUNA package
```

- `mne` – for EEG handling and .fif I/O [mne](https://mne.tools/stable/install/manual_install.html)
- `muselsl` + `pylsl` – for streaming Muse 2 over LSL [github](https://github.com/alexandrebarachant/muse-lsl)
- `zuna` – the model and its MNE‑compatible inference stack [huggingface](https://huggingface.co/api/resolve-cache/models/Zyphra/ZUNA/8eedc87bc4d10eae9d428ad43b7aa55a12eb0a35/README.md?download=true&etag=%22de70024cd7522c1d239f46ab17c514c445993b81%22)

### 4.3. Confirm Muse 2 streaming

1. Put Muse 2 into pairing mode and ensure the OS sees it as a BLE device (but do **not** pair it manually if following muselsl’s docs).
2. List Muses:

   ```bash
   muselsl list
   ```

   You should see something like `Muse-41D2` in the output. [github](https://github.com/alexandrebarachant/muse-lsl)

3. Start an LSL stream:

   ```bash
   # first Muse found
   muselsl stream

   # OR target a specific headset
   muselsl stream --name Muse-41D2
   ```

   This creates an LSL stream with four EEG channels TP9 / AF7 / AF8 / TP10 at 256 Hz. [github](https://github.com/alexandrebarachant/muse-lsl)

If you prefer BrainFlow instead:

- Use the Muse‑2 example with `BoardIds.MUSE_2_BOARD`, `prepare_session()`, `start_stream()`, `get_current_board_data()`, then `stop_stream()` and `release_session()` to save a `data.csv` with raw EEG. [brainflow](https://brainflow.org/2021-11-01-new-release/)

### 4.4. Record a `.fif` file with MNE

Approach A: directly via LSL into MNE (simplest if you stick with muselsl).

Very roughly (pseudocode):

```python
import mne
from mne_lsl import stream  # if you use an LSL helper package, or use pylsl directly

# 1. Connect to the Muse LSL stream (name/type "Muse" or as reported)
raw = mne.io.read_raw_lsl()  # or write a small wrapper that pulls from pylsl and builds RawArray

# 2. Set channel names/types explicitly if needed
raw.rename_channels(mapping={
    'Muse-TP9': 'TP9',
    'Muse-AF7': 'AF7',
    'Muse-AF8': 'AF8',
    'Muse-TP10': 'TP10',
})
raw.set_channel_types({ch: 'eeg' for ch in raw.info['ch_names']})

# 3. Attach 10-20 montage (includes AF7/AF8/TP9/TP10)
montage = mne.channels.make_standard_montage('standard_1020')
raw.set_montage(montage)

# 4. (Optional) Basic filtering / line noise removal to match ZUNA preprocessing
raw.filter(l_freq=0.5, h_freq=40.0)  # similar to ZUNA training high-pass at 0.5 Hz[cite:98]
raw.notch_filter(freqs=[50, 100])   # or 60 Hz depending on mains

# 5. Save as FIF for ZUNA
raw.save('muse2_raw.fif', overwrite=True)
```

If you use BrainFlow instead of LSL, your steps are:

1. Use the BrainFlow Muse 2 example to save a CSV of raw EEG with 4 EEG channels and a known channel order. [brainflow](https://brainflow.org/2021-06-22-muse-bled/)
2. Load CSV into NumPy, shape it to `(n_channels, n_times)`, and build an MNE `RawArray`:

   ```python
   import numpy as np
   import pandas as pd
   import mne

   df = pd.read_csv('muse2_data.csv')  # one column per channel
   data = df[['TP9','AF7','AF8','TP10']].to_numpy().T  # shape (4, n_times)

   info = mne.create_info(
       ch_names=['TP9', 'AF7', 'AF8', 'TP10'],
       sfreq=256.0,
       ch_types='eeg',
   )
   raw = mne.io.RawArray(data, info)  # see RawArray docs

   montage = mne.channels.make_standard_montage('standard_1020')
   raw.set_montage(montage)

   raw.save('muse2_raw.fif', overwrite=True)
   ```

Either way, you end up with `muse2_raw.fif` that satisfies ZUNA’s stated expectation: **MNE `.fif` with valid montage at 256 Hz**. [marktechpost](https://www.marktechpost.com/2026/02/18/zyphra-releases-zuna-a-380m-parameter-bci-foundation-model-for-eeg-data-advancing-noninvasive-thought-to-text-development/)

### 4.5. Run ZUNA on the Muse 2 data

Exact API details may evolve, but the documented pieces are:

- Install via `pip install zuna`. [huggingface](https://huggingface.co/api/resolve-cache/models/Zyphra/ZUNA/8eedc87bc4d10eae9d428ad43b7aa55a12eb0a35/README.md?download=true&etag=%22de70024cd7522c1d239f46ab17c514c445993b81%22)
- ZUNA expects `.fif` files and MNE objects as its input and provides an MNE‑compatible preprocessing/inference stack. [pawanpatra](https://pawanpatra.com/exploring-zyphras-zuna-a-deep-dive-into-the-380m-parameter-bci-foundation-model-for-eeg-data/)

The typical workflow (conceptually) is:

1. Load your `.fif` file into MNE:

   ```python
   import mne
   raw = mne.io.read_raw_fif('muse2_raw.fif', preload=True)
   ```

2. Call ZUNA’s inference helper on this `raw`. The README / Hugging Face page under the “Inference” section will give you the **exact function names and arguments** for your installed version. [huggingface](https://huggingface.co/api/resolve-cache/models/Zyphra/ZUNA/8eedc87bc4d10eae9d428ad43b7aa55a12eb0a35/README.md?download=true&etag=%22de70024cd7522c1d239f46ab17c514c445993b81%22)

   Conceptually, something like:

   ```python
   from zuna import run_inference  # NAME HERE IS JUST ILLUSTRATIVE – check the README

   result = run_inference(
       raw,
       upsample_to_channels=32,   # e.g. virtually upsample 4-channel Muse to 32 channels
       device='cuda',             # if you have a GPU
   )

   reconstructed_raw = result['reconstructed']  # or however they return it
   reconstructed_raw.save('muse2_zuna_32ch.fif', overwrite=True)
   ```

   Do **not** rely on the function names in this pseudocode; instead, copy the exact snippet from the current ZUNA README / GitHub, which will show how to feed an MNE `Raw` or `.fif` into the model. [huggingface](https://huggingface.co/api/resolve-cache/models/Zyphra/ZUNA/8eedc87bc4d10eae9d428ad43b7aa55a12eb0a35/README.md?download=true&etag=%22de70024cd7522c1d239f46ab17c514c445993b81%22)

3. Use `reconstructed_raw` (higher‑quality / virtual high‑density EEG) for your downstream decoding or analysis.

***

## 5. Risks / caveats before you buy

To be fully transparent:

- There is **no vendor‑level statement “Muse 2 is officially supported by ZUNA”** yet. The guarantee you get is:
  - ZUNA: “any EEG in MNE format; 2–256 channels; consumer headsets supported with no retraining.” [linkedin](https://www.linkedin.com/posts/zyphra_today-were-releasing-zuna-our-first-bci-activity-7429879992215384064-uuHs)
  - Muse 2: “4‑channel, 256 Hz EEG at standard 10–20 locations; raw accessible via LSL/BrainFlow, widely used in research pipelines with MNE.” [pmc.ncbi.nlm.nih](https://pmc.ncbi.nlm.nih.gov/articles/PMC10917334/)
- You will likely need to do some light glue work:
  - Decide on LSL vs BrainFlow (LSL is simpler on Linux, BrainFlow gives you a nice abstraction).
  - Possibly tweak channel naming so MNE and ZUNA pick up positions correctly.
- With only 4 channels, ZUNA will be doing **heavy super‑resolution**; the reconstructed signals will still be limited by the information content of those 4 sensors. For serious research you will eventually want more channels (OpenBCI‑class), but Muse 2 is fine to validate your pipeline and play with ZUNA’s behavior on sparse input.

***

## 6. Practical recommendation

Given this evidence:

- If your goal is to **validate ZUNA and build out your local pipeline**, buying Muse 2 is defensible:
  - It is supported by LSL and BrainFlow.
  - Its data is standard enough for MNE and therefore ZUNA.
- If your goal is eventually **serious decoding / thought‑to‑text experiments**, treat Muse 2 as a **starter device** and plan to step up to an OpenBCI‑class 8–16 channel board once your ZUNA tooling is solid.

If you want, the next step can be to sketch an actual small repo layout for you (e.g. `collector/`, `mne_preproc/`, `zuna_inference/`) with concrete Python scripts tailored to your OS (probably Linux) and preferred streaming backend (LSL vs BrainFlow).