import { useEffect, useRef } from "react";
import type { SensorBuffers } from "../../hooks/useSensorStream";

const CHANNEL_INDEX = 1; // AF7
const COLOR = "#59ccf2";
const SAMPLES_VISIBLE = 256 * 4;
const Y_SCALE = 0.003;

interface Props {
  buffersRef: React.RefObject<SensorBuffers>;
  height?: number;
}

export function EEGStrip({ buffersRef, height = 40 }: Props) {
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

      const data = buffers.eeg[CHANNEL_INDEX].getOrdered();
      const len = data.length;
      if (len < 2) {
        rafRef.current = requestAnimationFrame(animate);
        return;
      }

      const yCenter = h / 2;
      const samplesShow = Math.min(len, SAMPLES_VISIBLE);
      const startIdx = len - samplesShow;

      ctx.beginPath();
      ctx.strokeStyle = COLOR;
      ctx.lineWidth = dpr * 1.5;

      for (let i = 0; i < samplesShow; i++) {
        const x = (i / samplesShow) * w;
        const y = yCenter - data[startIdx + i] * Y_SCALE * h;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      rafRef.current = requestAnimationFrame(animate);
    };

    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [buffersRef]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height, display: "block", background: "transparent" }}
    />
  );
}
