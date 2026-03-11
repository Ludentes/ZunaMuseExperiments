#!/usr/bin/env python3
"""Generate brain.glb + electrodes.json from fsaverage pial surface.

Uses nilearn's fsaverage5 (10k vertices/hemisphere, ~40k total triangles).
Outputs:
  frontend/public/brain.glb   — merged pial surface mesh
  frontend/public/electrodes.json — electrode positions projected onto brain
"""

import json
from pathlib import Path

import mne
import nibabel as nib
import numpy as np
import trimesh

# --- Paths ---
FSAVERAGE_DIR = Path.home() / "mne_data" / "MNE-fsaverage-data" / "fsaverage"
OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public"

# Use fsaverage (full resolution pial), then decimate
SURF_LH = FSAVERAGE_DIR / "surf" / "lh.pial"
SURF_RH = FSAVERAGE_DIR / "surf" / "rh.pial"
SULC_LH = FSAVERAGE_DIR / "surf" / "lh.sulc"
SULC_RH = FSAVERAGE_DIR / "surf" / "rh.sulc"


def load_freesurfer_surface(surf_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load FreeSurfer surface file, return (vertices, faces)."""
    coords, faces = nib.freesurfer.read_geometry(str(surf_path))
    return coords.astype(np.float32), faces.astype(np.int32)


def load_sulcal_depth(sulc_path: Path) -> np.ndarray:
    """Load sulcal depth overlay."""
    return nib.freesurfer.read_morph_data(str(sulc_path)).astype(np.float32)


def merge_hemispheres(
    lh_verts: np.ndarray, lh_faces: np.ndarray,
    rh_verts: np.ndarray, rh_faces: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Merge left and right hemisphere meshes."""
    offset = len(lh_verts)
    verts = np.concatenate([lh_verts, rh_verts], axis=0)
    faces = np.concatenate([lh_faces, rh_faces + offset], axis=0)
    return verts, faces


def sulc_to_vertex_colors(sulc: np.ndarray) -> np.ndarray:
    """Convert sulcal depth to RGBA vertex colors (dark sulci, light gyri)."""
    # Normalize to 0-1 range
    smin, smax = np.percentile(sulc, [2, 98])
    normalized = np.clip((sulc - smin) / (smax - smin + 1e-8), 0, 1)
    # Sulci are positive → darker. Invert so gyri are brighter.
    brightness = 1.0 - normalized * 0.5  # range 0.5 to 1.0
    colors = np.zeros((len(sulc), 4), dtype=np.uint8)
    colors[:, 0] = (brightness * 200).astype(np.uint8)  # R — pinkish gray
    colors[:, 1] = (brightness * 180).astype(np.uint8)  # G
    colors[:, 2] = (brightness * 190).astype(np.uint8)  # B
    colors[:, 3] = 255
    return colors


def get_electrode_positions_mni() -> dict[str, list[float]]:
    """Get 10-10 electrode positions from MNE's standard montage (MNI mm)."""
    montage = mne.channels.make_standard_montage("standard_1020")
    positions = {}
    for name, pos in zip(montage.ch_names, montage.get_positions()["ch_pos"].values()):
        # MNE returns positions in meters, convert to mm
        positions[name] = (pos * 1000).tolist()
    return positions


def project_electrodes_to_brain(
    electrode_positions: dict[str, list[float]],
    vertices: np.ndarray,
) -> dict[str, dict]:
    """Project electrode scalp positions to nearest brain vertex."""
    from scipy.spatial import cKDTree
    tree = cKDTree(vertices)

    result = {}
    for name, pos in electrode_positions.items():
        dist, idx = tree.query(pos)
        brain_pos = vertices[idx].tolist()
        result[name] = {
            "scalp": pos,
            "brain": brain_pos,
            "vertex_idx": int(idx),
        }
    return result


def main():
    print("Loading FreeSurfer surfaces...")
    lh_v, lh_f = load_freesurfer_surface(SURF_LH)
    rh_v, rh_f = load_freesurfer_surface(SURF_RH)

    print(f"  LH: {len(lh_v)} vertices, {len(lh_f)} faces")
    print(f"  RH: {len(rh_v)} vertices, {len(rh_f)} faces")

    # Merge hemispheres
    verts, faces = merge_hemispheres(lh_v, lh_f, rh_v, rh_f)
    print(f"  Merged: {len(verts)} vertices, {len(faces)} faces")

    # Load sulcal depth for vertex coloring
    print("Loading sulcal depth...")
    lh_sulc = load_sulcal_depth(SULC_LH)
    rh_sulc = load_sulcal_depth(SULC_RH)
    sulc = np.concatenate([lh_sulc, rh_sulc])

    # Decimate if too heavy
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    target_faces = 80_000
    if len(faces) > target_faces:
        ratio = 1.0 - target_faces / len(faces)
        print(f"Decimating from {len(faces)} to ~{target_faces} faces (ratio={ratio:.3f})...")
        mesh = mesh.simplify_quadric_decimation(ratio)
        print(f"  After decimation: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
        # Reinterpolate sulcal depth to decimated mesh
        from scipy.spatial import cKDTree
        tree = cKDTree(verts)
        _, indices = tree.query(mesh.vertices)
        sulc = sulc[indices]
        verts = mesh.vertices.astype(np.float32)
        faces = mesh.faces.astype(np.int32)

    # Center at origin and normalize scale
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2
    verts -= center
    scale = np.abs(verts).max()
    verts /= scale  # normalize to roughly unit size

    # Apply vertex colors
    colors = sulc_to_vertex_colors(sulc)

    # Build final mesh
    mesh = trimesh.Trimesh(
        vertices=verts,
        faces=faces,
        vertex_colors=colors,
        process=False,
    )

    # Export GLB
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    glb_path = OUT_DIR / "brain.glb"
    mesh.export(str(glb_path), file_type="glb")
    size_kb = glb_path.stat().st_size / 1024
    print(f"Saved {glb_path} ({size_kb:.0f} KB)")

    # Get electrode positions and project onto brain
    print("Computing electrode positions...")
    scalp_positions = get_electrode_positions_mni()

    # Scale electrode positions to match our normalized mesh
    scaled_positions = {}
    for name, pos in scalp_positions.items():
        scaled = [(p - c) / scale for p, c in zip(pos, center)]
        scaled_positions[name] = scaled

    electrodes = project_electrodes_to_brain(scaled_positions, verts)

    # Convert numpy types to native Python for JSON
    def to_native(obj):
        if isinstance(obj, (np.floating,)):
            return round(float(obj), 5)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, dict):
            return {k: to_native(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [to_native(v) for v in obj]
        return obj

    # Save electrode data
    elec_path = OUT_DIR / "electrodes.json"
    with open(elec_path, "w") as f:
        json.dump(to_native(electrodes), f, indent=2)
    print(f"Saved {elec_path} ({len(electrodes)} electrodes)")

    # Print Muse 2 channels
    for ch in ["TP9", "AF7", "AF8", "TP10"]:
        if ch in electrodes:
            pos = electrodes[ch]["brain"]
            print(f"  {ch}: [{pos[0]:.3f}, {pos[1]:.3f}, {pos[2]:.3f}]")


if __name__ == "__main__":
    main()
