// frontend/src/components/BrainHeatmap.tsx
import { useRef, useMemo, useState, useCallback, useEffect } from "react";
import { Canvas, useFrame, useLoader } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
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
      const expandAlpha = state.samples < 30 ? 0.3 : 0.1;
      const shrinkAlpha = 0.005;
      if (v < state.min) state.min += (v - state.min) * expandAlpha;
      if (v > state.max) state.max += (v - state.max) * expandAlpha;
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

// --- Stats for legend overlay ---
interface HeatmapStats {
  baselineMin: number;
  baselineMax: number;
  baselineReady: boolean;
  baselineSamples: number;
  electrodeValues: Record<string, number>;
}

// --- Electrode position from electrodes.json ---
interface ElectrodeData {
  [name: string]: {
    scalp: [number, number, number];
    brain: [number, number, number];
    vertex_idx: number;
  };
}

// Channel names we care about
const MUSE_CHANNELS = ["TP9", "AF7", "AF8", "TP10"];
const ZUNA_CHANNELS = [
  "Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8",
  "AF7", "AF8",
  "T7", "T8", "TP9", "TP10",
  "C3", "Cz", "C4",
  "P7", "P3", "Pz", "P4", "P8",
  "O1", "O2",
];

// --- IDW interpolation for brain mesh ---
function computeBrainWeights(
  vertices: Float32Array,
  electrodePositions: [number, number, number][],
  power = 2,
  smoothing = 0.01,
): Float32Array {
  const numVerts = vertices.length / 3;
  const numElec = electrodePositions.length;
  const weights = new Float32Array(numVerts * numElec);

  for (let v = 0; v < numVerts; v++) {
    const vx = vertices[v * 3];
    const vy = vertices[v * 3 + 1];
    const vz = vertices[v * 3 + 2];

    let weightSum = 0;
    for (let e = 0; e < numElec; e++) {
      const [ex, ey, ez] = electrodePositions[e];
      const dx = vx - ex;
      const dy = vy - ey;
      const dz = vz - ez;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) + smoothing;
      const w = 1 / Math.pow(dist, power);
      weights[v * numElec + e] = w;
      weightSum += w;
    }
    for (let e = 0; e < numElec; e++) {
      weights[v * numElec + e] /= weightSum;
    }
  }

  return weights;
}

function interpolateToVertices(
  weights: Float32Array,
  electrodeValues: number[],
  numVertices: number,
  out?: Float32Array,
): Float32Array {
  const numElec = electrodeValues.length;
  const result = out && out.length === numVertices ? out : new Float32Array(numVertices);
  for (let v = 0; v < numVertices; v++) {
    let val = 0;
    for (let e = 0; e < numElec; e++) {
      val += weights[v * numElec + e] * electrodeValues[e];
    }
    result[v] = val;
  }
  return result;
}

// --- Brain mesh component ---
interface BrainMeshProps {
  geometry: THREE.BufferGeometry;
  electrodeData: ElectrodeData;
  channelNames: string[];
  bandPowers: BandPowers | null;
  selectedBand: BandName;
  debug?: "static" | "wave" | "random";
  onStats?: (stats: HeatmapStats) => void;
}

function BrainMesh({
  geometry,
  electrodeData,
  channelNames,
  bandPowers,
  selectedBand,
  debug,
  onStats,
}: BrainMeshProps) {
  const statsThrottleRef = useRef(0);

  // Get electrode brain positions for current channel set
  const electrodePositions = useMemo(() => {
    return channelNames
      .filter((name) => electrodeData[name])
      .map((name) => electrodeData[name].brain as [number, number, number]);
  }, [channelNames, electrodeData]);

  const activeChannels = useMemo(() => {
    return channelNames.filter((name) => electrodeData[name]);
  }, [channelNames, electrodeData]);

  // Clone geometry and always create fresh RGB vertex color attribute
  const coloredGeometry = useMemo(() => {
    const geo = geometry.clone();
    const pos = geo.attributes.position;
    // Always overwrite — GLB may use different attribute name or RGBA format
    const colors = new Float32Array(pos.count * 3);
    colors.fill(0.5);
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    return geo;
  }, [geometry]);

  // Compute interpolation weights
  const weights = useMemo(() => {
    const pos = coloredGeometry.attributes.position as THREE.BufferAttribute;
    return computeBrainWeights(
      pos.array as Float32Array,
      electrodePositions,
    );
  }, [coloredGeometry, electrodePositions]);

  // Pre-allocated buffers
  const interpBufRef = useRef<Float32Array | null>(null);
  const prevElecRef = useRef<number[] | null>(null);
  const targetElecRef = useRef<number[] | null>(null);
  const lerpStartRef = useRef(0);
  const lerpDurationRef = useRef(0.5);
  const baselineRef = useRef<BaselineState>({
    min: 0, max: 1, samples: 0, ready: false,
  });

  // Detect when bandPowers changes and set up lerp
  const prevBandPowersRef = useRef<BandPowers | null>(null);
  if (bandPowers !== prevBandPowersRef.current && bandPowers && !debug) {
    const bandValues = extractBandValues(bandPowers, selectedBand);
    const newTarget = activeChannels.map((name) => bandValues[name] ?? 0);
    prevElecRef.current = targetElecRef.current
      ? [...targetElecRef.current]
      : newTarget;
    targetElecRef.current = newTarget;
    lerpStartRef.current = performance.now() / 1000;
    prevBandPowersRef.current = bandPowers;
    updateBaseline(baselineRef.current, newTarget);
  }

  // Update vertex colors each frame
  useFrame(({ clock }) => {
    const colorAttr = coloredGeometry.attributes.color as THREE.BufferAttribute;
    const numVerts = colorAttr.count;

    let electrodeValues: number[];

    if (debug === "static") {
      electrodeValues = activeChannels.map((_, i) => (i + 1) / activeChannels.length);
    } else if (debug === "wave") {
      const t = clock.getElapsedTime();
      electrodeValues = activeChannels.map((_, i) =>
        0.5 + 0.5 * Math.sin(t * Math.PI - i * 0.5)
      );
    } else if (debug === "random") {
      const sec = Math.floor(clock.getElapsedTime());
      electrodeValues = activeChannels.map((_, i) =>
        Math.abs(Math.sin(sec * 13.7 + i * 7.3))
      );
    } else if (targetElecRef.current) {
      const now = performance.now() / 1000;
      const elapsed = now - lerpStartRef.current;
      const t = Math.min(elapsed / lerpDurationRef.current, 1.0);
      const smooth = t * t * (3 - 2 * t);
      const prev = prevElecRef.current!;
      const target = targetElecRef.current;
      electrodeValues = target.map((v, i) =>
        prev[i] + (v - prev[i]) * smooth
      );
    } else {
      return;
    }

    if (!interpBufRef.current || interpBufRef.current.length !== numVerts) {
      interpBufRef.current = new Float32Array(numVerts);
    }
    const vertexValues = interpolateToVertices(weights, electrodeValues, numVerts, interpBufRef.current);

    const colors = colorAttr.array as Float32Array;
    for (let i = 0; i < numVerts; i++) {
      const normalized = debug
        ? vertexValues[i]
        : normalize(vertexValues[i], baselineRef.current);
      valueToColor(normalized, _scratchColor);
      colors[i * 3] = _scratchColor.r;
      colors[i * 3 + 1] = _scratchColor.g;
      colors[i * 3 + 2] = _scratchColor.b;
    }

    colorAttr.needsUpdate = true;

    // Report stats (throttled to ~2Hz)
    if (onStats) {
      const now = clock.getElapsedTime();
      if (now - statsThrottleRef.current > 0.5) {
        statsThrottleRef.current = now;
        const ev: Record<string, number> = {};
        for (let e = 0; e < activeChannels.length; e++) {
          ev[activeChannels[e]] = electrodeValues[e];
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
    <mesh geometry={coloredGeometry}>
      <meshStandardMaterial
        vertexColors
        roughness={0.65}
        metalness={0.05}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

// --- Electrode dots ---
function ElectrodeDots({
  electrodeData,
  channelNames,
}: {
  electrodeData: ElectrodeData;
  channelNames: string[];
}) {
  const positions = useMemo(() => {
    return channelNames
      .filter((name) => electrodeData[name])
      .map((name) => {
        const pos = electrodeData[name].brain;
        return { name, position: new THREE.Vector3(pos[0], pos[1], pos[2]) };
      });
  }, [channelNames, electrodeData]);

  return (
    <>
      {positions.map(({ name, position }) => (
        <mesh key={name} position={position}>
          <sphereGeometry args={[0.03, 8, 8]} />
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
  focus: "Focus (\u03b8/\u03b2 ratio)",
  theta: "Theta (4\u20138 Hz)",
  alpha: "Alpha (8\u201313 Hz)",
  beta: "Beta (13\u201330 Hz)",
  gamma: "Gamma (30\u201350 Hz)",
  delta: "Delta (1\u20134 Hz)",
};

const BAND_UNITS: Record<string, string> = {
  focus: "ratio",
  theta: "\u00b5V\u00b2",
  alpha: "\u00b5V\u00b2",
  beta: "\u00b5V\u00b2",
  gamma: "\u00b5V\u00b2",
  delta: "\u00b5V\u00b2",
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
  const gradient =
    "linear-gradient(to right, #0000ff, #00ffff, #00ff00, #ffff00, #ff0000)";
  const minVal = stats ? stats.baselineMin.toFixed(1) : "\u2014";
  const maxVal = stats ? stats.baselineMax.toFixed(1) : "\u2014";
  const warmup = stats && !stats.baselineReady;
  const elecEntries = stats
    ? Object.entries(stats.electrodeValues).sort(([a], [b]) => a.localeCompare(b))
    : [];

  return (
    <div style={{ padding: "4px 8px", fontSize: "11px", color: "#aaa" }}>
      <div style={{ fontWeight: "bold", marginBottom: "4px", color: "#ccc" }}>
        {label}
        {warmup && (
          <span style={{ color: "#ff8800", marginLeft: "8px" }}>
            \u25cf warming up ({stats?.baselineSamples ?? 0}/5)
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
      ? "AI-reconstructed from 4 sensors \u2014 more spatial detail but not equivalent to physical electrodes"
      : "Estimated from 4 sensors \u2014 visualization only, not clinical EEG";
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

// --- Scene content ---
function BrainScene({
  bandPowers,
  selectedBand,
  debug,
  onStats,
}: {
  bandPowers: BandPowers | null;
  selectedBand: BandName;
  debug?: "static" | "wave" | "random";
  onStats: (s: HeatmapStats) => void;
}) {
  const gltf = useLoader(GLTFLoader, "/brain.glb");
  const [electrodeData, setElectrodeData] = useState<ElectrodeData | null>(null);

  // Load electrode positions
  useEffect(() => {
    fetch("/electrodes.json")
      .then((r) => r.json())
      .then((data) => setElectrodeData(data))
      .catch((err) => console.error("Failed to load electrodes.json:", err));
  }, []);

  // Extract geometry from GLTF
  const brainGeometry = useMemo(() => {
    let geo: THREE.BufferGeometry | null = null;
    gltf.scene.traverse((child) => {
      if (child instanceof THREE.Mesh && !geo) {
        geo = child.geometry;
      }
    });
    return geo;
  }, [gltf]);

  // Determine channel set
  const channelNames = useMemo(() => {
    if (bandPowers && Object.keys(bandPowers.channels).length > 4) {
      return ZUNA_CHANNELS;
    }
    return MUSE_CHANNELS;
  }, [bandPowers?.mode]);

  if (!brainGeometry || !electrodeData) {
    return null; // Loading
  }

  return (
    <>
      <ambientLight intensity={0.7} />
      <directionalLight position={[2, 3, 4]} intensity={0.5} />
      <directionalLight position={[-2, 3, -4]} intensity={0.5} />
      <directionalLight position={[0, -2, 0]} intensity={0.2} />
      <BrainMesh
        geometry={brainGeometry}
        electrodeData={electrodeData}
        channelNames={channelNames}
        bandPowers={bandPowers}
        selectedBand={selectedBand}
        debug={debug}
        onStats={onStats}
      />
      <ElectrodeDots electrodeData={electrodeData} channelNames={channelNames} />
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
          onStats={handleStats}
        />
      </Canvas>
      <Legend selectedBand={selectedBand} stats={stats} />
      <Disclaimer mode={mode} />
    </div>
  );
}
