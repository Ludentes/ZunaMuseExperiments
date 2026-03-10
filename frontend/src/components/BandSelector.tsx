import type { BandName } from "../hooks/useBandPowers";

const BANDS: { name: BandName; label: string }[] = [
  { name: "focus", label: "FOCUS" },
  { name: "theta", label: "θ" },
  { name: "alpha", label: "α" },
  { name: "beta", label: "β" },
  { name: "gamma", label: "γ" },
  { name: "delta", label: "δ" },
];

interface BandSelectorProps {
  selected: BandName;
  onSelect: (band: BandName) => void;
}

export function BandSelector({ selected, onSelect }: BandSelectorProps) {
  return (
    <div style={{ display: "flex", justifyContent: "center", gap: "4px", padding: "8px 0" }}>
      {BANDS.map(({ name, label }) => (
        <button
          key={name}
          onClick={() => onSelect(name)}
          style={{
            padding: "4px 12px",
            border: selected === name ? "1px solid #00ff88" : "1px solid #444",
            background: selected === name ? "#00ff8820" : "transparent",
            color: selected === name ? "#00ff88" : "#aaa",
            borderRadius: "4px",
            cursor: "pointer",
            fontSize: "14px",
            fontWeight: selected === name ? "bold" : "normal",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
