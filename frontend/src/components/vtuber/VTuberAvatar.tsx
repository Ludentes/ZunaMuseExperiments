import { useEffect, useRef, useState } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, type VRM } from "@pixiv/three-vrm";
import { Quaternion } from "three";
import { BlinkController } from "./BlinkController";

interface VTuberAvatarProps {
  /** Ref to smoothed quaternion from useHeadPose */
  quaternionRef: React.RefObject<Quaternion>;
  /** Latest bci_event kind — triggers blink on "single_blink" */
  lastBlinkTimestamp: number;
  onError?: (msg: string) => void;
}

// Split rotation between neck (60%) and head (40%) for natural look
const NECK_WEIGHT = 0.6;
const HEAD_WEIGHT = 0.4;

export function VTuberAvatar({
  quaternionRef,
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
        loadedVrm.scene.rotation.y = Math.PI; // Face the camera
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

    // --- Head rotation ---
    const q = quaternionRef.current;
    if (q) {
      const neckBone = vrm.humanoid?.getRawBoneNode("neck");
      const headBone = vrm.humanoid?.getRawBoneNode("head");

      if (neckBone && headBone) {
        // Split quaternion between neck and head
        const identity = new Quaternion();
        const neckQ = identity.clone().slerp(q, NECK_WEIGHT);
        const headQ = identity.clone().slerp(q, HEAD_WEIGHT);
        neckBone.quaternion.copy(neckQ);
        headBone.quaternion.copy(headQ);
      } else if (headBone) {
        // Fallback: all rotation to head
        headBone.quaternion.copy(q);
      }
    }

    // --- Blink ---
    if (lastBlinkTimestamp > prevBlinkTs.current) {
      prevBlinkTs.current = lastBlinkTimestamp;
      blinkRef.current.trigger();
    }

    const blinkValue = blinkRef.current.getValue();
    vrm.expressionManager?.setValue("blink", blinkValue);

    // --- Update VRM systems (expressions, spring bones, etc.) ---
    vrm.update(delta);
  });

  if (error) {
    return null; // Route will show error overlay
  }

  // VRM scene is added directly to the R3F scene via useEffect — no JSX mesh needed
  return null;
}
