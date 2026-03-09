import { useEffect, useRef } from "react";
import type { SensorBuffers } from "../hooks/useSensorStream";
import { CHANNEL_NAMES, EEG_CHANNELS } from "../lib/protocol";

const COLORS = [
  "#59ccf2",  // TP9  — cyan
  "#f29a4d",  // AF7  — orange
  "#99f266",  // AF8  — green
  "#d966f2",  // TP10 — purple
];

const SAMPLES_VISIBLE = 256 * 4; // 4 seconds at 256Hz
const Y_SCALE = 0.003; // µV to normalized (-1..1) per channel lane

interface Props {
  buffersRef: React.RefObject<SensorBuffers>;
}

export function EEGWaveformPanel({ buffersRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const animate = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = rect.width * dpr;
      const h = rect.height * dpr;

      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }

      ctx.clearRect(0, 0, w, h);

      const buffers = buffersRef.current;
      if (!buffers) {
        rafRef.current = requestAnimationFrame(animate);
        return;
      }

      const laneH = h / EEG_CHANNELS;

      for (let ch = 0; ch < EEG_CHANNELS; ch++) {
        const data = buffers.eeg[ch].getOrdered();
        const len = data.length;
        if (len < 2) continue;

        const yCenter = laneH * (ch + 0.5);
        const samplesShow = Math.min(len, SAMPLES_VISIBLE);
        const startIdx = len - samplesShow;

        ctx.beginPath();
        ctx.strokeStyle = COLORS[ch];
        ctx.lineWidth = dpr;

        for (let i = 0; i < samplesShow; i++) {
          const x = (i / samplesShow) * w;
          const y = yCenter - data[startIdx + i] * Y_SCALE * laneH;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();

        // Channel label
        ctx.fillStyle = COLORS[ch];
        ctx.font = `${11 * dpr}px monospace`;
        ctx.globalAlpha = 0.7;
        ctx.fillText(CHANNEL_NAMES[ch], 4 * dpr, laneH * ch + 14 * dpr);
        ctx.globalAlpha = 1;
      }

      // Grid lines between channels
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.lineWidth = dpr;
      for (let ch = 1; ch < EEG_CHANNELS; ch++) {
        const y = laneH * ch;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, [buffersRef]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-64 bg-black/50 rounded-md border border-white/10"
      style={{ display: "block" }}
    />
  );
}
