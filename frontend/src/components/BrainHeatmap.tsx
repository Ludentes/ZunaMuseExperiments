// frontend/src/components/BrainHeatmap.tsx
import { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import {
  ELECTRODES_4CH,
  ELECTRODES_23CH,
  sphericalToCartesian,
  type ElectrodePosition,
} from "../lib/electrodes";
import {
  computeInterpolationWeights,
  interpolateToVertices,
} from "../lib/interpolation";
import type { BandPowers } from "../lib/protocol";
import { extractBandValues, type BandName } from "../hooks/useBandPowers";

// Scratch objects reused per frame (avoid GC pressure at 60fps)
const _scratchColor = new THREE.Color();

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

  // Build geometry once
  const geometry = useMemo(() => {
    const geo = new THREE.SphereGeometry(1, 48, 32);
    // Slightly elongate vertically, flatten back
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
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

  // Pre-allocated buffers (reused every frame to avoid GC)
  const interpBufRef = useRef<Float32Array | null>(null);
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
      electrodeValues = electrodes.map((_: ElectrodePosition, i: number) => (i + 1) / electrodes.length);
    } else if (debug === "wave") {
      const t = clock.getElapsedTime();
      electrodeValues = electrodes.map((e: ElectrodePosition) => {
        return 0.5 + 0.5 * Math.sin(t * Math.PI - e.theta * 2);
      });
    } else if (debug === "random") {
      // Only update once per second
      const sec = Math.floor(clock.getElapsedTime());
      electrodeValues = electrodes.map((_: ElectrodePosition, i: number) =>
        Math.abs(Math.sin(sec * 13.7 + i * 7.3))
      );
    } else if (bandPowers) {
      const bandValues = extractBandValues(bandPowers, selectedBand);
      electrodeValues = electrodes.map((e: ElectrodePosition) => bandValues[e.name] ?? 0);
    } else {
      return; // No data
    }

    // Update baseline normalization
    if (!debug) {
      updateBaseline(baselineRef.current, electrodeValues);
    }

    // Interpolate to vertices (reuse buffer)
    if (!interpBufRef.current || interpBufRef.current.length !== numVerts) {
      interpBufRef.current = new Float32Array(numVerts);
    }
    const raw = interpolateToVertices(weights, electrodeValues, numVerts, interpBufRef.current);

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
    const colors = colorAttr.array as Float32Array;
    const s = smoothedRef.current!;

    for (let i = 0; i < numVerts; i++) {
      const normalized = debug
        ? s[i]  // debug modes are already 0-1
        : normalize(s[i], baselineRef.current);
      valueToColor(normalized, _scratchColor);
      colors[i * 3] = _scratchColor.r;
      colors[i * 3 + 1] = _scratchColor.g;
      colors[i * 3 + 2] = _scratchColor.b;
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
      // Match head mesh transforms: elongate y, flatten back
      const sy = y * 1.15;
      let sz = z;
      if (sz < -0.3) {
        const factor = 1 - 0.15 * Math.abs(sz + 0.3);
        sz = sz * Math.max(factor, 0.85);
      }
      // Small offset to sit on surface
      return new THREE.Vector3(x * 1.02, sy * 1.02, sz * 1.02);
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
