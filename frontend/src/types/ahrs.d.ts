declare module "ahrs" {
  interface AHRSOptions {
    sampleInterval?: number;
    algorithm?: "Madgwick" | "Mahony";
    beta?: number;
    kp?: number;
    ki?: number;
  }

  class AHRS {
    constructor(options?: AHRSOptions);
    update(
      gx: number, gy: number, gz: number,
      ax: number, ay: number, az: number,
      mx?: number, my?: number, mz?: number,
    ): void;
    getQuaternion(): { x: number; y: number; z: number; w: number };
    getEulerAngles(): { heading: number; pitch: number; roll: number };
  }

  export default AHRS;
}
