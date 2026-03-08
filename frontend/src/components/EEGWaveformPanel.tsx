import { useEffect, useRef } from "react";
import { WebglPlot, WebglLinePlot, ColorRGBA } from "webgl-plot";
import type { SensorBuffers } from "../hooks/useSensorStream";
import { CHANNEL_NAMES, EEG_CHANNELS } from "../lib/protocol";
import type { LineConfig } from "webgl-plot";

const COLORS: ColorRGBA[] = [
  new ColorRGBA(0.35, 0.8, 0.95, 1),   // TP9  — cyan
  new ColorRGBA(0.95, 0.6, 0.3, 1),    // AF7  — orange
  new ColorRGBA(0.6, 0.95, 0.4, 1),    // AF8  — green
  new ColorRGBA(0.85, 0.4, 0.95, 1),   // TP10 — purple
];

const SAMPLES_PER_CHANNEL = 256 * 5; // 5 seconds at 256Hz

interface Props {
  buffersRef: React.RefObject<SensorBuffers>;
}

/** Build initial interleaved (x, y) points for a flat line */
function makeInitialPoints(numSamples: number): Float32Array {
  const points = new Float32Array(numSamples * 2);
  for (let i = 0; i < numSamples; i++) {
    points[i * 2] = (i / (numSamples - 1)) * 2 - 1; // x: [-1, 1]
    points[i * 2 + 1] = 0;                            // y: 0
  }
  return points;
}

export function EEGWaveformPanel({ buffersRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wglRef = useRef<WebglPlot | null>(null);
  const plotterRef = useRef<WebglLinePlot | null>(null);
  const rafRef = useRef<number>(0);
  const yBufRef = useRef<Float32Array>(new Float32Array(SAMPLES_PER_CHANNEL));

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Initialize WebGL plot
    const wgl = new WebglPlot(canvas);
    wglRef.current = wgl;

    // Create a thin-line plotter with one line per EEG channel
    const plotter = wgl.newThinLinePlotter(EEG_CHANNELS);
    plotterRef.current = plotter;

    const linesConfig: LineConfig[] = [];
    for (let ch = 0; ch < EEG_CHANNELS; ch++) {
      const yOffset = 0.75 - ch * 0.5; // spread across [-1, 1]
      linesConfig.push({
        points: makeInitialPoints(SAMPLES_PER_CHANNEL),
        color: COLORS[ch].toArray() as [number, number, number, number],
        scale: [1, 0.002],       // scale microvolts to WebGL coordinates
        offset: [0, yOffset],    // stack channels vertically
      });
    }
    plotter.initLines(linesConfig);

    // Reusable buffer for Y updates
    const yBuf = yBufRef.current;

    // Animation loop — reads from ring buffers, updates WebGL
    const animate = () => {
      const buffers = buffersRef.current;
      if (buffers) {
        for (let ch = 0; ch < EEG_CHANNELS; ch++) {
          const data = buffers.eeg[ch].getOrdered();
          const len = Math.min(data.length, SAMPLES_PER_CHANNEL);
          // Fill the Y buffer; zero-pad if ring buffer has fewer samples
          for (let i = 0; i < len; i++) {
            yBuf[i] = data[i];
          }
          for (let i = len; i < SAMPLES_PER_CHANNEL; i++) {
            yBuf[i] = 0;
          }
          plotter.updateLineY(ch, yBuf);
        }
      }
      wgl.update();
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, [buffersRef]);

  return (
    <div className="relative w-full">
      {/* Channel labels */}
      <div className="absolute left-2 top-0 bottom-0 flex flex-col justify-around pointer-events-none z-10">
        {CHANNEL_NAMES.map((name, i) => (
          <span
            key={name}
            className="text-xs font-mono opacity-70"
            style={{ color: `rgba(${COLORS[i].r * 255}, ${COLORS[i].g * 255}, ${COLORS[i].b * 255}, 0.9)` }}
          >
            {name}
          </span>
        ))}
      </div>
      <canvas
        ref={canvasRef}
        className="w-full h-64 bg-black/50 rounded-md border border-white/10"
      />
    </div>
  );
}
