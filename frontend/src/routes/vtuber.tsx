import { useState, useRef, useEffect } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useSensorStream } from "../hooks/useSensorStream";
import { useMetrics } from "../hooks/useMetrics";
import { useEvents } from "../hooks/useEvents";
import { VTuberScene } from "../components/vtuber/VTuberScene";

export const Route = createFileRoute("/vtuber")({
  component: VTuberPage,
});

function VTuberPage() {
  const { metricsRef, eventsRef, imuRef, isConnected } = useSensorStream();
  const metrics = useMetrics(metricsRef);
  const { lastEvent } = useEvents(eventsRef);

  // Track last blink timestamp for the avatar
  const [lastBlinkTs, setLastBlinkTs] = useState(0);
  const [vrmError, setVrmError] = useState<string | null>(null);
  const prevEventRef = useRef<number>(0);
  const recenterRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.timestamp === prevEventRef.current) return;
    prevEventRef.current = lastEvent.timestamp;

    if (lastEvent.kind === "single_blink" || lastEvent.kind === "double_blink") {
      setLastBlinkTs(lastEvent.timestamp);
    }
    if (lastEvent.kind === "triple_blink") {
      recenterRef.current?.();
    }
  }, [lastEvent]);

  const fitStatus = metrics?.eeg?.fit_status ?? "poor";

  return (
    <div className="relative h-screen w-screen bg-zinc-950">
      {/* 3D Canvas */}
      <Canvas
        camera={{ position: [0, 1.4, 1.2], fov: 35 }}
        className="absolute inset-0"
      >
        <ambientLight intensity={0.6} />
        <directionalLight position={[2, 3, 2]} intensity={0.8} />
        <VTuberScene
          imuRef={imuRef}
          lastBlinkTimestamp={lastBlinkTs}
          onRecenterRef={recenterRef}
          onError={setVrmError}
        />
        <OrbitControls
          target={[0, 1.3, 0]}
          enablePan={false}
          minDistance={0.5}
          maxDistance={3}
        />
      </Canvas>

      {/* Overlay: connection + fit + recenter */}
      <div className="absolute top-4 left-4 flex flex-col gap-2 text-sm font-mono">
        <div
          className={`rounded px-2 py-1 ${
            isConnected ? "bg-green-900/80 text-green-300" : "bg-red-900/80 text-red-300"
          }`}
        >
          {isConnected ? "Connected" : "Disconnected"}
        </div>
        {isConnected && (
          <div
            className={`rounded px-2 py-1 ${
              fitStatus === "good"
                ? "bg-green-900/80 text-green-300"
                : fitStatus === "adjust"
                  ? "bg-yellow-900/80 text-yellow-300"
                  : "bg-red-900/80 text-red-300"
            }`}
          >
            Fit: {fitStatus}
          </div>
        )}
        <button
          onClick={() => recenterRef.current?.()}
          className="rounded bg-zinc-800 px-3 py-1 text-zinc-300 hover:bg-zinc-700 transition-colors"
        >
          Recenter
        </button>
      </div>

      {/* Instructions */}
      <div className="absolute bottom-4 left-4 text-xs text-zinc-500 font-mono">
        Move head to control avatar · Blink to trigger expression · Orbit: drag · Zoom: scroll
      </div>

      {vrmError && (
        <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/90">
          <div className="rounded-lg bg-red-950 border border-red-800 p-6 max-w-lg font-mono text-sm">
            <p className="text-red-300 font-bold mb-2">Failed to load VRM model</p>
            <p className="text-zinc-400 mb-3">Download the model file:</p>
            <code className="block bg-zinc-900 text-green-400 p-3 rounded text-xs break-all">
              curl -L -o frontend/public/models/default-avatar.vrm "https://github.com/pixiv/three-vrm/raw/release/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
            </code>
          </div>
        </div>
      )}
    </div>
  );
}
