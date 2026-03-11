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
import { fbm3 } from "../lib/noise";
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
  onMeshReady?: (mesh: THREE.Mesh | null) => void;
}

function HeadMesh({ bandPowers, selectedBand, debug, onStats, onMeshReady }: HeadMeshProps) {
  const statsThrottleRef = useRef(0);
  const meshRef = useRef<THREE.Mesh>(null);
  const meshReadyRef = useRef(false);

  // Build brain-like geometry once
  const geometry = useMemo(() => {
    const geo = new THREE.SphereGeometry(1, 64, 48);
    const pos = geo.attributes.position;
    const normal = geo.attributes.normal;

    for (let i = 0; i < pos.count; i++) {
      let x = pos.getX(i);
      let y = pos.getY(i);
      let z = pos.getZ(i);

      // 1. Brain shape: wider than tall, elongated front-to-back
      x *= 0.85;   // narrower left-right
      y *= 1.05;   // slightly taller
      z *= 0.95;   // slightly shorter front-back

      // 2. Flatten underside (brain base is flat, not spherical)
      if (y < -0.3) {
        y = -0.3 + (y + 0.3) * 0.3; // compress below -0.3
      }

      // 3. Interhemispheric fissure (midline groove)
      const midlineDist = Math.abs(x);
      if (midlineDist < 0.15 && y > 0.1) {
        const fissureDepth = 0.08 * (1 - midlineDist / 0.15) * Math.max(0, (y - 0.1) / 0.9);
        const nx = normal.getX(i);
        const ny = normal.getY(i);
        const nz = normal.getZ(i);
        // Push inward along normal
        x -= nx * fissureDepth;
        y -= ny * fissureDepth;
        z -= nz * fissureDepth;
      }

      // 4. Sulci via fBm noise displacement along normal
      const noiseScale = 3.5;
      const noiseAmp = 0.06;
      const n = fbm3(x * noiseScale, y * noiseScale, z * noiseScale, 4, 2.2, 0.5);
      const nx = normal.getX(i);
      const ny = normal.getY(i);
      const nz = normal.getZ(i);
      // Only displace inward (sulci are grooves, not bumps)
      const displacement = Math.min(0, n) * noiseAmp;
      x += nx * displacement;
      y += ny * displacement;
      z += nz * displacement;

      // 5. Frontal lobe bulge
      if (z > 0.4 && y > -0.1) {
        const bulge = 0.08 * Math.max(0, (z - 0.4) / 0.6) * Math.max(0, (y + 0.1) / 1.1);
        z += bulge;
      }

      // 6. Temporal lobe bulge (sides, lower)
      if (Math.abs(x) > 0.5 && y < 0.2 && z > -0.2) {
        const side = (Math.abs(x) - 0.5) / 0.5;
        const vert = Math.max(0, (0.2 - y) / 0.5);
        const tbulge = 0.06 * side * vert;
        x += Math.sign(x) * tbulge;
      }

      // 7. Occipital roundness (back)
      if (z < -0.5 && y > -0.1) {
        const backness = (-0.5 - z) / 0.5;
        const obulge = 0.05 * Math.min(1, backness);
        z -= obulge;
      }

      pos.setXYZ(i, x, y, z);
    }

    pos.needsUpdate = true;
    geo.computeVertexNormals();

    // Add vertex colors
    const colors = new Float32Array(pos.count * 3);
    colors.fill(0.5);
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
    // Notify parent of mesh ref (once)
    if (!meshReadyRef.current && meshRef.current && onMeshReady) {
      meshReadyRef.current = true;
      onMeshReady(meshRef.current);
    }

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
        roughness={0.7}
        metalness={0.05}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// --- Electrode dots (raycast onto brain surface) ---
function ElectrodeDots({
  electrodes,
  brainMesh,
}: {
  electrodes: ElectrodePosition[];
  brainMesh: THREE.Mesh | null;
}) {
  const positions = useMemo(() => {
    return electrodes.map((e) => {
      const [x, y, z] = sphericalToCartesian(e.theta, e.phi);
      // Start from a point outside the brain, shoot inward
      const dir = new THREE.Vector3(x, y, z).normalize();
      const origin = dir.clone().multiplyScalar(2.0); // outside

      if (brainMesh) {
        const raycaster = new THREE.Raycaster(origin, dir.clone().negate());
        const hits = raycaster.intersectObject(brainMesh);
        if (hits.length > 0) {
          // Offset slightly above surface
          return hits[0].point.clone().add(dir.clone().multiplyScalar(0.02));
        }
      }

      // Fallback: approximate position with brain shape transforms
      return new THREE.Vector3(x * 0.87, y * 1.07, z * 0.97);
    });
  }, [electrodes, brainMesh]);

  return (
    <>
      {positions.map((pos, i) => (
        <mesh key={electrodes[i].name} position={pos}>
          <sphereGeometry args={[0.025, 8, 8]} />
          <meshStandardMaterial
            color="#00ff88"
            emissive="#00ff88"
            emissiveIntensity={0.6}
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

// --- Scene content (needs access to mesh ref) ---
function BrainScene({
  bandPowers,
  selectedBand,
  debug,
  electrodes,
  onStats,
}: {
  bandPowers: BandPowers | null;
  selectedBand: BandName;
  debug?: "static" | "wave" | "random";
  electrodes: ElectrodePosition[];
  onStats: (s: HeatmapStats) => void;
}) {
  const [brainMesh, setBrainMesh] = useState<THREE.Mesh | null>(null);

  return (
    <>
      <ambientLight intensity={0.5} />
      <directionalLight position={[2, 4, 3]} intensity={0.7} />
      <directionalLight position={[-2, 2, -1]} intensity={0.3} color="#aaccff" />
      <HeadMesh
        bandPowers={bandPowers}
        selectedBand={selectedBand}
        debug={debug}
        onStats={onStats}
        onMeshReady={setBrainMesh}
      />
      <ElectrodeDots electrodes={electrodes} brainMesh={brainMesh} />
      <OrbitControls
        enablePan={false}
        enableZoom={false}
        autoRotate
        autoRotateSpeed={0.4}
      />
    </>
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
        style={{ height, background: "#0a0a0f" }}
        camera={{ position: [0, 0.6, 2.2], fov: 42 }}
      >
        <BrainScene
          bandPowers={bandPowers}
          selectedBand={selectedBand}
          debug={debug}
          electrodes={electrodes}
          onStats={handleStats}
        />
      </Canvas>
      <Legend selectedBand={selectedBand} stats={stats} />
      <Disclaimer mode={mode} />
    </div>
  );
}
