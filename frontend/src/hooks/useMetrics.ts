import { useEffect, useState } from "react";
import type { Metrics } from "../lib/protocol";

/**
 * Polls a metricsRef (set by useSensorStream) at a fixed rate
 * and updates React state. This limits React re-renders to the poll rate.
 */
export function useMetrics(
  metricsRef: React.RefObject<string | null>,
  pollRateMs: number = 250,
) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    const interval = setInterval(() => {
      const raw = metricsRef.current;
      if (raw) {
        try {
          setMetrics(JSON.parse(raw));
        } catch {
          // ignore parse errors
        }
      }
    }, pollRateMs);
    return () => clearInterval(interval);
  }, [metricsRef, pollRateMs]);

  return metrics;
}
