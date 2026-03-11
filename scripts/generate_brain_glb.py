#!/usr/bin/env python3
"""Generate brain.glb + electrodes.json from nilearn's fsaverage5.

Uses fsaverage5 (10k vertices/hemisphere, 40k faces total) — no decimation needed.
Outputs:
  frontend/public/brain.glb   — merged pial surface mesh with sulcal depth colors
  frontend/public/electrodes.json — 10-10 electrode positions projected onto brain
"""

import json
from pathlib import Path

import mne
import nibabel as nib
import numpy as np
import trimesh
from nilearn import datasets
from scipy.spatial import cKDTree

OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public"


def sulc_to_vertex_colors(sulc: np.ndarray) -> np.ndarray:
    """Convert sulcal depth to RGBA vertex colors (dark sulci, light gyri)."""
    smin, smax = np.percentile(sulc, [2, 98])
    normalized = np.clip((sulc - smin) / (smax - smin + 1e-8), 0, 1)
    # Sulci are positive → darker
    brightness = 1.0 - normalized * 0.5  # range 0.5 to 1.0
    colors = np.zeros((len(sulc), 4), dtype=np.uint8)
    colors[:, 0] = (brightness * 200).astype(np.uint8)  # pinkish gray
    colors[:, 1] = (brightness * 180).astype(np.uint8)
    colors[:, 2] = (brightness * 190).astype(np.uint8)
    colors[:, 3] = 255
    return colors


def main():
    print("Fetching fsaverage5 from nilearn...")
    fs = datasets.fetch_surf_fsaverage("fsaverage5")

    # Load both hemispheres (GIFTI format)
    all_verts = []
    all_faces = []
    all_sulc = []
    offset = 0

    for side in ["left", "right"]:
        mesh = nib.load(fs[f"pial_{side}"])
        verts = mesh.darrays[0].data.astype(np.float32)
        faces = mesh.darrays[1].data.astype(np.int32)
        sulc = nib.load(fs[f"sulc_{side}"]).darrays[0].data.astype(np.float32)

        print(f"  {side}: {len(verts)} verts, {len(faces)} faces, sulc [{sulc.min():.2f}, {sulc.max():.2f}]")

        all_verts.append(verts)
        all_faces.append(faces + offset)
        all_sulc.append(sulc)
        offset += len(verts)

    verts = np.concatenate(all_verts, axis=0)
    faces = np.concatenate(all_faces, axis=0)
    sulc = np.concatenate(all_sulc, axis=0)

    print(f"  Merged: {len(verts)} vertices, {len(faces)} faces")

    # Center at origin and normalize scale
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2
    verts -= center
    scale = np.abs(verts).max()
    verts /= scale

    # Apply sulcal depth as vertex colors
    colors = sulc_to_vertex_colors(sulc)

    # Build mesh — fix normals to ensure both hemispheres are lit correctly
    mesh = trimesh.Trimesh(
        vertices=verts,
        faces=faces,
        vertex_colors=colors,
        process=False,
    )
    mesh.fix_normals()

    # Export GLB
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    glb_path = OUT_DIR / "brain.glb"
    mesh.export(str(glb_path), file_type="glb")
    size_kb = glb_path.stat().st_size / 1024
    print(f"Saved {glb_path} ({size_kb:.0f} KB)")

    # --- Electrode positions ---
    print("Computing electrode positions...")
    montage = mne.channels.make_standard_montage("standard_1020")
    ch_pos = montage.get_positions()["ch_pos"]

    tree = cKDTree(verts)
    electrodes = {}

    for name, pos_m in ch_pos.items():
        # MNE returns meters, convert to mm then to our normalized coords
        pos_mm = pos_m * 1000.0
        scaled = (pos_mm - center) / scale
        _, idx = tree.query(scaled)
        brain_pos = verts[idx].tolist()
        electrodes[name] = {
            "scalp": [round(float(x), 5) for x in scaled],
            "brain": [round(float(x), 5) for x in brain_pos],
            "vertex_idx": int(idx),
        }

    elec_path = OUT_DIR / "electrodes.json"
    with open(elec_path, "w") as f:
        json.dump(electrodes, f, indent=2)
    print(f"Saved {elec_path} ({len(electrodes)} electrodes)")

    # Print Muse 2 channels
    for ch in ["TP9", "AF7", "AF8", "TP10"]:
        if ch in electrodes:
            pos = electrodes[ch]["brain"]
            print(f"  {ch}: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")


if __name__ == "__main__":
    main()
