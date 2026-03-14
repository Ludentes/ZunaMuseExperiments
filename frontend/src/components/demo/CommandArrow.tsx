import { useEffect, useState } from "react";
import type { BciEvent } from "../../lib/protocol";

interface Particle {
  id: number;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  color: string;
}

const TARGETS: Record<string, { x: number; y: number; color: string }> = {
  double_blink: { x: 85, y: 65, color: "var(--status-info)" },
  nod_yes: { x: 85, y: 20, color: "var(--status-good)" },
  nod_no: { x: 85, y: 35, color: "var(--status-bad)" },
};

const ORIGIN = { x: 30, y: 40 };

let particleId = 0;

interface Props {
  lastEvent: BciEvent | null;
}

export function CommandArrow({ lastEvent }: Props) {
  const [particles, setParticles] = useState<Particle[]>([]);

  useEffect(() => {
    if (!lastEvent) return;
    const target = TARGETS[lastEvent.kind];
    if ((lastEvent.confidence ?? 1) < 0.6) return;
    if (!target) return;

    const newParticle: Particle = {
      id: ++particleId,
      startX: ORIGIN.x,
      startY: ORIGIN.y,
      endX: target.x,
      endY: target.y,
      color: target.color,
    };

    setParticles((prev) => [...prev.slice(-4), newParticle]);

    const timer = setTimeout(() => {
      setParticles((prev) => prev.filter((p) => p.id !== newParticle.id));
    }, 600);

    return () => clearTimeout(timer);
  }, [lastEvent]);

  return (
    <div className="fixed inset-0 pointer-events-none z-40">
      {particles.map((p) => (
        <div
          key={p.id}
          className="absolute w-2 h-2 rounded-full"
          style={{
            left: `${p.startX}%`,
            top: `${p.startY}%`,
            background: p.color,
            boxShadow: `0 0 12px 4px ${p.color}`,
            animation: `particle-fly-${p.id} 500ms ease-in-out forwards`,
          }}
        >
          <style>{`
            @keyframes particle-fly-${p.id} {
              0% {
                left: ${p.startX}%;
                top: ${p.startY}%;
                opacity: 1;
                transform: scale(1);
              }
              80% {
                left: ${p.endX}%;
                top: ${p.endY}%;
                opacity: 0.8;
                transform: scale(1.5);
              }
              100% {
                left: ${p.endX}%;
                top: ${p.endY}%;
                opacity: 0;
                transform: scale(0.5);
              }
            }
          `}</style>
        </div>
      ))}
    </div>
  );
}
