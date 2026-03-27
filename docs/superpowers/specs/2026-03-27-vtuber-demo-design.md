# VTuber Head Control Demo — Design Spec

**Date:** 2026-03-27
**Status:** Draft
**Goal:** Demo MVP to discover caveats with IMU head tracking + EEG blink driving a VRM avatar

---

## Context

Phase 1 of a three-phase roadmap (demo → brainstorm delivery format → implement). The demo must prove out sensor fusion, yaw drift behavior, blink-to-expression mapping, and latency characteristics before we commit to a delivery format.

### Existing Infrastructure

| Layer | What exists | Relevant files |
|---|---|---|
| IMU acquisition | 6ch (accel xyz + gyro xyz) at 52Hz via AUXILIARY_PRESET | `backend/acquisition.py:71-95` |
| Binary streaming | `MSG_IMU=0x03` broadcast over WebSocket | `backend/main.py:501-508`, `backend/protocol.py` |
| Frontend decode | Binary frames received + decoded, but IMU data not stored (line 55) | `frontend/src/hooks/useSensorStream.ts` |
| Three.js stack | `three`, `@react-three/fiber`, `@react-three/drei` installed | `frontend/package.json` |
| Blink detection | EEG pipeline detector, ~99% accuracy, emits `bci_event` JSON | `backend/main.py:482-491` |
| Demo page | Modular component layout with overlays | `frontend/src/routes/demo.tsx` |

### What Synthetic Mode Provides

When running with `--synthetic`, BrainFlow generates synthetic IMU data. This will produce valid-shaped 6-channel frames but with noise rather than real motion. Sufficient for testing the rendering pipeline; real Muse needed to test actual head tracking quality.

## Architecture

```
IMU binary frames (52Hz)          bci_event JSON
       │                                │
       ▼                                ▼
┌─────────────────┐            ┌────────────────┐
│ useSensorStream │            │ useSensorStream │
│ decode IMU frame│            │ parse bci_event │
│ store latest    │            │ store in events │
└────────┬────────┘            └───────┬─────────┘
         │                             │
         ▼                             ▼
┌─────────────────┐            ┌────────────────┐
│ useHeadPose     │            │ VTuberAvatar    │
│ Madgwick filter │            │ onBlink handler │
│ → quaternion    │            │ → expression    │
└────────┬────────┘            └───────┬─────────┘
         │                             │
         └──────────┬──────────────────┘
                    ▼
            ┌───────────────┐
            │ VTuberAvatar  │
            │ @pixiv/three- │
            │ vrm + R3F     │
            │ head bone +   │
            │ expressions   │
            └───────────────┘
```

## Approach Decision

**Chosen: Frontend-side sensor fusion (Approach B)**

Alternatives considered:
- **A) Python backend fusion → quaternion in metrics JSON** — Rejected because metrics loop runs at 2Hz (0.5s interval), far too slow for head tracking. Would need a new fast path.
- **C) Dedicated backend head_pose message** — Rejected because it adds unnecessary backend complexity and 52 JSON messages/sec overhead. The binary frames already deliver the raw data.

Frontend fusion wins because: IMU binary frames already arrive at 52Hz in the browser, Madgwick at 52Hz is trivial computation, and it gives the lowest possible latency (no round-trip).

## Components

### 1. IMU Buffer in `useSensorStream.ts`

Extend the existing hook to store the latest IMU frame instead of discarding it.

```typescript
// Add to useSensorStream
const imuRef = useRef<{ accel: Float32Array; gyro: Float32Array } | null>(null);

// In the MSG_IMU handler (replacing the comment on line 55):
if (frame.type === MSG_IMU) {
  // frame.channels = 6: [accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z]
  // Each channel has N samples; take the latest sample from each
  const lastSample = frame.samples - 1;
  imuRef.current = {
    accel: new Float32Array([
      frame.data[0 * frame.samples + lastSample],  // ax
      frame.data[1 * frame.samples + lastSample],  // ay
      frame.data[2 * frame.samples + lastSample],  // az
    ]),
    gyro: new Float32Array([
      frame.data[3 * frame.samples + lastSample],  // gx (deg/s)
      frame.data[4 * frame.samples + lastSample],  // gy
      frame.data[5 * frame.samples + lastSample],  // gz
    ]),
  };
}
```

Expose `imuRef` from the hook return value.

### 2. `useHeadPose` Hook

New hook that runs the Madgwick filter on IMU data.

**Input:** `imuRef` from useSensorStream
**Output:** `{ quaternion: { x, y, z, w }, recenter: () => void }`

```typescript
// frontend/src/hooks/useHeadPose.ts
import AHRS from 'ahrs';

const madgwick = new AHRS({
  sampleInterval: 52,  // Hz (NOT milliseconds) — Muse IMU rate
  algorithm: 'Madgwick',
  beta: 0.4,           // tuning parameter — higher = faster convergence, more accel noise
});

// Per-frame update call — note: gyro args come FIRST, then accel
// Gyro must be converted from deg/s to rad/s
const DEG2RAD = Math.PI / 180;
madgwick.update(
  gx * DEG2RAD, gy * DEG2RAD, gz * DEG2RAD,  // gyro (rad/s)
  ax, ay, az                                    // accel (g's — ahrs expects g's, no conversion needed)
);
const q = madgwick.getQuaternion();  // returns { x, y, z, w } object
```

Key behaviors:
- On each animation frame, read latest `imuRef.current`, feed to Madgwick
- Convert gyro from deg/s to rad/s (`* Math.PI / 180`). Muse accel is in g's — `ahrs` expects g's, no conversion needed.
- `ahrs.update()` argument order: gyro first (gx, gy, gz), then accel (ax, ay, az). Magnetometer args omitted for 6DOF.
- `ahrs.getQuaternion()` returns `{ x, y, z, w }` object (not array)
- Output quaternion represents absolute orientation
- `recenter()` stores current quaternion as "home", all subsequent output is relative to home
- Recenter on first valid reading (auto-calibrate initial pose)

> **Note:** The research doc recommended backend-side fusion, but the metrics loop runs at 2Hz — far too slow for head tracking. Frontend fusion on the already-arriving 52Hz binary frames is more practical.

**Yaw drift mitigation:**
- Apply slow exponential decay toward home yaw when head is still (accel variance low)
- Expose a manual `recenter()` callable from UI (button or `triple_blink` bci_event)

### 3. `VTuberAvatar` Component

New R3F component that loads a VRM model and drives it from head pose + blink events.

**Location:** `frontend/src/components/demo/VTuberAvatar.tsx`

```typescript
interface VTuberAvatarProps {
  quaternion: { x: number; y: number; z: number; w: number };  // from useHeadPose
  blinkActive: boolean;                                         // from bci_event
}
```

Implementation:
- Use `GLTFLoader` + `VRMLoaderPlugin` from `@pixiv/three-vrm` to load a bundled VRM model
- In `useFrame()`:
  - Apply quaternion to head bone: `vrm.humanoid.getRawBoneNode('head').quaternion.set(x, y, z, w)`
  - Split rotation 60/40 between neck and head for natural look
  - Smooth with lerp (slerp for quaternions) — factor ~0.3 for responsive but not jittery
  - Set blink expression: `vrm.expressionManager.setValue('blink', blinkActive ? 1.0 : 0.0)`
  - Call `vrm.update(delta)` — this single call updates expressions, lookAt, spring bones, and humanoid together (three-vrm v3.x API)
  - Guard all bone/expression access with null checks — `getRawBoneNode()` may return null for malformed models
  - Display a fallback message if VRM load fails (network error, corrupt file)

**Canvas sizing:** The R3F `<Canvas>` fills its parent container. The `/vtuber` route should use a full-viewport container (`h-screen`) minus overlay space.

**VRM Model:**
- Bundle a free VRM model from VRoid Hub in `frontend/public/models/`
- Use a simple anime head model to keep file size small (<5MB)
- Later: allow user to drag-and-drop their own VRM

### 4. Blink Animation

Rather than a binary on/off, animate the blink:
- On `bci_event` with `kind === "blink"` (or `single_blink`): trigger a 150ms blink animation
- Ramp expression value: 0 → 1 over 75ms, then 1 → 0 over 75ms
- Use a simple timestamp-based approach in `useFrame()`, no external tween library needed

### 5. Demo Page Integration

Add the VTuber avatar as a new panel/section on the demo page, OR create a new `/vtuber` route.

**Decision: New `/vtuber` route.** Reasons:
- The demo page is already dense with components
- VTuber view wants a large viewport for the 3D model
- Can be fullscreen-friendly for streaming/OBS capture
- Keeps the demo page unchanged

Route layout:
- Large center: VRM avatar with transparent/green-screen background option
- Small overlay: connection status, fit indicator, recenter button
- Bottom strip: EEG waveform (reuse EEGStrip component)

### 6. Coordinate System Mapping

**Muse 2 IMU axes** (headband worn on forehead):
- Accel X: forward/backward (pitch)
- Accel Y: left/right (roll)
- Accel Z: up/down (gravity when level)
- Gyro: matching axes, deg/s

**Three.js / VRM conventions:**
- Y-up coordinate system
- Head bone rotation: pitch around X, yaw around Y, roll around Z

The Madgwick filter outputs a quaternion in the sensor's frame. We'll need to apply a fixed rotation to map from Muse's frame to Three.js frame. This mapping is a known caveat — **discovering the exact mapping is a key goal of the demo.**

Initial guess for the transform:
```
three_q = CALIBRATION_ROTATION * madgwick_q * inverse(home_q)
```

Where `CALIBRATION_ROTATION` accounts for Muse being worn on the forehead (tilted ~15° from vertical). This will need empirical tuning with real hardware.

## New Dependencies

| Package | Purpose | Size |
|---|---|---|
| `@pixiv/three-vrm` | VRM model loading + humanoid/expression API | ~150KB |
| `ahrs` | Madgwick/Mahony sensor fusion | ~15KB |

Both are well-maintained and lightweight.

## Data Flow Summary

1. Backend streams raw IMU binary at 52Hz (no changes needed)
2. `useSensorStream` decodes IMU frames, stores latest accel+gyro in ref
3. `useHeadPose` reads IMU ref each animation frame, feeds Madgwick, outputs quaternion
4. `VTuberAvatar` receives quaternion + blink events, applies to VRM model
5. Three.js renders at 60fps with slerp smoothing between 52Hz pose updates

## Testing Plan

1. **Synthetic mode first:** Verify pipeline works end-to-end — model loads, bones respond to synthetic IMU noise, blink events trigger expression
2. **Real Muse:** Connect Muse 2, verify head tracking axes map correctly, tune Madgwick beta, measure latency, observe yaw drift over time
3. **Key caveats to document:**
   - Coordinate system mapping (Muse → Three.js)
   - Madgwick beta tuning for Muse's 52Hz
   - Yaw drift rate and recenter UX
   - Blink animation timing vs EEG detection latency
   - VRM model compatibility (different models may have different bone scales)

## Non-Goals (for demo phase)

- VMC protocol output
- Webcam hybrid tracking
- EEG brain-state → avatar effects (alpha aura, concentration glow)
- User VRM upload
- Green screen / OBS integration
- Lip sync, eye gaze, facial expressions beyond blink
- Performance optimization

## Files to Create/Modify

| File | Action |
|---|---|
| `frontend/src/hooks/useHeadPose.ts` | Create — Madgwick fusion hook |
| `frontend/src/components/demo/VTuberAvatar.tsx` | Create — VRM renderer component |
| `frontend/src/routes/vtuber.tsx` | Create — dedicated VTuber route |
| `frontend/src/hooks/useSensorStream.ts` | Modify — store IMU data instead of discarding |
| `frontend/package.json` | Modify — add `@pixiv/three-vrm`, `ahrs` |
| `frontend/public/models/` | Create — bundle a default VRM model |
