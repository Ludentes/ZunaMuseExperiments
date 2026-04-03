# Muse VTuber Bridge — VTube Studio Setup Guide

**Date:** 2026-04-03
**Audience:** VTubers setting up the Muse VTuber Bridge with VTube Studio for the first time.

This guide explains how to connect the Muse VTuber Bridge to VTube Studio and how to actually use the BCI parameters to animate your avatar.

---

## Prerequisites

- VTube Studio installed and running (Steam version recommended on PC; iOS works too)
- VTS plugin API enabled: **Settings → General → Start API** (green toggle)
- Muse VTuber Bridge backend running: `uv run muse-vtuber --mac XX:XX:XX:XX:XX:XX`
- A Live2D model loaded in VTS

---

## Step 1: Connect the Plugin

When you start the backend, it automatically connects to VTube Studio on port 8001.

The **first time** you run it, VTube Studio shows a popup:

> *"Plugin 'muse-vtuber' by Muse VTuber Bridge wants to connect. Allow?"*

Click **Allow**. The token is saved to `~/.config/muse-vtuber/vts_token.txt`. Future connections are automatic — no popup.

To verify it worked: in VTS, go to **Settings → Plugins**. You should see "muse-vtuber" listed as connected.

---

## Step 2: Understand What Gets Sent

The plugin creates these parameters in VTube Studio automatically:

### EEG parameters (always active)

| Parameter | Range | What it represents |
|-----------|-------|-------------------|
| `MuseBlink` | 0 / 1 pulse | Blink detected — brief spike to 1, returns to 0 |
| `MuseClench` | 0 / 1 pulse | Jaw clench detected — brief spike to 1 |
| `MuseFocus` | 0–1 continuous | Concentration level (theta/beta ratio) |
| `MuseRelaxation` | 0–1 continuous | Relaxation level (alpha power) |

### Head tracking parameters (active when `--head-tracking` mode)

| Parameter | Range | What it represents |
|-----------|-------|-------------------|
| `FaceAngleX` | ±30° | Yaw (left/right) |
| `FaceAngleY` | ±30° | Pitch (up/down) |
| `FaceAngleZ` | ±30° | Roll (tilt) |
| `EyeOpenLeft` | 0–1 | Eye open state (0 = closed, 1 = open) — blink animation |
| `EyeOpenRight` | 0–1 | Same |

**Important:** `FaceAngleX/Y/Z` and `EyeOpenLeft/Right` are **built-in VTS parameters** that camera tracking also drives. If you have camera tracking enabled, set the Head Override sliders in the Setup UI to control the blend (1.0 = Muse overrides camera, 0.0 = camera wins).

---

## Step 3: Using Continuous Parameters (MuseFocus, MuseRelaxation)

These are the easiest to use. They smoothly drive a Live2D model parameter between 0 and 1.

**Steps:**

1. In VTS, open **Model Settings** (gear icon, third tab — only visible when a model is loaded)
2. Find the **VTS Parameter Setup** section
3. Locate the parameter you want to drive (e.g., `ParamEyeBrowLY` for eyebrow height)
4. Set the **Input** to `MuseFocus`
5. Set the **Input Range** to `0 → 1`
6. Set the **Output Range** to match what your model expects (check your model's parameter list — e.g., `-10 → 10`)
7. A red dot shows the current live value — watch it respond as you focus/relax

**Suggested bindings for continuous params:**

| Muse parameter | Suggested Live2D target | Effect |
|---------------|------------------------|--------|
| `MuseFocus` | `ParamEyeBrowLY` (raise/lower brow) | Focused look — eyebrows lower slightly |
| `MuseFocus` | `ParamEyeLOpen` / `ParamEyeROpen` | Eyes narrow with concentration |
| `MuseRelaxation` | `ParamEyeBrowLY` | Soft brows when relaxed |
| `MuseRelaxation` | Custom glow/aura parameter (if model has one) | Calm aura effect |

**Tips:**
- Add smoothing in the VTS mapping UI to prevent jitter — the default slider is usually fine
- Focus and Relaxation have 2–5 second lag — they read as "ambient mood", not instant reaction
- ~38% of people are neurofeedback non-responders and won't see much signal here — try it for a session before committing to this as a core feature

---

## Step 4: Using Pulse Parameters (MuseBlink, MuseClench)

Pulse parameters briefly spike to 1.0 then return to 0. VTube Studio has no built-in "trigger on threshold" logic, so there are two approaches.

### Option A: Live2D parameter binding (simplest, needs model support)

Bind the pulse parameter directly to a Live2D parameter, the same way as Step 3. When `MuseClench` hits 1.0, the model parameter snaps to its 1.0 pose, then snaps back.

This works well if your Live2D model has expression animations defined at that parameter value in Cubism Editor. Most purchased models have some expression curves set up — experiment with which parameters react interestingly.

**Try binding `MuseClench` to:**
- A "blush" or "excited" parameter
- `ParamEyeBrowLAngle` (angry eyebrow angle)
- Any custom expression parameter your model includes

### Option B: Expression hotkeys via Streamer.bot (more flexible)

For triggering full VTS expressions (preset expression files like "angry.exp3.json"):

1. Install **Streamer.bot** (free, streamers use it widely)
2. Add a VTube Studio integration action in Streamer.bot
3. Create a trigger: "When VTS parameter `MuseClench` > 0.5"
4. Action: Trigger VTS hotkey → select your angry/intense expression

This lets you trigger any expression or hotkey from any BCI event, without needing to edit your Live2D model.

### Option C: Hotkey triggering via our plugin (future)

A planned improvement: the plugin will call the VTS `TriggerHotkey` API directly when a BCI event fires, eliminating the need for Streamer.bot. Not implemented yet.

---

## Step 5: Head Tracking Blend (Head Override)

The Setup UI (open in browser at `http://localhost:5173`) has a **Head Override** section:

- **Pose slider** (0–1): Controls how much the Muse IMU drives `FaceAngleX/Y/Z`
  - 1.0 = Muse fully controls head angle (camera tracking suppressed for those params)
  - 0.0 = Camera/VTS tracking controls head angle (Muse data ignored)
  - 0.5 = 50/50 blend

- **Eyes slider** (0–1): Controls `EyeOpenLeft/Right` blend
  - 1.0 = Muse controls eye open/close animation (your physical blinks drive the avatar)
  - 0.0 = Camera tracking controls eye open/close

**Recommended starting points:**
- If you have **no webcam**: set both to 1.0
- If you have a **webcam and want camera to handle everything**: set both to 0.0
- If you want **camera for face but Muse for blink animation**: set Eyes to 1.0, Pose to 0.0

---

## Step 6: Sensitivity Controls

In the Setup UI, the **Sensitivity** section lets you scale head movement amplification:

- **Yaw**: Default 4.0x — the Muse IMU has limited yaw range due to the missing magnetometer. 4x maps the real ~±10° to the avatar's ±30° range.
- **Pitch**: Default 1.5x
- **Roll**: Default 1.0x

Adjust until head movements feel natural on your avatar.

---

## Step 7: Lip Sync Co-existence

VTube Studio's **Advanced Lipsync** (microphone MFCC) handles vowel animation — A/I/U/E/O confidence scores plus volume and frequency. Our plugin works **alongside** it without conflict, as long as you follow one rule:

**Do not bind any Muse parameter to `MouthOpen`, `VoiceA`–`VoiceO`, or `VoiceVolume`.** VTS owns the mouth during speech. Our signals go to separate parameters (expressions, eyebrows, glow effects).

### What Muse adds that lipsync can't

The one genuine gap in VTS lipsync — including iPhone ARKit — is **jaw clench**. The `Jaw Open` ARKit blendshape detects jaw *separation* (opening); it cannot distinguish resting-closed from actively-clenched. EEG EMG artifact from temporal muscles is the only signal that fires positively on clench. `MuseClench` fills this gap directly.

**Do not bind `MuseClench` to `MouthOpen`** — that conflicts with VTS's lipsync. Instead bind it to an intensity/anger expression parameter.

### MuseSpeaking (planned)

A future parameter `MuseSpeaking` will expose the existing EEG speech detector as a VTS parameter (0 = silent, 1 = speaking). This is useful when:
- Microphone lipsync is disabled but you still want the model's mouth to respond to speech
- You want to gate other EEG signals (suppress Focus/Relax changes while speaking)

Until then: if you use VTS Advanced Lipsync, `VoiceSilence` already handles mouth mode switching automatically.

---

## Complete parameter reference

| VTS Parameter | Type | Source | What to bind it to |
|--------------|------|--------|-------------------|
| `MuseBlink` | 0/1 pulse | Blink event | Eye twitch, sparkle parameter |
| `MuseClench` | 0/1 pulse | Jaw clench | Anger/intensity expression |
| `MuseFocus` | 0–1 continuous | theta/beta EEG | Brow tension, eye narrowing |
| `MuseRelaxation` | 0–1 continuous | alpha EEG | Soft expression, calm glow |
| `FaceAngleX` | ±30° | IMU yaw | Head left/right (built-in) |
| `FaceAngleY` | ±30° | IMU pitch | Head up/down (built-in) |
| `FaceAngleZ` | ±30° | IMU roll | Head tilt (built-in) |
| `EyeOpenLeft` | 0–1 | Blink animation | Eye open/close (built-in) |
| `EyeOpenRight` | 0–1 | Blink animation | Eye open/close (built-in) |

---

## Troubleshooting

**Plugin not connecting:**
- Check VTS has API enabled: Settings → General → Start API (must be green)
- Default port is 8001. If you changed it, pass `--vts-port XXXX` to the backend
- Delete `~/.config/muse-vtuber/vts_token.txt` and restart to force a fresh auth popup

**Parameters not appearing in VTS:**
- They're created on connection. If the plugin connected, they exist. Search for "Muse" in the VTS parameter list.
- If you revoked plugin access, parameters may show in red. Re-connect and they'll turn active again.

**Head tracking feels sluggish:**
- Increase Sensitivity sliders in the Setup UI
- The IMU needs ~5 seconds to settle after putting the headband on — wait for the "Settle" overlay to clear

**MuseFocus / MuseRelaxation not responding:**
- Ensure signal quality is good (check the Signal Quality panel in Setup UI — all green)
- Wait ~30 seconds after connecting for the signal to stabilize
- Some people (~38%) are neurofeedback non-responders — if after a few sessions there's no signal, this may apply to you

**Blinks not detecting:**
- Electrode fit is critical: AF7 and AF8 (forehead) must have good contact
- Check Signal Quality in Setup UI — amplitude_fit should be "good" or "ok"
- Blink detection is suppressed during speech — wait until you finish speaking

---

## Quick setup checklist

- [ ] VTS API enabled (Settings → General → Start API = green)
- [ ] Backend running (`uv run muse-vtuber --mac XX:XX:XX:XX:XX:XX`)
- [ ] Auth popup approved in VTS
- [ ] Model loaded in VTS
- [ ] At least one parameter bound in Model Settings → VTS Parameter Setup
- [ ] Setup UI open in browser to monitor signal quality and adjust sensitivity
