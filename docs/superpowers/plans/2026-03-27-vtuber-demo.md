# VTuber Head Control Demo — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Muse 2 IMU data through Madgwick sensor fusion to drive a VRM avatar's head bone, with EEG blink detection triggering eye-close expressions — all in the browser.

**Architecture:** Frontend-side sensor fusion. Raw IMU binary frames (52Hz) already arrive via WebSocket. A new `useHeadPose` hook runs Madgwick filter → quaternion. A new `VTuberAvatar` R3F component loads a VRM model and applies the quaternion to its head/neck bones + blink expressions. New `/vtuber` route hosts the 3D view.

**Tech Stack:** `@pixiv/three-vrm` (VRM loading + humanoid API), `ahrs` (Madgwick filter), `@react-three/fiber` + `@react-three/drei` (already installed), Three.js (already installed)

**Spec:** `docs/superpowers/specs/2026-03-27-vtuber-demo-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/package.json` | Modify | Add `@pixiv/three-vrm`, `ahrs` deps |
| `frontend/src/hooks/useSensorStream.ts` | Modify | Store latest IMU frame in ref instead of discarding |
| `frontend/src/lib/headPose.ts` | Create | Madgwick filter wrapper — pure logic, no React |
| `frontend/src/hooks/useHeadPose.ts` | Create | React hook: reads IMU ref, feeds headPose, outputs quaternion |
| `frontend/src/components/vtuber/VTuberAvatar.tsx` | Create | R3F component: loads VRM, applies head rotation + blink |
| `frontend/src/components/vtuber/BlinkController.ts` | Create | Blink animation state machine (timestamp-based ramp) |
| `frontend/src/routes/vtuber.tsx` | Create | `/vtuber` route with Canvas, overlays, recenter button |
| `frontend/public/models/default-avatar.vrm` | Create | Bundled CC0 VRM model from VRoid samples |

---

## Chunk 1: Dependencies + IMU Buffer

### Task 1: Install dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install packages**

```bash
cd frontend && pnpm add @pixiv/three-vrm ahrs
```

- [ ] **Step 2: Verify installation**

```bash
cd frontend && pnpm ls @pixiv/three-vrm ahrs
```

Expected: Both packages listed with versions.

- [ ] **Step 3: Verify dev server still starts**

```bash
cd frontend && pnpm dev &
sleep 5 && curl -s http://localhost:3000 | head -5
kill %1
```

Expected: HTML output, no build errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "feat(vtuber): add @pixiv/three-vrm and ahrs dependencies"
```

---

### Task 2: Store IMU data in useSensorStream

**Files:**
- Modify: `frontend/src/hooks/useSensorStream.ts`

- [ ] **Step 1: Add MSG_IMU import and imuRef**

In `frontend/src/hooks/useSensorStream.ts`, add `MSG_IMU` to the import from `../lib/protocol`:

```typescript
import {
  MSG_EEG, MSG_PPG, MSG_IMU,
  EEG_CHANNELS, PPG_CHANNELS,
  decodeBinaryFrame,
  getChannel,
  type BciEvent,
} from "../lib/protocol";
```

Add an `ImuSample` export and a ref inside `useSensorStream()`:

```typescript
export interface ImuSample {
  accel: Float32Array; // [ax, ay, az] in g's
  gyro: Float32Array;  // [gx, gy, gz] in deg/s
  timestamp: number;   // performance.now() when received
}
```

Inside the function body, after the existing refs:

```typescript
const imuRef = useRef<ImuSample | null>(null);
```

- [ ] **Step 2: Handle IMU frames**

Replace the comment on line 55 (`// IMU: not buffered for waveform, only used via metrics JSON`) with:

```typescript
} else if (frame.type === MSG_IMU) {
  const last = frame.samples - 1;
  imuRef.current = {
    accel: new Float32Array([
      frame.data[0 * frame.samples + last],
      frame.data[1 * frame.samples + last],
      frame.data[2 * frame.samples + last],
    ]),
    gyro: new Float32Array([
      frame.data[3 * frame.samples + last],
      frame.data[4 * frame.samples + last],
      frame.data[5 * frame.samples + last],
    ]),
    timestamp: performance.now(),
  };
}
```

Note: The `else if` chains after the existing `MSG_PPG` block. The closing `}` before the old comment becomes the start of the `else if`.

- [ ] **Step 3: Expose imuRef in the return value**

Add `imuRef` to the return object:

```typescript
return {
  buffers: buffersRef,
  metricsRef,
  eventsRef,
  imuRef,        // ← add this
  lastMessage,
  readyState,
  isConnected: readyState === ReadyState.OPEN,
  sendCommand,
  zunaStatus,
};
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSensorStream.ts
git commit -m "feat(vtuber): store latest IMU sample in useSensorStream"
```

---

## Chunk 2: Madgwick Sensor Fusion

### Task 3: Create headPose pure logic module

**Files:**
- Create: `frontend/src/lib/headPose.ts`

This module wraps the `ahrs` Madgwick filter with Muse-specific configuration and coordinate mapping. It is pure logic — no React, no DOM — so it can be tested independently.

- [ ] **Step 1: Create the headPose module**

Create `frontend/src/lib/headPose.ts`:

```typescript
import AHRS from "ahrs";
import { Quaternion } from "three";

const DEG2RAD = Math.PI / 180;

/**
 * Madgwick-based head pose estimator for Muse 2 IMU.
 *
 * Consumes raw accel (g's) + gyro (deg/s) at 52Hz,
 * outputs a quaternion relative to the "home" orientation.
 */
export class HeadPoseEstimator {
  private ahrs: InstanceType<typeof AHRS>;
  private homeInverse: Quaternion | null = null;
  private initialized = false;
  private frameCount = 0;

  // How many frames to accumulate before setting home pose (lets filter settle)
  private static SETTLE_FRAMES = 26; // ~0.5s at 52Hz

  constructor(beta = 0.4) {
    this.ahrs = new AHRS({
      sampleInterval: 52, // Hz
      algorithm: "Madgwick",
      beta,
    });
  }

  /**
   * Feed one IMU sample. Call at sensor rate (~52Hz).
   * @param accel [ax, ay, az] in g's
   * @param gyro  [gx, gy, gz] in deg/s
   */
  update(accel: Float32Array, gyro: Float32Array): void {
    this.ahrs.update(
      gyro[0] * DEG2RAD,
      gyro[1] * DEG2RAD,
      gyro[2] * DEG2RAD,
      accel[0],
      accel[1],
      accel[2],
    );

    this.frameCount++;

    // Auto-set home after filter settles
    if (!this.initialized && this.frameCount >= HeadPoseEstimator.SETTLE_FRAMES) {
      this.recenter();
      this.initialized = true;
    }
  }

  /**
   * Get current head orientation relative to home pose.
   * Returns identity quaternion until initialized.
   */
  getQuaternion(): Quaternion {
    if (!this.initialized) {
      return new Quaternion(); // identity
    }

    const raw = this.ahrs.getQuaternion();
    const current = new Quaternion(raw.x, raw.y, raw.z, raw.w);

    // Apply home offset: relative = homeInverse * current
    if (this.homeInverse) {
      return this.homeInverse.clone().multiply(current);
    }
    return current;
  }

  /**
   * Store current orientation as "home" (looking straight ahead).
   * All subsequent getQuaternion() calls return relative to this.
   */
  recenter(): void {
    const raw = this.ahrs.getQuaternion();
    const home = new Quaternion(raw.x, raw.y, raw.z, raw.w);
    this.homeInverse = home.clone().invert();
    this.initialized = true;
  }

  /** Reset filter and home pose. */
  reset(): void {
    this.ahrs = new AHRS({
      sampleInterval: 52,
      algorithm: "Madgwick",
      beta: 0.4,
    });
    this.homeInverse = null;
    this.initialized = false;
    this.frameCount = 0;
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors. If `ahrs` has no types, create a minimal declaration (see step 3).

- [ ] **Step 3: Add type declaration for ahrs if needed**

If step 2 fails with "Cannot find module 'ahrs'", create `frontend/src/types/ahrs.d.ts`:

```typescript
declare module "ahrs" {
  interface AHRSOptions {
    sampleInterval?: number;
    algorithm?: "Madgwick" | "Mahony";
    beta?: number;
    kp?: number;
    ki?: number;
  }

  class AHRS {
    constructor(options?: AHRSOptions);
    update(
      gx: number, gy: number, gz: number,
      ax: number, ay: number, az: number,
      mx?: number, my?: number, mz?: number,
    ): void;
    getQuaternion(): { x: number; y: number; z: number; w: number };
    getEulerAngles(): { heading: number; pitch: number; roll: number };
  }

  export default AHRS;
}
```

Then re-run `npx tsc --noEmit`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/headPose.ts frontend/src/types/ahrs.d.ts
git commit -m "feat(vtuber): add HeadPoseEstimator with Madgwick sensor fusion"
```

---

### Task 4: Create useHeadPose React hook

**Files:**
- Create: `frontend/src/hooks/useHeadPose.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/src/hooks/useHeadPose.ts`:

```typescript
import { useRef, useCallback } from "react";
import { useFrame } from "@react-three/fiber";
import { Quaternion } from "three";
import { HeadPoseEstimator } from "../lib/headPose";
import type { ImuSample } from "./useSensorStream";

/**
 * Drives Madgwick sensor fusion from IMU data each animation frame.
 * Must be used inside an R3F <Canvas>.
 *
 * @param imuRef - ref to latest IMU sample from useSensorStream
 * @param smoothing - slerp factor per frame (0 = no smoothing, 1 = frozen). Default 0.7.
 */
export function useHeadPose(
  imuRef: React.RefObject<ImuSample | null>,
  smoothing = 0.7,
) {
  const estimatorRef = useRef(new HeadPoseEstimator());
  const lastTimestampRef = useRef(0);
  const smoothedRef = useRef(new Quaternion());

  useFrame(() => {
    const sample = imuRef.current;
    if (!sample) return;

    // Only process new samples (avoid re-processing same data)
    if (sample.timestamp <= lastTimestampRef.current) return;
    lastTimestampRef.current = sample.timestamp;

    estimatorRef.current.update(sample.accel, sample.gyro);
    const target = estimatorRef.current.getQuaternion();

    // Slerp for smooth motion
    smoothedRef.current.slerp(target, 1 - smoothing);
  });

  const recenter = useCallback(() => {
    estimatorRef.current.recenter();
  }, []);

  const reset = useCallback(() => {
    estimatorRef.current.reset();
    smoothedRef.current.identity();
  }, []);

  return {
    quaternionRef: smoothedRef,
    recenter,
    reset,
  };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useHeadPose.ts
git commit -m "feat(vtuber): add useHeadPose hook with Madgwick + slerp smoothing"
```

---

## Chunk 3: VRM Avatar + Blink Animation

### Task 5: Download a default VRM model

**Files:**
- Create: `frontend/public/models/default-avatar.vrm`

- [ ] **Step 1: Download a CC0 VRM sample**

Download the VRoid sample model (AvatarSample_A, CC0 license) from the vrm-samples repo:

```bash
mkdir -p frontend/public/models
curl -L -o frontend/public/models/default-avatar.vrm \
  "https://github.com/madjin/vrm-samples/raw/main/vroid/AvatarSample_A.vrm"
```

If that URL fails, try the three-vrm repo's sample:

```bash
curl -L -o frontend/public/models/default-avatar.vrm \
  "https://github.com/pixiv/three-vrm/raw/release/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
```

- [ ] **Step 2: Verify file downloaded and is reasonable size**

```bash
ls -lh frontend/public/models/default-avatar.vrm
```

Expected: File exists, between 1-10MB.

- [ ] **Step 3: Add to .gitignore or commit**

VRM models are binary blobs. Add to git LFS or `.gitignore` and document the download step. For the demo, committing directly is acceptable if <5MB:

```bash
# If small enough to commit:
git add frontend/public/models/default-avatar.vrm
git commit -m "feat(vtuber): add default CC0 VRM avatar model"

# If too large, add to .gitignore instead:
# echo "frontend/public/models/*.vrm" >> .gitignore
# git add .gitignore
# git commit -m "chore: gitignore VRM model files (download separately)"
```

---

### Task 6: Create BlinkController

**Files:**
- Create: `frontend/src/components/vtuber/BlinkController.ts`

Pure logic class — no React. Manages the blink animation ramp (0→1→0 over 150ms).

- [ ] **Step 1: Create the blink controller**

Create `frontend/src/components/vtuber/BlinkController.ts`:

```typescript
/**
 * Timestamp-based blink animation.
 * On trigger: ramp 0→1 over HALF_DURATION, then 1→0 over HALF_DURATION.
 */
export class BlinkController {
  private static HALF_DURATION = 75; // ms

  private blinkStart: number | null = null;

  /** Trigger a blink animation. */
  trigger(): void {
    this.blinkStart = performance.now();
  }

  /**
   * Get current blink expression value (0-1).
   * Call every frame.
   */
  getValue(): number {
    if (this.blinkStart === null) return 0;

    const elapsed = performance.now() - this.blinkStart;
    const full = BlinkController.HALF_DURATION * 2;

    if (elapsed >= full) {
      this.blinkStart = null;
      return 0;
    }

    if (elapsed < BlinkController.HALF_DURATION) {
      // Closing: 0 → 1
      return elapsed / BlinkController.HALF_DURATION;
    }
    // Opening: 1 → 0
    return 1 - (elapsed - BlinkController.HALF_DURATION) / BlinkController.HALF_DURATION;
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/vtuber/BlinkController.ts
git commit -m "feat(vtuber): add BlinkController with 150ms ramp animation"
```

---

### Task 7: Create VTuberAvatar component

**Files:**
- Create: `frontend/src/components/vtuber/VTuberAvatar.tsx`

The main R3F component. Loads VRM, applies head rotation from quaternion ref, drives blink expression.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/vtuber/VTuberAvatar.tsx`:

```typescript
import { useEffect, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, type VRM } from "@pixiv/three-vrm";
import { Quaternion } from "three";
import { BlinkController } from "./BlinkController";

interface VTuberAvatarProps {
  /** Ref to smoothed quaternion from useHeadPose */
  quaternionRef: React.RefObject<Quaternion>;
  /** Latest bci_event kind — triggers blink on "single_blink" */
  lastBlinkTimestamp: number;
}

// Split rotation between neck (60%) and head (40%) for natural look
const NECK_WEIGHT = 0.6;
const HEAD_WEIGHT = 0.4;

export function VTuberAvatar({ quaternionRef, lastBlinkTimestamp }: VTuberAvatarProps) {
  const { scene } = useThree();
  const [vrm, setVrm] = useState<VRM | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blinkRef = useRef(new BlinkController());
  const prevBlinkTs = useRef(0);

  // Load VRM model
  useEffect(() => {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    loader.load(
      "/models/default-avatar.vrm",
      (gltf) => {
        const loadedVrm = gltf.userData.vrm as VRM;
        loadedVrm.scene.rotation.y = Math.PI; // Face the camera
        setVrm(loadedVrm);
      },
      undefined,
      (err) => {
        console.error("VRM load failed:", err);
        setError("Failed to load VRM model");
      },
    );
  }, []);

  // Add/remove VRM scene
  useEffect(() => {
    if (!vrm) return;
    scene.add(vrm.scene);
    return () => {
      scene.remove(vrm.scene);
    };
  }, [vrm, scene]);

  // Per-frame update
  useFrame((_, delta) => {
    if (!vrm) return;

    // --- Head rotation ---
    const q = quaternionRef.current;
    const neckBone = vrm.humanoid?.getRawBoneNode("neck");
    const headBone = vrm.humanoid?.getRawBoneNode("head");

    if (neckBone && headBone) {
      // Split quaternion between neck and head
      const identity = new Quaternion();
      const neckQ = identity.clone().slerp(q, NECK_WEIGHT);
      const headQ = identity.clone().slerp(q, HEAD_WEIGHT);
      neckBone.quaternion.copy(neckQ);
      headBone.quaternion.copy(headQ);
    } else if (headBone) {
      // Fallback: all rotation to head
      headBone.quaternion.copy(q);
    }

    // --- Blink ---
    if (lastBlinkTimestamp > prevBlinkTs.current) {
      prevBlinkTs.current = lastBlinkTimestamp;
      blinkRef.current.trigger();
    }

    const blinkValue = blinkRef.current.getValue();
    vrm.expressionManager?.setValue("blink", blinkValue);

    // --- Update VRM systems (expressions, spring bones, etc.) ---
    vrm.update(delta);
  });

  if (error) {
    return null; // Route will show error overlay
  }

  // VRM scene is added directly to the R3F scene via useEffect — no JSX mesh needed
  return null;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

If there are import issues with `three/addons/loaders/GLTFLoader.js`, use this alternative import:

```typescript
import { GLTFLoader } from "three-stdlib";
```

Or if three-stdlib isn't available (it's bundled with @react-three/drei):

```typescript
import { useLoader } from "@react-three/fiber";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
```

Adjust the import until it resolves, then proceed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/vtuber/VTuberAvatar.tsx
git commit -m "feat(vtuber): add VTuberAvatar component with head tracking + blink"
```

---

## Chunk 4: VTuber Route + Integration

### Task 8: Create the /vtuber route

**Files:**
- Create: `frontend/src/routes/vtuber.tsx`

- [ ] **Step 1: Create the route**

Create `frontend/src/routes/vtuber.tsx`:

```typescript
import { useState, useRef, useEffect } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { useEvents } from "../hooks/useEvents";
import { VTuberScene } from "../components/vtuber/VTuberScene";

export const Route = createFileRoute("/vtuber")({
  component: VTuberPage,
});

function VTuberPage() {
  const { buffers, metricsRef, eventsRef, imuRef, isConnected, sendCommand } =
    useSensorStream();
  const metrics = useMetrics(metricsRef);
  const { lastEvent } = useEvents(eventsRef);

  // Track last blink timestamp for the avatar
  const [lastBlinkTs, setLastBlinkTs] = useState(0);
  const prevEventRef = useRef<number>(0);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.timestamp === prevEventRef.current) return;
    prevEventRef.current = lastEvent.timestamp;

    if (lastEvent.kind === "single_blink" || lastEvent.kind === "double_blink") {
      setLastBlinkTs(lastEvent.timestamp);
    }
  }, [lastEvent]);

  const fitStatus = metrics?.eeg?.fit_status ?? "poor";

  return (
    <div className="relative h-screen w-screen bg-zinc-950">
      {/* 3D Canvas */}
      <Canvas
        camera={{ position: [0, 1.4, 1.2], fov: 35 }}
        className="absolute inset-0"
      >
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, 3, 2]} intensity={0.8} />
        <VTuberScene
          imuRef={imuRef}
          lastBlinkTimestamp={lastBlinkTs}
        />
        <OrbitControls
          target={[0, 1.3, 0]}
          enablePan={false}
          minDistance={0.5}
          maxDistance={3}
        />
      </Canvas>

      {/* Overlay: connection + fit + recenter */}
      <div className="absolute top-4 left-4 flex flex-col gap-2 text-sm font-mono">
        <div
          className={`rounded px-2 py-1 ${
            isConnected ? "bg-green-900/80 text-green-300" : "bg-red-900/80 text-red-300"
          }`}
        >
          {isConnected ? "Connected" : "Disconnected"}
        </div>
        {isConnected && (
          <div
            className={`rounded px-2 py-1 ${
              fitStatus === "good"
                ? "bg-green-900/80 text-green-300"
                : fitStatus === "adjust"
                  ? "bg-yellow-900/80 text-yellow-300"
                  : "bg-red-900/80 text-red-300"
            }`}
          >
            Fit: {fitStatus}
          </div>
        )}
      </div>

      {/* Instructions */}
      <div className="absolute bottom-4 left-4 text-xs text-zinc-500 font-mono">
        Move head to control avatar · Blink to trigger expression · Orbit: drag · Zoom: scroll
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create VTuberScene bridge component**

The `VTuberScene` component lives inside the R3F `<Canvas>` and bridges the hooks (which need R3F context) with the avatar.

Create `frontend/src/components/vtuber/VTuberScene.tsx`:

```typescript
import type { ImuSample } from "../../hooks/useSensorStream";
import { useHeadPose } from "../../hooks/useHeadPose";
import { VTuberAvatar } from "./VTuberAvatar";

interface VTuberSceneProps {
  imuRef: React.RefObject<ImuSample | null>;
  lastBlinkTimestamp: number;
}

/**
 * Bridge component inside R3F Canvas.
 * Connects useHeadPose (needs R3F context) to VTuberAvatar.
 */
export function VTuberScene({ imuRef, lastBlinkTimestamp }: VTuberSceneProps) {
  const { quaternionRef, recenter } = useHeadPose(imuRef);

  return (
    <>
      <VTuberAvatar
        quaternionRef={quaternionRef}
        lastBlinkTimestamp={lastBlinkTimestamp}
      />
    </>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: No errors.

- [ ] **Step 4: Smoke-test in browser**

```bash
cd frontend && pnpm dev
```

Open `http://localhost:3000/vtuber` in browser. Expected:
- Black background with lighting visible
- VRM model loads and appears (anime character facing camera)
- Connection status shows "Disconnected" (unless backend is running)
- No console errors (except possibly WebGL warnings on some systems)
- Orbit controls work (drag to rotate camera, scroll to zoom)

If the VRM model doesn't appear, check browser console for:
- 404 on `/models/default-avatar.vrm` → file not in `public/models/`
- CORS errors → shouldn't happen for local files
- VRM parse errors → model may be VRM 0.x vs 1.x, try a different sample

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/vtuber.tsx frontend/src/components/vtuber/VTuberScene.tsx
git commit -m "feat(vtuber): add /vtuber route with 3D canvas and overlays"
```

---

### Task 9: Add recenter button to the route

**Files:**
- Modify: `frontend/src/components/vtuber/VTuberScene.tsx`
- Modify: `frontend/src/routes/vtuber.tsx`

- [ ] **Step 1: Expose recenter via callback**

Update `VTuberScene` to accept and wire an `onRecenterRef`:

In `frontend/src/components/vtuber/VTuberScene.tsx`, add to props:

```typescript
interface VTuberSceneProps {
  imuRef: React.RefObject<ImuSample | null>;
  lastBlinkTimestamp: number;
  onRecenterRef: React.MutableRefObject<(() => void) | null>;
}
```

Inside the component, after `useHeadPose`:

```typescript
// Expose recenter to parent (outside Canvas)
onRecenterRef.current = recenter;
```

- [ ] **Step 2: Add recenter button to route**

In `frontend/src/routes/vtuber.tsx`, add a ref and pass it:

```typescript
const recenterRef = useRef<(() => void) | null>(null);
```

Pass to `VTuberScene`:

```typescript
<VTuberScene
  imuRef={imuRef}
  lastBlinkTimestamp={lastBlinkTs}
  onRecenterRef={recenterRef}
/>
```

Add a button in the overlay (after the fit indicator):

```typescript
<button
  onClick={() => recenterRef.current?.()}
  className="rounded bg-zinc-800 px-3 py-1 text-zinc-300 hover:bg-zinc-700 transition-colors"
>
  Recenter
</button>
```

- [ ] **Step 3: Also recenter on triple_blink event**

In the `useEffect` that handles blink events in `vtuber.tsx`, add:

```typescript
if (lastEvent.kind === "triple_blink") {
  recenterRef.current?.();
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/vtuber.tsx frontend/src/components/vtuber/VTuberScene.tsx
git commit -m "feat(vtuber): add recenter button and triple-blink recenter"
```

---

### Task 10: End-to-end test with synthetic backend

- [ ] **Step 1: Start backend in synthetic mode**

```bash
python -m backend.main --synthetic
```

Expected: Server starts on ws://localhost:8765, streaming synthetic EEG + IMU data.

- [ ] **Step 2: Open /vtuber in browser**

Navigate to `http://localhost:3000/vtuber`. Expected:
- Connection status: "Connected"
- VRM model visible
- Head may jitter slightly (synthetic IMU is noise) — this is expected
- No console errors

- [ ] **Step 3: Verify blink expression works**

Synthetic mode generates random bci_events. Wait for a blink event, or trigger one manually via browser console:

```javascript
// In browser console — simulate a blink event
window.dispatchEvent(new CustomEvent('test-blink'));
```

If blink events don't fire in synthetic mode, verify by checking the event log or adding a temporary `console.log` in the blink handler.

- [ ] **Step 4: Document observed caveats**

Create a brief notes file for findings during manual testing:

```bash
cat > docs/vtuber-demo-notes.md << 'EOF'
# VTuber Demo — Test Notes

## Synthetic Mode Observations
- [ ] Model loads correctly
- [ ] Head responds to IMU data (jitter from noise expected)
- [ ] Blink expression triggers on bci_event
- [ ] Recenter button works
- [ ] No console errors
- [ ] Frame rate acceptable (check with Stats)

## Real Muse Observations (fill in during hardware test)
- [ ] Coordinate mapping correct? (nod = pitch, turn = yaw, tilt = roll)
- [ ] Axes inverted? Which ones?
- [ ] Yaw drift rate (degrees per minute estimate)
- [ ] Madgwick beta value that feels best
- [ ] Blink animation timing vs detection latency
- [ ] Overall latency feel (responsive? laggy?)
- [ ] Any motion artifacts?
EOF
```

- [ ] **Step 5: Commit**

```bash
git add docs/vtuber-demo-notes.md
git commit -m "docs(vtuber): add test observation template for demo caveats"
```
