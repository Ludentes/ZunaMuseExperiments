import AHRS from "ahrs";
import { Quaternion } from "three";

const DEG2RAD = Math.PI / 180;

/**
 * Madgwick-based head pose estimator for Muse 2 IMU.
 *
 * Consumes raw accel (g's) + gyro (deg/s) at 52Hz,
 * outputs a quaternion relative to the "home" orientation.
 */
export class HeadPoseEstimator {
  private ahrs: InstanceType<typeof AHRS>;
  private homeInverse: Quaternion | null = null;
  private initialized = false;
  private frameCount = 0;
  private readonly beta: number;

  // How many frames to accumulate before setting home pose (lets filter settle)
  private static SETTLE_FRAMES = 26; // ~0.5s at 52Hz

  constructor(beta = 0.4) {
    this.beta = beta;
    this.ahrs = new AHRS({
      sampleInterval: 52, // Hz
      algorithm: "Madgwick",
      beta,
    });
  }

  /**
   * Feed one IMU sample. Call at sensor rate (~52Hz).
   * @param accel [ax, ay, az] in g's
   * @param gyro  [gx, gy, gz] in deg/s
   */
  update(accel: Float32Array, gyro: Float32Array): void {
    this.ahrs.update(
      gyro[0] * DEG2RAD,
      gyro[1] * DEG2RAD,
      gyro[2] * DEG2RAD,
      accel[0],
      accel[1],
      accel[2],
    );

    this.frameCount++;

    // Auto-set home after filter settles
    if (!this.initialized && this.frameCount >= HeadPoseEstimator.SETTLE_FRAMES) {
      this.recenter();
      this.initialized = true;
    }
  }

  /**
   * Get current head orientation relative to home pose.
   * Returns identity quaternion until initialized.
   */
  getQuaternion(): Quaternion {
    if (!this.initialized) {
      return new Quaternion(); // identity
    }

    const raw = this.ahrs.getQuaternion();
    const current = new Quaternion(raw.x, raw.y, raw.z, raw.w);

    // Apply home offset: relative = homeInverse * current
    if (this.homeInverse) {
      return this.homeInverse.clone().multiply(current);
    }
    return current;
  }

  /**
   * Store current orientation as "home" (looking straight ahead).
   * All subsequent getQuaternion() calls return relative to this.
   */
  recenter(): void {
    const raw = this.ahrs.getQuaternion();
    const home = new Quaternion(raw.x, raw.y, raw.z, raw.w);
    this.homeInverse = home.clone().invert();
    this.initialized = true;
  }

  /** Reset filter and home pose. */
  reset(): void {
    this.ahrs = new AHRS({
      sampleInterval: 52,
      algorithm: "Madgwick",
      beta: this.beta,
    });
    this.homeInverse = null;
    this.initialized = false;
    this.frameCount = 0;
  }
}
