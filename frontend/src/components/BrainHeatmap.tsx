// frontend/src/components/BrainHeatmap.tsx
import { useRef, useMemo, useState, useCallback } from "react";
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
      const expandAlpha = state.samples < 30 ? 0.3 : 0.1;  // fast expand
      const shrinkAlpha = 0.005;  // slow contract toward current range

      // Expand quickly when value is outside range
      if (v < state.min) state.min += (v - state.min) * expandAlpha;
      if (v > state.max) state.max += (v - state.max) * expandAlpha;

      // Contract slowly when value is inside range (prevents stuck extremes)
      if (v > state.min) state.min += (v - state.min) * shrinkAlpha;
      if (v < state.max) state.max += (v - state.max) * shrinkAlpha;
    }
    state.samples++;
  }
  state.ready = state.samples >= 5;
}

function normalize(value: number, baseline: BaselineState): number {
  if (!baseline.ready || baseline.max <= baseline.min) return 0.5;
  return (value - baseline.min) / (baseline.max - baseline.min);
}

// --- Stats for legend/debug overlay ---
interface HeatmapStats {
  baselineMin: number;
  baselineMax: number;
  baselineReady: boolean;
  baselineSamples: number;
  electrodeValues: Record<string, number>;  // current values per electrode
}

// --- Head mesh component ---
interface HeadMeshProps {
  bandPowers: BandPowers | null;
  selectedBand: BandName;
  debug?: "static" | "wave" | "random";
  onStats?: (stats: HeatmapStats) => void;
}

function HeadMesh({ bandPowers, selectedBand, debug, onStats }: HeadMeshProps) {
  const statsThrottleRef = useRef(0);
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
  // Electrode-level lerp state (smooth between 2s updates)
  const prevElecRef = useRef<number[] | null>(null);
  const targetElecRef = useRef<number[] | null>(null);
  const lerpStartRef = useRef(0);
  const lerpDurationRef = useRef(0.5); // seconds between updates (matches backend metrics_interval)
  const baselineRef = useRef<BaselineState>({
    min: 0, max: 1, samples: 0, ready: false,
  });

  // Detect when bandPowers changes and set up lerp
  const prevBandPowersRef = useRef<BandPowers | null>(null);
  if (bandPowers !== prevBandPowersRef.current && bandPowers && !debug) {
    const bandValues = extractBandValues(bandPowers, selectedBand);
    const newTarget = electrodes.map((e: ElectrodePosition) => bandValues[e.name] ?? 0);
    // Current interpolated position becomes the new start
    prevElecRef.current = targetElecRef.current
      ? [...targetElecRef.current]
      : newTarget;
    targetElecRef.current = newTarget;
    lerpStartRef.current = performance.now() / 1000;
    prevBandPowersRef.current = bandPowers;
    // Update baseline with new target values
    updateBaseline(baselineRef.current, newTarget);
  }

  // Update vertex colors each frame
  useFrame(({ clock }) => {
    const colorAttr = geometry.attributes.color as THREE.BufferAttribute;
    const numVerts = colorAttr.count;

    // Get electrode values — debug modes or lerped live values
    let electrodeValues: number[];

    if (debug === "static") {
      electrodeValues = electrodes.map((_: ElectrodePosition, i: number) => (i + 1) / electrodes.length);
    } else if (debug === "wave") {
      const t = clock.getElapsedTime();
      electrodeValues = electrodes.map((e: ElectrodePosition) => {
        return 0.5 + 0.5 * Math.sin(t * Math.PI - e.theta * 2);
      });
    } else if (debug === "random") {
      const sec = Math.floor(clock.getElapsedTime());
      electrodeValues = electrodes.map((_: ElectrodePosition, i: number) =>
        Math.abs(Math.sin(sec * 13.7 + i * 7.3))
      );
    } else if (targetElecRef.current) {
      // Lerp from previous to target over lerpDuration
      const now = performance.now() / 1000;
      const elapsed = now - lerpStartRef.current;
      const t = Math.min(elapsed / lerpDurationRef.current, 1.0);
      // Smooth step for natural feel
      const smooth = t * t * (3 - 2 * t);
      const prev = prevElecRef.current!;
      const target = targetElecRef.current;
      electrodeValues = target.map((v, i) =>
        prev[i] + (v - prev[i]) * smooth
      );
    } else {
      return; // No data yet
    }

    // Interpolate to vertices (reuse buffer)
    if (!interpBufRef.current || interpBufRef.current.length !== numVerts) {
      interpBufRef.current = new Float32Array(numVerts);
    }
    const vertexValues = interpolateToVertices(weights, electrodeValues, numVerts, interpBufRef.current);

    // Apply color map
    const colors = colorAttr.array as Float32Array;

    for (let i = 0; i < numVerts; i++) {
      const normalized = debug
        ? vertexValues[i]  // debug modes are already 0-1
        : normalize(vertexValues[i], baselineRef.current);
      valueToColor(normalized, _scratchColor);
      colors[i * 3] = _scratchColor.r;
      colors[i * 3 + 1] = _scratchColor.g;
      colors[i * 3 + 2] = _scratchColor.b;
    }

    colorAttr.needsUpdate = true;

    // Report stats for legend (throttled to ~2Hz)
    if (onStats) {
      const now = clock.getElapsedTime();
      if (now - statsThrottleRef.current > 0.5) {
        statsThrottleRef.current = now;
        const ev: Record<string, number> = {};
        for (let e = 0; e < electrodes.length; e++) {
          ev[electrodes[e].name] = electrodeValues[e];
        }
        onStats({
          baselineMin: baselineRef.current.min,
          baselineMax: baselineRef.current.max,
          baselineReady: baselineRef.current.ready,
          baselineSamples: baselineRef.current.samples,
          electrodeValues: ev,
        });
      }
    }
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

// --- Color legend ---
const BAND_LABELS: Record<string, string> = {
  focus: "Focus (θ/β ratio)",
  theta: "Theta (4–8 Hz)",
  alpha: "Alpha (8–13 Hz)",
  beta: "Beta (13–30 Hz)",
  gamma: "Gamma (30–50 Hz)",
  delta: "Delta (1–4 Hz)",
};

const BAND_UNITS: Record<string, string> = {
  focus: "ratio",
  theta: "µV²",
  alpha: "µV²",
  beta: "µV²",
  gamma: "µV²",
  delta: "µV²",
};

function Legend({
  selectedBand,
  stats,
}: {
  selectedBand: BandName;
  stats: HeatmapStats | null;
}) {
  const label = BAND_LABELS[selectedBand] || selectedBand;
  const unit = BAND_UNITS[selectedBand] || "";

  // Color bar gradient matching the 5-stop scale
  const gradient =
    "linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)";

  const minVal = stats ? stats.baselineMin.toFixed(1) : "—";
  const maxVal = stats ? stats.baselineMax.toFixed(1) : "—";
  const warmup = stats && !stats.baselineReady;

  // Per-electrode values for debugging
  const elecEntries = stats
    ? Object.entries(stats.electrodeValues).sort(([a], [b]) => a.localeCompare(b))
    : [];

  return (
    <div style={{ padding: "4px 8px", fontSize: "11px", color: "#aaa" }}>
      <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#ccc" }}>
        {label}
        {warmup && (
          <span style={{ color: "#ff8800", marginLeft: "8px" }}>
            ● warming up ({stats?.baselineSamples ?? 0}/5)
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
        <span>{minVal}</span>
        <div
          style={{
            flex: 1,
            height: "10px",
            background: gradient,
            borderRadius: "2px",
            border: "1px solid #333",
          }}
        />
        <span>{maxVal}</span>
        <span style={{ color: "#666" }}>{unit}</span>
      </div>
      {elecEntries.length > 0 && (
        <div
          style={{
            marginTop: "4px",
            display: "flex",
            flexWrap: "wrap",
            gap: "2px 8px",
            color: "#777",
            fontFamily: "monospace",
          }}
        >
          {elecEntries.map(([name, val]) => (
            <span key={name}>
              {name}:{val.toFixed(1)}
            </span>
          ))}
        </div>
      )}
    </div>
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
  debug?: "static" | "wave" | "random";
  height?: number;
}

export function BrainHeatmap({
  bandPowers,
  selectedBand = "focus",
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
  const [stats, setStats] = useState<HeatmapStats | null>(null);
  const handleStats = useCallback((s: HeatmapStats) => setStats(s), []);

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
          debug={debug}
          onStats={handleStats}
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
      <Legend selectedBand={selectedBand} stats={stats} />
      <Disclaimer mode={mode} />
    </div>
  );
}
