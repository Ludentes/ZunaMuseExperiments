# Research: IMU + Webcam Fusion for VTuber Head Tracking

**Date:** 2026-03-30
**Sources:** 14 sources (see below)

---

## Executive Summary

Fusing Muse 2 IMU (52Hz) with webcam face tracking (30fps) is a well-understood sensor fusion problem with a clear solution: a **quaternion complementary filter** that high-passes the IMU (smooth, fast, drifts) and low-passes the webcam (absolute, noisy, slow). This yields tracking that is **better than either source alone** — smooth like IMU, drift-free like webcam, with graceful degradation if either source drops out. The implementation is straightforward: ~50 lines of core fusion math, using MediaPipe FaceMesh for webcam pose extraction and our existing Madgwick filter for IMU. The architecture should support two modes: **passthrough mode** (VMC sender, no fusion, let client app blend) and **fusion mode** (internal MediaPipe + IMU fusion, single clean VMC output). Both modes share the same VMC output pipeline.

## Key Findings

### Why Fusion Works: Complementary Error Profiles

IMU and webcam tracking have opposite failure modes, making them ideal fusion candidates [1][2]:

| Property | Muse 2 IMU (52Hz) | Webcam/MediaPipe (30fps) |
|----------|-------------------|--------------------------|
| Short-term accuracy | Excellent (gyro integration) | Poor (landmark jitter) |
| Long-term accuracy | Terrible (gyro drift) | Excellent (absolute pose) |
| Latency | Low (~19ms sample) | Higher (~33ms + processing) |
| Sample rate | 52Hz | 30fps |
| Failure mode | Drift accumulates over seconds | Jitter on every frame |
| Lighting dependency | None | High |
| Occlusion handling | Immune (on forehead) | Breaks completely |

A complementary filter exploits this: use IMU for frame-to-frame motion (high-frequency), use webcam to anchor absolute orientation (low-frequency). This is the same principle as GPS+IMU fusion in navigation, or how 9-axis IMUs use a magnetometer for yaw correction [1][3].

### The Complementary Filter in Quaternion Space

The classic complementary filter in Euler angles is:

```
θ_fused = α · (θ_prev + gyro · dt) + (1-α) · θ_webcam
```

where α ∈ [0,1] controls the blend (typically 0.95-0.98 for IMU-favoring) [3][4].

For quaternion-based orientation (which avoids gimbal lock), the equivalent is:

```python
q_imu = q_prev * q_delta_from_gyro   # integrate IMU rotation
q_fused = slerp(q_webcam, q_imu, α)  # blend toward IMU, anchor to webcam
```

Where `slerp` is spherical linear interpolation and `α` controls how much to trust the IMU vs webcam. At α=0.98, the filter:
- Trusts IMU 98% for frame-to-frame motion (smooth, responsive)
- Pulls 2% toward webcam absolute pose each frame (kills drift over ~1-2 seconds)
- At 52Hz, full drift correction takes roughly `1/(1-0.98) / 52 ≈ 1 second` [4][5]

The gain α should be adaptive: when the webcam has high confidence (face clearly visible, low PnP error), lower α (trust webcam more). When webcam tracking is lost or uncertain, raise α toward 1.0 (rely on IMU only, accept drift) [2].

### Multi-Rate Handling (52Hz IMU + 30fps Webcam)

The sensors run at different rates, which requires a specific update strategy [1][2]:

**Approach: IMU-rate fusion with webcam corrections**

1. Run the fusion loop at IMU rate (52Hz)
2. Every IMU sample: predict orientation by integrating gyro (`q_imu = q_prev * q_delta`)
3. When a new webcam frame arrives (~every 1.7 IMU samples): correct by slerping toward webcam pose
4. Between webcam frames: pure IMU integration (no correction, fast and smooth)

This is exactly the "predict-correct" pattern used in Kalman filters, simplified to a complementary filter [2][6]:

```python
# Called at 52Hz (every IMU sample)
def update_imu(gyro, dt):
    q_predicted = q_fused * quaternion_from_gyro(gyro, dt)
    q_fused = q_predicted  # pure IMU between webcam frames

# Called at 30fps (every webcam frame)
def update_webcam(q_webcam, confidence):
    alpha = adaptive_alpha(confidence)  # 0.95-0.99
    q_fused = slerp(q_webcam, q_fused, alpha)
```

### Webcam Pose Extraction via MediaPipe

MediaPipe FaceMesh detects 468 3D face landmarks in real-time on CPU [7]. Head pose (yaw/pitch/roll) is extracted by solving the Perspective-n-Point (PnP) problem with OpenCV [8]:

1. Select 6 key landmarks: nose tip (1), eye corners (33, 263), mouth corners (61, 291), chin (199)
2. Define corresponding 3D model points (generic face model)
3. Call `cv2.solvePnP(model_3d, landmarks_2d, camera_matrix, dist_coeffs)`
4. Convert rotation vector → rotation matrix via `cv2.Rodrigues(rvec)`
5. Convert rotation matrix → quaternion via `scipy.spatial.transform.Rotation`

This gives absolute head orientation in camera frame at ~30fps on CPU. The PnP solution is noisy frame-to-frame (landmark jitter propagates) but has zero drift — exactly complementary to IMU [7][8].

**Alternative: OpenSeeFace** already does this and outputs via UDP binary protocol, including quaternion + euler + blendshapes [9]. Instead of running MediaPipe ourselves, we could consume OpenSeeFace output as the webcam source. This has the advantage of reusing the VTuber community's preferred tracking backend, but adds a dependency.

### Complementary Filter vs Kalman Filter: Which to Use

| Aspect | Complementary Filter | Extended Kalman Filter |
|--------|---------------------|----------------------|
| Complexity | ~50 lines | ~200-500 lines |
| Tuning | 1 parameter (α) | Noise covariance matrices (Q, R) |
| Latency | 3.23ms avg loop [6] | 9.26ms avg loop [6] |
| Accuracy | Good | Slightly better |
| Handles multi-rate | Yes (simple) | Yes (predict/update) |
| Handles confidence | Manual (adaptive α) | Natural (measurement noise) |

For our use case (VTuber head tracking, not surgical robotics), the complementary filter is the clear winner. It's simpler, faster, easier to tune, and the accuracy difference is negligible for avatar animation [3][6]. We already use Madgwick (which is itself a complementary filter variant) for IMU-only tracking — adding webcam as a correction source fits naturally.

An EKF would be warranted if we needed to fuse 3+ heterogeneous sensors (e.g., IMU + webcam + eye tracker + second IMU) or needed rigorous uncertainty estimates. For two-source fusion, it's overkill [6].

### Graceful Degradation

A key advantage of the fusion architecture is automatic fallback:

- **Webcam lost** (occlusion, lighting failure): α → 1.0, pure IMU tracking continues. Drift will accumulate but slowly (our yaw decay countermeasures still apply). When webcam returns, drift is corrected over ~1 second.
- **IMU lost** (BLE disconnect): fall back to webcam-only. Jittery but absolute. Apply One Euro filter for smoothing.
- **Both available**: best of both worlds.

This is a strict upgrade over either source alone — the user never gets worse tracking by having the fusion enabled.

### VMC Protocol: Sending Fused Data

The `python-vmcp` library [10] provides a clean API for sending VMC protocol over UDP:

```python
from vmcp.osc import OSC
from vmcp.protocol import bone_transform, blendshape, blendshape_apply
from vmcp.typing import Bone, CoordinateVector, Quaternion

# Send head bone rotation
Message(*bone_transform(
    Bone.HEAD,
    CoordinateVector.identity(),
    Quaternion(q.x, q.y, q.z, q.w)
))

# Send blink blendshape
Message(*blendshape("blink", 0.8))
Message(*blendshape_apply())
```

The VMC spec defines standard bone names matching Unity's `HumanBodyBones` enum. For head tracking, we send `Head` and optionally `Neck` bones. For EEG expressions, we send blendshape values [10][11].

### Existing OpenSeeFace Integration Pattern

OpenSeeFace outputs tracking via UDP binary protocol: quaternion, euler angles, 2D/3D landmarks, and facial features (eye blink, mouth shape) [9]. VSeeFace, Warudo, and other apps consume this directly.

**Integration option:** Instead of running MediaPipe ourselves, we could:
1. Consume OpenSeeFace UDP output as our webcam reference
2. Fuse it with Muse IMU data
3. Output the fused result as VMC protocol

This means the user runs OpenSeeFace (which they likely already have for VTubing) and our app sits between OpenSeeFace and the VTuber renderer, adding IMU fusion + EEG. Architecture:

```
OpenSeeFace (webcam) → UDP → Our App (fusion + EEG) → VMC → VSeeFace/Warudo/VNyan
Muse 2 (IMU + EEG)  → BLE →     ↗
```

This avoids us reimplementing webcam tracking and reuses the community's preferred tool. Downside: adds a dependency and requires the user to run OpenSeeFace separately.

## Proposed Architecture: Dual-Mode App

### Mode 1: Passthrough (No Fusion)
```
Muse 2 → BLE → Our App → VMC out (head bones + EEG blendshapes)
                       → VRChat OSC out (EEG parameters)
```
- Client VTuber app (VSeeFace/VNyan) runs its own webcam tracking
- Client app receives our VMC and blends it with webcam data (naive but functional)
- Simplest setup, works today
- User gets: EEG expressions + IMU head tracking (with known drift issues)

### Mode 2: Fusion (Internal)
```
Webcam → MediaPipe (or OpenSeeFace UDP) → absolute pose
                                              ↘
                                   Complementary Filter → VMC out (fused head + EEG)
                                              ↗
Muse 2 → BLE → IMU (Madgwick) → relative pose
             → EEG → focus/relax/blink → blendshapes → VMC out
```
- Our app owns webcam tracking (MediaPipe) or consumes OpenSeeFace
- Internal quaternion complementary filter fuses IMU + webcam
- Outputs single clean VMC stream
- User gets: smooth drift-free tracking + EEG expressions
- Strictly better than either source alone

### Shared Components (Both Modes)
- Muse BLE connection + IMU pipeline (already built)
- EEG processing (blink, focus, relaxation)
- VMC protocol output (`python-vmcp`)
- VRChat OSC output
- Configuration GUI

### Fusion-Specific Components
- Webcam capture + MediaPipe FaceMesh (or OpenSeeFace UDP receiver)
- PnP head pose extraction → quaternion
- Quaternion complementary filter (α=0.96, adaptive)
- Confidence estimation (face detection confidence → adaptive α)

## Implementation Estimate

| Component | Effort | Notes |
|-----------|--------|-------|
| VMC sender (passthrough mode) | Small | `python-vmcp` handles protocol, map our quaternion → VMC bones |
| MediaPipe head pose extraction | Small | ~30 lines: capture → FaceMesh → solvePnP → quaternion |
| Complementary filter | Small | ~50 lines: slerp-based fusion at IMU rate |
| Multi-rate scheduler | Small | IMU callback predicts, webcam callback corrects |
| OpenSeeFace UDP receiver | Small | Parse binary protocol, extract quaternion |
| Adaptive confidence | Small | Map FaceMesh confidence / PnP error → α |
| Configuration GUI | Medium | Mode selection, port config, signal preview |
| VTube Studio plugin | Medium | Separate WebSocket client, auth flow, parameter injection |

The fusion core (complementary filter + multi-rate scheduling) is genuinely simple — ~100 lines of Python. The bulk of the work is plumbing (BLE, webcam capture, VMC output, GUI).

## Open Questions

- **MediaPipe vs OpenSeeFace as webcam source?** MediaPipe is a library we embed (simpler for user, one app). OpenSeeFace is an external process (user may already have it, avoids duplicate webcam access). Could support both as input options.
- **Webcam frame rate impact on fusion quality?** At 30fps, webcam provides a correction every ~33ms. At 15fps (OpenSeeFace "Toaster" mode on weak hardware), corrections are every ~67ms — still sufficient for drift correction but less effective for jitter suppression. Need to test minimum viable webcam rate.
- **Camera coordinate frame alignment.** MediaPipe outputs pose in camera frame; Muse IMU is in head frame. Need a one-time calibration to align the two frames (user looks straight at camera, record both orientations as reference). This is analogous to our existing "recenter" button.
- **Dual webcam access.** If the user's VTuber app (VSeeFace) is already using the webcam, our app can't also open it. Solutions: (a) use OpenSeeFace as shared backend, (b) use a virtual camera splitter, (c) fusion mode replaces VSeeFace's tracking entirely (our app outputs VMC, VSeeFace receives it instead of running its own tracker).
- **Latency of MediaPipe in Python.** FaceMesh claims sub-ms on GPU, but Python overhead + webcam capture adds latency. Need to benchmark: is total webcam→quaternion latency under 50ms?

## Sources
[1] Cornman & Mei. "Extended Kalman Filtering for Head Tracking." Stanford EE267, Spring 2016. https://stanford.edu/class/ee267/Spring2016/report_cornman_mei.pdf
[2] MDPI Sensors. "Pose Estimation of a Mobile Robot Based on Fusion of IMU Data and Vision Data Using an Extended Kalman Filter." https://www.mdpi.com/1424-8220/17/10/2164
[3] OlliW. "IMU Data Fusing: Complementary, Kalman, and Mahony Filter." https://www.olliw.eu/2013/imu-data-fusing/
[4] seanboe. "Complementary Filters for IMU Fusion." https://seanboe.com/blog/complementary-filters
[5] MDPI Sensors. "Keeping a Good Attitude: A Quaternion-Based Orientation Filter for IMUs and MARGs." https://www.mdpi.com/1424-8220/15/8/19302
[6] MDPI Sensors. "IMU/UWB Fusion Method Using a Complementary Filter and a Kalman Filter." https://pmc.ncbi.nlm.nih.gov/articles/PMC10422251/
[7] Google. "MediaPipe Face Mesh." https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/face_mesh.md
[8] Jaykumaran R. "Real-Time Head Pose Estimation FaceMesh with MediaPipe and OpenCV." https://medium.com/@jaykumaran2217/real-time-head-pose-estimation-facemesh-with-mediapipe-and-opencv-a-comprehensive-guide-b63a2f40b7c6
[9] emilianavt/OpenSeeFace. "Robust realtime face and facial landmark tracking on CPU." https://github.com/emilianavt/OpenSeeFace (via https://deepwiki.com/emilianavt/OpenSeeFace)
[10] python-vmcp. "Virtual Motion Capture protocol package for Python." https://codeberg.org/vivi90/python-vmcp
[11] VMC Protocol. "VMC Protocol specification (English)." https://protocol.vmc.info/english.html
[12] VQF. "A Versatile Quaternion-based Filter for IMU Orientation Estimation." https://vqf.readthedocs.io/
[13] AHRS Python library. "Complementary Filter." https://ahrs.readthedocs.io/en/latest/filters/complementary.html
[14] GitHub. "python-osc." https://pypi.org/project/python-osc/
