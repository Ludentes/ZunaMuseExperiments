# Research: Practical BCI Commands with Muse 2 (4-Channel Consumer EEG)

**Date:** 2026-03-08
**Focus:** What actually works, with what accuracy, and who has done it

---

## TL;DR Ranking by Reliability

| Command | Detection Type | Realistic Accuracy | Latency | Practical? |
|---|---|---|---|---|
| Eye blink (single/double) | EOG artifact on AF7/AF8 | **99%+** | <100ms | **YES - best starting point** |
| Jaw clench | EMG artifact on TP9/TP10 | **95%+** | <200ms | **YES - very reliable** |
| Eyes open/closed (alpha blocking) | Alpha power change (8-13Hz) | **90-95%** | 1-2s window | **YES - proven** |
| Concentration/relaxation | Theta/beta ratio | **70-80%** binary | 2-5s window | **Moderate - high variance between users** |
| Motor imagery (L/R hand) | Mu rhythm asymmetry | **75-85%** (personalized model) | 1-3s | **Marginal - needs training, unreliable for control** |
| SSVEP | Visual evoked response | **~80%** (frontal only) | 2-4s | **Marginal - wrong electrode placement for Muse** |
| P300 | Event-related potential | **Poor** | N/A | **NO - needs parietal electrodes** |

---

## 1. Eye Blink Detection (EOG Artifacts)

### Why it works
Blinks produce massive voltage spikes (100-400 uV) easily visible on frontal electrodes AF7 and AF8. This is technically an artifact, not brain signal, which is exactly why it's so reliable -- the signal-to-noise ratio is enormous.

### Proven accuracy
- **MED algorithm (IEEE 2022):** 99.2% mean accuracy across 20 subjects using a single Muse channel. Top-5 subjects hit 100%, worst-5 subjects still achieved 97.2%. Published at IEEE SPMB 2022.
- **muse-blink (Uri Shaked):** Simple threshold on AF7 electrode, absolute value > 500mV = blink. Works "pretty good" for real-time demo with trivial code.

### Detection approach
- Simplest: threshold on raw signal amplitude on AF7 or AF8 (>500uV absolute)
- Better: peak detection with refractory period (prevent double-counting)
- For double-blink commands: detect two blinks within 500ms-1s window
- Single blink vs double blink vs triple blink gives you 3 distinct commands

### Key projects
- **urish/muse-blink** (GitHub): Angular + Web Bluetooth demo. Filters AF7, looks for spikes >500mV. Simple, works.
- **MED paper**: More sophisticated algorithm with single-channel EEG, designed for real-time.

### Caveats
- Natural blinks are frequent (~15-20/min), so you need a way to distinguish intentional from natural blinks
- Double-blink or hard-blink (exaggerated) as the trigger is more practical than single blink
- Some users report false positives from facial muscle movement

---

## 2. Jaw Clench Detection (EMG Artifacts)

### Why it works
Jaw clenching activates temporal muscles directly under TP9 and TP10 electrodes. The EMG signal is high-amplitude and broadband, very distinct from EEG. The Muse hardware explicitly records this -- it shows up as a massive increase in high-frequency power.

### Proven accuracy
- **95%+ reported** in multiple hobbyist projects and the Muse developer forum
- One project (JodieAsh/Real-Time-EEG-Classification-with-Muse) classified blink, jaw clench, and neutral state using 6-second windows from all 4 channels

### Detection approach
- Compute RMS or power in high-frequency band (>30Hz) on TP9/TP10
- Threshold crossing = clench detected
- Can distinguish single clench vs sustained clench vs double clench
- Combined with blink detection: gives you 4-6 distinct commands

### Caveats
- Sustained clenching causes jaw fatigue quickly
- Brief clench pulses are more practical for repeated use
- Some crosstalk with head movement artifacts

---

## 3. Alpha Blocking (Eyes Open/Closed)

### Why it works
Closing eyes causes a large increase in alpha power (8-13Hz), particularly visible on TP9/TP10 (temporal electrodes closest to occipital cortex on Muse). Opening eyes suppresses alpha. This is one of the most robust and well-documented EEG phenomena.

### Proven accuracy
- **90-95% binary classification** (eyes open vs closed) is routinely achieved with consumer EEG
- The Muse app itself is built on alpha detection for meditation feedback
- CruXUCLA/bci-smarthome project: used alpha relative values from Muse to control an LED (on = meditative/eyes closed state, off = alert)

### Detection approach
- Compute alpha band power (8-13Hz) over a 1-2 second sliding window on TP9/TP10
- Compare against baseline calibrated at session start
- Alpha power ratio (alpha / total power) is a robust feature

### Important note on electrode quality
Research shows TP9 and TP10 give **much better** signal consistency on Muse than AF7/AF8. The frontal channels have low amplitude because the reference electrode (Fpz) is physically close to them. For alpha-based features, always prioritize TP9/TP10.

### Caveats
- Slow -- requires 1-2 second windows for reliable detection
- Only gives binary state (eyes open/closed), not multiple commands
- Not practical as a rapid command interface -- you can't keep toggling your eyes

---

## 4. Concentration/Relaxation (Theta/Beta Ratio)

### Why it works
Increased concentration correlates with higher beta (13-30Hz) and lower theta (4-8Hz) power. The theta/beta ratio decreases with attention and increases with relaxation/drowsiness. This is the basis of ADHD neurofeedback protocols.

### Realistic accuracy
- **70-80% binary** (concentrated vs relaxed) with per-user calibration
- ~38% of users are "neurofeedback non-responders" -- they cannot reliably modulate these bands voluntarily
- Theta/beta ratio is used clinically for ADHD neurofeedback, but as a continuous metric, not a discrete command

### Detection approach
- Compute theta (4-8Hz) and beta (13-30Hz) power over 2-5 second windows
- Theta/beta ratio or beta/alpha ratio as the feature
- Requires per-session calibration (baseline recording)
- muselsl includes a neurofeedback example script that does exactly this

### Caveats
- High inter-subject variability -- what works for one person may not work for another
- Slow state transitions (seconds, not milliseconds)
- Best used as a continuous state indicator, not a discrete command trigger
- Easily confounded by movement, drowsiness, caffeine, etc.

---

## 5. Motor Imagery (Left/Right Hand)

### What the studies actually show
This is the most over-hyped capability for consumer EEG. The numbers require careful reading:

- **Tim de Boer "Building a Bedroom BCI" series (Medium):** Full walkthrough with Muse 2. Collected motor imagery data, preprocessed with ICA/PCA, trained ML classifiers. The series is honest about the difficulty -- real-time predictions were noisy and required significant training.
- **vinayakr99/Muse-MotorImageryClassification (GitHub):** CNN model on Muse 2 data. Claims reasonable accuracy but uses Mind Monitor app for data collection.
- **One study claims 96.9% accuracy** using MLP classifier on Muse 2 with OpenViBE -- but this used offline classification with extensive preprocessing, not real-time control. Such numbers do not transfer to real-time use.
- **More realistic:** 75-85% accuracy with personalized models, and 83% epoch-level / 75% subject-level with cross-validation.

### Why it's problematic with Muse
- Motor imagery relies on mu rhythm (8-13Hz) changes over the motor cortex (C3/C4 in the 10-20 system)
- Muse has NO electrodes over motor cortex -- AF7/AF8 are frontal, TP9/TP10 are temporal
- Any classification is picking up indirect, weaker correlates of motor imagery
- Requires extensive per-user training (many sessions of labeled data)
- Real-time performance degrades significantly compared to offline metrics

### Verdict
Motor imagery with Muse is a research curiosity, not a practical control method. If you need left/right commands, use two jaw clenches patterns or blink patterns instead.

---

## 6. SSVEP (Steady-State Visual Evoked Potentials)

### Theory
Staring at a flickering light (e.g., 12Hz) produces a corresponding frequency peak in the EEG. Different flicker frequencies = different commands.

### With Muse specifically
- SSVEP is strongest at occipital electrodes (O1, O2, Oz) -- Muse has none
- Research shows frontal SSVEP detection is possible with ~80% accuracy, but this is with optimized setups
- One study used Emotiv (14 channels including some posterior) and got decent SSVEP -- but Emotiv has better coverage than Muse
- No published study demonstrates reliable SSVEP specifically with Muse's AF7/AF8/TP9/TP10 configuration

### Verdict
SSVEP is theoretically possible but Muse's electrode placement is the worst possible for it. Not recommended.

---

## 7. P300

### Why it doesn't work with Muse
- P300 is maximal at parietal midline (Pz)
- The four optimal P300 electrodes identified in research: PO8, PO7, POz, CPz -- none available on Muse
- While Muse can detect some P300-like ERP components (one validation study found N200 and P300 in visual oddball tasks), the signal is weak and unreliable for BCI control
- Requires many repetitions/averaging to extract signal, making it too slow for practical commands

### Verdict
Not viable for BCI control with Muse.

---

## 8. MQTT + Home Assistant BCI Projects

### What exists

**EEG/MQTT Brain-to-Thing Communication (Academic):**
A published prototype uses EEG signals transmitted via MQTT to control smart home devices for immobilized people. Architecture: EEG sensor -> Bluetooth -> Arduino Mega (MQTT publisher) -> edge IoT devices (MQTT subscribers). Demonstrated opening doors and toggling alarms.

**CruXUCLA/bci-smarthome (GitHub):**
UCLA student project using Muse headset + Google Firebase to control an LED via alpha wave detection. Proof of concept for smart home control via meditation state. Plans mentioned for Phillips Hue and Chromecast integration.

**Home Assistant Community Forum:**
A feature request thread exists for "Control your house with a blink of an eye" discussing OpenBCI + MQTT + Home Assistant integration. OpenBCI's WIFI shield can stream directly to MQTT, which Home Assistant consumes natively.

**OpenBCI + Home Assistant:**
Multiple OpenBCI boards can be integrated with Home Assistant via MQTT. Sensor data streamed to InfluxDB via Home Assistant plugin, visualized in Grafana. This is the most documented path but uses OpenBCI, not Muse.

### What's missing
Nobody has published a complete, working Muse 2 -> MQTT -> Home Assistant pipeline. The pieces exist (muselsl/BrainFlow for Muse data, paho-mqtt for MQTT, Home Assistant MQTT integration), but no turnkey project combines them.

### Practical architecture for Muse + MQTT + HA
```
Muse 2 -> BrainFlow (Python) -> signal processing -> command classifier
    -> paho-mqtt publish to topic (e.g., "bci/command/blink_double")
        -> Home Assistant MQTT automation triggers
            -> toggle lights, lock doors, etc.
```

---

## 9. Simplest Reliable BCI Command for Proof of Concept

**Double eye blink detection -> MQTT -> Home Assistant light toggle**

Why this is the best starting point:
1. **99%+ detection accuracy** demonstrated in published research
2. **Trivial signal processing** -- threshold on raw amplitude, no ML needed
3. **Sub-100ms latency** -- feels instantaneous
4. **No calibration needed** -- blinks are blinks, universal across users
5. **Natural false positive mitigation** -- double-blink within 500ms window filters out natural single blinks
6. **Existing code** -- urish/muse-blink already does detection, just needs MQTT output added

### Second-simplest: jaw clench
Same reliability tier, different muscle group. Can be combined with blink for 2 independent commands immediately.

### Recommended initial command set (4 commands, artifact-based only)
| Pattern | Command | Example |
|---|---|---|
| Double blink | Toggle primary device | Lights on/off |
| Triple blink | Toggle secondary device | Fan on/off |
| Single jaw clench | Cycle through device selection | Select: lights -> fan -> TV -> ... |
| Sustained jaw clench (>1s) | Emergency / all off | Everything off |

This gives you a working BCI remote control with no machine learning, no training data, no calibration, and near-perfect reliability.

---

## Key GitHub Repositories

| Repository | What it does |
|---|---|
| [urish/muse-blink](https://github.com/urish/muse-blink) | Blink detection + Angular demo (Web Bluetooth) |
| [urish/muse-js](https://github.com/urish/muse-js) | Muse 2016 JavaScript library (Web Bluetooth) |
| [alexandrebarachant/muse-lsl](https://github.com/alexandrebarachant/muse-lsl) | Python LSL streaming + neurofeedback examples |
| [CruXUCLA/bci-smarthome](https://github.com/CruXUCLA/bci-smarthome) | Alpha wave -> LED control (Muse + Firebase) |
| [vinayakr99/Muse-MotorImageryClassification](https://github.com/vinayakr99/Muse-MotorImageryClassification) | Motor imagery CNN on Muse 2 data |
| [JodieAsh/Real-Time-EEG-Classification-with-Muse](https://github.com/JodieAsh/Real-Time-EEG-Classification-with-Muse) | Blink/clench/neutral real-time classification |
| [taz-chiles/Muse-BCI](https://github.com/taz-chiles/Muse-BCI) | First-attempt BCI with Muse 2 |
| [NeuroTechX/bci-workshop](https://github.com/NeuroTechX/bci-workshop) | BCI workshop materials (Muse compatible) |
| [dan-pavlov/muse-eeg-lsl-python-tools](https://github.com/dan-pavlov/muse-eeg-lsl-python-tools) | Real-time Muse EEG monitor via LSL |

---

## Key Papers and Articles

- **MED: Muse-based Eye-blink Detection Algorithm (IEEE SPMB 2022)** -- 99.2% blink accuracy on single channel
- **"Building a Bedroom BCI" (Tim de Boer, Medium)** -- Complete Muse 2 motor imagery project walkthrough, 5-part series
- **"Reactive Brain Waves" (Uri Shaked, Medium)** -- RxJS + Angular + Web Bluetooth for Muse
- **"Prototyping Smart Home for Immobilized People: EEG/MQTT-Based Brain-to-Thing Communication"** -- Academic paper on EEG -> MQTT -> smart home
- **"How to Decode Mental States With a Commercial EEG Headband" (Luke Guerdan)** -- Practical neurofeedback with Muse

---

## Sources

- [MED: Muse-based Eye-blink Detection (IEEE)](https://ieeexplore.ieee.org/document/10014708/)
- [MED paper PDF](https://isip.piconepress.com/conferences/ieee_spmb/2022/papers/l01_03.pdf)
- [urish/muse-blink GitHub](https://github.com/urish/muse-blink)
- [CruXUCLA/bci-smarthome GitHub](https://github.com/CruXUCLA/bci-smarthome)
- [Building a Bedroom BCI - Data Collection](https://medium.com/building-a-bedroom-bci/collecting-brain-signal-data-using-the-muse-2-eeg-headset-a2d45ae00455)
- [Building a Bedroom BCI - Real-Time Predictions](https://medium.com/building-a-bedroom-bci/real-time-motor-imagery-predictions-with-a-bedroom-bci-system-8db20fb7c36a)
- [Reactive Brain Waves (Uri Shaked)](https://urish.medium.com/reactive-brain-waves-af07864bb7d4)
- [Muse-MotorImageryClassification GitHub](https://github.com/vinayakr99/Muse-MotorImageryClassification)
- [Real-Time EEG Classification with Muse GitHub](https://github.com/JodieAsh/Real-Time-EEG-Classification-with-Muse)
- [EEG-BMI Paradigms for Muse (Forum)](http://forum.choosemuse.com/t/eeg-bmi-paradigms-to-use-with-the-muse/488)
- [Prototyping Smart Home: EEG/MQTT Brain-to-Thing](http://ric.zntu.edu.ua/article/view/259372)
- [HA Community: Control house with blink](https://community.home-assistant.io/t/control-your-house-with-a-blink-of-an-eye/427353)
- [SSVEP feasibility with consumer EEG (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4245767/)
- [P300 Channel Selection (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4106671/)
- [Low-cost EEG for SSVEP (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S2468067224000610)
- [BCI Smart Home Control (Springer)](https://link.springer.com/chapter/10.1007/978-3-031-42622-3_51)
- [Luke Guerdan - Decode Mental States](https://lukeguerdan.com/blog/2019/muse-neurofeedback/)
- [alexandrebarachant/muse-lsl GitHub](https://github.com/alexandrebarachant/muse-lsl)
- [Muse 2 headband specifications](https://ifelldh.tec.mx/sites/g/files/vgjovo1101/files/Muse_2_Specifications.pdf)
- [Real-Time Home Automation with BCI (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC11505471/)
- [Feasibility of BCI in Smart Home (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4999433/)
