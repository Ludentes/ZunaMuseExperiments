import { Quaternion } from "three";

/**
 * One Euro Filter for quaternions.
 *
 * Adapts smoothing based on motion speed:
 * - Slow/still → heavy smoothing (eliminates jitter)
 * - Fast motion → light smoothing (preserves responsiveness)
 *
 * Reference: Géry Casiez et al., "1€ Filter: A Simple Speed-based Low-pass Filter
 * for Noisy Input in Interactive Systems", CHI 2012.
 *
 * @param minCutoff - minimum cutoff frequency in Hz (lower = more smoothing at rest). Default 1.0.
 * @param beta - speed coefficient (higher = less smoothing during fast motion). Default 0.5.
 * @param dCutoff - cutoff for derivative estimation. Default 1.0.
 */
export class OneEuroQuaternionFilter {
  private readonly minCutoff: number;
  private readonly beta: number;
  private readonly dCutoff: number;

  private prevFiltered: Quaternion | null = null;
  private prevRaw: Quaternion | null = null;
  private prevTimestamp = 0;

  constructor(minCutoff = 1.0, beta = 0.5, dCutoff = 1.0) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
  }

  private smoothingFactor(rate: number, cutoff: number): number {
    const tau = 1.0 / (2 * Math.PI * cutoff);
    const te = 1.0 / rate;
    return 1.0 / (1.0 + tau / te);
  }

  filter(q: Quaternion, timestamp: number): Quaternion {
    if (!this.prevFiltered || !this.prevRaw) {
      this.prevFiltered = q.clone();
      this.prevRaw = q.clone();
      this.prevTimestamp = timestamp;
      return q.clone();
    }

    const dt = (timestamp - this.prevTimestamp) / 1000; // ms → seconds
    if (dt <= 0) return this.prevFiltered.clone();
    this.prevTimestamp = timestamp;

    const rate = 1.0 / dt;

    // Estimate speed as angular distance between consecutive raw samples
    // Ensure shortest path (dot > 0)
    const rawAligned = q.clone();
    if (rawAligned.dot(this.prevRaw) < 0) {
      rawAligned.set(-rawAligned.x, -rawAligned.y, -rawAligned.z, -rawAligned.w);
    }
    const angle = 2 * Math.acos(Math.min(1, Math.abs(rawAligned.dot(this.prevRaw))));
    const speed = angle / dt; // rad/s

    this.prevRaw.copy(rawAligned);

    // Smooth the speed estimate
    const dAlpha = this.smoothingFactor(rate, this.dCutoff);
    const smoothedSpeed = dAlpha * speed; // simplified: single-pole on speed

    // Dead zone: treat small angular velocities as zero (sensor noise at rest)
    // 0.15 rad/s ≈ 8.6°/s — below this, we assume the head is still
    const effectiveSpeed = smoothedSpeed < 0.15 ? 0 : smoothedSpeed;

    // Adapt cutoff based on speed
    const cutoff = this.minCutoff + this.beta * effectiveSpeed;
    const alpha = this.smoothingFactor(rate, cutoff);

    // Slerp toward new value with adaptive alpha
    this.prevFiltered.slerp(rawAligned, alpha);

    return this.prevFiltered.clone();
  }

  reset(): void {
    this.prevFiltered = null;
    this.prevRaw = null;
    this.prevTimestamp = 0;
  }
}
