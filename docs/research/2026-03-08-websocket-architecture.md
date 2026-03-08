# Research: WebSocket Architecture for High-Frequency EEG Dashboard

**Date:** 2026-03-08
**Sources:** 18 sources (key ones listed below)

---

## Executive Summary

For a 256Hz EEG streaming dashboard, the framework choice matters far less than the **data pipeline architecture inside the browser**. The proven pattern is: Python backend streams binary data over a plain WebSocket (not Socket.IO), React consumes it via `react-use-websocket` or native `WebSocket`, buffers incoming data in a `useRef` (never `setState` per message), and flushes to a WebGL-based chart on `requestAnimationFrame`. The charting library is the critical choice — **webgl-plot** (MIT, purpose-built for oscilloscope/waveform display) is the best fit for this project. TanStack Start, Vite, Next.js — none of these affect WebSocket performance; the real-time path bypasses the framework entirely.

---

## Key Findings

### 1. The Core Problem: React Re-renders at 256Hz

The fundamental challenge is not WebSocket transport — modern browsers handle thousands of WS messages per second trivially. The problem is **React's rendering model**. If every incoming EEG sample triggers `setState`, you get 256 render cycles per second minimum, which will destroy performance and block the main thread [1].

The established solution has three parts:

**Buffer in a ref, not state.** Incoming WebSocket messages go into a `useRef` array — a mutable container that doesn't trigger renders. This accumulates samples between frames [1].

**Flush on requestAnimationFrame.** A `requestAnimationFrame` loop reads the ref buffer, collapses all accumulated samples into a single state update (or directly feeds the chart), and clears the buffer. This limits UI updates to 60fps regardless of data rate [1].

**Isolate the chart component.** The chart component that consumes high-frequency data should be isolated from the rest of the React tree. Use `React.memo`, avoid passing streaming data through context, and consider rendering the chart outside React entirely (direct canvas/WebGL manipulation) [1].

```typescript
// The pattern (simplified)
const bufferRef = useRef<Float32Array[]>([]);
const { lastMessage } = useWebSocket(wsUrl);

useEffect(() => {
  if (lastMessage?.data) {
    bufferRef.current.push(new Float32Array(lastMessage.data));
  }
}, [lastMessage]);

useEffect(() => {
  const flush = () => {
    const samples = bufferRef.current.splice(0);
    // feed samples directly to WebGL chart (no setState)
    chart.appendData(samples);
    rafId = requestAnimationFrame(flush);
  };
  let rafId = requestAnimationFrame(flush);
  return () => cancelAnimationFrame(rafId);
}, []);
```

### 2. Python Backend: Plain `websockets` or FastAPI

Two solid options for the Python WebSocket server:

**`websockets` library (standalone):** Minimal, asyncio-native, ~50 lines for a streaming server. Best if the WebSocket server is all you need. Handles thousands of connections efficiently [3].

**FastAPI WebSocket routes:** If you want HTTP endpoints alongside WebSocket (e.g., REST API for session management, health checks). FastAPI's WebSocket support is built on Starlette and works well with asyncio [3]. The Convex Python client could also run in this process.

For EEG streaming, **send binary data (Float32Array), not JSON**. At 256Hz with 4 channels, JSON encoding/parsing adds measurable overhead. Binary WebSocket frames with `ArrayBuffer` on the client side eliminate parsing entirely [5].

```python
# Python side: pack EEG samples as binary
import struct
# 4 channels × 4 bytes (float32) = 16 bytes per sample
packet = struct.pack(f'{len(samples)}f', *samples)
await websocket.send(packet)
```

```typescript
// Client side: zero-copy read
ws.binaryType = 'arraybuffer';
ws.onmessage = (event) => {
  const samples = new Float32Array(event.data);
  // samples[0..3] = TP9, AF7, AF8, TP10
};
```

### 3. WebSocket Library Choice: Keep It Simple

| Library | Overhead | Binary Support | React Integration | Recommendation |
|---------|----------|---------------|-------------------|----------------|
| **Native WebSocket** | Zero | Yes (ArrayBuffer) | Manual hooks | Fine for simple cases |
| **react-use-websocket** | Minimal | Yes (binaryType) | Built-in hooks | Best for React projects |
| **Socket.IO** | Significant | Yes but abstracted | Via adapter | Overkill — adds fallback transports, rooms, namespaces you don't need |

**Recommendation: `react-use-websocket`** [6]. It provides `useWebSocket` with auto-reconnect, connection state management, and access to the underlying WebSocket for setting `binaryType`. Socket.IO's fallback transports (long polling, etc.) are unnecessary when you control both endpoints on localhost.

### 4. Charting Library: The Critical Decision

This is where performance is won or lost. At 256Hz × 4 channels, you're pushing ~1,024 data points per second with a sliding window of several seconds.

| Library | Rendering | License | Performance | EEG/Waveform Use | React Support |
|---------|-----------|---------|-------------|-------------------|---------------|
| **webgl-plot** | WebGL native | MIT | 60fps, lightweight | Purpose-built for oscilloscope/waveform | Yes (basic) |
| **LightningChart JS** | WebGL | Commercial ($790+/yr) | 400ch × 1kHz demonstrated | Official EEG demos | Yes |
| **SciChart JS** | WebGL + WASM | Commercial ($1,200+/yr) | 100M points at 60fps | ECG/EKG demos | Yes |
| **uPlot** | Canvas 2D | MIT | Very fast for Canvas | Time-series, not waveform-specific | Community |
| **Chart.js** | Canvas 2D | MIT | Slow at high frequency | Not suitable | Yes |
| **Recharts/Plotly** | SVG/Canvas | MIT | Too slow | Not suitable | Yes |

**Recommendation: webgl-plot** [7]. It's MIT-licensed, purpose-built for exactly this use case (oscilloscope/waveform display), renders at screen refresh rate via native WebGL, and has a minimal API (`setY(index, value)` per point, `update()` per frame). The API maps directly to the EEG data pipeline: allocate 4 `WebglLine` objects, feed samples via `setY`, call `update` on each animation frame.

If webgl-plot proves too minimal (you need axes, legends, zoom), **uPlot** is the Canvas 2D fallback — significantly faster than Chart.js/Recharts, and has a better API for time-series. But for raw waveform display, webgl-plot is hard to beat.

### 5. Architecture: Framework Is Irrelevant to the Hot Path

The WebSocket data path is entirely framework-agnostic:

```
BrainFlow (C++) → Python process → WebSocket (binary) → Browser
    → useRef buffer → requestAnimationFrame → WebGL canvas (direct)
```

React/TanStack Start/Vite only matter for:
- The app shell (layout, navigation, settings panels)
- Convex integration (session metadata, derived metrics at 1-4Hz)
- Non-real-time UI (buttons, forms, configuration)

The chart canvas is effectively **outside React's render cycle**. You get a ref to the canvas element, create the WebGL context, and update it imperatively. React doesn't know or care about the 256Hz data flowing through.

This means **TanStack Start is fine** — it won't help with WebSocket performance, but it won't hurt it either. The framework handles everything except the hot path, which bypasses it entirely.

### 6. Optimization Techniques for 256Hz+

**Batch on the server side.** Instead of sending 256 individual WebSocket messages per second, batch samples into chunks. Sending 4 batches of 64 samples per second (16ms intervals) is more efficient than 256 individual messages. This matches `requestAnimationFrame` cadence [1].

**Use SharedArrayBuffer + Web Worker** (optional, for compute-heavy processing). If you're doing FFT, band power calculation, or other DSP in the browser, offload to a Web Worker. The worker receives raw samples, computes derived metrics, and posts results back. SharedArrayBuffer enables zero-copy data sharing between threads [1].

**Ring buffer for chart data.** Don't grow arrays indefinitely. Use a fixed-size ring buffer (e.g., 5 seconds × 256Hz = 1,280 samples per channel). When the buffer is full, new samples overwrite the oldest. webgl-plot's `setY` API supports this pattern naturally.

**Downsample for zoomed-out views.** If you show a 60-second history, you don't need 15,360 points per channel. Downsample to ~500 points using min/max decimation (preserves peaks/troughs). Only show full resolution for the most recent 2-5 seconds.

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────┐
│ Python Process                                   │
│                                                  │
│  BrainFlow ──→ Ring Buffer ──→ WebSocket Server  │
│  (256Hz)       (collect)       (binary, batched)  │
│                    │                              │
│                    └──→ Compute derived metrics   │
│                         (band powers, HR, fit)   │
│                              │                   │
│                              └──→ Convex mutations│
│                                   (1-4Hz)        │
└──────────────────────────────────────────────────┘
          │ ws://localhost:8765 (binary)
          ▼
┌─────────────────────────────────────────────────┐
│ Browser (TanStack Start SPA)                     │
│                                                  │
│  useWebSocket ──→ useRef buffer                  │
│  (binary)         (no re-renders)                │
│                       │                          │
│                       ▼                          │
│              requestAnimationFrame               │
│                       │                          │
│           ┌───────────┼───────────┐              │
│           ▼           ▼           ▼              │
│     webgl-plot    Metrics UI   Fit Tool          │
│     (canvas,      (React,     (React,            │
│      imperative)   1-4Hz)     1-4Hz)             │
│                                                  │
│  Convex reactive queries ←── session/metadata    │
└──────────────────────────────────────────────────┘
```

---

## Open Questions

- **webgl-plot React wrapper maturity**: The React integration is "under development." May need to write a thin wrapper component (~30 lines) that manages the canvas ref and WebGL context lifecycle.
- **Server-side batching optimal interval**: 16ms (matching rAF) vs 50ms vs 100ms — needs benchmarking. Lower intervals mean smoother visuals but more WebSocket overhead.
- **Web Worker for browser-side DSP**: Worth it if you want browser-computed band powers or FFT. Not needed if all derived metrics come from Python.
- **WebTransport (HTTP/3)**: Emerging alternative to WebSocket with better multiplexing. Not widely adopted yet, but worth watching for future iterations [2].

---

## Sources

[1] SitePoint. "Streaming Backends & React: Controlling Re-render Chaos in High-Frequency Data." https://www.sitepoint.com/streaming-backends-react-controlling-re-render-chaos/
[2] JetBI. "Streaming in 2026: SSE vs WebSockets vs RSC." https://jetbi.com/blog/streaming-architecture-2026-beyond-websockets
[3] Leapcell. "Real-time Communication in Python with WebSockets and FastAPI." https://leapcell.io/blog/real-time-communication-in-python-with-websockets-and-fastapi
[4] FastAPI. "WebSockets." https://fastapi.tiangolo.com/advanced/websockets/
[5] MDN. "WebSocket: binaryType property." https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/binaryType
[6] npm. "react-use-websocket." https://www.npmjs.com/package/react-use-websocket
[7] GitHub. "webgl-plot: High-Performance real-time 2D plotting." https://github.com/danchitnis/webgl-plot
[8] LightningChart. "Data Visualization Real Time With WebSockets." https://lightningchart.com/blog/data-visualization-websockets/
[9] NetBurner. "Visualizing Sensor Data With WebGL And WebSockets." https://www.netburner.com/learn/visualizing-sensor-data-with-webgl-and-websockets/
[10] SciChart. "Alternatives to LightningChart." https://www.scichart.com/blog/alternatives-to-lightningchart/
[11] Ably. "Choosing the right WebSocket library for React projects." https://ably.com/blog/choosing-the-right-websocket-library-for-react-project
[12] webgl-plot docs. https://webgl-plot.vercel.app/docs
[13] DasRoot. "Python WebSocket Servers: Real-Time Communication Patterns." https://dasroot.net/posts/2026/02/python-websocket-servers-real-time-communication-patterns/
[14] OneUpTime. "How to Use WebSockets in React for Real-Time Applications." https://oneuptime.com/blog/post/2026-01-15-websockets-react-real-time-applications/view
