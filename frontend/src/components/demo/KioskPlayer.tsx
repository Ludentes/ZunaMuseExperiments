import { useCallback, useEffect, useRef, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Props {
  lastEvent: BciEvent | null;
  clips?: string[];
}

const DEFAULT_CLIPS = ["/demo/clip1.mp4", "/demo/clip2.mp4", "/demo/clip3.mp4"];

export function KioskPlayer({ lastEvent, clips = DEFAULT_CLIPS }: Props) {
  const [clipIndex, setClipIndex] = useState(0);
  const [showOverlay, setShowOverlay] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const lastProcessedRef = useRef<number>(0);

  const nextClip = useCallback(() => {
    setClipIndex((i) => (i + 1) % clips.length);
    setShowOverlay(true);
    setTimeout(() => setShowOverlay(false), 800);
  }, [clips.length]);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.kind !== "double_blink") return;
    if ((lastEvent.confidence ?? 1) < 0.6) return;
    if (lastEvent.timestamp === lastProcessedRef.current) return;
    lastProcessedRef.current = lastEvent.timestamp;
    nextClip();
  }, [lastEvent, nextClip]);

  useEffect(() => {
    videoRef.current?.play().catch(() => {});
  }, [clipIndex]);

  return (
    <div
      className="relative overflow-hidden"
      style={{
        background: "#000",
        border: "2px solid var(--border)",
        boxShadow: "0 0 20px rgba(0,0,0,0.5), inset 0 0 1px rgba(255,255,255,0.1)",
      }}
    >
      <video
        ref={videoRef}
        src={clips[clipIndex]}
        loop
        muted
        playsInline
        className="w-full"
        style={{ aspectRatio: "16/9", objectFit: "cover" }}
      />
      {showOverlay && (
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{
            background: "rgba(0,0,0,0.6)",
            animation: "flash-fade 800ms ease-out forwards",
          }}
        >
          <span className="text-2xl font-mono font-bold tracking-widest" style={{ color: "var(--status-info)" }}>
            NEXT
          </span>
        </div>
      )}
      <div
        className="absolute bottom-1 right-2 text-[9px] font-mono"
        style={{ color: "var(--text-dim)" }}
      >
        {clipIndex + 1}/{clips.length}
      </div>
    </div>
  );
}
