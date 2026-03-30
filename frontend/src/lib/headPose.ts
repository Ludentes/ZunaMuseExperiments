import AHRS from "ahrs";
import { Euler, Quaternion } from "three";

const DEG2RAD = Math.PI / 180;

// Gyro readings below this threshold (deg/s) are zeroed to reduce jitter and drift
const GYRO_DEADZONE = 2.0;

// Yaw decay rates (per second). When still, decay is aggressive. When moving, gentle.
const YAW_DECAY_STILL = 0.3; // 30%/s — aggressively pull back when not moving
const YAW_DECAY_MOVING = 0.02; // 2%/s — gentle background correction during motion

// Gyro magnitude (deg/s) below which we consider the head "still"
// Muse noise floor at rest is ~3°/s, so threshold must be above that
const STILL_THRESHOLD = 5.0;

// Number of consecutive "still" frames before engaging aggressive decay
const STILL_FRAMES_REQUIRED = 10; // ~0.2s at 52Hz

/**
 * Madgwick-based head pose estimator for Muse 2 IMU.
 *
 * Consumes raw accel (g's) + gyro (deg/s) at 52Hz,
 * outputs a quaternion relative to the "home" orientation.
 *
 * Feeds raw Muse data to AHRS (preserving gravity reference),
 * then remaps output quaternion from Muse frame to Three.js frame.
 *
 * Muse 2 IMU frame: [0]=forward, [1]=right, [2]=up
 * Three.js/VRM frame: X=right, Y=up, Z=forward
 */
export class HeadPoseEstimator {
  private ahrs: InstanceType<typeof AHRS>;
  private homeInverse: Quaternion | null = null;
  private initialized = false;
  private frameCount = 0;
  private stillFrames = 0;
  private wasStill = false;
  private yawLogCount = 0;
  private readonly beta: number;
  private readonly sampleRate: number;

  // How many frames to accumulate before setting home pose (lets filter fully converge)
  private static SETTLE_FRAMES = 260; // ~5s at 52Hz

  constructor(beta = 0.4, sampleRate = 52) {
    this.beta = beta;
    this.sampleRate = sampleRate;
    this.ahrs = new AHRS({
      sampleInterval: sampleRate,
      algorithm: "Madgwick",
      beta,
    });
  }

  /**
   * Feed one IMU sample. Call at sensor rate (~52Hz).
   * @param accel [ax, ay, az] in g's — raw Muse frame
   * @param gyro  [gx, gy, gz] in deg/s — raw Muse frame
   */
  update(accel: Float32Array, gyro: Float32Array): void {
    // Track stillness from raw gyro magnitude
    const gyroMag = Math.sqrt(gyro[0] ** 2 + gyro[1] ** 2 + gyro[2] ** 2);
    if (gyroMag < STILL_THRESHOLD) {
      this.stillFrames = Math.min(this.stillFrames + 1, STILL_FRAMES_REQUIRED + 1);
    } else {
      this.stillFrames = 0;
    }

    // Log state transitions
    const isStillNow = this.stillFrames >= STILL_FRAMES_REQUIRED;
    if (isStillNow !== this.wasStill) {
      console.log(`[HeadPose] still=${isStillNow} gyroMag=${gyroMag.toFixed(2)}°/s`);
      this.wasStill = isStillNow;
    }

    // Apply deadzone in raw Muse frame before feeding AHRS
    let g0 = gyro[0], g1 = gyro[1], g2 = gyro[2];
    if (Math.abs(g0) < GYRO_DEADZONE) g0 = 0;
    if (Math.abs(g1) < GYRO_DEADZONE) g1 = 0;
    if (Math.abs(g2) < GYRO_DEADZONE) g2 = 0;

    // Feed raw Muse axes to AHRS — no remapping here.
    // AHRS uses accel for gravity reference, so axes must be consistent.
    this.ahrs.update(
      g0 * DEG2RAD,
      g1 * DEG2RAD,
      g2 * DEG2RAD,
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
   * Remap quaternion from Muse frame to Three.js frame.
   * Muse: X=forward, Y=right, Z=up
   * Three.js: X=right, Y=up, Z=forward
   */
  private museToThreeJS(q: Quaternion): Quaternion {
    // Muse X→Three Z, Muse Y→Three X, Muse Z→Three Y
    return new Quaternion(q.y, q.z, q.x, q.w);
  }

  /**
   * Get current head orientation relative to home pose.
   * Returns identity quaternion until initialized.
   * Applies velocity-gated yaw decay to counteract gyro drift.
   */
  getQuaternion(): Quaternion {
    if (!this.initialized) {
      return new Quaternion(); // identity
    }

    const raw = this.ahrs.getQuaternion();
    const current = new Quaternion(raw.x, raw.y, raw.z, raw.w);

    // Apply home offset: relative = homeInverse * current
    let relative = current;
    if (this.homeInverse) {
      relative = this.homeInverse.clone().multiply(current);
    }

    // Remap from Muse frame to Three.js frame
    const remapped = this.museToThreeJS(relative);

    // Decompose to euler for axis corrections and yaw decay
    const euler = new Euler().setFromQuaternion(remapped, "YXZ");

    // Invert pitch — VRM bone convention is opposite to AHRS output
    euler.x = -euler.x;

    // Velocity-gated yaw decay: aggressive when still, gentle when moving
    const isStill = this.stillFrames >= STILL_FRAMES_REQUIRED;
    const yawDecayRate = isStill ? YAW_DECAY_STILL : YAW_DECAY_MOVING;
    const decayPerFrame = 1 - Math.pow(1 - yawDecayRate, 1 / this.sampleRate);
    const yawBefore = euler.y;
    euler.y *= 1 - decayPerFrame;

    // Log yaw correction when still and yaw is significant
    if (isStill && Math.abs(yawBefore) > 0.05) {
      this.yawLogCount++;
      if (this.yawLogCount % 52 === 1) {
        const yawDeg = (yawBefore / Math.PI) * 180;
        const corrDeg = ((yawBefore - euler.y) / Math.PI) * 180;
        console.log(`[HeadPose] yaw decay: ${yawDeg.toFixed(1)}° → correcting ${corrDeg.toFixed(2)}°/frame`);
      }
    }

    return new Quaternion().setFromEuler(euler);
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

  /** Settle progress: 0 = just started, 1 = ready. */
  get settleProgress(): number {
    if (this.initialized) return 1;
    return Math.min(1, this.frameCount / HeadPoseEstimator.SETTLE_FRAMES);
  }

  /** Reset filter and home pose. */
  reset(): void {
    this.ahrs = new AHRS({
      sampleInterval: this.sampleRate,
      algorithm: "Madgwick",
      beta: this.beta,
    });
    this.homeInverse = null;
    this.initialized = false;
    this.frameCount = 0;
    this.stillFrames = 0;
    this.wasStill = false;
    this.yawLogCount = 0;
  }
}
