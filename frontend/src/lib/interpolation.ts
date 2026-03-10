// frontend/src/lib/interpolation.ts
import type { ElectrodePosition } from "./electrodes";
import { sphericalToCartesian } from "./electrodes";

/**
 * Compute inverse-distance weighting matrix from electrodes to mesh vertices.
 * Uses spherical geodesic distance with power=2 (IDW).
 *
 * Returns Float32Array of shape [numVertices * numElectrodes] (row-major).
 * Each row sums to 1.0.
 */
export function computeInterpolationWeights(
  vertices: Float32Array,       // flat xyz, length = numVerts * 3
  electrodes: ElectrodePosition[],
  power: number = 2,
  smoothing: number = 0.01,     // prevents singularity at electrode positions
): Float32Array {
  const numVerts = vertices.length / 3;
  const numElec = electrodes.length;
  const weights = new Float32Array(numVerts * numElec);

  // Electrode positions in Cartesian
  const elecXYZ = electrodes.map((e) => sphericalToCartesian(e.theta, e.phi));

  for (let v = 0; v < numVerts; v++) {
    const vx = vertices[v * 3];
    const vy = vertices[v * 3 + 1];
    const vz = vertices[v * 3 + 2];

    // Normalize vertex to unit sphere for distance computation
    const vLen = Math.sqrt(vx * vx + vy * vy + vz * vz);
    const nvx = vx / vLen;
    const nvy = vy / vLen;
    const nvz = vz / vLen;

    let weightSum = 0;
    for (let e = 0; e < numElec; e++) {
      const [ex, ey, ez] = elecXYZ[e];
      const dx = nvx - ex;
      const dy = nvy - ey;
      const dz = nvz - ez;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) + smoothing;
      const w = 1 / Math.pow(dist, power);
      weights[v * numElec + e] = w;
      weightSum += w;
    }
    // Normalize row to sum to 1
    for (let e = 0; e < numElec; e++) {
      weights[v * numElec + e] /= weightSum;
    }
  }

  return weights;
}

/**
 * Interpolate electrode values to vertex values using precomputed weights.
 * electrodeValues: one value per electrode (e.g., alpha power)
 * Returns one value per vertex.
 */
export function interpolateToVertices(
  weights: Float32Array,
  electrodeValues: number[],
  numVertices: number,
): Float32Array {
  const numElec = electrodeValues.length;
  const result = new Float32Array(numVertices);

  for (let v = 0; v < numVertices; v++) {
    let val = 0;
    for (let e = 0; e < numElec; e++) {
      val += weights[v * numElec + e] * electrodeValues[e];
    }
    result[v] = val;
  }

  return result;
}
