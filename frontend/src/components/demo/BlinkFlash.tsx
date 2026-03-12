import { useEffect, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Props {
  lastEvent: BciEvent | null;
}

type FlashLevel = "none" | "single" | "double";

export function BlinkFlash({ lastEvent }: Props) {
  const [flash, setFlash] = useState<FlashLevel>("none");
  const [eventId, setEventId] = useState(0);

  useEffect(() => {
    if (!lastEvent) return;
    if (!lastEvent.kind.includes("blink")) return;

    const level: FlashLevel =
      lastEvent.kind === "double_blink" ? "double" : "single";

    setFlash(level);
    setEventId((id) => id + 1);

    const timer = setTimeout(() => setFlash("none"), 200);
    return () => clearTimeout(timer);
  }, [lastEvent]);

  if (flash === "none") return null;

  const intensity =
    flash === "double" ? "rgba(255,255,255,0.08)"
    : "rgba(255,255,255,0.03)";

  const spread =
    flash === "double" ? 50 : 30;

  return (
    <div
      key={eventId}
      className="fixed inset-0 pointer-events-none z-50"
      style={{
        boxShadow: `inset 0 0 ${spread}px ${spread / 2}px ${intensity}`,
        animation: "flash-fade 200ms ease-out forwards",
        transform: "none",
      }}
    />
  );
}
