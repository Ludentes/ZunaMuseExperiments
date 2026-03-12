import type { ZunaStatus } from "../hooks/useSensorStream";

interface ZunaToggleProps {
  zunaStatus: ZunaStatus;
  sendCommand: (cmd: Record<string, unknown>) => void;
}

export function ZunaToggle({ zunaStatus, sendCommand }: ZunaToggleProps) {
  if (!zunaStatus.available) return null;

  const toggle = () => {
    sendCommand({ cmd: "enable_zuna", enabled: !zunaStatus.enabled });
  };

  return (
    <button
      onClick={toggle}
      style={{
        padding: "4px 12px",
        border: zunaStatus.enabled ? "1px solid #00ff88" : "1px solid #444",
        background: zunaStatus.enabled ? "#00ff8820" : "transparent",
        color: zunaStatus.enabled ? "#00ff88" : "#aaa",
        borderRadius: "4px",
        cursor: "pointer",
        fontSize: "11px",
        fontFamily: "monospace",
        fontWeight: zunaStatus.enabled ? "bold" : "normal",
      }}
    >
      ZUNA {zunaStatus.enabled ? "23ch" : "OFF"}
    </button>
  );
}
