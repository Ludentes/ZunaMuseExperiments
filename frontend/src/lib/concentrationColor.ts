/**
 * Map concentration (0-1) to warm→cool color gradient.
 *
 * 1.0 (focused)  → warm orange #FF6600
 * 0.5 (neutral)  → white #FFFFFF
 * 0.0 (relaxed)  → cool blue #0066FF
 */
export function concentrationToHex(score: number): string {
  let r: number, g: number, b: number;

  if (score >= 0.5) {
    const t = (score - 0.5) * 2;
    r = 255;
    g = Math.round(255 - (255 - 102) * t);
    b = Math.round(255 - 255 * t);
  } else {
    const t = score * 2;
    r = Math.round(255 * t);
    g = Math.round(102 + (255 - 102) * t);
    b = 255;
  }

  return `#${r.toString(16).padStart(2, "0").toUpperCase()}${g.toString(16).padStart(2, "0").toUpperCase()}${b.toString(16).padStart(2, "0").toUpperCase()}`;
}
