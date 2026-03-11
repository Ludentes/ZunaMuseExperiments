# fsaverage Brain Mesh for Web (React Three Fiber)

**Date**: 2026-03-10
**Status**: Research complete, ready for implementation

---

## 1. Getting the Mesh

### Option A: MNE-Python `fetch_fsaverage` (RECOMMENDED)

MNE already downloads fsaverage to `~/mne_data/MNE-fsaverage-data/fsaverage/` when you call:

```python
import mne
fs_dir = mne.datasets.fetch_fsaverage(verbose=False)
# Returns: ~/mne_data/MNE-fsaverage-data/fsaverage/
```

This includes:
- `surf/lh.pial`, `surf/rh.pial` (brain surface, FreeSurfer binary format)
- `surf/lh.white`, `surf/rh.white` (white matter surface)
- `surf/lh.inflated`, `surf/rh.inflated` (inflated for visualization)
- `bem/` directory with BEM surfaces (inner_skull, outer_skull, **outer_skin** = scalp)

**Already on this machine**: `~/mne_data/MNE-fsaverage-data/fsaverage/`

### Option B: Nilearn `fetch_surf_fsaverage`

```python
from nilearn.datasets import fetch_surf_fsaverage
fs = fetch_surf_fsaverage('fsaverage5')  # 10,242 vertices per hemisphere
# Files in GIFTI (.gii.gz) format at ~/nilearn_data/
```

Resolution options:
| Mesh | Vertices/hemisphere | Triangles/hemisphere (approx) |
|------|--------------------|-----------------------------|
| fsaverage3 | 642 | ~1,280 |
| fsaverage4 | 2,562 | ~5,120 |
| **fsaverage5** | **10,242** | **~20,480** |
| fsaverage6 | 40,962 | ~81,920 |
| fsaverage7 | 163,842 | ~327,680 |

**fsaverage5 is ideal for web**: ~40k triangles for both hemispheres combined, well under the 100k target.

### Option C: Direct download (no FreeSurfer needed)

- **OSF (MNE's source)**: `https://osf.io/download/3bxqt?version=2` — ZIP file with fsaverage
- **Nilearn bundles fsaverage5** in-package at `nilearn/datasets/data/fsaverage5/` as `.gii.gz` files
- **GitHub**: FreeSurfer's `subjects/fsaverage` is in the FreeSurfer repo but the repo is huge

### License

FreeSurfer uses a **permissive BSD-style license** (FreeSurfer Software License v1.0, Feb 2011):
- Royalty-free, non-exclusive license to use, reproduce, make derivative works, display, distribute
- Must include license terms and copyright notices
- Research purposes only (no clinical use warranty)
- **fsaverage can be redistributed** as long as license is included
- MNE and nilearn both redistribute it freely

### File Formats

| Source | Format | Notes |
|--------|--------|-------|
| FreeSurfer native | FreeSurfer binary (`.pial`, `.white`) | Need nibabel to read |
| Nilearn | GIFTI (`.gii.gz`) | Standard neuroimaging mesh format |
| Neither | GLB/GLTF/OBJ | Must convert |

---

## 2. Converting to GLB/GLTF

### Recommended Pipeline: nibabel + trimesh

```python
#!/usr/bin/env python3
"""Convert fsaverage pial surface to GLB for web visualization."""
import nibabel as nib
import nibabel.freesurfer as fs
import trimesh
import numpy as np

# Option A: From FreeSurfer binary files (MNE's download)
def from_freesurfer(fs_dir):
    lh_verts, lh_faces = fs.read_geometry(f"{fs_dir}/surf/lh.pial")
    rh_verts, rh_faces = fs.read_geometry(f"{fs_dir}/surf/rh.pial")

    # Combine hemispheres (offset right hemi face indices)
    verts = np.vstack([lh_verts, rh_verts])
    faces = np.vstack([lh_faces, rh_faces + len(lh_verts)])

    return trimesh.Trimesh(vertices=verts, faces=faces)

# Option B: From nilearn GIFTI files
def from_gifti(gii_path):
    gii = nib.load(gii_path)
    verts = gii.darrays[0].data  # coordinates
    faces = gii.darrays[1].data  # triangles
    return trimesh.Trimesh(vertices=verts, faces=faces)

# Load
mesh = from_freesurfer("/home/newub/mne_data/MNE-fsaverage-data/fsaverage")

# Decimate if needed (fsaverage has ~327k triangles per hemi = ~655k total)
# Target: ~40-80k triangles
target_faces = 60000
if len(mesh.faces) > target_faces:
    mesh = mesh.simplify_quadric_decimation(target_faces)
    print(f"Decimated to {len(mesh.faces)} faces")

# Add sulcal depth as vertex colors (optional, for visual detail)
# lh_sulc = fs.read_morph_data(f"{fs_dir}/surf/lh.sulc")
# rh_sulc = fs.read_morph_data(f"{fs_dir}/surf/rh.sulc")
# ... map to gray colormap

# Export to GLB
mesh.export("brain_pial.glb")
print(f"Exported: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
```

### Alternative: Use fsaverage5 directly (skip decimation)

```python
from nilearn.datasets import fetch_surf_fsaverage
import nibabel as nib
import trimesh
import numpy as np

fs = fetch_surf_fsaverage('fsaverage5')  # Already ~10k verts/hemi

lh = nib.load(fs['pial_left'])
rh = nib.load(fs['pial_right'])

lh_v, lh_f = lh.darrays[0].data, lh.darrays[1].data
rh_v, rh_f = rh.darrays[0].data, rh.darrays[1].data

verts = np.vstack([lh_v, rh_v])
faces = np.vstack([lh_f, rh_f + len(lh_v)])

# Add sulcal depth for visual quality
lh_sulc = nib.load(fs['sulc_left']).darrays[0].data
rh_sulc = nib.load(fs['sulc_right']).darrays[0].data
sulc = np.concatenate([lh_sulc, rh_sulc])

# Map sulcal depth to colors (gyri=light gray, sulci=dark gray)
sulc_norm = np.clip((sulc - sulc.min()) / (sulc.max() - sulc.min()), 0, 1)
colors = np.zeros((len(verts), 4), dtype=np.uint8)
gray = (200 - sulc_norm * 120).astype(np.uint8)  # 80-200 gray range
colors[:, 0] = gray
colors[:, 1] = gray
colors[:, 2] = gray
colors[:, 3] = 255

mesh = trimesh.Trimesh(vertices=verts, faces=faces, vertex_colors=colors)
mesh.export("brain_fsaverage5.glb")
# Result: ~40k faces, ~20k vertices, well under 100k target
```

**This is the recommended approach** -- fsaverage5 is already the right resolution, no decimation needed.

### Decimation Quality

- `trimesh.simplify_quadric_decimation()` uses quadric error metrics -- preserves sulci detail well
- PyVista's `decimate()` also works: `mesh.decimate(0.9)` removes 90% of faces
- For best sulci preservation, decimate from fsaverage (163k/hemi) to ~30k/hemi rather than using pre-decimated fsaverage5
- In practice, fsaverage5 looks good enough for EEG visualization

### Required Python packages

```bash
pip install nibabel trimesh numpy
# trimesh needs pyglet or another backend for GLB export
# If GLB export fails, install: pip install pyglet
```

---

## 3. MNI Coordinates for 10-20 System

### Complete 10-10 system (97 electrodes) from MNE's `standard_1020.elc`

Source file: `mne/channels/data/montages/standard_1020.elc`
Coordinate system: MNI (mm), on the **scalp surface**

#### Muse 2 channels (the ones we need now):

| Electrode | X (mm) | Y (mm) | Z (mm) |
|-----------|--------|--------|--------|
| **TP9** | -85.619 | -46.515 | -45.707 |
| **AF7** | -54.840 | 68.572 | -10.590 |
| **AF8** | 55.743 | 69.657 | -10.755 |
| **TP10** | 86.162 | -47.035 | -45.869 |

#### Full 10-10 set (for future ZUNA 23ch):

| Electrode | X | Y | Z |
|-----------|-------|--------|---------|
| Fp1 | -29.437 | 83.917 | -6.990 |
| Fpz | 0.112 | 88.247 | -1.713 |
| Fp2 | 29.872 | 84.896 | -7.080 |
| AF7 | -54.840 | 68.572 | -10.590 |
| AF3 | -33.701 | 76.837 | 21.227 |
| AFz | 0.231 | 80.771 | 35.417 |
| AF4 | 35.712 | 77.726 | 21.956 |
| AF8 | 55.743 | 69.657 | -10.755 |
| F7 | -70.263 | 42.474 | -11.420 |
| F5 | -64.466 | 48.035 | 16.921 |
| F3 | -50.244 | 53.111 | 42.192 |
| F1 | -27.496 | 56.931 | 60.342 |
| Fz | 0.312 | 58.512 | 66.462 |
| F2 | 29.514 | 57.602 | 59.540 |
| F4 | 51.836 | 54.305 | 40.814 |
| F6 | 67.914 | 49.830 | 16.367 |
| F8 | 73.043 | 44.422 | -12.000 |
| FT7 | -80.775 | 14.120 | -11.135 |
| FC5 | -77.215 | 18.643 | 24.460 |
| FC3 | -60.182 | 22.716 | 55.544 |
| FC1 | -34.062 | 26.011 | 79.987 |
| FCz | 0.376 | 27.390 | 88.668 |
| FC2 | 34.784 | 26.438 | 78.808 |
| FC4 | 62.293 | 23.723 | 55.630 |
| FC6 | 79.534 | 19.936 | 24.438 |
| FT8 | 81.815 | 15.417 | -11.330 |
| T7 | -84.161 | -16.019 | -9.346 |
| C5 | -80.280 | -13.760 | 29.160 |
| C3 | -65.358 | -11.632 | 64.358 |
| C1 | -36.158 | -9.984 | 89.752 |
| Cz | 0.401 | -9.167 | 100.244 |
| C2 | 37.672 | -9.624 | 88.412 |
| C4 | 67.118 | -10.900 | 63.580 |
| C6 | 83.456 | -12.776 | 29.208 |
| T8 | 85.080 | -15.020 | -9.490 |
| TP9 | -85.619 | -46.515 | -45.707 |
| TP7 | -84.830 | -46.022 | -7.056 |
| CP5 | -79.592 | -46.551 | 30.949 |
| CP3 | -63.556 | -47.009 | 65.624 |
| CP1 | -35.513 | -47.292 | 91.315 |
| CPz | 0.386 | -47.318 | 99.432 |
| CP2 | 38.384 | -47.073 | 90.695 |
| CP4 | 66.612 | -46.637 | 65.580 |
| CP6 | 83.322 | -46.101 | 31.206 |
| TP8 | 85.549 | -45.545 | -7.130 |
| TP10 | 86.162 | -47.035 | -45.869 |
| P7 | -72.434 | -73.453 | -2.487 |
| P5 | -67.272 | -76.291 | 28.382 |
| P3 | -53.007 | -78.788 | 55.940 |
| P1 | -28.620 | -80.525 | 75.436 |
| Pz | 0.325 | -81.115 | 82.615 |
| P2 | 31.920 | -80.487 | 76.716 |
| P4 | 55.667 | -78.560 | 56.561 |
| P6 | 67.888 | -75.904 | 28.091 |
| P8 | 73.056 | -73.068 | -2.540 |
| PO7 | -54.840 | -97.528 | 2.792 |
| PO3 | -36.511 | -100.853 | 37.167 |
| POz | 0.216 | -102.178 | 50.608 |
| PO4 | 36.782 | -100.849 | 36.397 |
| PO8 | 55.667 | -97.625 | 2.730 |
| O1 | -29.413 | -112.449 | 8.839 |
| Oz | 0.108 | -114.892 | 14.657 |
| O2 | 29.843 | -112.156 | 8.800 |
| Iz | 0.005 | -118.565 | -23.078 |

**These are SCALP coordinates** (from the standard_1020.elc montage), which is exactly what we need for electrode placement.

### How to use in MNE:

```python
montage = mne.channels.make_standard_montage('standard_1020')
# montage.get_positions() returns dict with ch_pos in MNI meters
# Multiply by 1000 for mm
```

---

## 4. Brain vs. Scalp Surface: Architecture Decision

### The Problem

- **Pial surface** = brain cortex (inside skull). Good for showing which brain regions are active.
- **Scalp surface** = where electrodes physically sit. Available as fsaverage's BEM outer_skin surface.
- EEG electrodes are on the scalp, but we want to visualize brain activity.

### Recommendation: Pial brain only, electrodes projected inward

For a BCI dashboard (not clinical neuroimaging), the best approach:

1. **Show pial (brain) surface** with sulcal depth coloring (dark sulci, light gyri)
2. **Project electrode positions to nearest brain vertex** -- find the closest point on the pial surface for each MNI scalp coordinate
3. **Draw electrode markers as spheres** slightly above the brain surface (offset 2-3mm along vertex normal)
4. **Color the surrounding brain patch** based on channel power/activity (paint nearby vertices)

This is what MNE's `Brain` class, nilearn's `view_surf`, and every EEG paper does.

**Why NOT a scalp mesh:**
- Scalp mesh hides the brain (the interesting part)
- A transparent scalp over a brain is visually cluttered at dashboard scale
- Electrode projection to brain surface is trivial (nearest vertex search)

### Projection Code

```python
from scipy.spatial import cKDTree

# Build KD-tree from brain surface vertices
tree = cKDTree(brain_verts)

# For each electrode MNI coordinate, find nearest brain vertex
electrode_mni = {
    'TP9': [-85.619, -46.515, -45.707],
    'AF7': [-54.840, 68.572, -10.590],
    'AF8': [55.743, 69.657, -10.755],
    'TP10': [86.162, -47.035, -45.869],
}

projected = {}
for name, pos in electrode_mni.items():
    dist, idx = tree.query(pos)
    projected[name] = {
        'brain_vertex': int(idx),
        'brain_pos': brain_verts[idx].tolist(),
        'scalp_pos': pos,
        'projection_dist_mm': float(dist),
    }
```

### Alternative: Bake everything into GLB

A Python script can generate a single GLB with:
- Brain mesh (with sulcal depth vertex colors)
- Electrode spheres as separate mesh objects
- Named nodes in the GLB scene graph for React Three Fiber to target

```python
import trimesh

scene = trimesh.Scene()

# Add brain
scene.add_geometry(brain_mesh, node_name='brain')

# Add electrode spheres
for name, pos in projected.items():
    sphere = trimesh.creation.icosphere(radius=3.0)  # 3mm radius
    sphere.apply_translation(pos['brain_pos'])
    sphere.visual.vertex_colors = [255, 0, 0, 255]  # Red
    scene.add_geometry(sphere, node_name=f'electrode_{name}')

scene.export('brain_with_electrodes.glb')
```

---

## 5. Existing Web Implementations

### nilearn `view_surf` -- Standalone HTML

```python
from nilearn import plotting, datasets

fsaverage = datasets.fetch_surf_fsaverage()
view = plotting.view_surf(
    fsaverage['pial_left'],
    surf_map=None,  # or sulcal depth for shading
    symmetric_cmap=False,
)
view.save_as_html('brain.html')
```

- Produces self-contained HTML with embedded JavaScript (uses plotly.js internally)
- Mesh data is embedded as base64 in the HTML
- **Cannot export to GLB/GLTF** -- it's a plotly.js scatter3d trace, not a proper 3D scene
- Good for quick visualization, not for embedding in React

### NiiVue -- WebGL2 Brain Viewer

- **Official site**: https://github.com/niivue/niivue
- **React wrapper**: https://github.com/niivue/niivue-react (`<NiivueCanvas />`)
- Supports FreeSurfer surface files natively (can load `.pial`, `.white`, GIFTI, etc.)
- Supports 30+ mesh formats
- **Not on npm** (install from GitHub): `pnpm add niivue/niivue-react`
- Heavy dependency; brings its own WebGL2 renderer (not Three.js/R3F compatible)
- Better suited for full neuroimaging viewers, overkill for a dashboard heatmap

### MNE `Brain` class

- Uses PyVista (VTK) for rendering -- desktop only, no web export
- `brain.save_image()` saves screenshots (PNG), not 3D
- No GLB/GLTF/HTML export capability
- Could potentially use PyVista's export: `pv_mesh.save('brain.stl')` then convert

### npm packages

No significant npm packages bundle fsaverage or provide ready-to-use brain meshes for R3F. The space is mostly served by NiiVue (its own renderer) or custom implementations.

---

## 6. Recommended Implementation Plan

### Step 1: Generate GLB (Python script, run once)

```bash
pip install nibabel trimesh numpy scipy
python scripts/generate_brain_glb.py
# Output: frontend/public/models/brain_fsaverage5.glb
```

The script should:
1. Use nilearn's `fetch_surf_fsaverage('fsaverage5')` to get pre-decimated meshes
2. Combine left + right hemispheres
3. Add sulcal depth as vertex colors (gray shading)
4. Project Muse 2 electrode positions to brain surface
5. Export electrode positions as JSON (for R3F to render as dynamic spheres)
6. Export brain mesh as GLB

### Step 2: React Three Fiber component

```tsx
import { useGLTF } from '@react-three/drei'

function BrainMesh({ channelPowers }) {
  const { scene } = useGLTF('/models/brain_fsaverage5.glb')
  // ... color vertices near electrodes based on channelPowers
  return <primitive object={scene} />
}
```

### Step 3: Dynamic electrode coloring

- Load electrode positions from JSON
- Render as `<Sphere>` components in R3F
- Color based on real-time band power data
- Optionally: paint nearby brain vertices using vertex color updates

### Expected file sizes

| Asset | Size |
|-------|------|
| fsaverage5 GLB (both hemispheres + sulcal colors) | ~1-2 MB |
| Electrode positions JSON | < 1 KB |
| Total | ~2 MB |

---

## Key Files & URLs

| Resource | Location |
|----------|----------|
| MNE fsaverage (local) | `~/mne_data/MNE-fsaverage-data/fsaverage/` |
| MNE fsaverage (download) | `https://osf.io/download/3bxqt?version=2` |
| Nilearn fsaverage5 | `nilearn.datasets.fetch_surf_fsaverage('fsaverage5')` |
| 10-20 electrode coords | `mne/channels/data/montages/standard_1020.elc` |
| FreeSurfer license | BSD-style, redistributable, research-only |
| nibabel FreeSurfer I/O | `nibabel.freesurfer.read_geometry()` |
| trimesh GLB export | `mesh.export('file.glb')` |
