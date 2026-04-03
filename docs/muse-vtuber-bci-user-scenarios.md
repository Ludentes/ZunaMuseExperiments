# Muse VTuber Bridge — BCI User Scenarios

**Date:** 2026-04-03
**Status:** Reference document — update as new signals are added

This document describes reference user scenarios for the Muse VTuber Bridge. It serves as the product definition for what the BCI layer does, who it's for, and how reliable each capability is. Use it to evaluate feature priorities and communicate the value proposition.

---

## Available BCI Signals

### Discrete commands (reliable, intentional)

| Signal | Event | Reliability | Latency | Status |
|--------|-------|-------------|---------|--------|
| Single blink | `single_blink` | 99%+ | <100ms | Needs BlinkDetector upgrade (parent has it) |
| Double blink | `double_blink` | 99%+ | ~500ms window | Needs BlinkDetector upgrade |
| Jaw clench | `jaw_clench` | 95%+ | <200ms | ✓ Implemented |
| Head nod (yes) | `nod_yes` | 100% TP / 0% FP (training) | <100ms | Needs port from parent |
| Head shake (no) | `nod_no` | 100% TP / 0% FP (training) | <100ms | Needs port from parent |

Thresholds for nod/shake: gyro_pitch > 40 deg/s (nod), gyro_yaw > 100 deg/s (shake). Calibrated on 20 nod + 20 shake + 10 still recordings.

### Continuous signals (ambient/mood)

| Signal | VTS Param | Reliability | Lag | Notes |
|--------|-----------|-------------|-----|-------|
| Focus/concentration | `MuseFocus` | 70–80%, ~38% non-responders | 2–5s | theta/beta ratio, unsigned 0–1 |
| Relaxation | `MuseRelaxation` | 70–80%, ~38% non-responders | 2–5s | alpha power, unsigned 0–1 |
| Head pose | `FaceAngleX/Y/Z` | Mediocre yaw range (±10–15°) | ~100ms | IMU Madgwick filter, yaw decays without magnetometer |

### Physiological (not yet implemented)

| Signal | VTS Param | Reliability | Notes |
|--------|-----------|-------------|-------|
| Heartbeat pulse | `MuseHeartbeat` | Moderate (seated) | PPG on ANCILLARY_PRESET, needs pipeline |
| Heart rate (BPM) | `MuseHeartRate` | ±5–15 BPM error | 16s warmup, fails during movement |

---

## Scenario A: Camera-Free VTuber

**Who:** User without webcam, or who prefers not to use one.

**Setup:**
- Pose weight = 1.0 → Muse IMU drives head orientation
- Eye weight = 1.0 → Muse blink animation replaces camera eye tracking
- All other EEG signals active

**What they get:**

| Gesture | Avatar reaction |
|---------|----------------|
| Single blink | Eye close/open animation (via EyeOpenLeft/Right) |
| Double blink | Bind to surprise or sparkle expression |
| Jaw clench | Anger / determination expression |
| Head nod | Affirmative bounce / "yes!" emote |
| Head shake | Dismissive / "nope" emote |
| MuseFocus | Concentration glow or focused expression (ambient) |
| MuseRelaxation | Soft/calm expression (ambient) |
| MuseHeartbeat | Subtle chest pulse sync |

**Honest caveats:**
- IMU yaw range is limited (~±10–15° raw, 4x scale applied). Serviceable but visibly worse than camera.
- ~38% of users will not see meaningful Focus/Relaxation response.
- Heartbeat requires PPG pipeline (not yet built).

---

## Scenario B: Camera VTuber + EEG Overlay

**Who:** VTuber already using VTS with webcam. Wants to add signals that camera can't provide.

**Setup:**
- Pose weight = 0.0 → camera drives head pose entirely
- Eye weight = 0.0 (camera drives eyes) OR 1.0 (Muse drives blink animation — choose based on preference)
- EEG signals active as overlay

**What they get that camera can't provide:**

| Signal | Use |
|--------|-----|
| Double blink | Second intentional command, distinguishable from natural blinks |
| Jaw clench | On-demand expression trigger — camera would show a grimace but avatar shows a stylised "grr" |
| Head nod / shake | Reaction animations triggered by intentional gestures, camera still drives face |
| MuseFocus | Concentration-linked expression or glow — camera can't read mental state |
| MuseRelaxation | Calm/ambient expression changes |
| MuseHeartbeat | Live heartbeat visible to viewers — popular for horror gaming streams |

**Honest caveats:**
- Nod and head shake can false-positive during animated conversation. Calibrated thresholds reduce this but don't eliminate it.
- Focus/Relax only useful for ~62% of users.

---

## Scenario C: Ambient / Meditation VTuber

**Who:** Streamer who wants passive mental state changes during content (meditation streams, lo-fi, chatting).

**Setup:**
- Camera or IMU for face/head (either works)
- EEG continuous signals as primary driver

**What they get:**
- MuseRelaxation + MuseFocus together approximate an arousal signal:
  - Low HR + high Relaxation = calm → avatar expression softens
  - Low Relaxation + high Focus = active/alert → avatar expression sharpens
- Works best bound to subtle parameters (eye openness, eyebrow position) not extreme expressions

**Honest caveats:**
- Works only for neurofeedback responders (~62%).
- 2–5s lag. Reads as "ambient mood", not instant reaction — set expectations accordingly.
- Not suitable for fast-paced gaming content.

---

## Scenario D: Heartbeat VTuber

**Who:** Streamer who wants physiology visible — horror gaming, reaction content, "mind reading" streams.

**Setup:**
- PPG pipeline enabled (requires implementation)
- Camera or IMU for face/head
- `MuseHeartbeat` → chest/body pulse parameter
- `MuseHeartRate` (normalized) → color glow or overlay

**What they get:**
- Avatar chest visibly pulses to actual heartbeat (~1/second at rest)
- Heart rate elevation on scary moments drives expression shift
- Works with existing heart rate stream overlays as a companion

**Honest caveats:**
- PPG not yet implemented — requires ANCILLARY_PRESET polling + beat detector.
- Motion artifact: PPG fails during active movement. Best for seated content.
- 16s warmup before heart rate is available.

---

## Scenario E: Expressive Gesture Control

**Who:** Any VTuber who wants intentional, hands-free avatar reactions beyond facial expression.

**Command vocabulary:**

| Gesture | Suggested binding |
|---------|------------------|
| Single blink | Natural eye animation |
| Double blink | Surprise / sparkle expression |
| Jaw clench | Anger / intensity expression |
| Head nod | Happy bounce / "yes!" emote |
| Head shake | Smug dismiss / "nope" emote |

Five distinct intentional commands with no hands required. This is genuinely unique — no camera-only setup provides discrete intentional non-facial commands.

**Honest caveats:**
- Double-blink and nod/shake not yet ported to muse-vtuber (exist in parent project).
- Natural conversation head movements may occasionally trigger nod/shake at lower intensities. Thresholds set conservatively.

---

## What VTube Studio Can Do With These Signals

### Continuous parameters (MuseFocus, MuseRelaxation, FaceAngle)
Bind directly to Live2D model parameters in Model Settings → VTS Parameter Setup. Set input/output range mapping. Works out of the box.

### Pulse parameters (MuseBlink, MuseClench, MuseNod, MuseShake)
These go 0→1→0 briefly. VTS has no built-in threshold trigger. Two practical approaches:
1. **Bind to Live2D parameter** — the model reacts when the parameter hits 1.0, provided the Cubism model has animation curves set up at that value.
2. **External automation** (Streamer.bot, Mix It Up) — watches parameter value via VTS API, triggers VTS hotkeys when threshold crossed.

A future improvement: our plugin could call the VTS `TriggerHotkey` API directly when a pulse event fires, eliminating the need for external automation.

---

## Open Feature Gaps

| Gap | Impact | Effort |
|----|--------|--------|
| Port NodDetector | Adds 2 new commands | Low — copy from parent |
| Upgrade BlinkDetector (single/double) | Adds double-blink command | Low — copy from parent |
| PPG heartbeat pipeline | Enables Scenario D | Medium |
| Plugin-side hotkey triggering | Eliminates Streamer.bot dependency for pulse params | Medium |
| Sustained clench (held state) | Held expression possible | Low — extend ClenchDetector |
| Signed Focus/Relax | Direction above/below baseline | Low — expose from FocusRelaxStage |
