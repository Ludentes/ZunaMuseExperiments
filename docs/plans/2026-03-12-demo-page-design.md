# EUTERPE Demo Page — Design Document

**Date**: 2026-03-12
**Status**: Approved, ready for implementation plan

## Purpose

A `/demo` route for internal tech demo at the company where the CTO wears a Muse 2 EEG headband and controls lights/kiosks with brain signals. Tech-savvy audience. Equal weight on brain visualization and physical control.

## Aesthetic: Neural Command Center

Dark, atmospheric, alive. The screen breathes with your brain state.

**Key design moves:**
- **Ambient color bleed** — LightOrb uses massive box-shadow (120px+ spread) that tints surrounding panels. Right column shifts color temperature with concentration.
- **Scan line texture** — subtle repeating-linear-gradient overlay (1px transparent / 1px rgba black) for CRT depth.
- **Blink flash** — `box-shadow: inset 0 0 80px` pulse on blink events. Triple blink adds 2px CSS transform shake.
- **Command arrow** — absolutely-positioned 6px glowing circle animated via CSS keyframes from brain area to target panel.
- **EEG strip** — single cyan line on pure black, no chrome. Heartbeat monitor aesthetic.
- **Typography** — "EUTERPE" in Geist, ultra-wide letter-spacing (0.3em), weight 200. Data in JetBrains Mono. Event log highlights actions in signal color.

## Layout

Full-screen, dark background (`--bg-base`), no scrolling. Two-column grid, 60/40 split.

### Top Bar (minimal)
- "EUTERPE" label (Geist, letter-spaced)
- Compact fit indicator: 4 electrode dots (green/red per signal quality) + headband state badge (READY/FITTING/OFF)
- Battery indicator (percentage + icon)
- Connection status dot + WebSocket URL

### Left Column (hero, 60%)
- **BrainHeatmap** — existing R3F component, large, takes full column height minus EEG strip
- **BandSelector** underneath (default: focus)

### Right Column (stacked panels, 40%)
1. **LightOrb** — CSS glowing circle. Props: color (hex), brightness (0-255). Radial gradient fill + massive box-shadow that bleeds onto dark background. Multiple orbs for multiple lights. Label shows hex + brightness.
2. **Focus/Relax bars** — extracted from BrainMetrics, just the BCI State section. Two horizontal bars: Focus (beta color) and Relax (alpha color) with percentage labels.
3. **KioskPlayer** — `<video>` element styled as a small monitor (CSS bezel + shadow). Holds demo video playlist in `public/demo/`. Double blink → next clip with "NEXT" overlay flash. Shows current clip index.
4. **EventLog** — monospace scrolling feed, newest on top, max 50 entries. Format: `HH:MM:SS  signal (confidence)  →  action`. Color-coded: blink=white, concentration=orange/blue, eyes-closed=alpha color.

### Bottom Strip (full width)
- **EEGStrip** — single channel (AF7), ~40px tall, Canvas 2D. Reuses drawing logic from EEGWaveformPanel but one channel, no labels, no grid. Shows blink spikes visually.

### Overlay Effects (no panels)
- **BlinkFlash** — `pointer-events: none` overlay. Single blink = subtle white inset shadow (200ms). Double = brighter. Triple = full flash + CSS transform shake (2px, 150ms).
- **CommandArrow** — when BCI event triggers a command, animate a glowing particle from left column to the target panel on the right. CSS absolute positioning + keyframe animation. Queue-based for multiple simultaneous particles.

## Data Flow

Reuses existing `useSensorStream` hook — same WebSocket connection, same data.

**Currently available (works now):**
- Brain heatmap: `bandPowers` from metrics
- Focus/Relax: `metrics.brain.concentration`, `metrics.brain.relaxation`
- Eyes closed: `metrics.eyes_closed.active`
- Headband state: `metrics.headband.state`
- Signal quality: `metrics.eeg.signal_quality`
- EEG waveform: binary stream buffers

**Needs backend work (Phase 2):**
- Blink events in metrics stream (currently go through Actions, not serialized)
- MQTT command log (what UmkaBridgeStage actually sent)
- Light state (current color/brightness)
- Battery level — BrainFlow doesn't expose Muse 2 battery via `get_battery_channel`. Needs BrainFlow fix or direct BLE GATT read.

**Frontend-only fallback (for demo page before Phase 2):**
- Derive light color from concentration locally (mirror `_concentration_to_hex`)
- Derive eyes-closed dim locally
- Blink events: need to add to metrics serialization (small backend change)

## Components to Build

| Component | Type | Effort |
|-----------|------|--------|
| `demo.tsx` route | New page | Medium |
| `LightOrb` | New component | Small (CSS only) |
| `BlinkFlash` | New component | Small (CSS overlay) |
| `CommandArrow` | New component | Medium (CSS animation) |
| `EEGStrip` | New component | Small (reuse Canvas logic) |
| `KioskPlayer` | New component | Medium (video + commands) |
| `EventLog` | New component | Small (scrolling list) |
| `CompactFit` | New component | Small (extract from FitTool) |

## Components Reused As-Is

- `BrainHeatmap` (with BandSelector)
- `useSensorStream` hook
- `useMetrics` hook
- `useBandPowers` hook

## Out of Scope

- Recording panel (engineering tool, not demo)
- Controls panel (not needed during demo)
- Vitals/Motion panels (not relevant to demo narrative)
- ZUNA toggle (decided: no ZUNA for demo)
- Full band power table / ratios (engineering detail)
