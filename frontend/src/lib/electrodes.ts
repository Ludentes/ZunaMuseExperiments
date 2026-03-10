// frontend/src/lib/electrodes.ts

/** Electrode position in spherical coordinates (theta, phi) on unit sphere.
 *  theta: polar angle from top (0 = Cz/vertex, pi/2 = equator)
 *  phi: azimuthal angle (0 = nose, pi/2 = left ear, -pi/2 = right ear)
 */
export interface ElectrodePosition {
  name: string;
  theta: number;  // radians from top
  phi: number;    // radians from nose (CCW from above)
}

// Standard 10-20 positions as (theta, phi) on unit sphere
// Based on standard spherical head model
// theta: 0 = top (Cz), increases toward equator
// phi: 0 = nasion (front), pi/2 = left, -pi/2 = right, pi = inion (back)
export const ELECTRODES_23CH: ElectrodePosition[] = [
  // Frontal pole
  { name: "Fp1", theta: 0.51, phi: 0.31 },
  { name: "Fp2", theta: 0.51, phi: -0.31 },
  // Frontal
  { name: "F7",  theta: 0.67, phi: 0.79 },
  { name: "F3",  theta: 0.47, phi: 0.39 },
  { name: "Fz",  theta: 0.35, phi: 0.0 },
  { name: "F4",  theta: 0.47, phi: -0.39 },
  { name: "F8",  theta: 0.67, phi: -0.79 },
  // Anterior frontal (Muse positions)
  { name: "AF7", theta: 0.58, phi: 0.59 },
  { name: "AF8", theta: 0.58, phi: -0.59 },
  // Temporal
  { name: "T7",  theta: 0.79, phi: 1.18 },
  { name: "T8",  theta: 0.79, phi: -1.18 },
  // Temporal-parietal (Muse positions)
  { name: "TP9", theta: 0.87, phi: 1.38 },
  { name: "TP10",theta: 0.87, phi: -1.38 },
  // Central
  { name: "C3",  theta: 0.47, phi: 0.79 },
  { name: "Cz",  theta: 0.0,  phi: 0.0 },
  { name: "C4",  theta: 0.47, phi: -0.79 },
  // Parietal
  { name: "P7",  theta: 0.67, phi: 1.57 },
  { name: "P3",  theta: 0.47, phi: 1.18 },
  { name: "Pz",  theta: 0.35, phi: Math.PI },
  { name: "P4",  theta: 0.47, phi: -1.18 },
  { name: "P8",  theta: 0.67, phi: -1.57 },
  // Occipital
  { name: "O1",  theta: 0.51, phi: 2.83 },
  { name: "O2",  theta: 0.51, phi: -2.83 },
];

export const ELECTRODES_4CH: ElectrodePosition[] =
  ELECTRODES_23CH.filter((e) =>
    ["TP9", "AF7", "AF8", "TP10"].includes(e.name)
  );

/** Convert spherical (theta, phi) to Cartesian on unit sphere */
export function sphericalToCartesian(
  theta: number,
  phi: number,
): [number, number, number] {
  const x = Math.sin(theta) * Math.sin(phi);
  const y = Math.cos(theta);
  const z = Math.sin(theta) * Math.cos(phi);
  return [x, y, z];
}
