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
  const lastTimestampRef = useRef(0);

  useEffect(() => {
    const interval = setInterval(() => {
      const current = eventsRef.current;
      if (current.length === 0) return;
      const newest = current[current.length - 1];
      if (newest.timestamp !== lastTimestampRef.current) {
        lastTimestampRef.current = newest.timestamp;
        const copy = [...current];
        setEvents(copy);
        setLastEvent(newest);
      }
    }, pollRateMs);
    return () => clearInterval(interval);
  }, [eventsRef, pollRateMs]);

  return { events, lastEvent };
}
