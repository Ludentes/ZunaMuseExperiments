import { useRef, useCallback } from "react";
import type { Metrics, BandPowers } from "~/lib/protocol";

export type BandName = "delta" | "theta" | "alpha" | "beta" | "gamma" | "focus";

export function useBandPowers(metrics: Metrics | null) {
  const prevRef = useRef<BandPowers | null>(null);

  const getBandPowers = useCallback((): BandPowers | null => {
    if (!metrics?.band_powers) return prevRef.current;
    prevRef.current = metrics.band_powers;
    return metrics.band_powers;
  }, [metrics]);

  return { getBandPowers };
}

export function extractBandValues(
  bp: BandPowers,
  band: BandName,
): Record<string, number> {
  const result: Record<string, number> = {};
  for (const [ch, bands] of Object.entries(bp.channels)) {
    if (band === "focus") {
      const theta = bands.theta ?? 0;
      const beta = bands.beta ?? 1;
      result[ch] = beta > 0 ? theta / beta : 0;
    } else {
      result[ch] = bands[band] ?? 0;
    }
  }
  return result;
}
