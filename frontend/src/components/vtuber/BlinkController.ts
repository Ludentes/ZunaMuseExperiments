/**
 * Timestamp-based blink animation.
 * On trigger: ramp 0→1 over HALF_DURATION, then 1→0 over HALF_DURATION.
 */
export class BlinkController {
  private static HALF_DURATION = 75; // ms

  private blinkStart: number | null = null;

  /** Trigger a blink animation. */
  trigger(): void {
    this.blinkStart = performance.now();
  }

  /**
   * Get current blink expression value (0-1).
   * Call every frame.
   */
  getValue(): number {
    if (this.blinkStart === null) return 0;

    const elapsed = performance.now() - this.blinkStart;
    const full = BlinkController.HALF_DURATION * 2;

    if (elapsed >= full) {
      this.blinkStart = null;
      return 0;
    }

    if (elapsed < BlinkController.HALF_DURATION) {
      // Closing: 0 → 1
      return elapsed / BlinkController.HALF_DURATION;
    }
    // Opening: 1 → 0
    return 1 - (elapsed - BlinkController.HALF_DURATION) / BlinkController.HALF_DURATION;
  }
}
