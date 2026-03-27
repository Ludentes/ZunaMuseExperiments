# Research: Muse 2 IMU for VTuber 3D Head Control

**Date:** 2026-03-26
**Sources:** 18 sources (see bottom)

---

## Executive Summary

The Muse 2's accelerometer (±2g) and gyroscope (±245°/s) at 52Hz via BrainFlow's AUXILIARY_PRESET provide sufficient data for real-time 3D head pose estimation (pitch, roll, and partially yaw). Combined with our existing EEG-based blink detector, this creates a lightweight VTuber head controller without requiring a camera. The most practical implementation path is: Madgwick/Mahony sensor fusion in the Python backend → quaternion over WebSocket → three-vrm rendering a VRM model in the React frontend. All critical libraries exist and are open source. The main limitation is yaw drift (no magnetometer on Muse 2), which can be managed with periodic recalibration or gyro-only yaw with drift correction.

## Key Findings

### 1. IMU Head Pose Estimation from Muse 2

The Muse 2 provides 3-axis accelerometer (in g's, range ±2g) and 3-axis gyroscope (in °/s, range ±245°/s) at 52Hz through BrainFlow's AUXILIARY_PRESET [1][8]. Our backend already extracts these channels (`acquisition.py:71-83`) and computes basic pitch/roll from accelerometer means (`processing.py:132-135`).

For VTuber control, we need proper sensor fusion. The accelerometer alone gives stable pitch and roll but cannot measure yaw (rotation around gravity axis) and is noisy during motion. The gyroscope gives smooth short-term rotation for all three axes but drifts over time due to integration error [2][6]. The solution is a complementary or Madgwick filter that blends both sensors.

**Complementary filter** (simplest): `θ(t) = α × (θ(t-1) + gyro × dt) + (1-α) × accel_angle`, where α ≈ 0.95-0.98 [6]. This gives good pitch/roll but yaw still drifts.

**Madgwick filter** (recommended): Operates in quaternion space, avoiding gimbal lock. Outputs a quaternion `(x, y, z, w)` directly usable by Three.js. Only tunable parameter is β (convergence rate). Computationally cheap — designed for embedded systems [2][9]. The `ahrs` npm package implements both Madgwick and Mahony filters in JavaScript and returns quaternions directly [9].

**Yaw limitation:** Without a magnetometer, yaw (left-right head turn) will drift. Practical mitigations: (a) auto-recenter on button press or blink pattern, (b) use gyro-only yaw with slow decay toward center, (c) the HeadTracker project achieves "good enough" drift control after 5 seconds of continuous gyro calibration without a magnetometer [5].

### 2. VRM Format — The Standard for Web VTuber Avatars

VRM is the de facto open format for 3D VTuber avatars, built as a glTF 2.0 extension [3]. It standardizes:

- **Humanoid bone mapping** — consistent bone names across all models (Head, Neck, LeftEye, RightEye, etc.)
- **Expressions** — predefined blendshapes: `blink`, `blinkLeft`, `blinkRight`, `happy`, `angry`, `sad`, `relaxed`, `aa`, `ih`, `ou`, `ee`, `oh` (VRM 1.0 naming) [3][7]
- **LookAt** — eye gaze control system
- **Spring bones** — physics-based hair/accessory movement

Free VRM models are available from VRoid Hub, or users can create custom ones with VRoid Studio (free). Any VRM model will work with the same code since the bone/expression interface is standardized.

### 3. three-vrm — The Library to Use

`@pixiv/three-vrm` by Pixiv is the canonical library for rendering VRM in Three.js [3]. It provides everything needed:

**Loading:**
```javascript
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
loader.load('/model.vrm', (gltf) => {
  const vrm = gltf.userData.vrm;
  scene.add(vrm.scene);
});
```

**Setting head rotation (from quaternion or euler):**
```javascript
const head = vrm.humanoid.getRawBoneNode('head');
head.quaternion.set(qx, qy, qz, qw);
// or: head.rotation.set(pitch, yaw, roll);
```

**Triggering blink expression:**
```javascript
vrm.expressionManager.setValue('blink', 1.0);  // eyes closed
vrm.expressionManager.setValue('blink', 0.0);  // eyes open
vrm.expressionManager.update();
```

**Per-frame update loop:**
```javascript
function animate(delta) {
  vrm.expressionManager.update();
  vrm.lookAt?.update(delta);
  vrm.springBoneManager?.update(delta);
  vrm.humanoid.update();
}
```

For React integration, `@davidcks/r3f-vrm` wraps three-vrm for React Three Fiber with a `<VRMAvatar>` component and manager pattern [10].

### 4. Architecture: What We Can Reuse

Our existing stack already handles most of the pipeline:

| Component | Existing | New/Modified |
|---|---|---|
| IMU acquisition (52Hz) | `acquisition.py` — accel + gyro channels | — |
| IMU binary framing | `protocol.py` MSG_IMU (0x03) | — |
| WebSocket broadcast | `main.py` broadcasts IMU frames | — |
| Frontend binary decoder | Exists for EEG/PPG/IMU | — |
| Blink detection (EEG) | Pipeline detector, ~99% accuracy | Wire to expression |
| Sensor fusion (Madgwick) | — | **New**: ~50 lines Python or JS |
| Quaternion → VRM head bone | — | **New**: ~20 lines JS |
| VRM model loading + render | — | **New**: Three.js/R3F component |
| Expression mapping | — | **New**: blink event → blendshape |

The sensor fusion can live in either Python (using `ahrs` PyPI package or raw numpy) or JavaScript (using `ahrs` npm package). Python-side is simpler since we already process IMU there; we'd add a quaternion to the WebSocket message.

### 5. The VMC Protocol (Alternative/Interop Path)

The VMC (Virtual Motion Capture) Protocol is the standard interop protocol for VTuber motion data, using OSC over UDP [7]. Key messages:

- **Bone rotation:** `/VMC/Ext/Bone/Pos (string)Head (float)px (float)py (float)pz (float)qx (float)qy (float)qz (float)qw`
- **Blendshape:** `/VMC/Ext/Blend/Val (string)blinkLeft (float)1.0` followed by `/VMC/Ext/Blend/Apply`
- **Standard ports:** 39539 (marionette/receiver), 39540 (assistant/sender)

A Python VMC sender exists (`python-vmcp` on Codeberg) [7]. This would let our Muse backend drive **any** VMC-compatible VTuber app (VSeeFace, SnekStudio, Warudo, etc.) — not just our own frontend. This is a valuable interop layer but not required for an MVP.

### 6. Existing VTuber Software with External Input

Several open-source VTuber apps accept external tracking data [4]:

- **VSeeFace** — Windows, supports VMC protocol input, highly configurable. Could receive our Muse data via VMC sender.
- **SnekStudio** — Godot-based, open source, has VMC receiver built in. Modular architecture.
- **Kalidokit** — Not a VTuber app but a JS library that converts landmark arrays to VRM-compatible blendshapes and bone rotations [11]. Its `Face.solve()` outputs head rotation (euler angles in radians) and blink values. While designed for MediaPipe landmarks, the rotation-application code patterns are directly reusable.

### 7. Blink Detection Integration

Our EEG blink detector (99% accuracy per project docs) maps naturally to VRM expressions. The integration is straightforward:

```javascript
// On blink event from WebSocket
ws.onmessage = (msg) => {
  const data = JSON.parse(msg.data);
  if (data.type === 'blink') {
    // Animate blink: quick close + open over ~150ms
    animateBlink(vrm, 0.15); // duration in seconds
  }
};

function animateBlink(vrm, duration) {
  // Ramp blink to 1.0 over duration/2, then back to 0.0
  const half = duration / 2;
  // Use requestAnimationFrame or tween library
}
```

VRM supports separate `blinkLeft` and `blinkRight` expressions, so if our detector can distinguish laterality (it currently detects bilateral blinks), we could extend it later for winking.

## Proposed Implementation Architecture

```
┌─────────────────────────────────────┐
│  Muse 2 (BLE)                       │
│  EEG: 4ch @ 256Hz                   │
│  Accel: 3ch @ 52Hz                  │
│  Gyro: 3ch @ 52Hz                   │
└──────────┬──────────────────────────┘
           │ BrainFlow
┌──────────▼──────────────────────────┐
│  Python Backend                      │
│                                      │
│  ┌─────────────┐  ┌──────────────┐  │
│  │ EEG Pipeline │  │ IMU Fusion   │  │
│  │ Blink Det.   │  │ (Madgwick)   │  │
│  └──────┬──────┘  └──────┬───────┘  │
│         │                │           │
│    blink events    quaternion(xyzw)  │
│         │                │           │
│  ┌──────▼────────────────▼───────┐  │
│  │    WebSocket JSON + Binary    │  │
│  └──────────────┬────────────────┘  │
└─────────────────┼────────────────────┘
                  │
┌─────────────────▼────────────────────┐
│  React Frontend (Vite + R3F)         │
│                                      │
│  ┌──────────────────────────────┐   │
│  │  Three.js + @pixiv/three-vrm │   │
│  │                              │   │
│  │  quaternion → Head bone      │   │
│  │  blink evt → Expression      │   │
│  │  Spring bones → Hair physics │   │
│  └──────────────────────────────┘   │
└──────────────────────────────────────┘
```

## Comparison: Sensor Fusion Options

| Approach | Pitch/Roll | Yaw | Drift | Complexity | Latency |
|---|---|---|---|---|---|
| Accel-only (current) | Good, noisy | None | None | Trivial | ~20ms |
| Complementary filter | Good | Drifts | Moderate | ~20 LOC | ~20ms |
| Madgwick (6DOF) | Excellent | Drifts slowly | Low for P/R | ~50 LOC | ~20ms |
| Madgwick + mag (9DOF) | Excellent | Stable | Minimal | ~50 LOC | ~20ms |

Muse 2 has no magnetometer, so we're limited to 6DOF. Madgwick is the best option — stable pitch/roll, manageable yaw drift with periodic recenter.

## Comparison: Frontend Rendering Options

| Library | Format | React Integration | Expressions | Bone Control | Maturity |
|---|---|---|---|---|---|
| @pixiv/three-vrm | VRM | Manual or via r3f-vrm | Full VRM spec | Humanoid API | High, by Pixiv |
| @davidcks/r3f-vrm | VRM | Native R3F component | Manager API | Via manager | Medium, newer |
| Raw Three.js + GLTF | glTF | Manual | Custom | Manual | High but no VRM std |
| Kalidokit | — | — | Maps to VRM | Maps to VRM | Medium, lib only |

**Recommendation:** Use `@pixiv/three-vrm` directly with React Three Fiber. It's the most mature, best documented, and gives full control. The r3f-vrm wrapper adds convenience but also abstraction we may not want.

## VRoid & VRM Ecosystem

### VRoid Studio (Creator Tool)

VRoid Studio is Pixiv's free 3D character creation app (Windows, macOS, iPad, Steam — 94% positive from ~2800 reviews). It's an anime-style character creator with slider-based face/body customization, brush-based hair drawing, and direct texture painting on the 3D model. No 3D modeling skill required. Exports .vrm with full bone rigging, expressions, and spring bone physics baked in. Supports male and female character bases. Limitations: anime aesthetic only (no realistic), limited body type variety, no custom topology — it's a character dressup tool, not Blender.

### VRoid Hub (Marketplace/Platform)

Pixiv-run platform for sharing and distributing VRM models. Some models are free to download, others have creator-set usage conditions. Has an API for apps to pull avatars directly ("sign in with VRoid Hub, pick your avatar"). Integrated with dozens of apps and games.

### VRM Ecosystem Breadth

VRM has become a de facto standard with wide cross-platform support:

| Category | Notable Apps |
|---|---|
| Creation | VRoid Studio, Vket Avatar Maker (browser), Character Studio |
| VTuber/Streaming | VSeeFace, 3tene, Animaze, VirtualMotionCapture |
| Motion Capture | waidayo, Kalidoface 3D, iFacialMocap, FACEMOTION3D |
| Games | Craftopia, Synth Riders, VRChat (via conversion) |
| Social/Metaverse | cluster, VirtualCast, My Vket, Hyperfy |
| Dev Libraries | @pixiv/three-vrm (Three.js), UniVRM (Unity), VRM4U (Unreal), godot-vrm, VRM Add-on for Blender, bevy_vrm1 (Rust) |

Key implications for our project: (1) users can bring their own avatar — zero friction, (2) VRM is an open glTF extension, not proprietary, (3) VMC protocol bridges to existing VTuber apps, (4) three-vrm is maintained by Pixiv themselves (first-party, actively developed). Healthy, growing ecosystem driven by anime/VTuber community, but the underlying tech (standardized humanoid bones + expressions on glTF) is genuinely well-engineered.

## Muse vs Webcam: Honest Assessment

### What a webcam gives you (for free)

MediaPipe Face Mesh provides 468 facial landmarks at 30-60fps from any webcam. Combined with Kalidokit, this gives:

- **Head pose** (pitch, yaw, roll) — all three axes, no drift, no magnetometer needed
- **50+ blendshapes** via ARKit-compatible output — brows, mouth shapes, cheek puff, tongue, individual eye tracking
- **Eye gaze direction** — pupil tracking
- **Mouth shapes** for lip sync (A, I, U, E, O vowels)
- **No additional hardware** — every laptop has a webcam

This is the standard VTuber setup. VSeeFace, Kalidoface, and most VTuber software use exactly this pipeline. It works well.

### What Muse adds

| Capability | Webcam | Muse IMU | Muse EEG |
|---|---|---|---|
| Pitch (nod) | Good | Good | — |
| Yaw (turn) | Good | Drifts (no mag) | — |
| Roll (tilt) | Good | Good | — |
| Facial expressions (50+) | Yes | No | — |
| Blink detection | Yes (~90%) | No | Yes (~99%) |
| Eye gaze | Yes | No | No |
| Lip sync | Yes | No | No |
| Works in dark | No | Yes | Yes |
| Works off-camera | No | Yes | Yes |
| No camera needed | No | Yes | Yes |
| Latency | ~50-80ms | ~20ms | ~50ms |
| CPU usage | Moderate (ML inference) | Negligible | Low |
| Mental state data | No | No | Yes (alpha, theta, focus) |

### Honest verdict

**For pure VTuber head tracking, a webcam is strictly better.** It gives you more data (face, eyes, mouth) with less hassle (no yaw drift, no BLE pairing). The Muse IMU alone is a worse face tracker than MediaPipe.

### Where Muse becomes interesting

The Muse value proposition isn't "better webcam" — it's "things a webcam can't do":

1. **No-camera operation** — streams in the dark, from bed, without showing your face or room. Privacy-first VTubing. Some VTubers explicitly don't want a camera pointed at them.

2. **EEG-reactive avatar** — this is the unique selling point. The avatar could react to your *brain state*, not just your face:
   - Alpha power → relaxation expression / aura effect
   - Theta/beta ratio → concentration visual indicator
   - Blink from EEG (99%) is more reliable than webcam blink (~90%)
   - Future: jaw clench → custom expression trigger

3. **Lower latency** — IMU at 52Hz with Madgwick gives ~20ms pose updates vs ~50-80ms for webcam ML pipeline. Matters for rhythm games or reactive content.

4. **Hybrid approach** — Muse IMU for head pose + webcam for face. The IMU handles fast head motion (lower latency, no frame drops) while the camera handles expressions. This is actually how high-end VTuber setups work — iPhone for face + separate head tracker.

5. **Novelty/demo value** — "brain-controlled avatar" is a compelling demo even if the practical tracking is limited. Good for content, talks, exhibitions.

### Recommendation

Don't position this as a webcam replacement. Position it as:
- **"Brain-reactive VTuber"** — avatar that reflects your mental state, not just your face
- **"Camera-free VTubing"** — privacy-first, works anywhere
- **Hybrid input** — best of both when combined with webcam

The unique differentiator is EEG, not IMU. The IMU is "good enough" head tracking that happens to come free with the EEG headband.

## Open Questions

- **Yaw usability:** How much yaw drift is tolerable before users notice? Need to prototype and test. A 5-10° drift per minute might be acceptable with auto-recenter.
- **Latency budget:** 52Hz IMU → Madgwick → WebSocket → render. Target <50ms total. The 52Hz sample rate means ~19ms between samples, which sets a floor.
- **Model selection:** Should we bundle a default VRM model or let users load their own? VRoid Hub has free models. For MVP, bundle one.
- **Neck vs head bone:** VRM has separate Neck and Head bones. We might want to split rotation between them for more natural movement (e.g., 60% neck, 40% head).
- **Muse fit position:** The Muse sits on the forehead — its IMU tracks forehead orientation, which differs slightly from chin-level head tracking. May need a small angular offset calibration.

## Sources

[1] Muse 2 Specifications. https://ifelldh.tec.mx/sites/g/files/vgjovo1101/files/Muse%202%20Specifications.pdf (Retrieved: 2026-03-26)
[2] Atadiat. "Towards Understanding IMU: Basics of Accelerometer and Gyroscope Sensors". https://atadiat.com/en/e-towards-understanding-imu-basics-of-accelerometer-and-gyroscope-sensors/ (Retrieved: 2026-03-26)
[3] Pixiv. "three-vrm — Use VRM on Three.js". https://github.com/pixiv/three-vrm (Retrieved: 2026-03-26)
[4] emilianavt. "Best VTuber Software". https://gist.github.com/emilianavt/cbf4d6de6f7fb01a42d4cce922795794 (Retrieved: 2026-03-26)
[5] ysoldak. "HeadTracker — Zero configuration DIY Head Tracker". https://github.com/ysoldak/HeadTracker (Retrieved: 2026-03-26)
[6] Stanford EE267. "Inertial Measurement Units". https://stanford.edu/class/ee267/lectures/lecture9.pdf (Retrieved: 2026-03-26)
[7] VMC Protocol Specification. https://protocol.vmc.info/english.html (Retrieved: 2026-03-26)
[8] Muse 2 Product Page. https://choosemuse.com/products/muse-2 (Retrieved: 2026-03-26)
[9] psiphi75. "AHRS — Attitude Heading Reference Systems for JavaScript". https://github.com/psiphi75/ahrs (Retrieved: 2026-03-26)
[10] DavidCks. "r3f-vrm — VRM for React Three Fiber". https://github.com/DavidCks/r3f-vrm (Retrieved: 2026-03-26)
[11] yeemachine. "Kalidokit — Blendshape and Kinematics Calculator". https://github.com/yeemachine/kalidokit (Retrieved: 2026-03-26)
[12] DeepWiki. "pixiv/three-vrm Architecture". https://deepwiki.com/pixiv/three-vrm (Retrieved: 2026-03-26)
[13] Wawa Sensei. "VTuber Studio with Three.js, React & VRM". https://wawasensei.dev/tuto/vrm-avatar-with-threejs-react-three-fiber-and-mediapipe (Retrieved: 2026-03-26)
[14] python-vmcp. "Virtual Motion Capture Protocol for Python". https://codeberg.org/vivi90/python-vmcp (Retrieved: 2026-03-26)
[15] VRoid Studio. https://vroid.com/en/studio (Retrieved: 2026-03-26)
[16] VRM Showcase — Applications that support VRM. https://vrm.dev/en/showcase/ (Retrieved: 2026-03-26)
[17] VRoid Hub Apps. https://hub.vroid.com/en/apps (Retrieved: 2026-03-26)
[18] VRoid Studio on Steam. https://store.steampowered.com/app/1486350/VRoid_Studio/ (Retrieved: 2026-03-26)
