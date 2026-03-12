import { useState, useMemo } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { useBandPowers, type BandName } from "../hooks/useBandPowers";
import { useEvents } from "../hooks/useEvents";
import { BrainHeatmap } from "../components/BrainHeatmap";
import { BandSelector } from "../components/BandSelector";
import { CompactFit } from "../components/demo/CompactFit";
import { LightOrb } from "../components/demo/LightOrb";
import { BlinkFlash } from "../components/demo/BlinkFlash";
import { CommandArrow } from "../components/demo/CommandArrow";
import { EEGStrip } from "../components/demo/EEGStrip";
import { EventLog } from "../components/demo/EventLog";
import { KioskPlayer } from "../components/demo/KioskPlayer";
import { concentrationToHex } from "../lib/concentrationColor";

export const Route = createFileRoute("/demo")({
  component: DemoPage,
});

function DemoPage() {
  const { buffers, metricsRef, eventsRef, isConnected } = useSensorStream();
  const metrics = useMetrics(metricsRef);
  const { getBandPowers } = useBandPowers(metrics);
  const { events, lastEvent } = useEvents(eventsRef);
  const [selectedBand, setSelectedBand] = useState<BandName>("focus");

  // Derive light state from concentration
  const concentration = metrics?.brain?.concentration ?? 0.5;
  const eyesClosed = metrics?.eyes_closed?.active ?? false;
  const lightColor = useMemo(() => concentrationToHex(concentration), [concentration]);
  const lightBrightness = eyesClosed ? 10 : 255;

  return (
    <div
      className="h-screen flex flex-col overflow-hidden"
      style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}
    >
      {/* Scan line overlay */}
      <div
        className="fixed inset-0 pointer-events-none z-30"
        style={{
          background: "repeating-linear-gradient(0deg, transparent, transparent 1px, rgba(0,0,0,0.03) 1px, rgba(0,0,0,0.03) 2px)",
        }}
      />

      {/* Blink flash + command arrow overlays */}
      <BlinkFlash lastEvent={lastEvent} />
      <CommandArrow lastEvent={lastEvent} />

      {/* Top bar */}
      <div
        className="flex items-center justify-between h-10 px-4 shrink-0"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <span
          className="text-sm"
          style={{
            color: "var(--text-dim)",
            fontFamily: "var(--font-label)",
            letterSpacing: "0.3em",
            fontWeight: 200,
          }}
        >
          EUTERPE
        </span>
        <div className="flex items-center gap-4">
          <CompactFit
            signalQuality={metrics?.eeg?.signal_quality}
            headbandState={metrics?.headband}
          />
          <div
            className="flex items-center gap-2 text-[11px] font-mono"
            style={{ color: "var(--text-dim)" }}
          >
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{
                background: isConnected ? "var(--status-good)" : "var(--status-bad)",
                boxShadow: isConnected ? "0 0 6px var(--status-good)" : "none",
              }}
            />
            {isConnected ? "connected" : "disconnected"}
          </div>
        </div>
      </div>

      {/* Main content: two columns */}
      <div
        className="flex-1 grid grid-cols-5 min-h-0"
        style={{ gap: "var(--gap)", padding: "var(--gap)" }}
      >
        {/* Left column: brain (3/5) */}
        <div className="col-span-3 flex flex-col min-h-0">
          <div className="flex-1 min-h-0">
            <BrainHeatmap
              bandPowers={getBandPowers()}
              selectedBand={selectedBand}
              height="100%"
            />
          </div>
          <BandSelector selected={selectedBand} onSelect={setSelectedBand} />
        </div>

        {/* Right column: panels (2/5) */}
        <div
          className="col-span-2 flex flex-col min-h-0"
          style={{ gap: "var(--gap)" }}
        >
          {/* Light orb */}
          <div
            className="p-4 flex items-center justify-center"
            style={{
              background: "var(--bg-panel)",
              border: "1px solid var(--border)",
            }}
          >
            <LightOrb
              color={lightColor}
              brightness={lightBrightness}
              label="Main light"
            />
          </div>

          {/* Focus / Relax bars */}
          <div
            className="p-3"
            style={{
              background: "var(--bg-panel)",
              border: "1px solid var(--border)",
            }}
          >
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span
                  className="text-[11px] w-12"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Focus
                </span>
                <div
                  className="flex-1 h-2"
                  style={{ background: "var(--bg-input)" }}
                >
                  <div
                    className="h-full transition-all duration-300"
                    style={{
                      width: `${concentration * 100}%`,
                      background: "var(--band-beta)",
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span
                  className="text-[13px] font-mono w-10 text-right"
                  style={{ color: "var(--text-primary)" }}
                >
                  {(concentration * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="text-[11px] w-12"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Relax
                </span>
                <div
                  className="flex-1 h-2"
                  style={{ background: "var(--bg-input)" }}
                >
                  <div
                    className="h-full transition-all duration-300"
                    style={{
                      width: `${(metrics?.brain?.relaxation ?? 0) * 100}%`,
                      background: "var(--band-alpha)",
                      opacity: 0.7,
                    }}
                  />
                </div>
                <span
                  className="text-[13px] font-mono w-10 text-right"
                  style={{ color: "var(--text-primary)" }}
                >
                  {((metrics?.brain?.relaxation ?? 0) * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </div>

          {/* Kiosk player */}
          <KioskPlayer lastEvent={lastEvent} />

          {/* Event log */}
          <div className="flex-1 min-h-0 overflow-hidden">
            <EventLog events={events} />
          </div>
        </div>
      </div>

      {/* Bottom EEG strip */}
      <div
        className="shrink-0"
        style={{ borderTop: "1px solid var(--border)" }}
      >
        <EEGStrip buffersRef={buffers} height={40} />
      </div>
    </div>
  );
}
