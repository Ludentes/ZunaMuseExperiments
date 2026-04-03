# VTuber Getting Started Guide

**Date:** 2026-04-03  
**Platform:** Linux (Proton), with notes for other platforms where they differ  
**Goal:** Go from zero to a working Live2D + VTube Studio setup with webcam/iPhone, microphone lipsync, OBS, and then add the Muse EEG bridge on top.

---

## Part 0: What We're Building

By the end of this guide you'll have:

- A Live2D avatar animated by face tracking and microphone lipsync in VTube Studio
- The model showing in OBS with a transparent background
- (Optional) Muse 2 EEG signals driving additional parameters

**Software stack:**

| What | Software | Cost |
|------|----------|------|
| Avatar engine | VTube Studio (Steam) | Free (+ $15 DLC to remove watermark) |
| Face tracking on Linux | iPhone (recommended) or OpenSeeFace | Free |
| OBS | OBS Studio | Free |
| EEG plugin (later) | Muse VTuber Bridge | This project |

**Skip if:** You want a 3D VRM avatar — use VSeeFace instead of VTube Studio. VTube Studio is Live2D (2D) only; VRM files will not load.

---

## Part 1: VTube Studio on Linux

### Install

1. Install Steam, enable SteamPlay (Settings → Steam Play → Enable Steam Play for all titles → Proton Experimental)
2. Install VTube Studio from Steam (app ID 1325860) — free
3. Buy the **Artiste DLC** ($15) if you want no watermark on the streaming view. You can skip this until you're ready to go live.

### Proton version

VTS runs under Proton. Proton Experimental usually works. If you see crashes or black screens:

- Install **Proton-GE** (community-patched, better codec support): use ProtonUp-Qt or ProtonPlus
- Right-click VTS in Steam → Properties → Compatibility → Force specific Proton version → select Proton-GE

### What doesn't work under Linux/Proton

**Webcam tracking via DirectShow is broken.** The Mediapipe and NVIDIA trackers are Windows-only. The built-in webcam mode will not work.

Your two tracking options on Linux are:
1. **iPhone (strongly recommended)** — works via WiFi, better quality than webcam anyway
2. **OpenSeeFace** — native Linux Python process, detailed setup in Part 4B

---

## Part 2: Getting a Model

### Start with a free model

Do not commission a custom model until you've used the software for a while. You don't yet know what parameters and features matter to you.

**Best free sources:**

- **Live2D official samples** — high quality, good for testing; check the official Live2D website under "Learn → Sample Data"
- **BOOTH.pm** — largest marketplace, many free models; booth.pm/en, search "free live2d"
- **ShiraLive2D** — shiralive2d.com/live2d-sample-models — free models for practice/demo purposes
- **Kudos.tv** — curated list of 50 free models for VTubers

**What to check before downloading:**

A valid VTube Studio model folder must contain:
- `YourModelName.model3.json` — index file (VTS looks for this)
- `YourModelName.moc3` — compiled model binary
- `YourModelName.physics3.json` — cloth/hair physics (optional but makes it look natural)
- `textures/` or similar folder with `.png` texture files

**License:** check each model's license. Most free models allow non-commercial streaming with credit. Some restrict commercial use. Read before going live.

**Tip:** Download a model that uses standard Live2D parameter IDs (like `ParamAngleX`, `ParamMouthOpen`). Models with non-standard IDs require manual mapping in VTube Studio. The description usually mentions "VTS ready" or "auto-setup compatible" if it uses standard IDs.

### When to buy a model

Once you know what you want, BOOTH.pm is the primary marketplace ($30–$300 for pre-made models). For a custom model, budget $1,000–$3,000+ and find both an illustrator and a Live2D rigger — these are often separate people.

---

## Part 3: What Are Parameters?

A Live2D model is a rigged 2D illustration. The rigger defines **parameters** — named numbers with a range. For example, `ParamAngleX` ranges from -30 to +30 and controls how far the head turns left/right. At runtime, driving the parameter to different values interpolates between the drawn states.

VTube Studio maps tracking data (head pose, eye state, mouth opening) to these parameter values.

### Key standard parameters

| Parameter | What it controls | Typical range |
|-----------|-----------------|---------------|
| `ParamAngleX` | Head yaw (left/right) | -30 to +30 |
| `ParamAngleY` | Head pitch (up/down) | -30 to +30 |
| `ParamAngleZ` | Head roll (tilt) | -30 to +30 |
| `ParamEyeLOpen` | Left eye open/close | 0 to 1 |
| `ParamEyeROpen` | Right eye open/close | 0 to 1 |
| `ParamEyeBallX` | Eye gaze left/right | -1 to +1 |
| `ParamEyeBallY` | Eye gaze up/down | -1 to +1 |
| `ParamBrowLY` | Left brow height | -1 to +1 |
| `ParamBrowRY` | Right brow height | -1 to +1 |
| `ParamMouthOpenY` | Mouth open amount | 0 to 1 |
| `ParamMouthForm` | Smile/frown shape | -1 to +1 |

These are the **model's** parameters (Live2D output). VTube Studio has its own internal **tracking parameters** (`FaceAngleX`, `MouthOpen`, `EyeOpenLeft`, etc.) that feed into them. The mapping is configured in **Model Settings → VTS Parameter Setup**.

### Auto-Setup

When you first load a model, click **Auto-Setup**. VTS scans the model for parameters with standard Live2D IDs and configures the tracking mappings automatically. This works if the model follows standard naming; if it doesn't, you'll need to map parameters manually.

You can always open **Model Settings → VTS Parameter Setup** to see or adjust these mappings. Each row shows: input tracking parameter → output model parameter, with an adjustable range.

---

## Part 4A: Face Tracking via iPhone (Recommended on Linux)

iPhone tracking uses the **TrueDepth** camera — an infrared dot projector that works in any lighting and produces fundamentally better data than webcam-based optical tracking.

### Which iPhones work

Any iPhone with **Face ID** has TrueDepth: iPhone X through iPhone 16 series. **iPhone SE does not** (uses Touch ID, no TrueDepth).

Practical minimum: iPhone XS or XR (A12 chip). The iPhone X (A11) works but runs warm during long sessions.

**Should you use it for testing?** Yes, strongly. On Linux it is simpler to set up than a webcam and produces better results. If you have a qualifying iPhone, do this instead of the OpenSeeFace path.

### Setup

1. Install **VTube Studio** from the App Store on your iPhone (free)
2. Connect phone and PC to the **same WiFi network** (5GHz preferred for lower latency)
3. Open VTube Studio on iPhone — it will show an IP address on screen
4. Open VTS on PC → Tracking settings → select iPhone as tracker
5. Enter the iPhone's IP address (or use auto-discovery)
6. Calibrate once: look straight at the camera with a neutral face, click Calibrate

**If tracking looks wrong:** re-calibrate. This is always the first fix.

### What iPhone tracking adds

- More precise blink/wink detection
- Individual eyebrow tracking  
- Cheek puffs (if the model supports `ParamCheek`)
- Better eye gaze tracking
- Works in the dark

### What about VBridger?

VBridger (~$10 on Steam) enhances ARKit integration but is not needed for a first setup. Use the free built-in iOS tracking first.

---

## Part 4B: Face Tracking via OpenSeeFace (Webcam, Linux)

Use this if you don't have a qualifying iPhone. This is more work to set up but produces equivalent results to Windows webcam tracking.

**Architecture:** `webcam → OpenSeeFace (native Linux) → UDP:11573 → VTube Studio (inside Proton)`

### Step 1: Configure VTS to accept external tracking

Navigate to:
```
~/.steam/steam/steamapps/common/VTube Studio/VTube Studio_Data/StreamingAssets/
```

Create `ip.txt` with exactly this content:
```
ip=0.0.0.0
port=11573
```

This tells VTS to receive tracking data from OpenSeeFace over UDP.

### Step 2: Install dependencies

Ubuntu/Debian:
```bash
sudo apt-get install v4l-utils python3 python3-pip python3-virtualenv git
```

Arch:
```bash
sudo pacman -S v4l-utils python python-pip python-virtualenv git
```

### Step 3: Set up OpenSeeFace

```bash
mkdir -p ~/opt/openseeface
cd ~/opt/openseeface
git clone https://github.com/emilianavt/OpenSeeFace
cd OpenSeeFace
virtualenv -p python3 env
source env/bin/activate
pip3 install onnxruntime opencv-python pillow numpy
```

### Step 4: Find your webcam

```bash
v4l2-ctl --list-devices
```

Note the `/dev/videoN` number (usually 0).

### Step 5: Create a start script

Save as `~/opt/openseeface/start.sh`:
```bash
#!/bin/bash
cd ~/opt/openseeface/OpenSeeFace
source env/bin/activate
python facetracker.py -W 1280 -H 720 --discard-after 0 --scan-every 0 --no-3d-adapt 1 --max-feature-updates 900 -c 0
```

Make it executable: `chmod +x ~/opt/openseeface/start.sh`

Replace `-c 0` with your camera index if needed.

### Step 6: Run

1. Start OpenSeeFace: `~/opt/openseeface/start.sh`
2. Launch VTube Studio via Steam
3. In VTS tracking settings, enable the webcam tracker — VTS will receive data from OpenSeeFace

**Always start OpenSeeFace before VTS.** VTS polls the UDP port on startup.

### Webcam recommendations for Linux

Use a **USB UVC webcam** (plug-and-play, no drivers): Logitech C920 or C922 are the most reliable choices. Any modern webcam at 720p or 1080p will work.

### Lighting matters more than hardware

Put a soft light **in front of you** (ring light, monitor light). Backlit faces (window behind you) cause tracking failures. A $20 ring light improves tracking more than upgrading to a better webcam.

---

## Part 5: Microphone Lipsync

Lipsync is separate from face tracking — it reads your microphone and animates the mouth independently.

### Setup

1. In VTube Studio, go to **Settings** (gear icon)
2. Select your microphone from the dropdown
3. Enable **"Use microphone"**
4. Set **Lipsync Type** to **Advanced**
5. Click each vowel calibration button (A, I, U, E, O) and speak the vowel clearly when prompted
6. Run **Auto-Setup** on the model if you haven't already — this maps `VoiceVolume` and `VoiceFrequency` to mouth parameters automatically

### Advanced lipsync

Advanced lipsync detects Japanese vowel phonemes and drives the model's A/I/U/E/O mouth shapes (if the model has them rigged). It sounds better than basic volume-based lipsync.

The parameter `VoiceVolumePlusMouthOpen` blends microphone and face-tracked mouth data — useful if you also have facial tracking driving the mouth.

### Linux note

Microphone audio goes through Wine's audio layer. It generally works. If the mic isn't detected, check that PipeWire or PulseAudio is running and that the correct audio device is selected.

---

## Part 6: OBS Integration

### Transparent background

1. In VTS, open **Background Settings**
2. Set the background to **transparent** (checkered pattern icon, or set to pure green if your OBS setup uses chroma key)
3. Enable **"Use transparent background"** in the VTS streaming mode settings

### Capture in OBS

Add a **Game Capture** source in OBS pointing to VTube Studio:
- Source type: Game Capture
- Mode: Capture specific window → select VTube Studio
- Enable: **Allow Transparency** (required for transparent background to work)

Alternatively, use **Window Capture** — but Game Capture handles transparency more reliably.

### Virtual camera

VTS has a built-in virtual camera (Settings → Virtual Camera) for use in video calls (Discord, Zoom). This is separate from OBS output.

---

## Part 7: Setting Up Expressions and Hotkeys

Tracking animates the base head/eye/mouth movements. **Expressions** overlay additional states (happy, angry, surprised) on top of tracking data.

### Create expression files

In VTS, go to **Model Settings → Expressions**. You can create expression presets that set multiple parameters to specific values (e.g., raised brows + wide eyes = surprised). The model may come with pre-made expressions; load them here.

### Hotkeys

Go to **Settings → Hotkeys**. Assign keyboard shortcuts or Stream Deck buttons to:
- Toggle expressions
- Play animations
- Toggle items (props attached to the model)

Setting up 3–5 reaction expressions (happy, annoyed, surprised, embarrassed) makes streaming significantly more expressive and interactive.

---

## Part 8: VTS Visual Effects

VTube Studio has a built-in Visual Effects system (Windows/macOS only) that can be driven by any parameter — including the Muse custom parameters. Effects are applied inside VTS before output to OBS via Spout2 or virtual camera.

### Enable Visual Effects

Go to **Settings → Visual Effects**. The panel shows all available effect slots with on/off toggles and parameter bindings.

Built-in effects include: bloom/glow, lens distortion, particles, color overlay, and lighting effects. Each effect exposes one or more intensity knobs that can be bound to a tracking parameter.

### Binding a parameter to an effect

For each effect in the Visual Effects panel:
1. Enable the effect
2. Click the parameter binding slot next to the intensity control
3. Select the parameter to drive it — any tracking parameter, expression parameter, or custom injected parameter works

### Useful mappings for Muse signals

| Effect | Parameter | Result |
|--------|-----------|--------|
| Bloom/glow intensity | `MuseRelaxation` | Soft glow builds as you relax |
| Color overlay opacity | `MuseFocus` | Subtle tint intensifies with concentration |
| Particle emission rate | `MuseClench` | Burst on jaw clench |
| Lens distortion | `MuseRelaxation` inverted | Sharpens when alert, softens when relaxed |

Because these are driven by injected parameters, they respond to live Muse data with no hotkey needed.

### Linux note

Visual Effects require the Windows/macOS VTS build. Under Linux/Proton, the Visual Effects panel may not appear or effects may not render. Test first — if unavailable, use the OBS color-correction filter approach instead (see `docs/research/2026-04-03-biometric-streaming-overlays.md`).

---

## Part 9: Adding Muse EEG on Top

Once your basic VTuber setup is working, you can add the Muse 2 EEG bridge.

### What it adds

The Muse VTuber Bridge sends additional parameters to VTube Studio that face tracking can't provide:

| Signal | What it does |
|--------|-------------|
| `MuseClench` | Jaw clench (EMG) → anger/intensity expression |
| `MuseFocus` | Concentration level → subtle brow/eye changes |
| `MuseRelaxation` | Relaxation level → calm expression ambient |
| `MuseBlink` | EEG-detected blink animation (can replace camera eye tracking) |
| `FaceAngleX/Y/Z` | Head pose from IMU (can replace camera head tracking) |
| `EyeOpenLeft/Right` | Blink animation via IMU (can replace camera eyes) |

### Setup

See `docs/muse-vtuber-vts-setup-guide.md` for the complete Muse VTuber Bridge setup walkthrough, including:
- How to connect the plugin to VTS (WebSocket auth)
- How to bind parameters in VTS Model Settings
- How to set Pose and Eye weight sliders (blend Muse vs. camera)
- Sensitivity controls for head tracking

### Recommended config when using iPhone + Muse together

- iPhone tracks: face pose, eyes, mouth, brows
- Muse tracks: jaw clench expression, focus/relax ambient, (optionally) blinks

Set the Pose slider to 0.0 and Eye slider to 0.0 (camera/iPhone wins for head tracking and eyes). The Muse custom parameters (`MuseClench`, `MuseFocus`, `MuseRelaxation`) run as overlays — they don't conflict with iPhone tracking because they go to different model parameters.

---

## Quick Reference: Files and Paths

Steam via Flatpak (this machine):
```
~/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/VTube Studio/VTube Studio_Data/StreamingAssets/
```

Native Steam install:
```
~/.steam/steam/steamapps/common/VTube Studio/VTube Studio_Data/StreamingAssets/
```

| What | Relative to StreamingAssets/ |
|------|------------------------------|
| VTS Live2D models folder | `Live2DModels/` |
| VTS OpenSeeFace config | `ip.txt` |

**Bundled sample models** (already in `Live2DModels/`, no download needed):

| Model | Quality | Notes |
|-------|---------|-------|
| `hiyori_vts` | ✓ Best | Physics, full params — use this for testing |
| `akari_vts` | ✓ Good | Expressions folder pre-configured |
| `hijiki_vts` | OK | Simple, no physics |
| `tororo_vts` | OK | Simple, no physics |
| `wanko_vts` | OK | Simple, no physics |

| What | Path |
|------|------|
| Muse VTuber auth token | `~/.config/muse-vtuber/vts_token.txt` |
| VTS OpenSeeFace config | See StreamingAssets path above + `ip.txt` |
| Muse VTuber auth token | `~/.config/muse-vtuber/vts_token.txt` |
| Setup UI (when backend is running) | `http://localhost:5173` |

---

## Troubleshooting

**Model doesn't appear in VTS:**
- Copy the whole model folder (not just the `.model3.json`) into `Live2DModels/`
- Restart VTS — it must scan the folder fresh
- Verify the folder contains a `.model3.json` file at the root (not in a subfolder)

**Tracking looks wrong / avatar tilts:**
- Recalibrate: look straight at camera with neutral face, click Calibrate in VTS
- On iPhone: re-pair if the app was restarted

**Mouth doesn't move:**
- Check that a microphone is selected and enabled in VTS settings
- Run Auto-Setup again after changing microphone selection
- Verify `ParamMouthOpenY` is mapped in Model Settings

**OpenSeeFace not connecting:**
- Verify `ip.txt` exists at the exact path with exactly `ip=0.0.0.0` and `port=11573`
- Start OpenSeeFace before VTS
- Check that the Python venv is activated before running `facetracker.py`

**Avatar has watermark:**
- This is the free version. Buy the Artiste DLC ($15) on Steam to remove it.
