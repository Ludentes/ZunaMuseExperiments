# VTuber Zero-to-Setup: Research Notes

**Date:** 2026-04-03  
**Purpose:** Raw research for a first-time setup guide targeting a Linux developer going from zero to a working Live2D + VTube Studio setup. Later integration point: Muse 2 EEG via custom plugin.  
**Scope:** VTube Studio on Linux, Live2D models (free + paid), webcam tracking, microphone lipsync, iPhone ARKit upgrade path.

---

## 1. The Landscape: What Software Does What

### VTube Studio (VTS)

The dominant choice for Live2D model animation [1][2]. It is a Steam application (app ID 1325860) built by a single developer (DenchiSoft, Karlsruhe, Germany). Free base app with a $15 "Artiste" DLC that removes the watermark on the desktop streaming mode [2]. It is explicitly a **Live2D-only** application — it will not load VRM/VRoid 3D models [1].

Tracking hierarchy per official docs: **iOS > Webcam > Android** [3].

Runs on Windows, macOS, iOS, Android. No official Linux build. Linux is via Proton (see section 6).

### VSeeFace

Free, Windows-only (runs on Mono). The go-to for **VRM/3D models**. Uses OpenSeeFace internally for webcam tracking (same backend as VTS webcam mode). VTS iOS tracking data can be piped into VSeeFace for better quality on 3D avatars [4]. Not relevant for a Live2D + VTS workflow but worth knowing if the user ever wants 3D.

### Warudo

Scene-based, more like a full production environment. Supports VMC protocol, custom scenes, physics, streaming overlays. More complex than VTS. Probably overkill for a first setup. Supports VRM models [4].

### The verdict for this use case

**Use VTube Studio.** It is the standard for Live2D streaming, has the largest plugin ecosystem (important for EEG integration later), runs acceptably on Linux via Proton + OpenSeeFace, and has the best iOS ARKit integration when you want to upgrade. VSeeFace is only relevant if the user goes 3D.

---

## 2. Where to Get Free Live2D Models

### Official Live2D sample models

The Live2D company provides several free sample models. These are high-quality reference models intended for use with their software and SDK. Available at `https://www.live2d.com/en/learn/sample/` [5]. Models include well-known samples like "Hiyori Momose", "Mao", "Natori Sana", and others. License: free for non-commercial use within Live2D-compatible software; check each model's individual license.

### BOOTH.pm

Japanese-operated marketplace (`https://booth.pm`) — the single largest source of VTuber assets [6][7]. Search terms: "free live2d", "フリーLive2D". Many creators post free models to build their portfolio. Navigation is mostly in Japanese; use the English version at `https://booth.pm/en`. Even "free" listings often require a BOOTH account to download. Example: half-body models specifically built for VTube Studio can be found here at `https://booth.pm/en/items/4711410` [6].

### ShiraLive2D

`https://shiralive2d.com/live2d-sample-models/` — free models specifically for practice, study, and testing in VTube Studio. Explicitly states models are for demonstration purposes [7].

### StreamSkins

`https://streamskins.net/free-vtuber-model/` — professionally designed free models, some with matching stream overlays and PSD files [7].

### live3d.io

`https://live3d.io/vtuber-model` — claims 100+ free VTuber model downloads [7].

### Kudos.tv list

`https://kudos.tv/blogs/stream-blog/free-vtuber-models` — curated "top 50 free VTuber models" list as of 2025 [7].

### VTubing.info assets page

`https://vtubing.info/docs/free-vtuber-models-assets/free-live2d-assets/` — aggregated list of free Live2D asset sources [7].

### DeviantArt

StreamSkins also publishes on DeviantArt: `https://www.deviantart.com/streamskins/art/Free-Vtuber-Model-Live-2D-Pack-1188965821` [7].

### Twitter / X hashtags

`#フリー素材` ("free materials") surfaces free overlays, backgrounds, and accessories for VTuber rigs. Not full models but supplementary assets [7].

### What to look for in a free model

- Must include a `.model3.json` file (the index file VTS looks for)
- Must include a `.moc3` file (the compiled model binary)
- Should include `physics3.json` (cloth/hair physics; tracking works without it but looks stiff)
- Textures folder with `.png` files
- License: check for streaming permission, commercial use restrictions, credit requirements
- Parameter IDs: a model that uses standard Live2D parameter names (e.g., `ParamAngleX`, `ParamMouthOpen`) will auto-configure in VTS; non-standard IDs require manual mapping [8]

---

## 3. Where to Get Paid Live2D Models

### BOOTH.pm (pre-made paid models)

The dominant marketplace. Pre-made models range from approximately $30 to $600+, with most decent quality ones in the $50–$300 range [9]. Search `https://booth.pm/en/search/live2d`. Many models come rigged for VTube Studio with parameter IDs already matching VTS auto-setup.

### Etsy and Gumroad

Western-facing alternatives. Prices comparable to BOOTH for pre-made models.

### Custom commissions — price breakdown [9][10]

Commissioning a completely custom model involves two separate jobs: **artwork** and **rigging**.

- Art only (2D illustration): $250–$700 for entry-level artists, $500–$2000+ for established ones
- Rigging only (converting art to Live2D): $200–$750 entry-level, $500–$1500+ professional
- Combined entry-level package: ~$450–$1450 total
- Mid-range custom: $1600–$3300
- Premium/professional: $3500–$7500
- Agency-grade with complex rigs: $15,000+

Finding riggers: BOOTH profiles, Twitter/X VTuber community, VTuber subreddit, dedicated Discord servers like "The VTuber Hangout". Many riggers list commissions open/closed status on their Twitter profile.

### VRoid Hub

`https://hub.vroid.com` — this is for **3D VRM models**, not Live2D. Not directly relevant for VTS. Mentioned here because beginners often confuse VRoid (3D) with Live2D (2D). If you load a VRM from VRoid Hub into VTS, it will not work [1].

---

## 4. Live2D Parameters Explained

### What parameters are

A Live2D model is a rigged 2D illustration. The rigger defines a set of **parameters** — named numeric values with a defined range. For example, `ParamAngleX` might range from -30 to +30 and controls how far the head turns left/right. The rigger has drawn and interpolated the illustration at various values of each parameter. At runtime, driving the parameter to different values smoothly interpolates between those drawn states.

VTube Studio maps incoming tracking data (from webcam, iPhone, etc.) to these parameter values via its parameter mapping system [8].

### Auto-Setup and why standard parameter IDs matter

When you load a model and click "Auto-Setup", VTS looks for parameters with **standard Live2D IDs** and configures the mappings automatically [8]. The standard IDs are defined by the Live2D company at `https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/`.

If a model uses non-standard names (e.g., a rigger named the head-turn parameter `HeadRotX` instead of `ParamAngleX`), Auto-Setup won't find it and you must map it manually.

### Standard parameter list (key ones)

From the official Live2D documentation [11] and VTS documentation [8]:

**Head/body angles:**
- `ParamAngleX` — head yaw (left/right), range -30 to +30
- `ParamAngleY` — head pitch (up/down), range -30 to +30
- `ParamAngleZ` — head roll (tilt), range -30 to +30
- `ParamBodyAngleX` — body sway left/right
- `ParamBodyAngleY` — body lean forward/back
- `ParamBodyAngleZ` — body rotation

**Eyes:**
- `ParamEyeLOpen` — left eye open/close, range 0 to 1
- `ParamEyeROpen` — right eye open/close, range 0 to 1
- `ParamEyeLSmile` — left eye smile shape
- `ParamEyeRSmile` — right eye smile shape
- `ParamEyeBallX` — eye gaze left/right
- `ParamEyeBallY` — eye gaze up/down

**Eyebrows:**
- `ParamBrowLY` — left brow height
- `ParamBrowRY` — right brow height
- `ParamBrowLAngle` — left brow angle
- `ParamBrowRAngle` — right brow angle
- `ParamBrowLForm` / `ParamBrowRForm` — brow shape/expression

**Mouth:**
- `ParamMouthOpenY` — mouth open amount, range 0 to 1
- `ParamMouthForm` — mouth shape (smile to frown), range -1 to +1
- `ParamTongue` — tongue out (supported in some trackers)

**Cheeks:**
- `ParamCheek` — cheek puff (not supported in all trackers; iOS only)

### Why some models have more parameters than others

A basic model might only rig the core head-angle and mouth-open parameters (~10–15 parameters). A more expressive model adds individual brow tracking, wink states, multiple mouth forms, cheek puffs, tongue, individual finger control, hair physics parameters, clothing physics, etc. Professional agency models can have 50–100+ parameters. More parameters require more rigging work, which is why commission prices scale steeply.

For a beginner's first model, 20–35 parameters is typical and is more than enough to look expressive during streaming.

### VTS input parameters (tracking → model mapping)

VTS exposes its own set of "input parameters" that represent the tracked face data. Key ones:
- `FaceAngleX`, `FaceAngleY`, `FaceAngleZ` — head angles
- `MouthOpen`, `MouthSmile` — mouth state
- `EyeOpenLeft`, `EyeOpenRight` — individual eye state
- `EyeLeftX/Y`, `EyeRightX/Y` — gaze direction
- `BrowLeftY`, `BrowRightY` — brow height
- `VoiceVolume`, `VoiceFrequency` — from microphone for lipsync
- `VoiceVolumePlusMouthOpen`, `VoiceFrequencyPlusMouthSmile` — combined voice+face mouth control [12]

These VTS input parameters map to the model's Live2D output parameters. The ranges can be freely remapped; e.g., a model's `ParamMouthOpen` with range 0–1 maps from the `MouthOpen` input 0–1 range, but you can invert, clamp, or scale as needed [8].

---

## 5. Full Webcam Tracking Setup

### Tracker options on Windows/macOS (for context)

VTS ships with multiple webcam trackers on Windows:
- **[Google] Mediapipe Tracker** — built-in, no special hardware, quality comparable to NVIDIA tracker, Windows-only [13]. Supports brows, blink/wink, hands. Does NOT support cheek puff or tongue. Has more restrictive rotation range than OpenSeeFace.
- **NVIDIA Tracker** — requires NVIDIA GPU, uses RTX features, Windows-only [14].
- **OpenSeeFace** — the original tracker; cross-platform; used on Linux as the only option.

On Linux, **only OpenSeeFace is available** (see section 6).

### Resolution and FPS settings

- Recommended resolution: **1280x720** [15]
- FPS: highest stable option your webcam can sustain
- Minimum for decent eye tracking: 1280x720 @ 10fps (but higher is better)
- Tracking Level 5 (highest) is recommended on modern CPUs; **only Level 5 supports winking** [15]

### Calibration

After starting the webcam tracker, press **Calibrate** while looking directly at the camera with a neutral face (no expression, head straight). Calibration data persists across restarts. Re-calibrate if head angles look wrong on the model [15].

### Lighting — the most impactful free improvement

- Place a soft light **in front of you** (ring light, monitor light, desk lamp with diffuser)
- Avoid backlighting (window behind you) — silhouettes the face
- Shadows on the face cause tracking jitter and loss of features
- Consistent lighting matters more than expensive lighting equipment [15][16]

### Smoothing settings

- Higher smoothing = less jitter but more input lag
- Recommended range: **5–15** for most parameters [15]
- For fast expressions (blinks, quick mouth movements) keep smoothing lower
- For slow head movements keep it higher

### Eye blinking setting

Use **"When face is rotated"** mode OR the newer **Manual** (default) mode. In Manual mode, set the sensitivity sliders to fit your eye opening range [15].

### Webcam hardware recommendations [16]

Any modern webcam at 1080p/60fps works. Tracking crops and rescales the face to 224×224 internally, so resolution beyond 1080p provides diminishing returns. Sweet spot: **720p–1080p**.

Specific models mentioned in community recommendations:
- **Logitech C920** / **C922** — workhorse budget option, widely supported on Linux (USB UVC), ~$70–$100
- **Logitech Brio** / **MX Brio** — 4K, but mostly useful for OBS stream quality, not tracking quality
- **Razer Kiyo X** — good low-light, comparable price to C920
- **OBSBOT Tiny 2** — 1/1.5" sensor, fast autofocus, premium option ~$200

For Linux specifically: prefer **USB UVC webcams** (plug-and-play on Linux without drivers). The Logitech C920 and C922 are the most reliable choices on Linux.

---

## 6. Microphone Lipsync

VTS has a **separate lipsync system** that is independent of (and composable with) webcam tracking [12]. It analyzes microphone audio in real time to drive mouth parameters.

### Lipsync types

**Advanced Lipsync** (recommended): calibrates to your voice, detects Japanese vowel phonemes A/I/U/E/O. Available on all platforms (Windows, macOS, Android, iOS) [12].

**Basic Lipsync**: uses only volume level to drive mouth open/close. No phoneme detection.

### Setup steps

1. In VTS, go to Settings → select your microphone
2. Enable "Use microphone"
3. Set "Lipsync Type" to Advanced
4. Click each "Calibrate" button while speaking the respective vowel clearly
5. Run Auto-Setup on the model to wire `VoiceVolume` and `VoiceFrequency` to mouth parameters

### Combining with face tracking

The parameters `VoiceVolumePlusMouthOpen` and `VoiceFrequencyPlusMouthSmile` blend microphone data with face-tracked mouth data [12]. This is recommended — face tracking drives the raw open/close, voice fills in the expression shape.

### Linux note

Microphone lipsync should work on Linux via Proton since it reads audio through Wine's audio layer. No confirmed issues found, but may require PulseAudio/PipeWire to be configured correctly.

---

## 7. iPhone Tracking: Full Picture

### Why it's better than webcam

iOS ARKit uses the **TrueDepth camera** (infrared dot projector + IR camera + flood illuminator on the front-facing notch/dynamic island). This projects 30,000 invisible IR dots onto your face and reads their distortion to reconstruct a 3D mesh — no lighting required. It is fundamentally different from (and more accurate than) webcam-based optical tracking [3][17].

Specifically better for: eye tracking precision, blink detection, cheek puffs, individual brow control, tongue (on some trackers), expression subtlety.

### Which iPhones support TrueDepth/ARKit face tracking [17]

**All iPhones with Face ID** have the TrueDepth camera and support ARKit face tracking:
- iPhone X (introduced TrueDepth, late 2017)
- iPhone XS, XS Max, XR
- iPhone 11, 11 Pro, 11 Pro Max
- iPhone 12, 12 mini, 12 Pro, 12 Pro Max
- iPhone 13, 13 mini, 13 Pro, 13 Pro Max
- iPhone 14, 14 Plus, 14 Pro, 14 Pro Max
- iPhone 15, 15 Plus, 15 Pro, 15 Pro Max
- iPhone 16 series

**Does NOT have TrueDepth:** all iPhone SE models (they use Touch ID, not Face ID).

**iPads with TrueDepth:** iPad Pro (all generations), iPad Air 4th gen and later with M1+.

VTS wiki says A12 chip or newer is recommended to avoid overheating during long tracking sessions [3]. That means iPhone XS/XR (A12) at minimum as a practical choice; older X (A11) works but runs warm.

### Built-in VTS iOS tracking vs. VBridger

VTube Studio has a free **iOS companion app** on the App Store. Install it on your iPhone, put phone and PC on the same WiFi network, and connect. This already gives you ARKit tracking [3]. The iOS app is free.

**VBridger** (Steam, ~$10) is a separate paid plugin that enhances what you can do with the ARKit data [18]:
- Allows mixing/blending multiple tracking sources (iPhone + webcam simultaneously)
- Better use of the 52 ARKit blendshapes on models rigged for ARKit specifically
- Supports combining iFacialMocap, FaceMotion3D, MeowFace (Android), MediaPipe as inputs
- The "Editor DLC" (~$5 extra) allows riggers to create custom parameter outputs

**Is VBridger worth it?** For a first setup: **no**. Use the free built-in VTS iOS tracking first. Upgrade to VBridger only if you commission a model specifically rigged for ARKit parameters, or if you want to blend sources. The built-in iOS tracking is already dramatically better than webcam.

### Connection setup (built-in iOS method)

1. Install VTube Studio on your iPhone (App Store, free)
2. Connect phone and PC to the same WiFi network (2.4GHz has more range; 5GHz is lower latency — prefer 5GHz)
3. Open VTS on iPhone
4. Open VTS on PC, go to tracking settings, select iPhone as tracker
5. Enter the IP address shown on the iPhone app into the PC app (or use auto-discovery)
6. Calibrate once

Official warning: 2.4GHz networks can introduce latency for the tracking stream [19].

---

## 8. Linux Setup: The Real Picture

### Official status

VTube Studio has **no official Linux build**. The developer has not committed to a Linux release. The app runs under Proton (Wine-based Steam compatibility layer) but with significant caveats [20][21].

### What works under Proton

- The application launches and is usable
- Model loading, expressions, physics, items, API — all functional
- Microphone audio (likely works via Wine audio layer)
- iPhone tracking over WiFi (network stack works in Wine)

### What doesn't work under Proton

- **Direct webcam capture via DirectShow** — this is a Windows-specific camera API that Proton does not implement [20][21]
- Mediapipe tracker — Windows only, not in the Linux/Proton build
- NVIDIA tracker — Windows only

**The webcam simply won't work natively.** The camera may appear to be detected but produces no usable image or wrong resolutions/formats.

### The workaround: OpenSeeFace

OpenSeeFace (`https://github.com/emilianavt/OpenSeeFace`) is an open-source face tracker that runs natively on Linux (Python + ONNX Runtime + OpenCV). It reads your webcam, does face tracking, and transmits the data to VTS over UDP on port 11573 — the same port VTS uses internally for its OpenSeeFace integration [20].

Architecture: `webcam → OpenSeeFace (native Linux Python process) → UDP:11573 → VTS (inside Proton)`

VTS already has code to receive this UDP stream; you just configure it.

### Step-by-step Linux setup [20][22]

**1. Install VTube Studio via Steam**
Enable SteamPlay in Steam settings. Install VTS. Try Proton Experimental or the latest Proton-GE (install via ProtonUp-Qt or ProtonPlus).

**2. Configure VTS to receive external tracking**
Navigate to: `~/.steam/steam/steamapps/common/VTube Studio/VTube Studio_Data/StreamingAssets/`
Create or edit `ip.txt` with:
```
ip=0.0.0.0
port=11573
```
This tells VTS to accept OpenSeeFace tracking from any local address.

**3. Install system dependencies**
```bash
sudo apt-get install v4l-utils python3 python3-pip python3-virtualenv git
```
On Arch: `sudo pacman -S v4l-utils python python-pip python-virtualenv git`

**4. Clone and set up OpenSeeFace**
```bash
mkdir -p ~/opt/openseeface
cd ~/opt/openseeface
git clone https://github.com/emilianavt/OpenSeeFace
cd OpenSeeFace
virtualenv -p python3 env
source env/bin/activate
pip3 install onnxruntime opencv-python pillow numpy
```

**5. Find your webcam device**
```bash
v4l2-ctl --list-devices
```
Note the `/dev/videoN` number (usually 0).

**6. Start OpenSeeFace**
```bash
cd ~/opt/openseeface/OpenSeeFace
source env/bin/activate
python facetracker.py -W 1280 -H 720 --discard-after 0 --scan-every 0 --no-3d-adapt 1 --max-feature-updates 900 -c 0
```
Replace `-c 0` with your camera index if needed.

**7. Start VTS via Steam**
In VTS tracking settings, enable the webcam and set it to "Autostart cam with VTS". VTS should now receive tracking data from OpenSeeFace.

**8. Activate the virtual environment every session**
The Python venv must be activated before running facetracker.py. Consider writing a shell script that activates it and starts the tracker automatically.

### Proton version recommendations

- Proton Experimental: usually the latest features, good starting point
- Proton-GE (GloriousEggroll): community-patched version with more codecs and fixes; often better for non-game apps; install via ProtonUp-Qt [21]
- ProtonDB page for VTS: `https://www.protondb.com/app/1325860`

### iPhone tracking on Linux

iPhone tracking works on Linux via Proton because it goes over WiFi (TCP/UDP socket), not through DirectShow. This is actually the **recommended Linux approach** — skip webcam tracking entirely, use your iPhone [3][20].

### Honest assessment for the developer persona

This is not a one-click setup. Expect 30–60 minutes of configuration on first run. If you are comfortable with Python venvs and terminal work, it is manageable. The result is fully functional: tracking quality is identical to the Windows OpenSeeFace path.

If you have an iPhone, the iPhone path is significantly easier on Linux than the OpenSeeFace webcam path, and produces better tracking anyway.

---

## 9. First-Time Full Setup Flow

This is a logical sequence for someone starting from zero on Linux.

### Phase 1: Get the software

1. Install Steam, enable SteamPlay with Proton Experimental
2. Install VTube Studio (free) from Steam
3. Install the $15 "Artiste" DLC if you want to stream without watermark (can wait)
4. On your phone: install VTube Studio iOS/Android app if using phone tracking

### Phase 2: Get a model

5. Download a free model from Live2D official samples or BOOTH
6. Verify the folder contains: `*.model3.json`, `*.moc3`, `*.physics3.json`, texture folder

### Phase 3: Load the model

7. In VTS, use the folder button to open the `Live2DModels` directory
   - Steam path: `~/.steam/steam/steamapps/common/VTube Studio/VTube Studio_Data/StreamingAssets/Live2DModels/`
8. Copy your model folder there
9. Restart VTS (required first time to generate `.vtube.json` config file) [19]
10. Select the model from the model picker
11. Click "Auto-Setup" — accepts the prompt to auto-configure parameters

### Phase 4: Set up tracking

**Option A: iPhone (recommended for Linux)**
12. Put phone and PC on same WiFi (5GHz preferred)
13. Open VTS iOS app, follow in-app pairing instructions
14. In VTS PC, select iPhone as tracker
15. Calibrate once

**Option B: Webcam via OpenSeeFace (if no iPhone)**
12. Follow the OpenSeeFace setup from section 8
13. Configure `ip.txt`
14. Start OpenSeeFace, then start VTS
15. Calibrate in VTS

### Phase 5: Set up microphone lipsync

16. Go to VTS Settings → select your microphone
17. Enable "Use microphone", set Lipsync Type to Advanced
18. Click through vowel calibration (say A, I, U, E, O when prompted)

### Phase 6: Connect to OBS

19. In VTS, set background to transparent (green or transparent depending on OBS setup)
20. In OBS, add "Game Capture" or "Window Capture" source pointing to VTube Studio
21. For transparent background: use "Game Capture" with "Allow transparency" enabled
    - Or export via VTS virtual camera if using video call software

### Phase 7: Verify

22. Check model responds to head movement
23. Check mouth opens when speaking
24. Check expressions trigger correctly
25. Check OBS shows the model with transparent background

---

## 10. Common Beginner Mistakes

From community sources [23][24]:

### Technical mistakes

**1. Loading VRM models into VTS**
VTS is Live2D only. VRM (VRoid) models will not load. Use VSeeFace for VRM or convert to a VTS-compatible format (not straightforward).

**2. Skipping calibration**
Head angles will look wrong or jerky. Always calibrate after changing position, lighting, or equipment.

**3. Not restarting after first model copy**
VTS needs to generate its `.vtube.json` config file on first load. If the file isn't there, model settings won't save.

**4. Using standard parameters with non-standard IDs**
Auto-Setup won't configure a model that uses non-standard parameter names. Check the model's documentation and do manual mapping if needed.

**5. Smoothing too high**
Tracking that's over-smoothed looks like the model is floating or lagging. Keep smoothing 5–15; go lower for fast expressions.

**6. Webcam pointed the wrong direction**
Webcam should be at face level, not looking up from a desk or down from a monitor top. Below-eye angle looks unnatural on the model.

**7. On Linux: not activating the Python venv before starting OpenSeeFace**
The tracker will fail silently or crash. Write a shell script wrapper.

**8. On Linux: wrong port in ip.txt**
Must be port 11573. Copy-paste, don't retype.

### Model quality mistakes

**9. Using a model with too few parameters**
A simple model might not support winking, individual brows, or expressions. Fine for starting out, but can feel limiting.

**10. Using a model not rigged for VTS Auto-Setup**
Saves significant setup time if the model follows standard parameter naming conventions.

### Workflow mistakes

**11. Waiting for a perfect model**
Start with a free model to learn the software. Commission or buy a paid model once you understand what parameters and features matter to you.

**12. Not setting up expressions/hotkeys**
VTS supports hotkeys that trigger expressions (happy, angry, etc.) overlaid on tracking data. Setting these up early makes streaming much more expressive.

**13. Ignoring lighting**
Lighting is the highest-ROI improvement for webcam tracking quality. A $20 ring light outperforms a $200 webcam in a dark room.

---

## 11. EEG Plugin Integration (Muse 2 — Future Work)

This guide is a prerequisite for adding Muse 2 EEG control via a VTS plugin. The relevant integration point:

- VTube Studio exposes a **WebSocket API** on port 8001 by default [25]
- External plugins authenticate via the API, then can **inject parameter values** in real time
- This is the same mechanism used by VBridger, face tracking apps, etc.
- A Python process reading Muse 2 BrainFlow data can drive any VTS parameter (e.g., brow raise on relaxation, wink on eye blink command, expression toggle on jaw clench)
- API documentation: `https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins`

This setup works on Linux because the API is a plain WebSocket — no platform-specific code.

---

## Sources

1. VTube Studio GitHub Wiki — Introduction & Requirements: `https://github.com/DenchiSoft/VTubeStudio/wiki/Introduction-&-Requirements`
2. VTube Studio on Steam: `https://store.steampowered.com/app/1325860/VTube_Studio/`
3. VTube Studio Wiki — Android vs iPhone vs Webcam: `https://github.com/DenchiSoft/VTubeStudio/wiki/Android-vs.-iPhone-vs.-Webcam`
4. VSeeFace official site: `https://www.vseeface.icu/`
5. Live2D Sample Data: `https://www.live2d.com/en/learn/sample/`
6. BOOTH.pm free Live2D: `https://booth.pm/en/search/free%20live2d`; example model `https://booth.pm/en/items/4711410`
7. Free model aggregator — VTubing.info: `https://vtubing.info/docs/free-vtuber-models-assets/free-live2d-assets/`; Kudos list `https://kudos.tv/blogs/stream-blog/free-vtuber-models`; ShiraLive2D `https://shiralive2d.com/live2d-sample-models/`; StreamSkins `https://streamskins.net/free-vtuber-model/`; live3d `https://live3d.io/vtuber-model`
8. VTube Studio Wiki — VTS Model Settings: `https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings`
9. VTuber model pricing — ARwall: `https://arwall.co/blogs/arwall-blogs/how-much-do-vtuber-models-cost`; ShiraLive2D pricing `https://shiralive2d.com/live2d/how-much-does-a-live2d-model-cost/`
10. Animotions Studio pricing: `https://animotionsstudio.com/how-much-does-a-vtuber-model-cost/`
11. Live2D official standard parameter list: `https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/`
12. VTube Studio Wiki — Lipsync: `https://github.com/DenchiSoft/VTubeStudio/wiki/Lipsync`; VTS tweet on VoiceVolumePlusMouthOpen: `https://x.com/vtubestudio/status/1412595209691709449`
13. VTube Studio Wiki — Mediapipe Webcam Tracker: `https://github.com/DenchiSoft/VTubeStudio/wiki/Mediapipe-Webcam-Tracker`
14. VTube Studio Wiki — NVIDIA Webcam Tracker: `https://github.com/DenchiSoft/VTubeStudio/wiki/NVIDIA-Webcam-Tracker`
15. VTube Studio Wiki — Settings: `https://github.com/DenchiSoft/VTubeStudio/wiki/VTube-Studio-Settings`; tryfix.it guide `https://tryfix.it.com/how-to-set-up-tracking-on-vtube-studio-the-ultimate-pro-guide/`
16. Streamlabs webcam guide: `https://streamlabs.com/content-hub/post/best-webcams-for-vtubers`
17. Apple Face ID supported devices: `https://support.apple.com/en-us/102854`; ARKit face tracking docs `https://developer.apple.com/documentation/arkit/tracking-and-visualizing-faces`
18. VBridger on Steam: `https://store.steampowered.com/app/1898830/VBridger/`; bilvyy VBridger guide `https://www.bilvyy.com/post/vbridger`
19. VTube Studio Wiki — Getting Started: `https://github.com/DenchiSoft/VTubeStudio/wiki/Getting-Started`; model loading `https://github.com/DenchiSoft/VTubeStudio/wiki/Loading-your-own-Models`
20. VTube Studio Wiki — Running VTS on Linux: `https://github.com/DenchiSoft/VTubeStudio/wiki/Running-VTS-on-Linux`
21. ProtonDB page for VTS: `https://www.protondb.com/app/1325860`; Codeberg Linux VTubing guide `https://codeberg.org/RogueRen/Linux-Guide-to-Vtubing`
22. OpenSeeFace Ubuntu install gist: `https://gist.github.com/Kelketek/14e473479a7a043786be646213f4f05e`; Arch Linux guide `https://gist.github.com/BenKato151/b8b4a6897cc6cc7835ac9107288d3df2`; OpenSeeFace repo `https://github.com/emilianavt/OpenSeeFace`
23. VTuberLab beginner mistakes: `https://vtuberlab.com/2025/06/06/vtubing-for-beginners-avoid-these-10-common-mistakes-new-vtubers-make/`
24. VTuber Sensei common problems: `https://vtubersensei.wordpress.com/2024/09/20/how-to-fix-common-vtuber-tech-problems/`
25. VTube Studio Wiki — Plugins API: `https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins`
