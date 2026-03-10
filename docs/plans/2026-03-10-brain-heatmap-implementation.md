# Brain Heatmap + ZUNA Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a real-time 3D brain heatmap to the dashboard, fed by per-channel band powers from the backend. Optionally enhance with ZUNA 23ch superresolution.

**Architecture:** Backend computes per-channel band powers at 1Hz and sends as `band_powers` JSON over WebSocket. Frontend renders a 3D head (React Three Fiber) with spherical spline interpolation from electrode values to vertex colors. ZUNA integration is behind `--zuna` flag — model loads once at startup, runs inference on 5s chunks.

**Tech Stack:** Python (BrainFlow, PyTorch, MNE), React (TanStack Start), React Three Fiber, Three.js, TypeScript

**Design docs:**
- `docs/plans/2026-03-10-brain-heatmap-design.md` — heatmap visual design, interpolation, test cases
- `docs/plans/2026-03-10-zuna-pipeline-design.md` — ZUNA integration, pipeline stages, protocol

---

## Task 1: Backend — BandPowerBroadcaster stage (4ch)

**Goal:** Send per-channel band powers as a new `band_powers` JSON message at 1Hz.

**Context:** The existing `BandPowerExtractor` (SLOW, 2s cadence) already computes band powers and stores them in `BandPowerResult`. Rather than duplicate computation, we add a new stage that reads `BandPowerResult` and emits a `band_powers` WebSocket message. This piggybacks on the existing 2s metrics loop — good enough for heatmap (design says 1Hz, but 0.5Hz with EMA smoothing looks identical).

**Files:**
- Create: `backend/pipeline/stages/band_power_broadcaster.py`
- Modify: `backend/pipeline/factory.py` — add stage
- Modify: `backend/pipeline/serialize.py` — add band_powers to output
- Modify: `backend/pipeline/types.py` — add channel names constant if needed
- Test: `tests/test_band_power_broadcaster.py`

**Step 1: Write the failing test**

```python
# tests/test_band_power_broadcaster.py
import numpy as np
from backend.pipeline.types import PipelineFrame, CH_NAMES
from backend.pipeline.stages.features import BandPowerResult
from backend.pipeline.stages.band_power_broadcaster import (
    BandPowerBroadcaster,
    BandPowerMessage,
)


def test_band_power_broadcaster_produces_message():
    """BandPowerBroadcaster reads BandPowerResult and produces BandPowerMessage."""
    stage = BandPowerBroadcaster()
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=1.0)

    # Simulate upstream BandPowerResult
    bp = BandPowerResult(
        band_powers={
            "delta": [4.1, 3.8, 3.5, 4.3],
            "theta": [5.2, 4.9, 5.1, 5.5],
            "alpha": [12.1, 6.5, 5.9, 13.2],
            "beta": [8.3, 7.1, 6.8, 9.1],
            "gamma": [2.1, 1.8, 1.9, 2.3],
        },
        theta_beta_ratio=[0.63, 0.69, 0.75, 0.60],
        frontal_alpha_asymmetry=0.1,
    )
    frame.set(bp)

    stage.process(frame)

    msg = frame.get(BandPowerMessage)
    assert msg is not None
    assert msg.mode == "4ch"
    assert "TP9" in msg.channels
    assert "AF7" in msg.channels
    assert "AF8" in msg.channels
    assert "TP10" in msg.channels
    assert msg.channels["TP9"]["delta"] == 4.1
    assert msg.channels["AF7"]["theta"] == 4.9
    assert msg.channels["TP10"]["gamma"] == 2.3


def test_band_power_broadcaster_skips_without_upstream():
    """No BandPowerResult upstream → no BandPowerMessage."""
    stage = BandPowerBroadcaster()
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=1.0)
    stage.process(frame)
    assert frame.get(BandPowerMessage) is None
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/test_band_power_broadcaster.py -v`
Expected: FAIL — module not found

**Step 3: Implement BandPowerBroadcaster**

```python
# backend/pipeline/stages/band_power_broadcaster.py
from dataclasses import dataclass, field
from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame, CH_NAMES
from backend.pipeline.stages.features import BandPowerResult

BAND_NAMES = ["delta", "theta", "alpha", "beta", "gamma"]


@dataclass
class BandPowerMessage:
    """Result type: per-channel band powers formatted for WebSocket."""
    mode: str  # "4ch" or "23ch"
    channels: dict[str, dict[str, float]] = field(default_factory=dict)


class BandPowerBroadcaster(Stage):
    """SLOW. Reads BandPowerResult, reformats as per-channel dict for heatmap."""

    name = "band_power_broadcaster"
    cadence = Cadence.SLOW

    def __init__(self, channel_names: list[str] | None = None):
        self.channel_names = channel_names or list(CH_NAMES)

    def process(self, frame: PipelineFrame) -> None:
        bp = frame.get(BandPowerResult)
        if bp is None:
            return

        channels = {}
        for i, ch_name in enumerate(self.channel_names):
            channels[ch_name] = {
                band: bp.band_powers[band][i]
                for band in BAND_NAMES
                if band in bp.band_powers and i < len(bp.band_powers[band])
            }

        mode = "4ch" if len(self.channel_names) <= 4 else "23ch"
        frame.set(BandPowerMessage(mode=mode, channels=channels))
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/test_band_power_broadcaster.py -v`
Expected: PASS

**Step 5: Wire into pipeline and serialization**

Add to `backend/pipeline/factory.py`:
```python
from backend.pipeline.stages.band_power_broadcaster import BandPowerBroadcaster

# In create_default_pipeline(), add after ConcentrationScorer:
    BandPowerBroadcaster(),
```

Add to `backend/pipeline/serialize.py` in `frame_to_metrics()`:
```python
from backend.pipeline.stages.band_power_broadcaster import BandPowerMessage

# After existing serialization blocks:
bpm = frame.get(BandPowerMessage)
if bpm:
    metrics["band_powers"] = {
        "mode": bpm.mode,
        "channels": bpm.channels,
    }
```

**Step 6: Run all tests**

Run: `PYTHONPATH=. python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Manual verification**

Run: `python -m backend.main --synthetic`
Open ws://localhost:8765 in browser console or wscat.
Confirm metrics JSON now includes `band_powers` key with `mode: "4ch"` and per-channel dicts.

**Step 8: Commit**

```bash
git add backend/pipeline/stages/band_power_broadcaster.py tests/test_band_power_broadcaster.py
git add backend/pipeline/factory.py backend/pipeline/serialize.py
git commit -m "feat(pipeline): add BandPowerBroadcaster stage for heatmap data"
```

---

## Task 2: Frontend — useBandPowers hook

**Goal:** Parse `band_powers` from the existing WebSocket metrics and expose to components.

**Context:** The existing `useSensorStream` hook handles binary frames and stores the latest JSON message in `metricsRef`. The `useMetrics` hook parses it every 250ms. We need to extract `band_powers` from the metrics payload. Since `band_powers` is now part of the metrics message (via `frame_to_metrics`), we just need a hook that reads it from the parsed metrics.

**Files:**
- Create: `frontend/src/hooks/useBandPowers.ts`
- Modify: `frontend/src/lib/protocol.ts` — add BandPowers type

**Step 1: Add TypeScript types**

Add to `frontend/src/lib/protocol.ts`:
```typescript
export interface BandPowers {
  mode: "4ch" | "23ch";
  channels: Record<string, Record<string, number>>;
  // Record<channelName, Record<bandName, power>>
  // e.g. { "TP9": { "delta": 4.1, "theta": 5.2, ... }, ... }
}
```

And add to the existing `Metrics` interface:
```typescript
band_powers?: BandPowers;
```

**Step 2: Create useBandPowers hook**

```typescript
// frontend/src/hooks/useBandPowers.ts
import { useRef, useCallback } from "react";
import type { Metrics, BandPowers } from "~/lib/protocol";

export type BandName = "delta" | "theta" | "alpha" | "beta" | "gamma" | "focus";

export function useBandPowers(metrics: Metrics | null) {
  const prevRef = useRef<BandPowers | null>(null);

  const getBandPowers = useCallback((): BandPowers | null => {
    if (!metrics?.band_powers) return prevRef.current;
    prevRef.current = metrics.band_powers;
    return metrics.band_powers;
  }, [metrics]);

  return { getBandPowers };
}

/**
 * Extract a single value per channel for a given band.
 * For "focus", computes theta/beta ratio.
 */
export function extractBandValues(
  bp: BandPowers,
  band: BandName,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [ch, bands] of Object.entries(bp.channels)) {
    if (band === "focus") {
      const theta = bands.theta ?? 0;
      const beta = bands.beta ?? 1;
      result[ch] = beta > 0 ? theta / beta : 0;
    } else {
      result[ch] = bands[band] ?? 0;
    }
  }
  return result;
}
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/useBandPowers.ts frontend/src/lib/protocol.ts
git commit -m "feat(frontend): add useBandPowers hook and BandPowers type"
```

---

## Task 3: Frontend — Install React Three Fiber

**Goal:** Add R3F and Three.js dependencies.

**Files:**
- Modify: `frontend/package.json`

**Step 1: Install dependencies**

```bash
cd frontend && pnpm add three @react-three/fiber @react-three/drei && pnpm add -D @types/three
```

**Step 2: Verify build**

```bash
cd frontend && pnpm build
```
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "deps(frontend): add React Three Fiber, drei, three"
```

---

## Task 4: Frontend — Electrode positions & interpolation math

**Goal:** Define 10-20 electrode positions in spherical coordinates, compute spherical spline weight matrix for interpolation from electrodes to mesh vertices.

**Context:** This is pure math — no rendering yet. We need electrode positions that work for both 4ch (TP9, AF7, AF8, TP10) and 23ch (full 10-20 montage). The weight matrix maps electrode values → vertex colors on the head mesh.

**Files:**
- Create: `frontend/src/lib/electrodes.ts` — electrode positions
- Create: `frontend/src/lib/interpolation.ts` — spherical spline math

**Step 1: Define electrode positions**

```typescript
// frontend/src/lib/electrodes.ts

/** Electrode position in spherical coordinates (theta, phi) on unit sphere.
 *  theta: polar angle from top (0 = Cz/vertex, pi/2 = equator)
 *  phi: azimuthal angle (0 = nose, pi/2 = left ear, -pi/2 = right ear)
 */
export interface ElectrodePosition {
  name: string;
  theta: number;  // radians from top
  phi: number;    // radians from nose (CCW from above)
}

// Standard 10-20 positions as (theta, phi) on unit sphere
// Based on standard spherical head model
// theta: 0 = top (Cz), increases toward equator
// phi: 0 = nasion (front), pi/2 = left, -pi/2 = right, pi = inion (back)
export const ELECTRODES_23CH: ElectrodePosition[] = [
  // Frontal pole
  { name: "Fp1", theta: 0.51, phi: 0.31 },
  { name: "Fp2", theta: 0.51, phi: -0.31 },
  // Frontal
  { name: "F7",  theta: 0.67, phi: 0.79 },
  { name: "F3",  theta: 0.47, phi: 0.39 },
  { name: "Fz",  theta: 0.35, phi: 0.0 },
  { name: "F4",  theta: 0.47, phi: -0.39 },
  { name: "F8",  theta: 0.67, phi: -0.79 },
  // Anterior frontal (Muse positions)
  { name: "AF7", theta: 0.58, phi: 0.59 },
  { name: "AF8", theta: 0.58, phi: -0.59 },
  // Temporal
  { name: "T7",  theta: 0.79, phi: 1.18 },
  { name: "T8",  theta: 0.79, phi: -1.18 },
  // Temporal-parietal (Muse positions)
  { name: "TP9", theta: 0.87, phi: 1.38 },
  { name: "TP10",theta: 0.87, phi: -1.38 },
  // Central
  { name: "C3",  theta: 0.47, phi: 0.79 },
  { name: "Cz",  theta: 0.0,  phi: 0.0 },
  { name: "C4",  theta: 0.47, phi: -0.79 },
  // Parietal
  { name: "P7",  theta: 0.67, phi: 1.57 },
  { name: "P3",  theta: 0.47, phi: 1.18 },
  { name: "Pz",  theta: 0.35, phi: Math.PI },
  { name: "P4",  theta: 0.47, phi: -1.18 },
  { name: "P8",  theta: 0.67, phi: -1.57 },
  // Occipital
  { name: "O1",  theta: 0.51, phi: 2.83 },
  { name: "O2",  theta: 0.51, phi: -2.83 },
];

export const ELECTRODES_4CH: ElectrodePosition[] =
  ELECTRODES_23CH.filter((e) =>
    ["TP9", "AF7", "AF8", "TP10"].includes(e.name)
  );

/** Convert spherical (theta, phi) to Cartesian on unit sphere */
export function sphericalToCartesian(
  theta: number,
  phi: number,
): [number, number, number] {
  const x = Math.sin(theta) * Math.sin(phi);
  const y = Math.cos(theta);
  const z = Math.sin(theta) * Math.cos(phi);
  return [x, y, z];
}
```

**Step 2: Implement interpolation**

```typescript
// frontend/src/lib/interpolation.ts
import type { ElectrodePosition } from "./electrodes";
import { sphericalToCartesian } from "./electrodes";

/**
 * Compute inverse-distance weighting matrix from electrodes to mesh vertices.
 * Uses spherical geodesic distance with power=2 (IDW).
 *
 * Returns Float32Array of shape [numVertices * numElectrodes] (row-major).
 * Each row sums to 1.0.
 */
export function computeInterpolationWeights(
  vertices: Float32Array,       // flat xyz, length = numVerts * 3
  electrodes: ElectrodePosition[],
  power: number = 2,
  smoothing: number = 0.01,     // prevents singularity at electrode positions
): Float32Array {
  const numVerts = vertices.length / 3;
  const numElec = electrodes.length;
  const weights = new Float32Array(numVerts * numElec);

  // Electrode positions in Cartesian
  const elecXYZ = electrodes.map((e) => sphericalToCartesian(e.theta, e.phi));

  for (let v = 0; v < numVerts; v++) {
    const vx = vertices[v * 3];
    const vy = vertices[v * 3 + 1];
    const vz = vertices[v * 3 + 2];

    // Normalize vertex to unit sphere for distance computation
    const vLen = Math.sqrt(vx * vx + vy * vy + vz * vz);
    const nvx = vx / vLen;
    const nvy = vy / vLen;
    const nvz = vz / vLen;

    let weightSum = 0;
    for (let e = 0; e < numElec; e++) {
      const [ex, ey, ez] = elecXYZ[e];
      const dx = nvx - ex;
      const dy = nvy - ey;
      const dz = nvz - ez;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) + smoothing;
      const w = 1 / Math.pow(dist, power);
      weights[v * numElec + e] = w;
      weightSum += w;
    }
    // Normalize row to sum to 1
    for (let e = 0; e < numElec; e++) {
      weights[v * numElec + e] /= weightSum;
    }
  }

  return weights;
}

/**
 * Interpolate electrode values to vertex values using precomputed weights.
 * electrodeValues: one value per electrode (e.g., alpha power)
 * Returns one value per vertex.
 */
export function interpolateToVertices(
  weights: Float32Array,
  electrodeValues: number[],
  numVertices: number,
): Float32Array {
  const numElec = electrodeValues.length;
  const result = new Float32Array(numVertices);

  for (let v = 0; v < numVertices; v++) {
    let val = 0;
    for (let e = 0; e < numElec; e++) {
      val += weights[v * numElec + e] * electrodeValues[e];
    }
    result[v] = val;
  }

  return result;
}
```

**Step 3: Commit**

```bash
git add frontend/src/lib/electrodes.ts frontend/src/lib/interpolation.ts
git commit -m "feat(frontend): add electrode positions and interpolation math"
```

---

## Task 5: Frontend — BrainHeatmap component (static rendering)

**Goal:** Render a 3D head with vertex coloring, OrbitControls, and a nose indicator. Start with static colors to verify geometry.

**Files:**
- Create: `frontend/src/components/BrainHeatmap.tsx`

**Step 1: Create BrainHeatmap component**

```tsx
// frontend/src/components/BrainHeatmap.tsx
import { useRef, useMemo, useEffect, useCallback } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import {
  ELECTRODES_4CH,
  ELECTRODES_23CH,
  sphericalToCartesian,
  type ElectrodePosition,
} from "~/lib/electrodes";
import {
  computeInterpolationWeights,
  interpolateToVertices,
} from "~/lib/interpolation";
import type { BandPowers } from "~/lib/protocol";
import { extractBandValues, type BandName } from "~/hooks/useBandPowers";

// --- Color scale: blue → cyan → green → yellow → red ---
const COLOR_STOPS = [
  new THREE.Color(0x0000ff), // 0.0 blue
  new THREE.Color(0x00ffff), // 0.25 cyan
  new THREE.Color(0x00ff00), // 0.5 green
  new THREE.Color(0xffff00), // 0.75 yellow
  new THREE.Color(0xff0000), // 1.0 red
];

function valueToColor(t: number, target: THREE.Color): void {
  const clamped = Math.max(0, Math.min(1, t));
  const idx = clamped * (COLOR_STOPS.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, COLOR_STOPS.length - 1);
  const frac = idx - lo;
  target.lerpColors(COLOR_STOPS[lo], COLOR_STOPS[hi], frac);
}

// --- Baseline normalization ---
interface BaselineState {
  min: number;
  max: number;
  samples: number;
  ready: boolean;
}

function updateBaseline(state: BaselineState, values: number[]): void {
  for (const v of values) {
    if (state.samples === 0) {
      state.min = v;
      state.max = v;
    } else {
      // EMA toward observed range
      const alpha = state.samples < 30 ? 0.1 : 0.02;
      if (v < state.min) state.min += (v - state.min) * alpha;
      if (v > state.max) state.max += (v - state.max) * alpha;
    }
    state.samples++;
  }
  state.ready = state.samples >= 5;
}

function normalize(value: number, baseline: BaselineState): number {
  if (!baseline.ready || baseline.max <= baseline.min) return 0.5;
  return (value - baseline.min) / (baseline.max - baseline.min);
}

// --- Head mesh component ---
interface HeadMeshProps {
  bandPowers: BandPowers | null;
  selectedBand: BandName;
  emaAlpha: number;
  debug?: "static" | "wave" | "random";
}

function HeadMesh({ bandPowers, selectedBand, emaAlpha, debug }: HeadMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const geometryRef = useRef<THREE.SphereGeometry>(null);

  // Build geometry once
  const geometry = useMemo(() => {
    const geo = new THREE.SphereGeometry(1, 48, 32);
    // Slightly elongate vertically, flatten back
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      let y = pos.getY(i);
      const z = pos.getZ(i);
      y *= 1.15; // taller
      // Flatten back slightly
      if (z < -0.3) {
        const factor = 1 - 0.15 * Math.abs(z + 0.3);
        pos.setZ(i, z * Math.max(factor, 0.85));
      }
      pos.setY(i, y);
    }
    pos.needsUpdate = true;
    geo.computeVertexNormals();

    // Add vertex colors
    const colors = new Float32Array(pos.count * 3);
    colors.fill(0.5); // neutral green-ish
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    return geo;
  }, []);

  // Determine electrodes based on mode
  const electrodes = useMemo(() => {
    if (bandPowers && Object.keys(bandPowers.channels).length > 4) {
      return ELECTRODES_23CH;
    }
    return ELECTRODES_4CH;
  }, [bandPowers?.mode]);

  // Compute interpolation weights (recompute when electrode set changes)
  const weights = useMemo(() => {
    const pos = geometry.attributes.position as THREE.BufferAttribute;
    return computeInterpolationWeights(
      pos.array as Float32Array,
      electrodes,
    );
  }, [geometry, electrodes]);

  // State for EMA smoothing and baseline
  const smoothedRef = useRef<Float32Array | null>(null);
  const baselineRef = useRef<BaselineState>({
    min: 0, max: 1, samples: 0, ready: false,
  });

  // Update vertex colors each frame
  useFrame(({ clock }) => {
    const colorAttr = geometry.attributes.color as THREE.BufferAttribute;
    const numVerts = colorAttr.count;

    // Get electrode values
    let electrodeValues: number[];

    if (debug === "static") {
      electrodeValues = electrodes.map((_, i) => (i + 1) / electrodes.length);
    } else if (debug === "wave") {
      const t = clock.getElapsedTime();
      electrodeValues = electrodes.map((e) => {
        return 0.5 + 0.5 * Math.sin(t * Math.PI - e.theta * 2);
      });
    } else if (debug === "random") {
      // Only update once per second
      const sec = Math.floor(clock.getElapsedTime());
      electrodeValues = electrodes.map((_, i) =>
        Math.abs(Math.sin(sec * 13.7 + i * 7.3))
      );
    } else if (bandPowers) {
      const bandValues = extractBandValues(bandPowers, selectedBand);
      electrodeValues = electrodes.map((e) => bandValues[e.name] ?? 0);
    } else {
      return; // No data
    }

    // Update baseline normalization
    if (!debug) {
      updateBaseline(baselineRef.current, electrodeValues);
    }

    // Interpolate to vertices
    const raw = interpolateToVertices(weights, electrodeValues, numVerts);

    // EMA smoothing
    if (!smoothedRef.current || smoothedRef.current.length !== numVerts) {
      smoothedRef.current = raw;
    } else {
      const s = smoothedRef.current;
      for (let i = 0; i < numVerts; i++) {
        s[i] = emaAlpha * raw[i] + (1 - emaAlpha) * s[i];
      }
    }

    // Apply color map
    const color = new THREE.Color();
    const colors = colorAttr.array as Float32Array;
    const s = smoothedRef.current;

    for (let i = 0; i < numVerts; i++) {
      const normalized = debug
        ? s[i]  // debug modes are already 0-1
        : normalize(s[i], baselineRef.current);
      valueToColor(normalized, color);
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
    }

    colorAttr.needsUpdate = true;
  });

  return (
    <mesh ref={meshRef} geometry={geometry}>
      <meshStandardMaterial
        vertexColors
        transparent
        opacity={0.85}
        roughness={0.3}
        metalness={0.1}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// --- Nose indicator ---
function NoseIndicator() {
  return (
    <mesh position={[0, -0.1, 1.05]} rotation={[Math.PI / 2, 0, 0]}>
      <coneGeometry args={[0.08, 0.2, 8]} />
      <meshStandardMaterial color="#888" />
    </mesh>
  );
}

// --- Electrode dots ---
function ElectrodeDots({ electrodes }: { electrodes: ElectrodePosition[] }) {
  const positions = useMemo(
    () => electrodes.map((e) => {
      const [x, y, z] = sphericalToCartesian(e.theta, e.phi);
      // Scale to head radius + small offset
      return new THREE.Vector3(x * 1.02, y * 1.15 * 1.02, z * 1.02);
    }),
    [electrodes],
  );

  return (
    <>
      {positions.map((pos, i) => (
        <mesh key={electrodes[i].name} position={pos}>
          <sphereGeometry args={[0.03, 8, 8]} />
          <meshStandardMaterial
            color="#00ff88"
            emissive="#00ff88"
            emissiveIntensity={0.5}
          />
        </mesh>
      ))}
    </>
  );
}

// --- Disclaimer ---
function Disclaimer({ mode }: { mode: string }) {
  const text =
    mode === "23ch"
      ? "AI-reconstructed from 4 sensors — more spatial detail but not equivalent to physical electrodes"
      : "Estimated from 4 sensors — visualization only, not clinical EEG";
  return (
    <div
      style={{
        textAlign: "center",
        fontSize: "11px",
        color: "#888",
        padding: "4px 8px",
      }}
    >
      {text}
    </div>
  );
}

// --- Main component ---
export interface BrainHeatmapProps {
  bandPowers: BandPowers | null;
  selectedBand?: BandName;
  emaAlpha?: number;
  debug?: "static" | "wave" | "random";
  height?: number;
}

export function BrainHeatmap({
  bandPowers,
  selectedBand = "focus",
  emaAlpha = 0.3,
  debug,
  height = 300,
}: BrainHeatmapProps) {
  const electrodes = useMemo(() => {
    if (bandPowers && Object.keys(bandPowers.channels).length > 4) {
      return ELECTRODES_23CH;
    }
    return ELECTRODES_4CH;
  }, [bandPowers?.mode]);

  const mode = bandPowers?.mode ?? "4ch";

  return (
    <div>
      <Canvas
        style={{ height, background: "#111" }}
        camera={{ position: [0, 0.5, 2.5], fov: 45 }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[2, 3, 4]} intensity={0.8} />
        <HeadMesh
          bandPowers={bandPowers}
          selectedBand={selectedBand}
          emaAlpha={emaAlpha}
          debug={debug}
        />
        <NoseIndicator />
        <ElectrodeDots electrodes={electrodes} />
        <OrbitControls
          enablePan={false}
          enableZoom={false}
          autoRotate
          autoRotateSpeed={0.5}
        />
      </Canvas>
      <Disclaimer mode={mode} />
    </div>
  );
}
```

**Step 2: Verify it renders with debug mode**

Add temporarily to the dashboard route (`frontend/src/routes/index.tsx`):
```tsx
import { BrainHeatmap } from "~/components/BrainHeatmap";
// In the JSX, add:
<BrainHeatmap debug="wave" bandPowers={null} height={300} />
```

Run: `cd frontend && pnpm dev`
Open http://localhost:3000 — should see a colored 3D head with a wave pattern.

**Step 3: Commit**

```bash
git add frontend/src/components/BrainHeatmap.tsx
git commit -m "feat(frontend): add BrainHeatmap 3D component with interpolation"
```

---

## Task 6: Frontend — Band selection toggle

**Goal:** Add toggle strip below the heatmap for selecting which band drives the color map.

**Files:**
- Create: `frontend/src/components/BandSelector.tsx`

**Step 1: Create BandSelector**

```tsx
// frontend/src/components/BandSelector.tsx
import type { BandName } from "~/hooks/useBandPowers";

const BANDS: { name: BandName; label: string }[] = [
  { name: "focus", label: "FOCUS" },
  { name: "theta", label: "θ" },
  { name: "alpha", label: "α" },
  { name: "beta", label: "β" },
  { name: "gamma", label: "γ" },
  { name: "delta", label: "δ" },
];

interface BandSelectorProps {
  selected: BandName;
  onSelect: (band: BandName) => void;
}

export function BandSelector({ selected, onSelect }: BandSelectorProps) {
  return (
    <div style={{ display: "flex", justifyContent: "center", gap: "4px", padding: "8px 0" }}>
      {BANDS.map(({ name, label }) => (
        <button
          key={name}
          onClick={() => onSelect(name)}
          style={{
            padding: "4px 12px",
            border: selected === name ? "1px solid #00ff88" : "1px solid #444",
            background: selected === name ? "#00ff8820" : "transparent",
            color: selected === name ? "#00ff88" : "#aaa",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "14px",
            fontWeight: selected === name ? "bold" : "normal",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/BandSelector.tsx
git commit -m "feat(frontend): add BandSelector toggle for heatmap"
```

---

## Task 7: Frontend — Wire heatmap into dashboard

**Goal:** Connect BrainHeatmap to live WebSocket data, add band selection state, place in dashboard layout.

**Files:**
- Modify: `frontend/src/routes/index.tsx` — add heatmap panel
- Modify: `frontend/src/hooks/useBandPowers.ts` — if adjustments needed

**Step 1: Add heatmap to dashboard**

In `frontend/src/routes/index.tsx`, add:

```tsx
import { useState } from "react";
import { BrainHeatmap } from "~/components/BrainHeatmap";
import { BandSelector } from "~/components/BandSelector";
import { useBandPowers, type BandName } from "~/hooks/useBandPowers";
```

In the component body:
```tsx
const { getBandPowers } = useBandPowers(metrics);
const [selectedBand, setSelectedBand] = useState<BandName>("focus");
```

In the JSX layout (exact placement depends on existing layout — put it in the right column or below waveforms):
```tsx
<div>
  <BrainHeatmap
    bandPowers={getBandPowers()}
    selectedBand={selectedBand}
    height={300}
  />
  <BandSelector selected={selectedBand} onSelect={setSelectedBand} />
</div>
```

**Step 2: Test with synthetic backend**

Run backend: `python -m backend.main --synthetic`
Run frontend: `cd frontend && pnpm dev`
Open http://localhost:3000 — heatmap should show live color changes from synthetic EEG band powers.

**Step 3: Commit**

```bash
git add frontend/src/routes/index.tsx
git commit -m "feat(frontend): wire BrainHeatmap into dashboard with band selection"
```

---

## Task 8: Backend — ZunaStage (optional, `--zuna` flag)

**Goal:** Load ZUNA model at startup, buffer 5s of EEG, run inference, emit 23ch data.

**Context:** This task requires reading ZUNA internals carefully. The model is at `zuna.inference.AY2l.lingua.apps.AY2latent_bci.transformer.EncoderDecoder`. It expects specific input format: `[B, seq_len, 131]` tensor. Preprocessing uses MNE for spherical spline interpolation 4→23ch.

**IMPORTANT:** Before implementing, read these files to understand ZUNA's API:
- `/home/newub/miniconda3/lib/python3.12/site-packages/zuna/pipeline.py` — existing subprocess flow
- `zuna/inference/AY2l/lingua/apps/AY2latent_bci/transformer.py` — `EncoderDecoder`, `ModelArgs`, `sample()`
- `zuna/preprocessing/processor.py` — epoch creation, normalization
- `scripts/run_zuna.py` — existing script that calls ZUNA

**Files:**
- Create: `backend/pipeline/stages/zuna_stage.py`
- Modify: `backend/pipeline/factory.py` — add ZunaStage when `--zuna`
- Modify: `backend/pipeline/stages/band_power_broadcaster.py` — accept 23ch channel names
- Modify: `backend/main.py` — add `--zuna` CLI arg, pass to factory
- Test: `tests/test_zuna_stage.py`

**Step 1: Write test for ZunaStage buffer behavior (no GPU needed)**

```python
# tests/test_zuna_stage.py
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from backend.pipeline.types import PipelineFrame


def test_zuna_stage_buffers_until_full():
    """ZunaStage should accumulate data and only produce output after 5s."""
    with patch("backend.pipeline.stages.zuna_stage.load_zuna_model") as mock_load:
        mock_model = MagicMock()
        mock_load.return_value = mock_model

        from backend.pipeline.stages.zuna_stage import ZunaStage, ZunaResult
        stage = ZunaStage(device="cpu")

        # Send 1s of data (256 samples) — not enough
        frame = PipelineFrame(
            eeg=np.random.randn(4, 256).astype(np.float32),
            ppg=None, imu=None, timestamp=1.0,
        )
        stage.process(frame)
        assert frame.get(ZunaResult) is None  # still buffering

        # Send 4 more seconds
        for i in range(4):
            frame = PipelineFrame(
                eeg=np.random.randn(4, 256).astype(np.float32),
                ppg=None, imu=None, timestamp=2.0 + i,
            )
            stage.process(frame)

        # After 5s total, should have produced a result (mock the inference)
        # The exact behavior depends on how we mock model.sample()


def test_zuna_stage_skips_without_eeg():
    """ZunaStage should do nothing if frame.eeg is None."""
    with patch("backend.pipeline.stages.zuna_stage.load_zuna_model") as mock_load:
        mock_load.return_value = MagicMock()
        from backend.pipeline.stages.zuna_stage import ZunaStage, ZunaResult
        stage = ZunaStage(device="cpu")

        frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=1.0)
        stage.process(frame)
        assert frame.get(ZunaResult) is None
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tests/test_zuna_stage.py -v`
Expected: FAIL — module not found

**Step 3: Implement ZunaStage**

```python
# backend/pipeline/stages/zuna_stage.py
"""ZUNA superresolution stage — 4ch → 23ch EEG via diffusion model.

Requires: torch, zuna package, MNE
Only active when --zuna flag is passed.
"""
import logging
import time
from dataclasses import dataclass, field

import numpy as np

from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame

log = logging.getLogger(__name__)

# 23ch standard 10-20 montage output by ZUNA
ZUNA_CH_NAMES = [
    "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "T7", "C3", "Cz", "C4", "T8",
    "TP9", "TP10",
    "P7", "P3", "Pz", "P4", "P8",
    "O1", "O2",
    "AF7", "AF8",
]

SFREQ = 256
EPOCH_SAMPLES = SFREQ * 5  # 1280 (5s)
HOP_SAMPLES = SFREQ * 2    # 512 (2s hop → matches SLOW cadence)


@dataclass
class ZunaResult:
    """23-channel superresolved EEG for one epoch."""
    eeg_23ch: np.ndarray  # (23, 1280)
    channel_names: list[str] = field(default_factory=lambda: list(ZUNA_CH_NAMES))


def load_zuna_model(device: str = "cuda"):
    """Load ZUNA EncoderDecoder model from HuggingFace cache."""
    import torch
    from huggingface_hub import snapshot_download

    log.info("Downloading/loading ZUNA model...")
    model_path = snapshot_download("Zyphra/ZUNA")

    # Import ZUNA internals
    from zuna.inference.AY2l.lingua.apps.AY2latent_bci.transformer import (
        EncoderDecoder,
    )
    from zuna.inference.AY2l.lingua.apps.AY2latent_bci.args import ModelArgs
    import json
    from pathlib import Path
    from safetensors.torch import load_file

    # Load model config
    config_path = Path(model_path) / "config.json"
    with open(config_path) as f:
        config = json.load(f)

    args = ModelArgs(**config)
    model = EncoderDecoder(args).to(device)

    # Load weights
    weights_path = Path(model_path) / "model.safetensors"
    state_dict = load_file(str(weights_path))
    model.load_state_dict(state_dict)
    model.eval()

    vram_mb = torch.cuda.memory_allocated(device) / 1024 / 1024
    log.info("ZUNA model loaded (%.0f MB VRAM)", vram_mb)

    return model


class ZunaStage(Stage):
    """SLOW. Buffers 5s of 4ch EEG, runs ZUNA inference, emits 23ch.

    Only instantiated when --zuna flag is passed.
    """

    name = "zuna_stage"
    cadence = Cadence.SLOW

    def __init__(self, device: str = "cuda"):
        import torch
        self.device = device
        self.model = load_zuna_model(device)
        self.buffer = np.zeros((4, 0), dtype=np.float64)
        self._torch = torch

    def process(self, frame: PipelineFrame) -> None:
        if frame.eeg is None or frame.eeg.shape[1] == 0:
            return

        # Accumulate
        self.buffer = np.hstack([self.buffer, frame.eeg.astype(np.float64)])

        if self.buffer.shape[1] < EPOCH_SAMPLES:
            return  # still buffering

        # Take 5s epoch, slide buffer
        epoch_4ch = self.buffer[:, :EPOCH_SAMPLES]
        self.buffer = self.buffer[:, HOP_SAMPLES:]

        try:
            t0 = time.monotonic()
            result_23ch = self._run_inference(epoch_4ch)
            dt = time.monotonic() - t0
            log.debug("ZUNA inference: %.2fs for 5s epoch", dt)
            frame.set(ZunaResult(eeg_23ch=result_23ch))
        except Exception:
            log.exception("ZUNA inference failed, skipping epoch")

    def _run_inference(self, epoch_4ch: np.ndarray) -> np.ndarray:
        """Preprocess 4ch → 23ch interpolation → model.sample() → 23ch output."""
        import mne
        import torch

        # Step 1: Create MNE raw from 4ch
        info = mne.create_info(
            ch_names=["TP9", "AF7", "AF8", "TP10"],
            sfreq=SFREQ,
            ch_types="eeg",
        )
        raw = mne.io.RawArray(epoch_4ch * 1e-6, info)  # µV → V for MNE
        raw.set_montage("standard_1020")

        # Step 2: Preprocess (notch + highpass)
        raw.notch_filter(50.0, verbose=False)
        raw.filter(l_freq=0.1, h_freq=None, verbose=False)

        # Step 3: Spherical spline interpolation 4→23ch
        target_info = mne.create_info(
            ch_names=ZUNA_CH_NAMES,
            sfreq=SFREQ,
            ch_types="eeg",
        )
        target_info.set_montage("standard_1020")
        # Use MNE interpolation — raw must have all target channels
        # This is the tricky part: we need to interpolate missing channels
        # Using ZUNA's preprocessing approach
        from zuna.preprocessing.processor import ZUNAPreprocessor
        # NOTE: The exact API may differ — read ZUNA source to confirm.
        # Fallback: manual spherical spline using scipy

        # Step 4: Normalize (divide by 10.0)
        data_23ch = raw.get_data() * 1e6 / 10.0  # V → µV → ZUNA scale

        # Step 5: Prepare tensor [B=1, seq_len=1280, 131]
        # ZUNA expects specific input format — check transformer.py
        encoder_input = torch.tensor(
            data_23ch.T,  # (1280, 23) → need to pad/format to (1280, 131)
            dtype=torch.float32,
        ).unsqueeze(0).to(self.device)

        # Step 6: Run inference
        with torch.no_grad():
            final_z, _ = self.model.sample(
                encoder_input=encoder_input,
                seq_lens=torch.tensor([EPOCH_SAMPLES]),
                tok_idx=None,  # Check if needed
                sample_steps=50,
            )

        # Step 7: Denormalize and return
        output = final_z.squeeze(0).cpu().numpy().T * 10.0  # (23, 1280) in µV
        return output
```

**NOTE:** The `_run_inference` method has several `# NOTE` comments where the exact ZUNA API needs verification. The implementer MUST read the ZUNA source files listed above and adjust:
- How `encoder_input` is formatted (padding to 131 features)
- Whether `tok_idx` is required and how to compute it
- How to do the 4→23ch interpolation (ZUNA's preprocessor vs manual)
- The exact `model.sample()` call signature

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. python -m pytest tests/test_zuna_stage.py -v`
Expected: PASS (buffer tests use mocked model)

**Step 5: Wire into factory with --zuna flag**

Modify `backend/main.py` argparse:
```python
parser.add_argument("--zuna", action="store_true", help="Enable ZUNA 23ch superresolution (requires GPU)")
```

Modify `backend/pipeline/factory.py`:
```python
def create_default_pipeline(enable_zuna: bool = False) -> Pipeline:
    stages = [
        WaveletDenoiser(),
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
    ]

    if enable_zuna:
        try:
            from backend.pipeline.stages.zuna_stage import ZunaStage, ZUNA_CH_NAMES
            stages.append(ZunaStage())
            stages.append(BandPowerBroadcaster(channel_names=list(ZUNA_CH_NAMES)))
        except Exception as e:
            log.warning("ZUNA failed to load, falling back to 4ch: %s", e)
            stages.append(BandPowerBroadcaster())
    else:
        stages.append(BandPowerBroadcaster())

    stages.extend([
        SpeechDetector(),
        BlinkDetector(),
    ])
    actions = [LogAction()]
    return Pipeline(stages, actions)
```

**Step 6: Update BandPowerBroadcaster to use ZunaResult when available**

In `backend/pipeline/stages/band_power_broadcaster.py`, add logic to check for `ZunaResult` and compute band powers from 23ch data if present (instead of reading from 4ch `BandPowerResult`).

**Step 7: Run all tests**

Run: `PYTHONPATH=. python -m pytest tests/ -v`
Expected: All PASS

**Step 8: Commit**

```bash
git add backend/pipeline/stages/zuna_stage.py tests/test_zuna_stage.py
git add backend/pipeline/factory.py backend/main.py
git add backend/pipeline/stages/band_power_broadcaster.py
git commit -m "feat(pipeline): add ZunaStage for optional 23ch superresolution"
```

---

## Task 9: Integration testing

**Goal:** Verify the full data flow works end-to-end.

**Step 1: Test 4ch mode (no ZUNA)**

```bash
python -m backend.main --synthetic
```
Open browser → dashboard should show:
- [x] Existing waveforms work
- [x] BrainHeatmap renders with colors updating
- [x] Band selector changes color pattern
- [x] Disclaimer says "Estimated from 4 sensors"

**Step 2: Test ZUNA mode (requires GPU)**

```bash
python -m backend.main --synthetic --zuna
```
Wait 30s for model load, then:
- [x] Console shows "ZUNA loaded (XXXX MB VRAM)"
- [x] Band powers message has `mode: "23ch"`
- [x] Heatmap shows 23 electrode dots (vs 4 before)
- [x] Heatmap gradients are sharper
- [x] Disclaimer says "AI-reconstructed from 4 sensors"

**Step 3: Test debug modes**

In dashboard code, temporarily set `debug="static"`, `debug="wave"`, `debug="random"`:
- [x] Static: each electrode has different fixed color, interpolation visible
- [x] Wave: smooth front-to-back sweep
- [x] Random: colors change every second, EMA smoothing visible

**Step 4: Heatmap validation test 6 (interpolation sanity)**

Using debug="static" with modified values (TP9=1.0, others=0):
- [x] Hot spot appears at left temporal (near ear), not wrong location
- [x] Opposite side is cool
- [x] Smooth gradient between

**Step 5: Commit integration test notes**

```bash
git commit --allow-empty -m "test: verify brain heatmap integration (4ch + 23ch)"
```

---

## Task 10: Visual polish

**Goal:** Add fresnel glow, subtle pulsing, and visual refinements.

**Files:**
- Modify: `frontend/src/components/BrainHeatmap.tsx`

**Step 1: Add fresnel edge glow**

Replace the `meshStandardMaterial` with a custom shader or use drei's `<MeshTransmissionMaterial>`. Simpler approach — add a second transparent shell mesh slightly larger:

```tsx
function GlowShell() {
  return (
    <mesh scale={[1.03, 1.03 * 1.15, 1.03]}>
      <sphereGeometry args={[1, 32, 24]} />
      <meshStandardMaterial
        color="#4488ff"
        transparent
        opacity={0.05}
        side={THREE.BackSide}
      />
    </mesh>
  );
}
```

Add `<GlowShell />` next to `<HeadMesh />` in the Canvas.

**Step 2: Commit**

```bash
git add frontend/src/components/BrainHeatmap.tsx
git commit -m "feat(frontend): add visual polish to brain heatmap"
```

---

## Summary

| Task | Description | Depends on | Estimated effort |
|------|-------------|-----------|-----------------|
| 1 | Backend BandPowerBroadcaster | — | Small |
| 2 | Frontend useBandPowers hook | Task 1 protocol | Small |
| 3 | Install R3F deps | — | Trivial |
| 4 | Electrode positions + interpolation math | — | Medium |
| 5 | BrainHeatmap component | Tasks 3, 4 | Large |
| 6 | Band selector | — | Small |
| 7 | Wire into dashboard | Tasks 1, 2, 5, 6 | Medium |
| 8 | ZunaStage backend | Task 1 | Large (ZUNA internals) |
| 9 | Integration testing | Tasks 7, 8 | Medium |
| 10 | Visual polish | Task 5 | Small |

**Parallelizable:** Tasks 1-2 (backend) and 3-6 (frontend) can proceed in parallel.
**Critical path:** Task 8 (ZunaStage) requires the most exploration and is most likely to need iteration.
