import { useFrame } from "@react-three/fiber";
import type { ImuSample } from "../../hooks/useSensorStream";
import { useHeadPose } from "../../hooks/useHeadPose";
import { VTuberAvatar, type AngleBias } from "./VTuberAvatar";

interface VTuberSceneProps {
  imuRef: React.RefObject<ImuSample | null>;
  biasRef: React.RefObject<AngleBias>;
  lastBlinkTimestamp: number;
  onRecenterRef: React.MutableRefObject<(() => void) | null>;
  onSettleRef: React.MutableRefObject<number>;
  onError?: (msg: string) => void;
}

/**
 * Bridge component inside R3F Canvas.
 * Connects useHeadPose (needs R3F context) to VTuberAvatar.
 */
export function VTuberScene({ imuRef, biasRef, lastBlinkTimestamp, onRecenterRef, onSettleRef, onError }: VTuberSceneProps) {
  const { quaternionRef, settleRef, recenter } = useHeadPose(imuRef);

  // Expose recenter to parent (outside Canvas)
  onRecenterRef.current = recenter;

  // Bridge settle progress to parent ref each frame
  useFrame(() => {
    onSettleRef.current = settleRef.current;
  });

  return (
    <VTuberAvatar
      quaternionRef={quaternionRef}
      biasRef={biasRef}
      lastBlinkTimestamp={lastBlinkTimestamp}
      onError={onError}
    />
  );
}
