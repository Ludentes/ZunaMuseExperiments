import { useRef, useCallback } from "react";
import { useFrame } from "@react-three/fiber";
import { Quaternion } from "three";
import { HeadPoseEstimator } from "../lib/headPose";
import type { ImuSample } from "./useSensorStream";

/**
 * Drives Madgwick sensor fusion from IMU data each animation frame.
 * Must be used inside an R3F <Canvas>.
 *
 * @param imuRef - ref to latest IMU sample from useSensorStream
 * @param smoothing - slerp factor per frame (0 = no smoothing, 1 = frozen). Default 0.7.
 */
export function useHeadPose(
  imuRef: React.RefObject<ImuSample | null>,
  smoothing = 0.7,
) {
  const estimatorRef = useRef(new HeadPoseEstimator());
  const lastTimestampRef = useRef(0);
  const smoothedRef = useRef(new Quaternion());

  useFrame(() => {
    const sample = imuRef.current;
    if (!sample) return;

    // Only process new samples (avoid re-processing same data)
    if (sample.timestamp <= lastTimestampRef.current) return;
    lastTimestampRef.current = sample.timestamp;

    estimatorRef.current.update(sample.accel, sample.gyro);
    const target = estimatorRef.current.getQuaternion();

    // Slerp for smooth motion
    smoothedRef.current.slerp(target, 1 - smoothing);
  });

  const recenter = useCallback(() => {
    estimatorRef.current.recenter();
  }, []);

  const reset = useCallback(() => {
    estimatorRef.current.reset();
    smoothedRef.current.identity();
  }, []);

  return {
    quaternionRef: smoothedRef,
    recenter,
    reset,
  };
}
