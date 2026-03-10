# 3D Brain Heatmap Design

**Date:** 2026-03-10

---

## Overview

Real-time 3D brain heatmap visualization for the Muse trainer dashboard. A semi-transparent stylized head model displays interpolated EEG activity across the scalp, updating every second with EMA smoothing. Works in two modes: 4ch (browser-side interpolation from raw Muse) and 23ch (ZUNA-reconstructed on GPU). The heatmap is primarily a visualization/wow feature — underlying detection uses raw 4ch features.

## Disclaimers

- **4ch mode:** "Estimated from 4 sensors — visualization only, not clinical EEG"
- **ZUNA 23ch mode:** "AI-reconstructed from 4 sensors — more spatial detail but not equivalent to physical electrodes"

Always visible below the head. Not dismissible.

---

## Architecture

### Data Flow

```
Muse 2 → BrainFlow (4ch raw) → Python backend
                                    ├→ WebSocket: raw 4ch frames (existing)
                                    ├→ WebSocket: band powers per channel (new, 1Hz)
                                    └→ [if GPU] ZUNA pipeline → 23ch band powers (1Hz)

Browser receives band_powers → interpolate to scalp grid → color map → 3D head
```

### Band Powers Message (1Hz)

```json
{
  "type": "band_powers",
  "mode": "4ch",
  "channels": {
    "TP9":  {"delta": 4.1, "theta": 5.2, "alpha": 12.1, "beta": 8.3, "gamma": 2.1},
    "AF7":  {"delta": 3.8, "theta": 4.9, "alpha": 6.5, "beta": 7.1, "gamma": 1.8},
    "AF8":  {"delta": 3.5, "theta": 5.1, "alpha": 5.9, "beta": 6.8, "gamma": 1.9},
    "TP10": {"delta": 4.3, "theta": 5.5, "alpha": 13.2, "beta": 9.1, "gamma": 2.3}
  },
  "timestamp": 1710000000.0
}
```

ZUNA mode: same format with 23 channel entries. Frontend handles both identically — more channels = more interpolation points = sharper gradients.

---

## 3D Head Model & Rendering

**Stack:** React Three Fiber (R3F) inside the existing React dashboard.

**Geometry:** Parametric ellipsoid (~2000 vertices). Slightly elongated vertically, flattened at back. Stylized glass head, not anatomically realistic.

**Visual style:**
- Semi-transparent shell with fresnel glow at edges
- Electrode positions as small glowing dots
- Nose indicator at front for orientation
- Slow auto-rotation (grabbable for manual rotation)
- Subtle pulsing tied to dominant frequency

**Color scale:** Cool-to-warm gradient (blue → cyan → green → yellow → red). Adaptive normalization: first 30 seconds establish baseline, then colors show deviation from personal baseline.

**Performance:** 2000-vertex mesh, color updates 1/second with EMA lerp. Trivial for any WebGL-capable device.

---

## Interpolation

### Spherical Spline (4ch → scalp)

Each electrode maps to spherical coordinates (θ, φ) on the head. Weight matrix W computed once at startup:

```
W[vertex_i, electrode_j] = spline_weight(distance(vertex_i, electrode_j))
```

Each frame:
```
vertex_values = W × electrode_values  // 2000×4 multiply, microseconds
```

For 23ch ZUNA: W is 2000×23. Same code path, more data points, sharper result.

### EMA Smoothing

Per-vertex in frontend:
```
display[i] = α * new[i] + (1 - α) * display[i]
```

Start with α=0.3 (70% smoothing). Tunable via dev slider.

---

## Band Selection UI

Toggle strip below the heatmap:

```
[FOCUS] [θ] [α] [β] [γ] [δ]
```

- **FOCUS** (default): theta/beta ratio (validated at d=1.61+ for 3-state classification)
- **θ α β γ δ**: Individual band powers (4-8, 8-13, 13-30, 30-50, 1-4 Hz)

Selecting a band changes which values drive the color map. All bands sent every second — no backend change needed.

Optional toggle: show/hide electrode labels (Fp1, Fz, O2, etc.) floating above dots. Off by default.

---

## Debug & Development Tools

### Simulated Data Mode

`<BrainHeatmap debug="wave" />` — no backend needed.

- **`static`**: Fixed values per channel — verify interpolation and color mapping
- **`wave`**: Sine wave sweeping front-to-back (2s cycle) — verify spatial interpolation is smooth
- **`random`**: Random per-channel values, 1Hz — stress test EMA smoothing

### Dev Panel (visible when debug is set)

- Per-electrode value sliders (manually verify spatial mapping)
- EMA alpha slider (0.1 to 1.0)
- Color scale min/max override
- Wireframe toggle
- Interpolation weight visualization checkbox

### Console Logging

When debug active: log every band_powers message and resulting interpolated vertex values.

---

## Development Order

1. 3D head with static coloring (verify geometry)
2. Debug sliders (verify interpolation math)
3. Connect to WebSocket (verify real data flow)
4. EMA smoothing (tune feel)
5. Band selection toggle
6. Polish (fresnel, glow, pulsing animation)

Each step independently testable. No Muse or ZUNA needed until step 3.

---

## Validation Test Cases

### Test 1: Alpha Blocking

- Record 30s eyes open, 30s eyes closed
- Select α band
- **Expected:** Back of head (occipital/parietal) lights up warm during eyes closed, cools during eyes open. Front changes less.
- **Pass:** Back visibly warmer than front during eyes closed. (Proven: 2.54x at O1/O2 ZUNA, 3.68x at TP9/TP10 raw.)

### Test 2: Meditation vs Mental Math

- Select FOCUS (theta/beta)
- 60s meditation, then 60s mental math
- **Expected:** Frontal area lights up warm during math (high theta/beta), cools during meditation.
- **Pass:** Visible color shift between conditions. (Proven: d=1.61+.)

### Test 3: Left vs Right Asymmetry

- Clench jaw on right side only
- **Expected:** Asymmetric pattern — TP10/AF8 side shows more activity.
- **Pass:** Two sides of head are visibly different colors.

### Test 4: Spatial Gradient (4ch vs 23ch)

- Same session, compare 4ch interpolation vs 23ch ZUNA
- **Expected:** 4ch = smooth blobby gradients. 23ch = sharper, more distinct regions.
- **Pass:** 23ch has visibly more spatial detail.

### Test 5: Baseline Normalization

- Sit still 30s (baseline), then do something (blink, math, meditate)
- **Expected:** Head starts neutral (green/mid), shifts when activity changes.
- **Pass:** Head doesn't start all-red or all-blue.

### Test 6: Interpolation Sanity

- Debug sliders: TP9=max, all others=0
- **Expected:** Left temporal area hot, opposite side cool, smooth gradient between.
- **Pass:** Hot spot at TP9's actual scalp position (left ear area), not wrong location.

Tests 1-2: existing recordings. Tests 3, 5: live with Muse. Test 4: requires ZUNA GPU. Test 6: debug panel only.

---

## Dependencies

- `@react-three/fiber` — React Three.js renderer
- `@react-three/drei` — Helpers (OrbitControls, etc.)
- `three` — Three.js core

No external 3D model files. Head geometry generated procedurally.
