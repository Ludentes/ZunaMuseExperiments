# Frontend Design: EEG Dashboard

**Date:** 2026-03-08
**Aesthetic:** Industrial-scientific instrument. Think oscilloscope meets Bloomberg terminal.

---

## Design Direction

**Tone:** Utilitarian precision. This is a lab instrument, not an app. Every pixel serves a purpose. Dense information, low visual noise.

**Key aesthetic choices:**
- **Dark background** — `#0a0e14` (near-black with blue undertone), not pure black. Reduces eye strain during long sessions.
- **Accent grid lines** — faint `rgba(255,255,255,0.04)` grid pattern in waveform panels, like oscilloscope CRT phosphor traces
- **Monospace data** — all numeric values in `JetBrains Mono`. Labels in `Geist Sans` (geometric, precise).
- **Color palette:** Muted neons on dark — cyan `#5ce0d8`, amber `#e8a838`, lime `#8ce840`, violet `#b068e8`, rose `#e84868` for alerts. No pure white — text is `#c8d0dc`.
- **Panel borders:** 1px `rgba(255,255,255,0.08)` with no border-radius. Sharp corners. Instruments don't have rounded corners.
- **Status indicators:** Small pulsing dots, not badges. Green/amber/red. Pulse rate encodes severity.
- **Dense layout:** Minimize whitespace. Panels packed tight with 8px gaps. Information density is a feature, not a bug.

## CSS Variables

```css
:root {
  /* Background layers */
  --bg-base: #0a0e14;
  --bg-panel: #0f1419;
  --bg-elevated: #141a22;
  --bg-input: #1a2230;

  /* Text */
  --text-primary: #c8d0dc;
  --text-secondary: #6b7a8d;
  --text-dim: #3d4a5c;

  /* Channel colors */
  --ch-tp9: #5ce0d8;
  --ch-af7: #e8a838;
  --ch-af8: #8ce840;
  --ch-tp10: #b068e8;

  /* Status */
  --status-good: #38e870;
  --status-warn: #e8a838;
  --status-bad: #e84868;
  --status-info: #5ca8e0;

  /* Band power colors */
  --band-delta: #5c68e0;
  --band-theta: #5ce0d8;
  --band-alpha: #8ce840;
  --band-beta: #e8a838;
  --band-gamma: #e85c5c;

  /* Borders */
  --border: rgba(255, 255, 255, 0.08);
  --border-focus: rgba(255, 255, 255, 0.2);

  /* Spacing */
  --gap: 8px;
  --panel-padding: 12px;

  /* Fonts */
  --font-data: 'JetBrains Mono', monospace;
  --font-label: 'Geist Sans', sans-serif;
}
```

## Typography Scale

```
Panel title:    12px, font-label, uppercase, letter-spacing 0.08em, text-secondary
Data value:     20px, font-data, text-primary (large metrics like HR)
Data value sm:  14px, font-data, text-primary (band powers, ratios)
Channel label:  11px, font-data, channel color, opacity 0.8
Status text:    11px, font-label, status color
Input label:    11px, font-label, text-secondary
```

---

## Component Designs

### 1. Top Bar

Minimal strip. Left: title "CORTEX" in font-data, 14px, text-dim. Right: connection status dot (pulsing green when connected, static red when not) + "ws://localhost:8765" in font-data 11px text-dim.

```
┌──────────────────────────────────────────────────────────┐
│  CORTEX                              ● ws://localhost:8765│
└──────────────────────────────────────────────────────────┘
```

Height: 32px. Background: transparent (sits on bg-base).

### 2. Fit Tool Panel

**Layout:** Horizontal strip. Left: SVG head diagram (top-down oval). Right: 4 electrode quality bars + status text.

**Head diagram (SVG):**
- Simple oval outline (head shape) in `--border`
- Nose indicator triangle at top center
- 4 circles at electrode positions: TP9 (left), AF7 (upper-left), AF8 (upper-right), TP10 (right)
- Circle fill color: green/amber/red based on quality score
- Circle size: 8px, with a subtle glow (box-shadow matching the color) when quality > 0.7

**Quality bars:**
- Each channel: `[TP9 ████████░░ 95%]`
- Label in channel color, bar fill in same color with opacity gradient, value in font-data
- Bar height: 6px, width: 120px, background: var(--bg-input)
- Fill uses the channel color at 80% opacity

**Status line:**
- Fit status word in status color: "GOOD" / "ADJUST" / "POOR"
- If "ADJUST": append recommendation text in text-secondary: "adjust left ear"
- Motion + jaw indicators: small text with status dots

```tsx
// Key visual structure
<div className="flex items-center gap-6 p-3 border-b" style={{ borderColor: 'var(--border)' }}>
  <HeadDiagram quality={signalQuality} />  {/* 80x80px SVG */}
  <div className="flex-1 grid grid-cols-2 gap-x-6 gap-y-1">
    {channels.map(ch => <QualityBar key={ch} channel={ch} value={quality[ch]} />)}
  </div>
  <div className="text-right">
    <FitStatusBadge status={fitStatus} />
    <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>
      Motion: {motionArtifact ? '⚠ MOVING' : 'still'} | Jaw: {jawClench ? '⚠ CLENCH' : 'clear'}
    </div>
  </div>
</div>
```

### 3. EEG Waveform Panel

**Layout:** Full width. 4 channels stacked vertically inside a single webgl-plot canvas.

**Visual treatment:**
- Canvas background: `var(--bg-panel)` with CSS background-image of subtle horizontal grid lines every 25% height (channel dividers)
- Left column (40px): channel labels in channel colors, vertically centered in each quarter
- Right edge: faint scale indicator "±100 uV" in text-dim
- Top-right corner overlay: time window label "5.0s" in text-dim

**Panel title strip:**
```
EEG  ·  256 Hz  ·  0.5–45 Hz                              5.0s ▾
```
Title in panel-title style. Sampling rate and filter in text-dim. Window selector as a tiny dropdown.

**Canvas sizing:** `width: 100%; height: 256px` (64px per channel). Responsive via ResizeObserver updating webgl-plot dimensions.

### 4. Brain Metrics Panel

**Layout:** Left column in the bottom grid. Two sections stacked.

**Band Powers section:**
```
BAND POWERS
δ delta    ████████████████░░░░░  12.3
θ theta    ██████████░░░░░░░░░░░   8.1
α alpha    ████████████████████░  15.7
β beta     ████████░░░░░░░░░░░░░   6.2
γ gamma    ███░░░░░░░░░░░░░░░░░░   2.1
```
- Greek letter in band color, 14px font-data
- Band name in text-secondary, 11px
- Horizontal bar: band color at 60% opacity, background var(--bg-input)
- Bar width proportional to power value (normalized to max across bands)
- Numeric value right-aligned in font-data 13px

**Ratios section:**
```
RATIOS
θ/β   1.31  relaxed
FAA  -0.03  neutral
```
- Ratio name in text-secondary
- Value in font-data, text-primary
- Interpretation label in a pill: "focused" (green), "relaxed" (cyan), "neutral" (dim), "drowsy" (amber)
- Pill: 2px border in the interpretation color, no fill, 9px font-label uppercase

### 5. Vitals Panel

**Layout:** Right column top. Three metric cards + PPG waveform.

**Heart Rate card:**
```
HR
♥ 72                  bpm
```
- "HR" panel title style
- Heart symbol in `--status-bad` (rose), pulses with a CSS animation synced to the displayed BPM (approximated via `animation-duration: calc(60s / bpm)`)
- Large number: 32px font-data, text-primary
- "bpm" unit: 11px font-data, text-dim

**SpO2 card:**
```
SpO₂
98.2%
```
- Value in font-data 20px
- Color: green if >95%, amber if 90-95%, red if <90%

**HRV card:**
```
HRV (RMSSD)
42.3 ms
```
- Value in font-data 16px, text-primary

**PPG Waveform:**
- Small webgl-plot canvas, height: 48px
- Single line in rose/red color
- Same visual treatment as EEG panel but smaller, no channel labels
- Label: "PPG IR · 64 Hz" in panel title style above

### 6. Motion Panel

**Layout:** Right column bottom, below vitals.

```
MOTION
Pitch  -5.2°   Roll  1.8°       Movement  0.12 (still)
[████████████████████████████████████████████████████░░░] artifact threshold
```

- Head pose values in font-data
- Degree symbol in text-dim
- Movement value with interpretation: "still" (green), "light" (amber), "moving" (red)
- Artifact bar: full width, thin (4px height), fills with amber/red when motion_artifact is true. Green when clear.
- Jaw clench indicator: small text "JAW CLENCH" that flashes red when detected, otherwise hidden

### 7. Controls Panel

**Layout:** Full width bottom strip. Horizontal arrangement.

```
┌──────────────────────────────────────────────────────────────────┐
│  ● REC  ⏹ STOP  │  HP 0.5 Hz  LP 45 Hz  Notch 50Hz  │  PPG ● IMU ●  │
└──────────────────────────────────────────────────────────────────┘
```

**Record button:**
- Default: outlined button, text "REC" with a small circle icon
- Recording state: solid `--status-bad` background, pulsing, text "REC ● 00:32" with a live timer
- Stop: only visible when recording

**Filter controls:**
- Small labeled inputs (40px wide) for highpass, lowpass
- Notch filter: segmented toggle: OFF | 50Hz | 60Hz
- All in font-data 12px

**Stream toggles:**
- "PPG" and "IMU" labels with small toggle switches (shadcn Switch component)
- When off, respective panels show "disabled" state with dimmed content

**Style:** Background var(--bg-panel), border-top var(--border). Height: ~44px. Everything aligned center vertically.

---

## Responsive Behavior

**Primary target: 1920×1080 desktop monitor** (lab/workstation use).

At smaller widths (<1200px):
- Bottom grid stacks to single column (Brain Metrics full width, then Vitals+Motion full width)
- Controls wrap to 2 rows

At <768px:
- Not a priority (this is a workstation tool), but don't break — just stack everything vertically

---

## Animation Inventory

Minimal. Lab instruments don't bounce.

1. **Connection dot pulse** — `@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.4 } }` duration 2s, only when connected
2. **Heart pulse** — CSS animation on the heart symbol, duration derived from BPM
3. **Recording pulse** — Red dot next to "REC" pulses at 1s interval when recording
4. **Fit status transition** — 200ms color transition on quality bars and head diagram circles when values change
5. **Artifact flash** — Motion artifact bar flashes amber→transparent, 300ms, when artifact detected

No page transitions, no panel entrance animations, no hover effects on data displays. Data changes are the animation.

---

## Font Loading

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Geist+Sans:wght@400;500&display=swap" rel="stylesheet">
```

Fallback chain: `'JetBrains Mono', 'Fira Code', 'SF Mono', monospace` and `'Geist Sans', 'Inter', system-ui, sans-serif`.

---

## shadcn/ui Customization

Override shadcn defaults to match the instrument aesthetic:

- **Card:** Remove border-radius, reduce padding to 12px, use var(--bg-panel) background
- **Badge:** Remove border-radius, use 1px border only (no fill), font-data 10px uppercase
- **Button:** Remove border-radius, 1px border, font-data, uppercase, letter-spacing 0.05em
- **Switch:** Keep shadcn default but tint the active state to channel colors
- **Slider:** Thin track (2px), small thumb (10px), track color var(--bg-input), fill color var(--status-info)

Apply via shadcn's `globals.css` / tailwind theme extension. Do not modify shadcn component source files.
