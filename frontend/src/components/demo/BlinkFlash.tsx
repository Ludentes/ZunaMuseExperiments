import { useEffect, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Props {
  lastEvent: BciEvent | null;
}

type FlashLevel = "none" | "single" | "double" | "triple";

export function BlinkFlash({ lastEvent }: Props) {
  const [flash, setFlash] = useState<FlashLevel>("none");
  const [shake, setShake] = useState(false);
  const [eventId, setEventId] = useState(0);

  useEffect(() => {
    if (!lastEvent) return;
    if (!lastEvent.kind.includes("blink")) return;

    const level: FlashLevel =
      lastEvent.kind === "triple_blink" ? "triple"
      : lastEvent.kind === "double_blink" ? "double"
      : "single";

    setFlash(level);
    setEventId((id) => id + 1);

    if (level === "triple") {
      setShake(true);
      setTimeout(() => setShake(false), 150);
    }

    const timer = setTimeout(() => setFlash("none"), 200);
    return () => clearTimeout(timer);
  }, [lastEvent]);

  if (flash === "none") return null;

  const intensity =
    flash === "triple" ? "rgba(255,255,255,0.15)"
    : flash === "double" ? "rgba(255,255,255,0.08)"
    : "rgba(255,255,255,0.03)";

  const spread =
    flash === "triple" ? 80
    : flash === "double" ? 50
    : 30;

  return (
    <div
      key={eventId}
      className="fixed inset-0 pointer-events-none z-50"
      style={{
        boxShadow: `inset 0 0 ${spread}px ${spread / 2}px ${intensity}`,
        animation: "flash-fade 200ms ease-out forwards",
        transform: shake ? "translate(2px, -1px)" : "none",
      }}
    />
  );
}
