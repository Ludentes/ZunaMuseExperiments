interface Props {
  headMovement?: number;
  headPose?: { pitch: number; roll: number };
  motionArtifact?: boolean;
  jawClench?: boolean;
}

export function MotionPanel({ headMovement, headPose, motionArtifact, jawClench }: Props) {
  const movementLabel = (headMovement ?? 0) < 0.01 ? "still" : (headMovement ?? 0) < 0.05 ? "light" : "moving";
  const movementColor = movementLabel === "still" ? "var(--status-good)" : movementLabel === "light" ? "var(--status-warn)" : "var(--status-bad)";

  return (
    <div className="p-3" style={{ background: "var(--bg-panel)", border: "1px solid var(--border)" }}>
      <div className="text-[12px] uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)", fontFamily: "var(--font-label)" }}>
        Motion
      </div>
      <div className="flex items-center gap-4 text-sm font-mono">
        <span style={{ color: "var(--text-secondary)" }}>Pitch</span>
        <span style={{ color: "var(--text-primary)" }}>{headPose?.pitch.toFixed(1) ?? "--"}°</span>
        <span style={{ color: "var(--text-secondary)" }}>Roll</span>
        <span style={{ color: "var(--text-primary)" }}>{headPose?.roll.toFixed(1) ?? "--"}°</span>
        <span style={{ color: "var(--text-secondary)" }}>Movement</span>
        <span style={{ color: movementColor }}>{(headMovement ?? 0).toFixed(4)} ({movementLabel})</span>
      </div>
      {/* Artifact bar */}
      <div className="mt-2 h-1 w-full" style={{ background: "var(--bg-input)" }}>
        <div className="h-full transition-all" style={{
          width: motionArtifact ? "100%" : "0%",
          background: "var(--status-warn)",
          opacity: motionArtifact ? 0.8 : 0
        }} />
      </div>
      {jawClench && (
        <div className="mt-1 text-[11px] font-mono animate-pulse" style={{ color: "var(--status-bad)" }}>
          JAW CLENCH
        </div>
      )}
    </div>
  );
}
