import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { BlinkController } from "./BlinkController";

describe("BlinkController", () => {
  let mockNow: ReturnType<typeof vi.spyOn>;
  let currentTime: number;

  beforeEach(() => {
    currentTime = 0;
    mockNow = vi.spyOn(performance, "now").mockImplementation(() => currentTime);
  });

  afterEach(() => {
    mockNow.mockRestore();
  });

  it("returns 0 before any trigger", () => {
    const ctrl = new BlinkController();
    expect(ctrl.getValue()).toBe(0);
  });

  it("returns > 0 immediately after trigger", () => {
    const ctrl = new BlinkController();
    currentTime = 1000;
    ctrl.trigger();
    currentTime = 1001; // 1ms elapsed
    expect(ctrl.getValue()).toBeGreaterThan(0);
  });

  it("returns ~1.0 at halfway point (75ms)", () => {
    const ctrl = new BlinkController();
    currentTime = 1000;
    ctrl.trigger();
    currentTime = 1075; // exactly halfway
    expect(ctrl.getValue()).toBeCloseTo(1.0, 5);
  });

  it("returns 0 after full duration (150ms+)", () => {
    const ctrl = new BlinkController();
    currentTime = 1000;
    ctrl.trigger();
    currentTime = 1151; // past end
    expect(ctrl.getValue()).toBe(0);
  });

  it("re-triggering during active blink resets animation", () => {
    const ctrl = new BlinkController();
    currentTime = 1000;
    ctrl.trigger();
    currentTime = 1100; // mid-animation
    ctrl.trigger(); // re-trigger — resets start time to 1100
    currentTime = 1101; // 1ms into new animation
    expect(ctrl.getValue()).toBeGreaterThan(0);
    expect(ctrl.getValue()).toBeLessThan(0.1); // near start of new animation
  });
});
