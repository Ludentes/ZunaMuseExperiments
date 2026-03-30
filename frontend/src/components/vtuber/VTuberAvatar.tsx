import { useEffect, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, type VRM } from "@pixiv/three-vrm";
import { Euler, Quaternion } from "three";
import { BlinkController } from "./BlinkController";

export interface AngleBias {
  pitch: number; // degrees
  yaw: number;
  roll: number;
}

interface VTuberAvatarProps {
  /** Ref to smoothed quaternion from useHeadPose */
  quaternionRef: React.RefObject<Quaternion>;
  /** Ref to constant angle bias (degrees) */
  biasRef: React.RefObject<AngleBias>;
  /** Latest bci_event kind — triggers blink on "single_blink" */
  lastBlinkTimestamp: number;
  onError?: (msg: string) => void;
}

// Split rotation between neck (60%) and head (40%) for natural look
const NECK_WEIGHT = 0.6;
const HEAD_WEIGHT = 0.4;


const DEG2RAD = Math.PI / 180;

export function VTuberAvatar({
  quaternionRef,
  biasRef,
  lastBlinkTimestamp,
  onError,
}: VTuberAvatarProps) {
  const { scene } = useThree();
  const [vrm, setVrm] = useState<VRM | null>(null);
  const [error, setError] = useState<string | null>(null);
  const blinkRef = useRef(new BlinkController());
  const prevBlinkTs = useRef(0);

  // Load VRM model
  useEffect(() => {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));

    loader.load(
      "/models/default-avatar.vrm",
      (gltf) => {
        const loadedVrm = gltf.userData.vrm as VRM;
        // VRM models face +Z by default, which is toward camera in Three.js — no rotation needed
        setVrm(loadedVrm);
      },
      undefined,
      (err) => {
        console.error("VRM load failed:", err);
        setError("Failed to load VRM model");
        onError?.("Failed to load VRM model. Run: curl -L -o frontend/public/models/default-avatar.vrm \"https://github.com/pixiv/three-vrm/raw/release/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm\"");
      },
    );
  }, []);

  // Add/remove VRM scene
  useEffect(() => {
    if (!vrm) return;
    scene.add(vrm.scene);
    return () => {
      scene.remove(vrm.scene);
    };
  }, [vrm, scene]);

  // Per-frame update
  useFrame((_, delta) => {
    if (!vrm) return;

    // --- Blink (set before update so expressionManager.update() applies it) ---
    if (lastBlinkTimestamp > prevBlinkTs.current) {
      prevBlinkTs.current = lastBlinkTimestamp;
      blinkRef.current.trigger();
    }

    const blinkValue = blinkRef.current.getValue();
    vrm.expressionManager?.setValue("blink", blinkValue);

    // --- Update VRM systems (expressions, spring bones, etc.) ---
    // Must run BEFORE bone rotation — humanoid.update() inside resets raw bones
    vrm.update(delta);

    // --- Head rotation ---
    // After vrm.update(), bones are in their rest pose. Read rest, then compose IMU on top.
    const neckBone = vrm.humanoid?.getRawBoneNode("neck");
    const headBone = vrm.humanoid?.getRawBoneNode("head");

    const q = quaternionRef.current;
    if (q) {
      // Compose IMU quaternion with constant bias offset
      const bias = biasRef.current;
      const biasQ = new Quaternion().setFromEuler(
        new Euler(bias.pitch * DEG2RAD, bias.yaw * DEG2RAD, bias.roll * DEG2RAD, "YXZ"),
      );
      const combined = biasQ.multiply(q);

      if (neckBone && headBone) {
        const identity = new Quaternion();
        const neckQ = identity.clone().slerp(combined, NECK_WEIGHT);
        const headQ = identity.clone().slerp(combined, HEAD_WEIGHT);
        neckBone.quaternion.multiply(neckQ);
        headBone.quaternion.multiply(headQ);
      } else if (headBone) {
        headBone.quaternion.multiply(combined);
      }
    }
  });

  if (error) {
    return null; // Route will show error overlay
  }

  // VRM scene is added directly to the R3F scene via useEffect — no JSX mesh needed
  return null;
}
