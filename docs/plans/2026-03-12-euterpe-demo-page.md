# EUTERPE Demo Page — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a `/demo` route ("EUTERPE") that visualizes brain activity and shows BCI-controlled lights/kiosks for an internal tech demo.

**Architecture:** A new TanStack Start route (`/demo`) reuses existing hooks (`useSensorStream`, `useMetrics`, `useBandPowers`) and `BrainHeatmap` component. New components handle light emulation, blink flash effects, command arrows, EEG strip, kiosk video, and event logging. BCI events are already broadcast as `{"type": "bci_event"}` JSON messages over the WebSocket — the frontend just needs to listen for them.

**Tech Stack:** React 19, TanStack Start (SPA), Tailwind CSS 4, R3F (BrainHeatmap), Canvas 2D (EEGStrip), CSS animations (BlinkFlash, CommandArrow)

**Design doc:** `docs/plans/2026-03-12-demo-page-design.md`

---

### Task 1: Listen for BCI events in useSensorStream

The backend already broadcasts blink/clench events as JSON: `{"type": "bci_event", "kind": "double_blink", "confidence": 0.85, "timestamp": ...}` (see `backend/main.py:336-348`). The frontend ignores them. We need to capture them.

**Files:**
- Modify: `frontend/src/hooks/useSensorStream.ts`
- Modify: `frontend/src/lib/protocol.ts`

**Step 1: Add BciEvent type to protocol.ts**

Add to `frontend/src/lib/protocol.ts` after the `Metrics` interface:

```typescript
export interface BciEvent {
  type: "bci_event";
  kind: string;       // "single_blink" | "double_blink" | "triple_blink" | "clench"
  confidence: number;
  timestamp: number;
  channel?: string;
}
```

**Step 2: Add event buffer to useSensorStream**

Modify `frontend/src/hooks/useSensorStream.ts`:

1. Import `BciEvent` from protocol.
2. Add a ref to hold recent events:
```typescript
const eventsRef = useRef<BciEvent[]>([]);
```
3. In the JSON message handler (the `else` branch at line 55), before the existing `try` block, add a check for `bci_event`:
```typescript
try {
  const msg = JSON.parse(event.data);
  if (msg.type === "zuna_status") {
    setZunaStatus({ available: msg.available, enabled: msg.enabled });
  } else if (msg.type === "bci_event") {
    eventsRef.current = [...eventsRef.current.slice(-49), msg as BciEvent];
  } else {
    metricsRef.current = event.data;
  }
} catch {
  metricsRef.current = event.data;
}
```
4. Return `eventsRef` from the hook:
```typescript
return {
  buffers: buffersRef,
  metricsRef,
  eventsRef,
  readyState,
  isConnected: readyState === ReadyState.OPEN,
  sendCommand,
  zunaStatus,
};
```

**Step 3: Verify the existing dashboard still works**

Run: `cd frontend && pnpm dev`
Open `http://localhost:3000/` — dashboard should render unchanged. The `eventsRef` is returned but not consumed by the existing dashboard.

**Step 4: Commit**

```bash
git add frontend/src/hooks/useSensorStream.ts frontend/src/lib/protocol.ts
git commit -m "feat: capture BCI events in useSensorStream hook"
```

---

### Task 2: useEvents hook

A hook that polls `eventsRef` and provides reactive state for components that need to respond to blink events.

**Files:**
- Create: `frontend/src/hooks/useEvents.ts`

**Step 1: Create the hook**

```typescript
// frontend/src/hooks/useEvents.ts
import { useEffect, useRef, useState } from "react";
import type { BciEvent } from "../lib/protocol";

/**
 * Polls an eventsRef and provides:
 * - events: full event log (last 50)
 * - lastEvent: most recent event (for triggering animations)
 */
export function useEvents(
  eventsRef: React.RefObject<BciEvent[]>,
  pollRateMs: number = 100,
) {
  const [events, setEvents] = useState<BciEvent[]>([]);
  const [lastEvent, setLastEvent] = useState<BciEvent | null>(null);
  const prevLenRef = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const current = eventsRef.current;
      if (current.length !== prevLenRef.current) {
        prevLenRef.current = current.length;
        setEvents([...current]);
        setLastEvent(current[current.length - 1] ?? null);
      }
    }, pollRateMs);
    return () => clearInterval(interval);
  }, [eventsRef, pollRateMs]);

  return { events, lastEvent };
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors related to `useEvents.ts`

**Step 3: Commit**

```bash
git add frontend/src/hooks/useEvents.ts
git commit -m "feat: add useEvents hook for reactive BCI event access"
```

---

### Task 3: CompactFit component

A minimal fit indicator for the demo top bar: 4 electrode dots + headband state badge.

**Files:**
- Create: `frontend/src/components/demo/CompactFit.tsx`

**Step 1: Create the component**

```typescript
// frontend/src/components/demo/CompactFit.tsx
import { CHANNEL_NAMES } from "../../lib/protocol";

const CH_COLORS: Record<string, string> = {
  TP9: "var(--ch-tp9)",
  AF7: "var(--ch-af7)",
  AF8: "var(--ch-af8)",
  TP10: "var(--ch-tp10)",
};

interface Props {
  signalQuality?: Record<string, number>;
  headbandState?: { state: "ready" | "fitting" | "headband_off"; seconds_in_state: number };
}

export function CompactFit({ signalQuality, headbandState }: Props) {
  const stateColor = headbandState?.state === "ready" ? "var(--status-good)"
    : headbandState?.state === "fitting" ? "var(--status-warn)"
    : "var(--status-bad)";

  const stateLabel = headbandState?.state === "ready" ? "READY"
    : headbandState?.state === "fitting" ? "FITTING"
    : headbandState?.state === "headband_off" ? "OFF"
    : "---";

  return (
    <div className="flex items-center gap-2">
      {/* Electrode dots */}
      <div className="flex items-center gap-1">
        {CHANNEL_NAMES.map((name) => {
          const q = signalQuality?.[name] ?? 0;
          const good = q > 0.7;
          return (
            <div
              key={name}
              title={`${name}: ${Math.round(q * 100)}%`}
              className="w-2 h-2 rounded-full"
              style={{
                background: good ? CH_COLORS[name] : "var(--status-bad)",
                opacity: good ? 1 : 0.4,
              }}
            />
          );
        })}
      </div>
      {/* Headband state badge */}
      <span
        className="text-[9px] uppercase px-1.5 py-0.5 border font-mono"
        style={{ color: stateColor, borderColor: stateColor }}
      >
        {stateLabel}
      </span>
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/demo/CompactFit.tsx
git commit -m "feat: add CompactFit component for demo top bar"
```

---

### Task 4: LightOrb component

The glowing orb that shows commanded light color/brightness with ambient bleed.

**Files:**
- Create: `frontend/src/components/demo/LightOrb.tsx`

**Step 1: Create the component**

```typescript
// frontend/src/components/demo/LightOrb.tsx

interface Props {
  color: string;       // hex color, e.g. "#FF6600"
  brightness: number;  // 0-255
  label?: string;      // optional device label
}

export function LightOrb({ color, brightness, label }: Props) {
  const opacity = brightness / 255;
  const glowSpread = 80 + (brightness / 255) * 60; // 80-140px

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="w-24 h-24 rounded-full transition-all duration-500"
        style={{
          background: `radial-gradient(circle at 40% 35%, rgba(255,255,255,0.3), ${color} 50%, transparent 70%)`,
          opacity: Math.max(opacity, 0.05),
          boxShadow: `0 0 ${glowSpread}px ${glowSpread / 2}px ${color}`,
          filter: `brightness(${0.5 + opacity * 0.5})`,
        }}
      />
      <div className="text-center">
        <div className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>
          {color} · {Math.round((brightness / 255) * 100)}%
        </div>
        {label && (
          <div className="text-[9px] font-mono" style={{ color: "var(--text-dim)" }}>
            {label}
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/demo/LightOrb.tsx
git commit -m "feat: add LightOrb component with ambient glow"
```

---

### Task 5: BlinkFlash overlay

Full-screen flash on blink events. CSS-only animation triggered by `lastEvent`.

**Files:**
- Create: `frontend/src/components/demo/BlinkFlash.tsx`

**Step 1: Create the component**

```typescript
// frontend/src/components/demo/BlinkFlash.tsx
import { useEffect, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Props {
  lastEvent: BciEvent | null;
}

type FlashLevel = "none" | "single" | "double" | "triple";

export function BlinkFlash({ lastEvent }: Props) {
  const [flash, setFlash] = useState<FlashLevel>("none");
  const [shake, setShake] = useState(false);
  const [eventId, setEventId] = useState(0);

  useEffect(() => {
    if (!lastEvent) return;
    if (!lastEvent.kind.includes("blink")) return;

    const level: FlashLevel =
      lastEvent.kind === "triple_blink" ? "triple"
      : lastEvent.kind === "double_blink" ? "double"
      : "single";

    setFlash(level);
    setEventId((id) => id + 1);

    if (level === "triple") {
      setShake(true);
      setTimeout(() => setShake(false), 150);
    }

    const timer = setTimeout(() => setFlash("none"), 200);
    return () => clearTimeout(timer);
  }, [lastEvent]);

  if (flash === "none") return null;

  const intensity =
    flash === "triple" ? "rgba(255,255,255,0.15)"
    : flash === "double" ? "rgba(255,255,255,0.08)"
    : "rgba(255,255,255,0.03)";

  const spread =
    flash === "triple" ? 80
    : flash === "double" ? 50
    : 30;

  return (
    <div
      key={eventId}
      className="fixed inset-0 pointer-events-none z-50"
      style={{
        boxShadow: `inset 0 0 ${spread}px ${spread / 2}px ${intensity}`,
        animation: "flash-fade 200ms ease-out forwards",
        transform: shake ? "translate(2px, -1px)" : "none",
      }}
    />
  );
}
```

**Step 2: Add the CSS animation to styles.css**

Add at the end of `frontend/src/styles.css`:

```css
@keyframes flash-fade {
  0% { opacity: 1; }
  100% { opacity: 0; }
}
```

**Step 3: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 4: Commit**

```bash
git add frontend/src/components/demo/BlinkFlash.tsx frontend/src/styles.css
git commit -m "feat: add BlinkFlash overlay for blink event feedback"
```

---

### Task 6: EEGStrip component

Single-channel waveform strip for the bottom of the demo page. Reuses Canvas 2D approach from `EEGWaveformPanel`.

**Files:**
- Create: `frontend/src/components/demo/EEGStrip.tsx`

**Step 1: Create the component**

AF7 = channel index 1 (frontal, shows blinks clearly).

```typescript
// frontend/src/components/demo/EEGStrip.tsx
import { useEffect, useRef } from "react";
import type { SensorBuffers } from "../../hooks/useSensorStream";

const CHANNEL_INDEX = 1; // AF7
const COLOR = "#59ccf2";  // cyan
const SAMPLES_VISIBLE = 256 * 4; // 4 seconds
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
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/demo/EEGStrip.tsx
git commit -m "feat: add EEGStrip single-channel waveform component"
```

---

### Task 7: EventLog component

Scrolling monospace feed showing detected events and triggered actions.

**Files:**
- Create: `frontend/src/components/demo/EventLog.tsx`

**Step 1: Create the component**

```typescript
// frontend/src/components/demo/EventLog.tsx
import { useEffect, useRef } from "react";
import type { BciEvent } from "../../lib/protocol";

const KIND_COLORS: Record<string, string> = {
  single_blink: "var(--text-primary)",
  double_blink: "var(--text-primary)",
  triple_blink: "var(--text-primary)",
  clench: "var(--status-warn)",
};

const KIND_ACTIONS: Record<string, string> = {
  single_blink: "blink detected",
  double_blink: "kiosk → next",
  triple_blink: "light → toggle",
  clench: "clench detected",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

interface Props {
  events: BciEvent[];
}

export function EventLog({ events }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events.length]);

  const reversed = [...events].reverse();

  return (
    <div
      className="p-3"
      style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
    >
      <div
        className="text-[12px] uppercase tracking-wider mb-2"
        style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}
      >
        Event Log
      </div>
      <div
        ref={scrollRef}
        className="overflow-y-auto font-mono text-[11px] space-y-0.5"
        style={{ maxHeight: 160, color: "var(--text-dim)" }}
      >
        {reversed.length === 0 && (
          <div style={{ color: "var(--text-dim)" }}>Waiting for events...</div>
        )}
        {reversed.map((ev, i) => (
          <div key={`${ev.timestamp}-${i}`} className="flex items-center gap-2">
            <span style={{ color: "var(--text-dim)" }}>{formatTime(ev.timestamp)}</span>
            <span style={{ color: KIND_COLORS[ev.kind] ?? "var(--text-secondary)" }}>
              {ev.kind.replace(/_/g, " ")}
            </span>
            <span style={{ color: "var(--text-dim)" }}>
              ({(ev.confidence * 100).toFixed(0)}%)
            </span>
            <span style={{ color: "var(--text-dim)" }}>→</span>
            <span style={{ color: "var(--status-info)" }}>
              {KIND_ACTIONS[ev.kind] ?? ev.kind}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/demo/EventLog.tsx
git commit -m "feat: add EventLog component for BCI event feed"
```

---

### Task 8: KioskPlayer component

A faux kiosk: video player that advances on double-blink. Uses demo clips from `public/demo/`.

**Files:**
- Create: `frontend/src/components/demo/KioskPlayer.tsx`

**Step 1: Create placeholder demo videos directory**

Run: `mkdir -p frontend/public/demo`

Add a placeholder text file so the directory is committed:

```bash
echo "Place demo .mp4 clips here. KioskPlayer cycles through them on double-blink." > frontend/public/demo/README.txt
```

**Step 2: Create the component**

```typescript
// frontend/src/components/demo/KioskPlayer.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Props {
  lastEvent: BciEvent | null;
  clips?: string[]; // paths relative to public, e.g. ["/demo/clip1.mp4"]
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

  // Listen for double_blink events
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.kind !== "double_blink") return;
    if (lastEvent.timestamp === lastProcessedRef.current) return;
    lastProcessedRef.current = lastEvent.timestamp;
    nextClip();
  }, [lastEvent, nextClip]);

  // Auto-play when clip changes
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
      {/* NEXT overlay */}
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
      {/* Clip counter */}
      <div
        className="absolute bottom-1 right-2 text-[9px] font-mono"
        style={{ color: "var(--text-dim)" }}
      >
        {clipIndex + 1}/{clips.length}
      </div>
    </div>
  );
}
```

**Step 3: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 4: Commit**

```bash
git add frontend/src/components/demo/KioskPlayer.tsx frontend/public/demo/README.txt
git commit -m "feat: add KioskPlayer component with double-blink navigation"
```

---

### Task 9: CommandArrow animation

Animated glowing particle that flies from brain area to target panel when a command fires.

**Files:**
- Create: `frontend/src/components/demo/CommandArrow.tsx`

**Step 1: Create the component**

```typescript
// frontend/src/components/demo/CommandArrow.tsx
import { useEffect, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Particle {
  id: number;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  color: string;
}

// Target positions as percentages of viewport
const TARGETS: Record<string, { x: number; y: number; color: string }> = {
  double_blink: { x: 85, y: 65, color: "var(--status-info)" },   // kiosk area
  triple_blink: { x: 85, y: 20, color: "var(--status-warn)" },   // light orb area
};

const ORIGIN = { x: 30, y: 40 }; // center of brain heatmap area

let particleId = 0;

interface Props {
  lastEvent: BciEvent | null;
}

export function CommandArrow({ lastEvent }: Props) {
  const [particles, setParticles] = useState<Particle[]>([]);

  useEffect(() => {
    if (!lastEvent) return;
    const target = TARGETS[lastEvent.kind];
    if (!target) return;

    const newParticle: Particle = {
      id: ++particleId,
      startX: ORIGIN.x,
      startY: ORIGIN.y,
      endX: target.x,
      endY: target.y,
      color: target.color,
    };

    setParticles((prev) => [...prev.slice(-4), newParticle]);

    // Remove after animation completes
    const timer = setTimeout(() => {
      setParticles((prev) => prev.filter((p) => p.id !== newParticle.id));
    }, 600);

    return () => clearTimeout(timer);
  }, [lastEvent]);

  return (
    <div className="fixed inset-0 pointer-events-none z-40">
      {particles.map((p) => (
        <div
          key={p.id}
          className="absolute w-2 h-2 rounded-full"
          style={{
            left: `${p.startX}%`,
            top: `${p.startY}%`,
            background: p.color,
            boxShadow: `0 0 12px 4px ${p.color}`,
            animation: `particle-fly-${p.id} 500ms ease-in-out forwards`,
          }}
        >
          <style>{`
            @keyframes particle-fly-${p.id} {
              0% {
                left: ${p.startX}%;
                top: ${p.startY}%;
                opacity: 1;
                transform: scale(1);
              }
              80% {
                left: ${p.endX}%;
                top: ${p.endY}%;
                opacity: 0.8;
                transform: scale(1.5);
              }
              100% {
                left: ${p.endX}%;
                top: ${p.endY}%;
                opacity: 0;
                transform: scale(0.5);
              }
            }
          `}</style>
        </div>
      ))}
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/components/demo/CommandArrow.tsx
git commit -m "feat: add CommandArrow particle animation"
```

---

### Task 10: Concentration-to-color utility

Shared function to map concentration score to hex color. Used by both the demo page (LightOrb) and the backend (UmkaBridgeStage).

**Files:**
- Create: `frontend/src/lib/concentrationColor.ts`

**Step 1: Create the utility**

```typescript
// frontend/src/lib/concentrationColor.ts

/**
 * Map concentration (0-1) to warm→cool color gradient.
 *
 * 1.0 (focused)  → warm orange #FF6600
 * 0.5 (neutral)  → white #FFFFFF
 * 0.0 (relaxed)  → cool blue #0066FF
 */
export function concentrationToHex(score: number): string {
  let r: number, g: number, b: number;

  if (score >= 0.5) {
    const t = (score - 0.5) * 2; // 0→1
    r = 255;
    g = Math.round(255 - (255 - 102) * t); // 255→102
    b = Math.round(255 - 255 * t);          // 255→0
  } else {
    const t = score * 2; // 0→1
    r = Math.round(255 * t);                // 0→255
    g = Math.round(102 + (255 - 102) * t);  // 102→255
    b = 255;
  }

  return `#${r.toString(16).padStart(2, "0").toUpperCase()}${g.toString(16).padStart(2, "0").toUpperCase()}${b.toString(16).padStart(2, "0").toUpperCase()}`;
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`

**Step 3: Commit**

```bash
git add frontend/src/lib/concentrationColor.ts
git commit -m "feat: add concentrationToHex color mapping utility"
```

---

### Task 11: Demo page route — wire everything together

**Files:**
- Create: `frontend/src/routes/demo.tsx`

**Step 1: Create the route**

```typescript
// frontend/src/routes/demo.tsx
import { useState, useMemo } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { useBandPowers, type BandName } from "../hooks/useBandPowers";
import { useEvents } from "../hooks/useEvents";
import { BrainHeatmap } from "../components/BrainHeatmap";
import { BandSelector } from "../components/BandSelector";
import { CompactFit } from "../components/demo/CompactFit";
import { LightOrb } from "../components/demo/LightOrb";
import { BlinkFlash } from "../components/demo/BlinkFlash";
import { CommandArrow } from "../components/demo/CommandArrow";
import { EEGStrip } from "../components/demo/EEGStrip";
import { EventLog } from "../components/demo/EventLog";
import { KioskPlayer } from "../components/demo/KioskPlayer";
import { concentrationToHex } from "../lib/concentrationColor";

export const Route = createFileRoute("/demo")({
  component: DemoPage,
});

function DemoPage() {
  const { buffers, metricsRef, eventsRef, isConnected } = useSensorStream();
  const metrics = useMetrics(metricsRef);
  const { getBandPowers } = useBandPowers(metrics);
  const { events, lastEvent } = useEvents(eventsRef);
  const [selectedBand, setSelectedBand] = useState<BandName>("focus");

  // Derive light state from concentration
  const concentration = metrics?.brain?.concentration ?? 0.5;
  const eyesClosed = metrics?.eyes_closed?.active ?? false;
  const lightColor = useMemo(() => concentrationToHex(concentration), [concentration]);
  const lightBrightness = eyesClosed ? 10 : 255;

  return (
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}
    >
      {/* Scan line overlay */}
      <div
        className="fixed inset-0 pointer-events-none z-30"
        style={{
          background: "repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0,0,0,0.03) 1px, rgba(0,0,0,0.03) 2px)",
        }}
      />

      {/* Blink flash + command arrow overlays */}
      <BlinkFlash lastEvent={lastEvent} />
      <CommandArrow lastEvent={lastEvent} />

      {/* Top bar */}
      <div className="flex items-center justify-between h-10 px-4 shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
        <span
          className="text-sm font-mono"
          style={{
            color: "var(--text-dim)",
            fontFamily: "var(--font-label)",
            letterSpacing: "0.3em",
            fontWeight: 200,
          }}
        >
          EUTERPE
        </span>
        <div className="flex items-center gap-4">
          <CompactFit
            signalQuality={metrics?.eeg?.signal_quality}
            headbandState={metrics?.headband}
          />
          <div className="flex items-center gap-2 text-[11px] font-mono" style={{ color: "var(--text-dim)" }}>
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{
                background: isConnected ? "var(--status-good)" : "var(--status-bad)",
                boxShadow: isConnected ? "0 0 6px var(--status-good)" : "none",
              }}
            />
            {isConnected ? "connected" : "disconnected"}
          </div>
        </div>
      </div>

      {/* Main content: two columns */}
      <div className="flex-1 grid grid-cols-5 min-h-0" style={{ gap: "var(--gap)", padding: "var(--gap)" }}>
        {/* Left column: brain (3/5) */}
        <div className="col-span-3 flex flex-col min-h-0">
          <div className="flex-1 min-h-0">
            <BrainHeatmap
              bandPowers={getBandPowers()}
              selectedBand={selectedBand}
              height="100%"
            />
          </div>
          <BandSelector selected={selectedBand} onSelect={setSelectedBand} />
        </div>

        {/* Right column: panels (2/5) */}
        <div className="col-span-2 flex flex-col min-h-0" style={{ gap: "var(--gap)" }}>
          {/* Light orb */}
          <div
            className="p-4 flex items-center justify-center"
            style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}
          >
            <LightOrb color={lightColor} brightness={lightBrightness} label="Main light" />
          </div>

          {/* Focus / Relax bars */}
          <div className="p-3" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[11px] w-12" style={{ color: "var(--text-secondary)" }}>Focus</span>
                <div className="flex-1 h-2" style={{ background: "var(--bg-input)" }}>
                  <div
                    className="h-full transition-all duration-300"
                    style={{
                      width: `${concentration * 100}%`,
                      background: "var(--band-beta)",
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span className="text-[13px] font-mono w-10 text-right" style={{ color: "var(--text-primary)" }}>
                  {(concentration * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] w-12" style={{ color: "var(--text-secondary)" }}>Relax</span>
                <div className="flex-1 h-2" style={{ background: "var(--bg-input)" }}>
                  <div
                    className="h-full transition-all duration-300"
                    style={{
                      width: `${(metrics?.brain?.relaxation ?? 0) * 100}%`,
                      background: "var(--band-alpha)",
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span className="text-[13px] font-mono w-10 text-right" style={{ color: "var(--text-primary)" }}>
                  {((metrics?.brain?.relaxation ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>

          {/* Kiosk player */}
          <KioskPlayer lastEvent={lastEvent} />

          {/* Event log */}
          <div className="flex-1 min-h-0 overflow-hidden">
            <EventLog events={events} />
          </div>
        </div>
      </div>

      {/* Bottom EEG strip */}
      <div className="shrink-0" style={{ borderTop: "1px solid var(--border)" }}>
        <EEGStrip buffersRef={buffers} height={40} />
      </div>
    </div>
  );
}
```

**Step 2: Handle BrainHeatmap height prop**

The existing `BrainHeatmap` accepts `height` as a `number`. We're passing `"100%"`. Modify `frontend/src/components/BrainHeatmap.tsx`:

In the `BrainHeatmapProps` interface, change:
```typescript
height?: number | string;
```

This affects the Canvas `style` and the placeholder `div` — both already use `style={{ height }}` which accepts `number | string`.

**Step 3: Verify the page loads**

Run: `cd frontend && pnpm dev`
Open: `http://localhost:3001/demo`

Expected: Demo page renders with brain heatmap on left, light orb + bars + event log on right, EEG strip at bottom. EUTERPE label in top bar with fit indicator and connection dot.

**Step 4: Commit**

```bash
git add frontend/src/routes/demo.tsx frontend/src/components/BrainHeatmap.tsx
git commit -m "feat: add /demo route — EUTERPE demo page with full layout"
```

---

### Task 12: Rename CORTEX to EUTERPE on main dashboard

**Files:**
- Modify: `frontend/src/routes/index.tsx`

**Step 1: Update the label**

In `frontend/src/routes/index.tsx`, find line 31:
```tsx
<span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>CORTEX</span>
```

Replace with:
```tsx
<span className="text-sm font-mono" style={{ color: "var(--text-dim)" }}>EUTERPE</span>
```

**Step 2: Verify**

Open `http://localhost:3001/` — top bar should say EUTERPE.

**Step 3: Commit**

```bash
git add frontend/src/routes/index.tsx
git commit -m "feat: rename CORTEX to EUTERPE"
```

---

### Task 13: Visual polish and testing

**Files:**
- Possibly adjust: `frontend/src/components/demo/*.tsx`, `frontend/src/routes/demo.tsx`

**Step 1: Test with synthetic backend**

Run in separate terminals:
```bash
# Terminal 1: backend
python -m backend.main --synthetic

# Terminal 2: frontend
cd frontend && pnpm dev
```

Open `http://localhost:3001/demo`

**Step 2: Visual checklist**

- [ ] Brain heatmap renders and rotates (colors update with synthetic data)
- [ ] Band selector works (click different bands, heatmap changes)
- [ ] Light orb glows and changes color (tracks concentration)
- [ ] Focus/Relax bars move with synthetic data
- [ ] EEG strip shows waveform at bottom
- [ ] Top bar: EUTERPE label, electrode dots, headband badge, connection dot
- [ ] Event log shows "Waiting for events..." (synthetic board doesn't generate blinks)
- [ ] Page is full-screen, no scroll, dark background

**Step 3: Test blink events (if headband available)**

Connect real Muse:
```bash
python -m backend.main --mac XX:XX:XX:XX:XX:XX
```

- [ ] Single blink → subtle flash
- [ ] Double blink → brighter flash + kiosk advances + command arrow to kiosk
- [ ] Triple blink → full flash + shake + command arrow to light orb
- [ ] Events appear in log with timestamps and confidence

**Step 4: Adjust colors/sizing if needed**

Common tweaks:
- LightOrb glow spread (adjust `glowSpread` calculation)
- CommandArrow target positions (adjust `TARGETS` percentages)
- EEGStrip line width
- Panel relative sizes in the grid

**Step 5: Commit any polish**

```bash
git add -u
git commit -m "fix: visual polish for demo page"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Capture BCI events in hook | `useSensorStream.ts`, `protocol.ts` |
| 2 | `useEvents` hook | `useEvents.ts` |
| 3 | `CompactFit` | `demo/CompactFit.tsx` |
| 4 | `LightOrb` | `demo/LightOrb.tsx` |
| 5 | `BlinkFlash` | `demo/BlinkFlash.tsx`, `styles.css` |
| 6 | `EEGStrip` | `demo/EEGStrip.tsx` |
| 7 | `EventLog` | `demo/EventLog.tsx` |
| 8 | `KioskPlayer` | `demo/KioskPlayer.tsx` |
| 9 | `CommandArrow` | `demo/CommandArrow.tsx` |
| 10 | Color utility | `concentrationColor.ts` |
| 11 | Demo route (wire all) | `demo.tsx`, `BrainHeatmap.tsx` |
| 12 | Rename CORTEX→EUTERPE | `index.tsx` |
| 13 | Visual polish + testing | various |

**Dependencies:** Tasks 1-10 are independent (can parallelize). Task 11 depends on all of them. Tasks 12-13 depend on 11.
