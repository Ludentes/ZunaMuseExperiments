import type { ImuSample } from "../../hooks/useSensorStream";
import { useHeadPose } from "../../hooks/useHeadPose";
import { VTuberAvatar } from "./VTuberAvatar";

interface VTuberSceneProps {
  imuRef: React.RefObject<ImuSample | null>;
  lastBlinkTimestamp: number;
  onRecenterRef: React.MutableRefObject<(() => void) | null>;
  onError?: (msg: string) => void;
}

/**
 * Bridge component inside R3F Canvas.
 * Connects useHeadPose (needs R3F context) to VTuberAvatar.
 */
export function VTuberScene({ imuRef, lastBlinkTimestamp, onRecenterRef, onError }: VTuberSceneProps) {
  const { quaternionRef, recenter } = useHeadPose(imuRef);

  // Expose recenter to parent (outside Canvas)
  onRecenterRef.current = recenter;

  return (
    <VTuberAvatar
      quaternionRef={quaternionRef}
      lastBlinkTimestamp={lastBlinkTimestamp}
      onError={onError}
    />
  );
}
