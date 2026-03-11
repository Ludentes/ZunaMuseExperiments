# EEG Topomap / Brain Visualization — Web Library Research

**Date:** 2026-03-10
**Goal:** Find existing libraries for browser-based EEG topographic maps and 3D brain visualization. Evaluate build-vs-buy.

## Context: What We Already Have

Our `BrainHeatmap.tsx` already implements:
- 3D head mesh via `@react-three/fiber` + `three.js` on a deformed `SphereGeometry`
- 10-20 electrode positions in spherical coords (`electrodes.ts`, 4ch + 23ch sets)
- IDW (inverse distance weighting, power=2) interpolation from electrodes to mesh vertices (`interpolation.ts`)
- Vertex coloring with 5-stop blue-cyan-green-yellow-red scale
- Adaptive baseline normalization with EMA
- Smooth lerp between band power updates
- Auto-rotate, orbit controls, nose indicator, electrode dots, legend, disclaimer
- Debug modes: static, wave, random

**Stack:** Three.js 0.183, @react-three/fiber 9.5, @react-three/drei 10.7

---

## Library Comparison

### 1. topogrid (NeuroJS)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/NeuroJS/topogrid |
| **npm** | `topogrid` |
| **Stars** | ~9 |
| **Last update** | ~2017 (9 years ago on npm) |
| **What it does** | JavaScript interpolation for 2D topographic EEG plots. Takes electrode x/y + values, outputs a 2D grid. |
| **Real-time?** | Possibly (it's just math), but not designed for it |
| **License** | MIT |
| **React integration** | Manual — it outputs a grid, you'd render on Canvas 2D |
| **Verdict** | **Dead project.** Only does 2D grid interpolation. Our `interpolation.ts` already does the same thing but in 3D with IDW. No value. |

### 2. eeg-pipes (Neurosity)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/neurosity/eeg-pipes |
| **Stars** | ~50 |
| **Last update** | 2020-ish |
| **What it does** | RxJS operators for EEG DSP: bandpass, epoch, FFT, etc. No visualization. |
| **Real-time?** | Yes (streaming RxJS) |
| **License** | MIT |
| **React integration** | Easy (RxJS operators) |
| **Verdict** | **No visualization.** DSP-only. We already have our own pipeline in Python backend. |

### 3. BrainBrowser (McGill/ACES)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/aces/brainbrowser |
| **Stars** | ~375 |
| **Last update** | Sporadic commits, last release 2017 (v2.5.2). Some commits in 2024. |
| **What it does** | Two viewers: (1) **Surface Viewer** — WebGL 3D brain surface with data maps, color maps, thresholds, blending. Uses Three.js. (2) **Volume Viewer** — HTML5 Canvas slice viewer for MINC/NIfTI/MGH. |
| **Real-time?** | Not designed for real-time streaming. Loads static data files. |
| **License** | MIT-like (custom academic) |
| **React integration** | **Hard.** Old jQuery-era code. No React wrapper. Would need heavy adaptation. |
| **Verdict** | **Impressive but wrong tool.** Designed for MRI/fMRI brain surface visualization, not EEG topomaps. The surface viewer could theoretically be repurposed, but it loads MNI brain meshes (FreeSurfer, Wavefront) — completely different from our use case of mapping 4 EEG channels to a scalp surface. Too heavy, too old, wrong problem. |

### 4. NiiVue

| Field | Value |
|-------|-------|
| **URL** | https://github.com/niivue/niivue |
| **npm** | `@niivue/niivue` |
| **Stars** | ~300+ |
| **Last update** | Active (2025-2026) |
| **What it does** | WebGL2 medical image viewer. 30+ volume/mesh formats (NIfTI, DICOM, GIfTI, FreeSurfer). Slice views, 3D rendering, overlays. |
| **Real-time?** | No. Loads static volumes. |
| **License** | BSD-2-Clause |
| **React integration** | `niivue-react` wrapper exists (not on npm yet, install from GitHub) |
| **Verdict** | **Wrong tool.** Full neuroimaging viewer. We don't have MRI data. We need to map 4 electrode values to a scalp surface, not view brain volumes. |

### 5. threejs-brain-animation (bytezpro)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/bytezpro/threejs-brain-animation |
| **npm** | `threejs-brain-animation` |
| **Stars** | ~5-10 |
| **Last update** | Unknown, likely 2024 |
| **What it does** | React component rendering 3D brain with parcellation, interactive controls. Uses Three.js. |
| **Real-time?** | Static display, not data-driven heatmap |
| **License** | MIT |
| **React integration** | Native React component |
| **Verdict** | **Cosmetic only.** Renders a brain model with atlas parcellation. No data mapping, no heatmap, no interpolation. Could provide a nicer mesh than our deformed sphere, but would need all the data mapping rebuilt on top. |

### 6. webgl-heatmap (pyalot)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/pyalot/webgl-heatmap |
| **Stars** | ~908 |
| **Last update** | 2013 (abandoned) |
| **What it does** | GPU-accelerated 2D heatmap via WebGL. Additive blending of point intensities with fragment shaders. Fast for thousands of points. |
| **Real-time?** | Yes — GPU-based, designed for it |
| **License** | MIT |
| **React integration** | Manual Canvas wrapper needed |
| **Verdict** | **2D only, abandoned.** High performance but only does Gaussian splat heatmaps on a 2D canvas. Not scalp-shaped. Could theoretically be used for a 2D topomap (project electrodes to 2D, splat heatmap, clip to head circle), but the approach is dated. |

### 7. EpiCurrents

| Field | Value |
|-------|-------|
| **URL** | https://github.com/epicurrents |
| **Stars** | Low (new project) |
| **Last update** | Active (2026, published in scientific journal Feb 2026) |
| **What it does** | Modular JS library for viewing clinical neurophysiology signals (EEG, EMG, NCS). Signal waveform viewer, FFT, annotations. PWA. |
| **Real-time?** | Yes (progressive web app, streaming capable) |
| **License** | Open source (exact license TBD) |
| **React integration** | Unknown framework, likely vanilla |
| **Verdict** | **No topomap.** Signal viewer only (waveforms, FFT). No spatial/topographic visualization. Similar in scope to our existing waveform display. |

### 8. rbf (thibauts)

| Field | Value |
|-------|-------|
| **URL** | https://github.com/thibauts/rbf |
| **npm** | `rbf` |
| **Stars** | ~24 |
| **Last update** | Old (likely 2015-2016) |
| **What it does** | Radial Basis Function interpolation in pure JS. Supports linear, cubic, quintic, thin-plate, gaussian, multiquadric, inverse-multiquadric kernels. |
| **Real-time?** | The interpolation itself is fast, but solves a linear system on init (O(n^3) for n points). For 4-23 electrodes this is instant. |
| **License** | MIT |
| **React integration** | Pure math library, easy to use anywhere |
| **Verdict** | **Potentially useful as an interpolation upgrade.** Our current IDW is simple but produces blobby results with 4 electrodes. RBF (thin-plate spline) is what MNE uses under the hood (via scipy's CloughTocher2DInterpolator, which is similar). Could swap our IDW for RBF for smoother interpolation. However, with only 4 electrodes the difference is minimal. |

### 9. BCI2000Web / bci2k.js

| Field | Value |
|-------|-------|
| **URL** | https://github.com/cronelab/bci2k.js |
| **Stars** | ~15 |
| **Last update** | ~2018-2019 |
| **What it does** | JavaScript WebSocket connector to BCI2000. WebFM uses d3.js for brain surface visualization of high-gamma modulation. |
| **Real-time?** | Yes (WebSocket streaming from BCI2000) |
| **License** | Open source |
| **React integration** | Manual |
| **Verdict** | **Wrong platform.** Requires BCI2000 running as backend. The WebFM visualization is d3.js on a 2D brain image, not a reusable component. |

### 10. muse-js / eeg-explorer

| Field | Value |
|-------|-------|
| **URL** | https://github.com/urish/muse-js / https://github.com/urish/eeg-explorer |
| **Stars** | ~400 (muse-js) |
| **Last update** | 2020-ish |
| **What it does** | Web Bluetooth connection to Muse headsets + simple waveform visualization |
| **Real-time?** | Yes |
| **License** | MIT |
| **React integration** | Angular-based examples |
| **Verdict** | **Connection library, no topomap.** We already use BrainFlow for Muse connection. No spatial visualization. |

---

## MNE's Topomap Algorithm (Reference Implementation)

MNE-Python's `mne.viz.plot_topomap` is the gold standard. Key implementation details:

1. **Interpolation methods:**
   - `cubic` (default): `scipy.interpolate.CloughTocher2DInterpolator` — piecewise cubic, C1 continuous
   - `linear`: `scipy.interpolate.LinearNDInterpolator`
   - `nearest`: Voronoi tessellation (no interpolation)

2. **Process:**
   - Project 3D electrode positions to 2D (azimuthal equidistant projection)
   - Create a regular grid covering the head circle
   - Interpolate electrode values to grid using chosen method
   - Mask to head circle outline
   - Apply colormap

3. **Extrapolation:** `local` (near sensors only), `head` (to head circle), `box` (beyond head)

4. **Key insight for us:** With only 4 electrodes, the interpolation method matters less — IDW, RBF, and CloughTocher all produce similar blobby results. The spatial resolution is fundamentally limited by electrode count, not interpolation quality.

---

## Summary: Nothing Exists That We Should Use

**There is no maintained, React-compatible, EEG topomap library for the web.**

The landscape breaks down as:
- **Dead projects** (topogrid, webgl-heatmap) — 7-10 years old
- **Wrong problem** (BrainBrowser, NiiVue, threejs-brain-animation) — designed for MRI/fMRI, not EEG topomaps
- **DSP only** (eeg-pipes) — no visualization
- **Signal viewers** (EpiCurrents, eeg-explorer) — waveforms, not spatial maps
- **Platform-locked** (BCI2000Web) — requires BCI2000 backend

**Our existing implementation is already the state-of-the-art for this use case:**
- react-three-fiber 3D head with vertex coloring
- IDW interpolation (adequate for 4 channels)
- Adaptive baseline normalization
- Real-time updates with smooth lerping
- 10-20 electrode position mapping

## Recommendations

### What to keep (already built)
1. Our Three.js/R3F approach is correct — no library does this for us
2. IDW interpolation is fine for 4 channels (MNE's CloughTocher wouldn't improve with so few points)
3. Adaptive baseline is good for real-time use

### Potential improvements (build, not buy)
1. **Better head mesh:** Replace deformed sphere with a proper head-shaped mesh (load a `.glb` head model). Several free head models exist on Sketchfab/Turbosquid.
2. **2D topomap option:** Add a flat 2D Canvas view (azimuthal projection + head circle, MNE-style) as an alternative to 3D. Simpler, lighter, more familiar to neuroscience users.
3. **Shader-based coloring:** Move vertex coloring to a custom shader for better performance and smoother gradients (fragment-level interpolation instead of vertex-level).
4. **RBF interpolation:** If/when we get 23-channel ZUNA reconstruction working, switch from IDW to thin-plate spline RBF (the `rbf` npm package or hand-roll — it's ~50 lines of math). Worth it at 23+ channels, not at 4.

### Not worth pursuing
- Any existing library (all dead, wrong problem, or insufficient)
- BrainBrowser/NiiVue integration (MRI viewers, not EEG topomaps)
- webgl-heatmap (2D only, 2013 code)
