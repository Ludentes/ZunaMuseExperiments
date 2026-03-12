import { useEffect, useRef, useState } from "react";
import type { BciEvent } from "../lib/protocol";

/**
 * Polls an eventsRef and provides:
 * - events: full event log (last 50)
 * - lastEvent: most recent event (for triggering animations)
 */
export function useEvents(
  eventsRef: React.RefObject<BciEvent[]>,
  pollRateMs: number = 100,
) {
  const [events, setEvents] = useState<BciEvent[]>([]);
  const [lastEvent, setLastEvent] = useState<BciEvent | null>(null);
  const prevLenRef = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const current = eventsRef.current;
      if (current.length !== prevLenRef.current) {
        prevLenRef.current = current.length;
        setEvents([...current]);
        setLastEvent(current[current.length - 1] ?? null);
      }
    }, pollRateMs);
    return () => clearInterval(interval);
  }, [eventsRef, pollRateMs]);

  return { events, lastEvent };
}
