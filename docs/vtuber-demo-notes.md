# VTuber Demo — Test Notes

## Setup (Required Before First Run)

The VRM model file is not committed (11MB binary). Download it before running:

```bash
curl -L -o frontend/public/models/default-avatar.vrm \
  "https://github.com/pixiv/three-vrm/raw/release/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
```

Then start the backend and frontend:
```bash
# Terminal 1
python -m backend.main --synthetic   # or --mac "XX:XX:XX:XX:XX:XX"

# Terminal 2
cd frontend && pnpm dev
```

Open: http://localhost:3001/vtuber

## Hardware Test Results (2026-03-30)

### Overall Assessment: Poor for real-time, usable with heavy filtering

The Muse 2 IMU (6-axis, no magnetometer) is **not viable for real-time VTuber head tracking**. The fundamental tradeoff between jitter suppression and latency cannot be resolved — you must choose one or the other, and in practice this means no real-time.

### Core Problems

1. **Jitter vs latency tradeoff (unsolvable with Muse-only)**
   - High-frequency jitter is always visible at low smoothing (head vibrates at rest)
   - Heavy smoothing eliminates jitter but introduces ~100-200ms lag
   - One Euro Filter (adaptive smoothing) helps but doesn't solve the fundamental noise floor
   - Muse gyro noise at rest: ~3°/s magnitude — extremely high for motion tracking
   - Gyro deadzone (2°/s) and One Euro speed deadzone (0.15 rad/s) partially mitigate

2. **Drift is severe**
   - **Yaw**: No magnetometer means yaw drifts continuously via gyro integration error
   - After a couple of head nods or shakes, yaw offset is noticeable and demands manual recenter
   - Velocity-gated yaw decay (30%/s when still, 2%/s when moving) helps at rest but cannot correct drift accumulated during motion
   - **Pitch/roll**: Gravity-corrected by Madgwick but still noisy

3. **Blink detection works**
   - Blink-to-expression mapping (single_blink → blink animation) is functional
   - Not perfectly real-time but acceptable latency
   - BlinkController animation: 75ms close + 75ms open = 150ms total

### What Would Be Needed for Real-Time
- A 9-axis IMU (with magnetometer) to eliminate yaw drift
- Higher quality gyroscope with lower noise floor
- Higher sample rate (Muse: 52Hz vs typical motion tracking: 200-1000Hz)
- Or: abandon IMU and use webcam-based face tracking (MediaPipe, etc.)

### Practical Use Case
With **very heavy filtering + frequent recentering**, the Muse IMU could work for:
- Slow, deliberate head movements (presentations, casual streaming)
- Combined with webcam tracking as a secondary input
- NOT suitable for: fast head motion, gaming, anything requiring <50ms latency

## Technical Findings

### Coordinate Mapping (confirmed empirically)
- Muse 2 IMU raw axes on forehead: [0]=forward, [1]=right, [2]=up
- Three.js/VRM bone convention: X=right, Y=up, Z=forward
- Remap applied at AHRS **output** level (not input — input must match gravity reference)
- `museToThreeJS()`: Muse X→Three Z, Muse Y→Three X, Muse Z→Three Y
- Pitch axis is inverted between AHRS output and VRM bone convention (negated in euler)

### Latency Pipeline (measured)
| Stage | Latency |
|-------|---------|
| BLE packet accumulation | ~20ms |
| Backend poll cycle (16ms interval) | 0-16ms, avg 8ms |
| WebSocket + browser event loop | ~2ms |
| Madgwick filter convergence | variable |
| One Euro smoothing at rest | ~50-200ms |
| **Total** | **~80-250ms** |

### Key Implementation Details
- **VRM scene rotation**: No `scene.rotation.y = Math.PI` — VRM models face +Z which is already toward camera
- **Bone rest pose**: Must `multiply()` IMU quaternion onto rest pose (set by `vrm.update()`), not replace it
- **Update order**: `vrm.update(delta)` must run BEFORE bone rotation — `humanoid.update()` inside resets raw bones
- **Expression order**: Set expression values BEFORE `vrm.update()` so `expressionManager.update()` applies them
- **AHRS input**: Feed raw Muse axes directly (no remap) — gravity reference must be consistent
- **Madgwick beta**: 0.8 (high — prioritizes responsiveness over stability)

### Drift Countermeasures (all frontend)
- **Gyro deadzone** (2°/s): zeros small readings at rest to prevent noise drift
- **Velocity-gated yaw decay**: still=30%/s, moving=2%/s (still threshold: 5°/s gyro magnitude)
- **One Euro Filter**: adaptive smoothing — minCutoff=0.3, beta=1.5
- **Settle time**: 260 frames (~5s) before auto-home — lets Madgwick fully converge
- **Manual recenter**: button + triple-blink to re-home at any time
- **Angle bias sliders**: pitch/yaw/roll ±45° manual offset for calibration

### Sensor Noise Characteristics (Muse 2 at rest)
- Gyro magnitude: ~2-4°/s (noise floor)
- Gyro spikes above 3°/s frequently while head is completely still
- Still-detection gate chatters at threshold < 5°/s
- Accel: stable (~0.98g on Z axis), slight offset on Y (~0.2g, head tilt)

## UI Controls
- **Recenter button** — re-homes current orientation as center
- **Triple blink** — triggers recenter via BCI
- **Pitch/Yaw/Roll sliders** — ±45° constant bias offset
- **Calibration countdown** — 5s overlay while Madgwick filter settles
- **Connection/Fit status** — top-left overlay badges

## Files
- `frontend/src/lib/headPose.ts` — Madgwick filter, axis remap, drift countermeasures
- `frontend/src/lib/oneEuroFilter.ts` — adaptive smoothing (One Euro Filter for quaternions)
- `frontend/src/hooks/useHeadPose.ts` — R3F hook bridging IMU to filter pipeline
- `frontend/src/components/vtuber/VTuberAvatar.tsx` — VRM loading, bone/expression application
- `frontend/src/components/vtuber/VTuberScene.tsx` — bridge between R3F context and route
- `frontend/src/components/vtuber/BlinkController.ts` — blink animation state machine
- `frontend/src/routes/vtuber.tsx` — full-screen route with Canvas, overlays, controls
