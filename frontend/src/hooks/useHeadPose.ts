import { useRef, useCallback } from "react";
import { useFrame } from "@react-three/fiber";
import { Quaternion } from "three";
import { HeadPoseEstimator } from "../lib/headPose";
import { OneEuroQuaternionFilter } from "../lib/oneEuroFilter";
import type { ImuSample } from "./useSensorStream";

/**
 * Drives Madgwick sensor fusion from IMU data each animation frame.
 * Must be used inside an R3F <Canvas>.
 *
 * Uses One Euro Filter for adaptive smoothing:
 * - Still/slow → heavy smoothing (no jitter)
 * - Fast motion → minimal smoothing (no latency)
 */
export function useHeadPose(
  imuRef: React.RefObject<ImuSample | null>,
) {
  const estimatorRef = useRef(new HeadPoseEstimator(0.8));
  const lastTimestampRef = useRef(0);
  const smoothedRef = useRef(new Quaternion());
  const settleRef = useRef(0);
  // minCutoff: lower = more smoothing at rest. beta: higher = faster response to motion.
  const filterRef = useRef(new OneEuroQuaternionFilter(0.3, 1.5, 1.0));

  useFrame(() => {
    const sample = imuRef.current;
    if (!sample) return;

    // Only process new samples (avoid re-processing same data)
    if (sample.timestamp <= lastTimestampRef.current) return;
    lastTimestampRef.current = sample.timestamp;

    estimatorRef.current.update(sample.accel, sample.gyro);
    const target = estimatorRef.current.getQuaternion();

    // Adaptive smoothing via One Euro Filter
    const filtered = filterRef.current.filter(target, sample.timestamp);
    smoothedRef.current.copy(filtered);

    // Update settle progress
    settleRef.current = estimatorRef.current.settleProgress;
  });

  const recenter = useCallback(() => {
    estimatorRef.current.recenter();
    filterRef.current.reset();
  }, []);

  const reset = useCallback(() => {
    estimatorRef.current.reset();
    filterRef.current.reset();
    smoothedRef.current.identity();
    settleRef.current = 0;
  }, []);

  return {
    quaternionRef: smoothedRef,
    settleRef,
    recenter,
    reset,
  };
}
