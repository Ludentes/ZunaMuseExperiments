const BANDS = [
  { key: "delta", symbol: "δ", color: "var(--band-delta)" },
  { key: "theta", symbol: "θ", color: "var(--band-theta)" },
  { key: "alpha", symbol: "α", color: "var(--band-alpha)" },
  { key: "beta", symbol: "β", color: "var(--band-beta)" },
  { key: "gamma", symbol: "γ", color: "var(--band-gamma)" },
] as const;

interface Props {
  bandPowers?: Record<string, number[]>;
  thetaBetaRatio?: number[];
  faa?: number;
  concentration?: number;
  relaxation?: number;
}

export function BrainMetrics({ bandPowers, thetaBetaRatio, faa, concentration, relaxation }: Props) {
  // Find max power for normalization
  const allPowers = bandPowers
    ? Object.values(bandPowers).flatMap((v) => v)
    : [];
  const maxPower = Math.max(...allPowers, 1);

  // Average theta/beta across channels
  const avgTBR = thetaBetaRatio && thetaBetaRatio.length > 0
    ? thetaBetaRatio.reduce((a, b) => a + b, 0) / thetaBetaRatio.length
    : 0;

  const tbrLabel = avgTBR > 2 ? "relaxed" : avgTBR > 1 ? "neutral" : "focused";
  const faaLabel = (faa ?? 0) > 0.1 ? "approach" : (faa ?? 0) < -0.1 ? "withdraw" : "neutral";

  return (
    <div className="p-3" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
      <div className="text-[12px] uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
        Band Powers
      </div>
      <div className="space-y-1.5">
        {BANDS.map(({ key, symbol, color }) => {
          const values = bandPowers?.[key] ?? [];
          const avg = values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : 0;
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="text-sm font-mono w-4" style={{ color }}>{symbol}</span>
              <span className="text-[11px] w-10" style={{ color: "var(--text-secondary)" }}>{key}</span>
              <div className="flex-1 h-1.5" style={{ background: "var(--bg-input)" }}>
                <div className="h-full transition-all" style={{ width: `${(avg / maxPower) * 100}%`, background: color, opacity: 0.6 }} />
              </div>
              <span className="text-[13px] font-mono w-10 text-right" style={{ color: "var(--text-primary)" }}>
                {avg.toFixed(1)}
              </span>
            </div>
          );
        })}
      </div>

      <div className="text-[12px] uppercase tracking-wider mt-4 mb-2" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
        Ratios
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>θ/β</span>
          <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>{avgTBR.toFixed(2)}</span>
          <span className="text-[9px] uppercase px-1.5 py-0.5 border" style={{ color: tbrLabel === "focused" ? "var(--status-good)" : tbrLabel === "relaxed" ? "var(--ch-tp9)" : "var(--text-dim)", borderColor: "currentColor" }}>
            {tbrLabel}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono" style={{ color: "var(--text-secondary)" }}>FAA</span>
          <span className="text-sm font-mono" style={{ color: "var(--text-primary)" }}>{(faa ?? 0).toFixed(3)}</span>
          <span className="text-[9px] uppercase px-1.5 py-0.5 border" style={{ color: "var(--text-dim)", borderColor: "currentColor" }}>
            {faaLabel}
          </span>
        </div>
      </div>

      {/* Concentration / Relaxation */}
      {(concentration != null || relaxation != null) && (
        <>
          <div className="text-[12px] uppercase tracking-wider mt-4 mb-2" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
            BCI State
          </div>
          <div className="space-y-1.5">
            {concentration != null && (
              <div className="flex items-center gap-2">
                <span className="text-[11px] w-16" style={{ color: "var(--text-secondary)" }}>Focus</span>
                <div className="flex-1 h-2" style={{ background: "var(--bg-input)" }}>
                  <div className="h-full transition-all" style={{
                    width: `${concentration * 100}%`,
                    background: "var(--band-beta)",
                    opacity: 0.7,
                  }} />
                </div>
                <span className="text-[13px] font-mono w-10 text-right" style={{ color: "var(--text-primary)" }}>
                  {(concentration * 100).toFixed(0)}%
                </span>
              </div>
            )}
            {relaxation != null && (
              <div className="flex items-center gap-2">
                <span className="text-[11px] w-16" style={{ color: "var(--text-secondary)" }}>Relax</span>
                <div className="flex-1 h-2" style={{ background: "var(--bg-input)" }}>
                  <div className="h-full transition-all" style={{
                    width: `${relaxation * 100}%`,
                    background: "var(--band-alpha)",
                    opacity: 0.7,
                  }} />
                </div>
                <span className="text-[13px] font-mono w-10 text-right" style={{ color: "var(--text-primary)" }}>
                  {(relaxation * 100).toFixed(0)}%
                </span>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
