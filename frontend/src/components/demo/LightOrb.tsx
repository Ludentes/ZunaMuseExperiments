interface Props {
  color: string;
  brightness: number;
  label?: string;
}

export function LightOrb({ color, brightness, label }: Props) {
  const opacity = brightness / 255;
  const glowSpread = 80 + (brightness / 255) * 60;

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="w-24 h-24 rounded-full transition-all duration-500"
        style={{
          background: `radial-gradient(circle at 40% 35%, rgba(255,255,255,0.3), ${color} 50%, transparent 70%)`,
          opacity: Math.max(opacity, 0.05),
          boxShadow: `0 0 ${glowSpread}px ${glowSpread / 2}px ${color}`,
          filter: `brightness(${0.5 + opacity * 0.5})`,
        }}
      />
      <div className="text-center">
        <div className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>
          {color} · {Math.round((brightness / 255) * 100)}%
        </div>
        {label && (
          <div className="text-[9px] font-mono" style={{ color: "var(--text-dim)" }}>
            {label}
          </div>
        )}
      </div>
    </div>
  );
}
