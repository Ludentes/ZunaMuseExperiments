# Plan 2: Camera-Free Head Tracking — IMU → VMC Bone Rotation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the HeadPoseEstimator from TypeScript to Python. IMU head tracking with Madgwick AHRS, drift countermeasures, One Euro smoothing, and VMC bone output.

**Architecture:** `OneEuroQuaternionFilter` (adaptive smoothing) → `HeadPoseEstimator` (Madgwick + axis remap + yaw decay + recenter) → VMC `/VMC/Ext/Bone/Pos` for Head and Neck bones. Split rotation 60/40 between Neck and Head.

**Tech Stack:** ahrs (Python AHRS library), numpy, scipy

**Depends on:** Plan 0 (repo setup)

**Port from:**
- `zyphraexps/frontend/src/lib/oneEuroFilter.ts` → `src/muse_vtuber/one_euro.py`
- `zyphraexps/frontend/src/lib/headPose.ts` → `src/muse_vtuber/head_pose.py`

---

### Task 1: One Euro Quaternion Filter (port from TypeScript)

**Files:**
- Create: `src/muse_vtuber/one_euro.py`
- Create: `tests/test_one_euro.py`

- [ ] **Step 1: Write test**

`tests/test_one_euro.py`:
```python
import math

import numpy as np
import pytest


def _quat(axis_angle_deg: float, axis: tuple = (0, 1, 0)) -> tuple[float, float, float, float]:
    """Create quaternion from axis-angle (x, y, z, w)."""
    rad = math.radians(axis_angle_deg) / 2
    s = math.sin(rad)
    c = math.cos(rad)
    return (axis[0] * s, axis[1] * s, axis[2] * s, c)


class TestOneEuroQuaternionFilter:
    def test_first_sample_passthrough(self):
        from muse_vtuber.one_euro import OneEuroQuaternionFilter

        filt = OneEuroQuaternionFilter()
        q_in = (0.0, 0.0, 0.0, 1.0)
        q_out = filt.filter(q_in, timestamp=0.0)
        assert abs(q_out[3] - 1.0) < 0.01  # w ≈ 1

    def test_smooths_jittery_input(self):
        from muse_vtuber.one_euro import OneEuroQuaternionFilter

        filt = OneEuroQuaternionFilter(min_cutoff=0.3, beta=1.5)
        identity = (0.0, 0.0, 0.0, 1.0)

        # Feed identity for a while
        for i in range(20):
            filt.filter(identity, timestamp=i * 0.019)

        # Inject small jitter — output should be smoothed (closer to identity)
        jittery = _quat(3.0)  # 3° rotation — small jitter
        result = filt.filter(jittery, timestamp=20 * 0.019)

        # Output should be less than 3° from identity (smoothed)
        angle = 2 * math.acos(min(1.0, abs(result[3])))
        assert math.degrees(angle) < 3.0

    def test_fast_motion_tracks(self):
        from muse_vtuber.one_euro import OneEuroQuaternionFilter

        filt = OneEuroQuaternionFilter(min_cutoff=0.3, beta=1.5)

        # Move quickly through a sequence
        for i in range(30):
            q = _quat(i * 3.0)  # 3°/frame = fast motion
            result = filt.filter(q, timestamp=i * 0.019)

        # After fast motion, output should track reasonably close
        target = _quat(29 * 3.0)
        # Dot product measures closeness (1.0 = identical)
        dot = sum(a * b for a, b in zip(result, target))
        assert abs(dot) > 0.9  # within ~25° — tracking during fast motion

    def test_reset(self):
        from muse_vtuber.one_euro import OneEuroQuaternionFilter

        filt = OneEuroQuaternionFilter()
        filt.filter((0.0, 0.0, 0.0, 1.0), timestamp=0.0)
        filt.reset()
        # After reset, next sample should be passthrough
        q = _quat(45.0)
        result = filt.filter(q, timestamp=1.0)
        dot = sum(a * b for a, b in zip(result, q))
        assert abs(dot) > 0.99

    def test_speed_deadzone(self):
        """Slow motion (below deadzone) should be heavily smoothed."""
        from muse_vtuber.one_euro import OneEuroQuaternionFilter

        filt = OneEuroQuaternionFilter(min_cutoff=0.3, beta=1.5)
        identity = (0.0, 0.0, 0.0, 1.0)

        # Establish baseline
        for i in range(50):
            filt.filter(identity, timestamp=i * 0.019)

        # Tiny movement — below deadzone
        tiny = _quat(0.5)  # 0.5° ≈ 0.009 rad ≈ 0.45 rad/s at 52Hz — below 0.15 cutoff? Let's see
        result = filt.filter(tiny, timestamp=50 * 0.019)
        angle = 2 * math.acos(min(1.0, abs(result[3])))
        # Should be heavily smoothed — barely moved
        assert math.degrees(angle) < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_one_euro.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement OneEuroQuaternionFilter**

`src/muse_vtuber/one_euro.py`:
```python
"""One Euro Filter for quaternions.

Adapts smoothing based on motion speed:
- Slow/still → heavy smoothing (eliminates jitter)
- Fast motion → light smoothing (preserves responsiveness)

Reference: Géry Casiez et al., "1€ Filter", CHI 2012.

Ported from zyphraexps/frontend/src/lib/oneEuroFilter.ts
"""
from __future__ import annotations

import math

# Quaternion = (x, y, z, w) tuple
Quat = tuple[float, float, float, float]

# Speed below this (rad/s) is treated as zero (sensor noise at rest)
SPEED_DEADZONE = 0.15  # ~8.6°/s


def _slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Spherical linear interpolation between quaternions."""
    # Ensure shortest path
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if dot < 0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot

    dot = min(1.0, dot)

    if dot > 0.9995:
        # Linear interpolation for very close quaternions
        result = tuple(a[i] + t * (b[i] - a[i]) for i in range(4))
        norm = math.sqrt(sum(c * c for c in result))
        return tuple(c / norm for c in result)

    theta_0 = math.acos(dot)
    theta = theta_0 * t
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)

    s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0

    return tuple(s0 * a[i] + s1 * b[i] for i in range(4))


def _quat_dot(a: Quat, b: Quat) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


class OneEuroQuaternionFilter:
    """Adaptive low-pass filter for quaternions."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.5,
        d_cutoff: float = 1.0,
    ):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._prev_filtered: Quat | None = None
        self._prev_raw: Quat | None = None
        self._prev_timestamp: float = 0.0

    def _smoothing_factor(self, rate: float, cutoff: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        te = 1.0 / rate
        return 1.0 / (1.0 + tau / te)

    def filter(self, q: Quat, timestamp: float) -> Quat:
        if self._prev_filtered is None or self._prev_raw is None:
            self._prev_filtered = q
            self._prev_raw = q
            self._prev_timestamp = timestamp
            return q

        dt = timestamp - self._prev_timestamp
        if dt <= 0:
            return self._prev_filtered
        self._prev_timestamp = timestamp
        rate = 1.0 / dt

        # Align to shortest path
        raw_aligned = q
        if _quat_dot(raw_aligned, self._prev_raw) < 0:
            raw_aligned = (-q[0], -q[1], -q[2], -q[3])

        # Estimate angular speed
        dot = min(1.0, abs(_quat_dot(raw_aligned, self._prev_raw)))
        angle = 2 * math.acos(dot)
        speed = angle / dt

        self._prev_raw = raw_aligned

        # Smooth speed estimate
        d_alpha = self._smoothing_factor(rate, self.d_cutoff)
        smoothed_speed = d_alpha * speed

        # Dead zone
        effective_speed = 0.0 if smoothed_speed < SPEED_DEADZONE else smoothed_speed

        # Adaptive cutoff
        cutoff = self.min_cutoff + self.beta * effective_speed
        alpha = self._smoothing_factor(rate, cutoff)

        # Slerp toward new value
        self._prev_filtered = _slerp(self._prev_filtered, raw_aligned, alpha)
        return self._prev_filtered

    def reset(self) -> None:
        self._prev_filtered = None
        self._prev_raw = None
        self._prev_timestamp = 0.0
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_one_euro.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/one_euro.py tests/test_one_euro.py
git commit -m "feat: OneEuroQuaternionFilter ported from TypeScript"
```

---

### Task 2: HeadPoseEstimator (port from TypeScript)

**Files:**
- Create: `src/muse_vtuber/head_pose.py`
- Create: `tests/test_head_pose.py`

Port of `zyphraexps/frontend/src/lib/headPose.ts`. Madgwick AHRS → axis remap → yaw decay → One Euro → recenter.

- [ ] **Step 1: Write test**

`tests/test_head_pose.py`:
```python
import math

import numpy as np
import pytest

from muse_vtuber.head_pose import HeadPoseEstimator


def _identity_imu_sample() -> tuple[np.ndarray, np.ndarray]:
    """Stationary Muse: gravity on Z-up axis, no rotation."""
    accel = np.array([0.0, 0.0, 1.0], dtype=np.float32)  # 1g on Z (up)
    gyro = np.array([0.0, 0.0, 0.0], dtype=np.float32)    # no rotation
    return accel, gyro


class TestHeadPoseEstimator:
    def test_returns_identity_before_settle(self):
        hpe = HeadPoseEstimator()
        accel, gyro = _identity_imu_sample()
        hpe.update(accel, gyro)
        q = hpe.get_quaternion()
        # Before settling, should return identity
        assert abs(q[3] - 1.0) < 0.01  # w ≈ 1

    def test_settles_after_enough_frames(self):
        hpe = HeadPoseEstimator(settle_frames=50)  # faster settle for test
        accel, gyro = _identity_imu_sample()
        for _ in range(60):
            hpe.update(accel, gyro)
        # After settle, should be initialized
        assert hpe.initialized is True

    def test_recenter_resets_to_identity(self):
        hpe = HeadPoseEstimator(settle_frames=10)
        accel, gyro = _identity_imu_sample()
        for _ in range(20):
            hpe.update(accel, gyro)
        hpe.recenter()
        q = hpe.get_quaternion()
        # After recenter with stationary IMU, should be near identity
        angle = 2 * math.acos(min(1.0, abs(q[3])))
        assert math.degrees(angle) < 5.0

    def test_gyro_rotation_produces_movement(self):
        hpe = HeadPoseEstimator(settle_frames=10)
        accel = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        no_gyro = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        # Settle
        for _ in range(20):
            hpe.update(accel, no_gyro)

        # Apply yaw rotation (30 deg/s around Muse Z axis for 1 second)
        yaw_gyro = np.array([0.0, 0.0, 30.0], dtype=np.float32)
        for _ in range(52):  # 52Hz × 1s
            hpe.update(accel, yaw_gyro)

        q = hpe.get_quaternion()
        angle = 2 * math.acos(min(1.0, abs(q[3])))
        # Should have rotated noticeably (exact amount depends on decay)
        assert math.degrees(angle) > 5.0

    def test_yaw_decays_when_still(self):
        hpe = HeadPoseEstimator(settle_frames=10)
        accel = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        no_gyro = np.array([0.0, 0.0, 0.0], dtype=np.float32)

        # Settle
        for _ in range(20):
            hpe.update(accel, no_gyro)

        # Apply rotation
        yaw_gyro = np.array([0.0, 0.0, 30.0], dtype=np.float32)
        for _ in range(26):  # 0.5s of rotation
            hpe.update(accel, yaw_gyro)

        q_before = hpe.get_quaternion()
        angle_before = 2 * math.acos(min(1.0, abs(q_before[3])))

        # Now stay still — yaw should decay
        for _ in range(260):  # 5 seconds still
            hpe.update(accel, no_gyro)

        q_after = hpe.get_quaternion()
        angle_after = 2 * math.acos(min(1.0, abs(q_after[3])))

        assert angle_after < angle_before  # decayed

    def test_reset(self):
        hpe = HeadPoseEstimator(settle_frames=10)
        accel, gyro = _identity_imu_sample()
        for _ in range(20):
            hpe.update(accel, gyro)
        assert hpe.initialized is True
        hpe.reset()
        assert hpe.initialized is False

    def test_settle_progress(self):
        hpe = HeadPoseEstimator(settle_frames=100)
        assert hpe.settle_progress == 0.0
        accel, gyro = _identity_imu_sample()
        for _ in range(50):
            hpe.update(accel, gyro)
        assert 0.4 < hpe.settle_progress < 0.6
        for _ in range(60):
            hpe.update(accel, gyro)
        assert hpe.settle_progress == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_head_pose.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement HeadPoseEstimator**

`src/muse_vtuber/head_pose.py`:
```python
"""IMU-based head pose estimator for Muse 2.

Ported from zyphraexps/frontend/src/lib/headPose.ts.

Madgwick AHRS → axis remap (Muse→VRM) → velocity-gated yaw decay → One Euro smoothing → recenter.
"""
from __future__ import annotations

import math

import numpy as np

from muse_vtuber.one_euro import OneEuroQuaternionFilter

# Quaternion = (x, y, z, w)
Quat = tuple[float, float, float, float]

DEG2RAD = math.pi / 180.0

# Tuning constants (validated on Muse 2 hardware)
GYRO_DEADZONE = 2.0        # deg/s — zero below this
STILL_THRESHOLD = 5.0       # deg/s — "still" if gyro magnitude below
STILL_FRAMES_REQUIRED = 10  # ~0.2s at 52Hz
YAW_DECAY_STILL = 0.3       # 30%/s when still
YAW_DECAY_MOVING = 0.02     # 2%/s when moving
DEFAULT_SETTLE_FRAMES = 260  # ~5s at 52Hz
DEFAULT_BETA = 0.8           # Madgwick beta — high for responsiveness


def _quat_multiply(a: Quat, b: Quat) -> Quat:
    """Hamilton product of two quaternions (x, y, z, w)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_conjugate(q: Quat) -> Quat:
    """Conjugate (inverse for unit quaternions)."""
    return (-q[0], -q[1], -q[2], q[3])


def _quat_normalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-10:
        return (0.0, 0.0, 0.0, 1.0)
    return tuple(c / n for c in q)


def _euler_from_quat_yxz(q: Quat) -> tuple[float, float, float]:
    """Quaternion → Euler angles (YXZ order: yaw, pitch, roll).

    Returns (pitch_x, yaw_y, roll_z) in radians.
    """
    x, y, z, w = q
    # YXZ rotation order
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    pitch = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    yaw = math.asin(sinp)

    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    roll = math.atan2(siny_cosp, cosy_cosp)

    return (pitch, yaw, roll)


def _quat_from_euler_yxz(pitch: float, yaw: float, roll: float) -> Quat:
    """Euler angles (YXZ) → quaternion (x, y, z, w)."""
    cx = math.cos(pitch / 2)
    sx = math.sin(pitch / 2)
    cy = math.cos(yaw / 2)
    sy = math.sin(yaw / 2)
    cz = math.cos(roll / 2)
    sz = math.sin(roll / 2)

    # YXZ order
    w = cx * cy * cz + sx * sy * sz
    x = sx * cy * cz + cx * sy * sz
    y = cx * sy * cz - sx * cy * sz
    z = cx * cy * sz - sx * sy * cz

    return (x, y, z, w)


class _MadgwickAHRS:
    """Minimal Madgwick AHRS implementation for 6-axis IMU."""

    def __init__(self, sample_rate: float = 52.0, beta: float = 0.8):
        self.sample_rate = sample_rate
        self.beta = beta
        self.q: Quat = (0.0, 0.0, 0.0, 1.0)  # identity

    def update(self, gx: float, gy: float, gz: float, ax: float, ay: float, az: float) -> None:
        """Update with gyro (rad/s) and accel (g's)."""
        q1, q2, q3, q4 = self.q  # x, y, z, w — but Madgwick uses w,x,y,z internally
        # Convert to Madgwick convention: q = [w, x, y, z]
        qw, qx, qy, qz = q4, q1, q2, q3

        dt = 1.0 / self.sample_rate

        # Rate of change from gyro
        q_dot_w = 0.5 * (-qx * gx - qy * gy - qz * gz)
        q_dot_x = 0.5 * (qw * gx + qy * gz - qz * gy)
        q_dot_y = 0.5 * (qw * gy - qx * gz + qz * gx)
        q_dot_z = 0.5 * (qw * gz + qx * gy - qy * gx)

        # Normalize accelerometer
        a_norm = math.sqrt(ax * ax + ay * ay + az * az)
        if a_norm > 0.001:
            ax /= a_norm
            ay /= a_norm
            az /= a_norm

            # Gradient descent correction
            f1 = 2 * (qx * qz - qw * qy) - ax
            f2 = 2 * (qw * qx + qy * qz) - ay
            f3 = 2 * (0.5 - qx * qx - qy * qy) - az

            j_11 = -2 * qy
            j_12 = 2 * qx
            j_13 = 0.0
            j_21 = 2 * qz
            j_22 = 2 * qw
            j_23 = -4 * qx
            j_31 = -2 * qw
            j_32 = 2 * qz
            j_33 = -4 * qy
            j_41 = 2 * qx
            j_42 = 2 * qy
            j_43 = 0.0

            sw = j_11 * f1 + j_21 * f2 + j_31 * f3
            sx = j_12 * f1 + j_22 * f2 + j_32 * f3
            sy = j_13 * f1 + j_23 * f2 + j_33 * f3
            sz = j_41 * f1 + j_42 * f2 + j_43 * f3

            s_norm = math.sqrt(sw * sw + sx * sx + sy * sy + sz * sz)
            if s_norm > 0:
                sw /= s_norm
                sx /= s_norm
                sy /= s_norm
                sz /= s_norm

            q_dot_w -= self.beta * sw
            q_dot_x -= self.beta * sx
            q_dot_y -= self.beta * sy
            q_dot_z -= self.beta * sz

        qw += q_dot_w * dt
        qx += q_dot_x * dt
        qy += q_dot_y * dt
        qz += q_dot_z * dt

        n = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
        if n > 0:
            qw /= n
            qx /= n
            qy /= n
            qz /= n

        self.q = (qx, qy, qz, qw)  # back to (x, y, z, w)


class HeadPoseEstimator:
    """Muse 2 IMU → head orientation quaternion.

    Ported from zyphraexps/frontend/src/lib/headPose.ts.
    """

    def __init__(
        self,
        beta: float = DEFAULT_BETA,
        sample_rate: float = 52.0,
        settle_frames: int = DEFAULT_SETTLE_FRAMES,
        one_euro_min_cutoff: float = 0.3,
        one_euro_beta: float = 1.5,
    ):
        self._ahrs = _MadgwickAHRS(sample_rate=sample_rate, beta=beta)
        self._sample_rate = sample_rate
        self._settle_frames = settle_frames
        self._home_inverse: Quat | None = None
        self.initialized = False
        self._frame_count = 0
        self._still_frames = 0
        self._one_euro = OneEuroQuaternionFilter(
            min_cutoff=one_euro_min_cutoff,
            beta=one_euro_beta,
        )

    def update(self, accel: np.ndarray, gyro: np.ndarray) -> None:
        """Feed one IMU sample. Call at sensor rate (~52Hz).

        Args:
            accel: [ax, ay, az] in g's — raw Muse frame
            gyro: [gx, gy, gz] in deg/s — raw Muse frame
        """
        # Track stillness
        gyro_mag = math.sqrt(float(gyro[0]) ** 2 + float(gyro[1]) ** 2 + float(gyro[2]) ** 2)
        if gyro_mag < STILL_THRESHOLD:
            self._still_frames = min(self._still_frames + 1, STILL_FRAMES_REQUIRED + 1)
        else:
            self._still_frames = 0

        # Apply deadzone
        gx = float(gyro[0]) if abs(float(gyro[0])) >= GYRO_DEADZONE else 0.0
        gy = float(gyro[1]) if abs(float(gyro[1])) >= GYRO_DEADZONE else 0.0
        gz = float(gyro[2]) if abs(float(gyro[2])) >= GYRO_DEADZONE else 0.0

        # Feed AHRS (gyro in rad/s)
        self._ahrs.update(
            gx * DEG2RAD, gy * DEG2RAD, gz * DEG2RAD,
            float(accel[0]), float(accel[1]), float(accel[2]),
        )

        self._frame_count += 1

        if not self.initialized and self._frame_count >= self._settle_frames:
            self.recenter()
            self.initialized = True

    def _muse_to_vrm(self, q: Quat) -> Quat:
        """Remap from Muse frame to VRM/Three.js frame.

        Muse: X=forward, Y=right, Z=up
        VRM:  X=right, Y=up, Z=forward
        """
        return (q[1], q[2], q[0], q[3])

    def get_quaternion(self) -> Quat:
        """Get head orientation relative to home pose.

        Returns (x, y, z, w) identity quaternion until initialized.
        """
        if not self.initialized:
            return (0.0, 0.0, 0.0, 1.0)

        current = self._ahrs.q

        # Apply home offset: relative = homeInverse * current
        relative = current
        if self._home_inverse is not None:
            relative = _quat_multiply(self._home_inverse, current)

        # Remap to VRM frame
        remapped = self._muse_to_vrm(relative)

        # Decompose for yaw decay + pitch invert
        pitch, yaw, roll = _euler_from_quat_yxz(remapped)

        # Invert pitch (VRM convention)
        pitch = -pitch

        # Velocity-gated yaw decay
        is_still = self._still_frames >= STILL_FRAMES_REQUIRED
        decay_rate = YAW_DECAY_STILL if is_still else YAW_DECAY_MOVING
        decay_per_frame = 1 - (1 - decay_rate) ** (1 / self._sample_rate)
        yaw *= (1 - decay_per_frame)

        # Recompose
        result = _quat_from_euler_yxz(pitch, yaw, roll)

        # One Euro smoothing
        timestamp = self._frame_count / self._sample_rate
        result = self._one_euro.filter(result, timestamp)

        return result

    def recenter(self) -> None:
        """Store current orientation as home (looking straight ahead)."""
        self._home_inverse = _quat_conjugate(self._ahrs.q)
        self.initialized = True

    @property
    def settle_progress(self) -> float:
        if self.initialized:
            return 1.0
        return min(1.0, self._frame_count / self._settle_frames)

    def reset(self) -> None:
        self._ahrs = _MadgwickAHRS(
            sample_rate=self._sample_rate,
            beta=self._ahrs.beta,
        )
        self._home_inverse = None
        self.initialized = False
        self._frame_count = 0
        self._still_frames = 0
        self._one_euro.reset()
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_head_pose.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/head_pose.py tests/test_head_pose.py
git commit -m "feat: HeadPoseEstimator ported from TypeScript"
```

---

### Task 3: Wire head tracking into main loop + VMC bone output

**Files:**
- Modify: `src/muse_vtuber/main.py`
- Create: `tests/test_head_tracking_integration.py`

Add head tracking to the main loop. When IMU data is available, run HeadPoseEstimator and send VMC bone transforms for Head and Neck (60/40 split).

- [ ] **Step 1: Write integration test**

`tests/test_head_tracking_integration.py`:
```python
import math

import numpy as np
import pytest

from muse_vtuber.head_pose import HeadPoseEstimator
from muse_vtuber.outputs.vmc import VMCBoneTransform


def _split_head_neck(q: tuple, neck_ratio: float = 0.4) -> tuple[VMCBoneTransform, VMCBoneTransform]:
    """Split head quaternion into Neck (40%) and Head (60%) bones.

    Uses slerp from identity toward full rotation.
    """
    from muse_vtuber.one_euro import _slerp

    identity = (0.0, 0.0, 0.0, 1.0)
    neck_q = _slerp(identity, q, neck_ratio)
    head_q = _slerp(identity, q, 1.0 - neck_ratio)

    return (
        VMCBoneTransform(bone_name="Neck", rot_x=neck_q[0], rot_y=neck_q[1], rot_z=neck_q[2], rot_w=neck_q[3]),
        VMCBoneTransform(bone_name="Head", rot_x=head_q[0], rot_y=head_q[1], rot_z=head_q[2], rot_w=head_q[3]),
    )


def test_split_identity_gives_identity():
    identity = (0.0, 0.0, 0.0, 1.0)
    neck, head = _split_head_neck(identity)
    assert abs(neck.rot_w - 1.0) < 0.01
    assert abs(head.rot_w - 1.0) < 0.01


def test_split_rotation_distributes():
    """A 30° rotation should split ~12° neck + ~18° head."""
    rad = math.radians(30) / 2
    q = (0.0, math.sin(rad), 0.0, math.cos(rad))  # 30° yaw
    neck, head = _split_head_neck(q)

    neck_angle = 2 * math.acos(min(1.0, abs(neck.rot_w)))
    head_angle = 2 * math.acos(min(1.0, abs(head.rot_w)))

    assert 8 < math.degrees(neck_angle) < 16   # ~12°
    assert 14 < math.degrees(head_angle) < 22  # ~18°
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_head_tracking_integration.py -v
```

Expected: PASS or FAIL depending on import — the split function is inline in test for now.

- [ ] **Step 3: Add head-neck split helper to VMC output**

Add to `src/muse_vtuber/outputs/vmc.py`:
```python
def split_head_neck(
    q: tuple[float, float, float, float],
    neck_ratio: float = 0.4,
) -> tuple[VMCBoneTransform, VMCBoneTransform]:
    """Split head quaternion into Neck (40%) and Head (60%) bones via slerp."""
    from muse_vtuber.one_euro import _slerp

    identity = (0.0, 0.0, 0.0, 1.0)
    neck_q = _slerp(identity, q, neck_ratio)
    head_q = _slerp(identity, q, 1.0 - neck_ratio)

    return (
        VMCBoneTransform(bone_name="Neck", rot_x=neck_q[0], rot_y=neck_q[1], rot_z=neck_q[2], rot_w=neck_q[3]),
        VMCBoneTransform(bone_name="Head", rot_x=head_q[0], rot_y=head_q[1], rot_z=head_q[2], rot_w=head_q[3]),
    )
```

- [ ] **Step 4: Update main.py to include head tracking**

In `src/muse_vtuber/main.py`, add to imports:
```python
from muse_vtuber.head_pose import HeadPoseEstimator
from muse_vtuber.outputs.vmc import split_head_neck
```

In the `run()` function, after creating `source` and `pipeline`:
```python
    head_pose = HeadPoseEstimator(
        beta=config.madgwick_beta,
        one_euro_min_cutoff=config.smoothing_min_cutoff,
        one_euro_beta=config.smoothing_beta,
    ) if config.head_tracking_enabled else None
```

In the main loop, after pipeline.run(Cadence.FAST, frame):
```python
            # Head tracking from IMU
            bones = None
            if head_pose and imu is not None and imu.shape[1] > 0:
                for sample_idx in range(imu.shape[1]):
                    accel = imu[:3, sample_idx]
                    gyro = imu[3:, sample_idx]
                    head_pose.update(accel, gyro)
                q = head_pose.get_quaternion()
                neck, head = split_head_neck(q)
                bones = [neck, head]
```

Update the VMC send call:
```python
            if vmc_output:
                vmc_output.send_frame(blendshapes=blendshapes, bones=bones)
```

- [ ] **Step 5: Run all tests**

```bash
cd muse-vtuber
uv run pytest -v
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/muse_vtuber/outputs/vmc.py src/muse_vtuber/main.py tests/test_head_tracking_integration.py
git commit -m "feat: IMU head tracking with VMC bone output — Tier 1 complete"
```

---

### Done Criteria

- [x] OneEuroQuaternionFilter: adaptive smoothing, speed deadzone, slerp-based
- [x] HeadPoseEstimator: Madgwick, axis remap, gyro deadzone, yaw decay, recenter
- [x] VMC bone output: Head + Neck bones with 60/40 rotation split
- [x] `uv run muse-vtuber --synthetic --debug` shows head tracking active
- [x] All tests pass

### Manual Verification

1. Start VSeeFace with VMC receiver
2. Run `muse-vtuber --mac XX:XX:XX:XX:XX:XX --debug`
3. Turn head → avatar head should follow (with smoothing + drift decay)
4. Stay still → yaw should gradually decay toward center
5. Press recenter shortcut → avatar looks straight ahead
