# Research: OpenSeeFace UDP Binary Protocol Format

**Date:** 2026-03-30
**Sources:** OpenSeeFace `facetracker.py` (sender), `Unity/OpenSee.cs` (receiver)

---

## Summary

OpenSeeFace sends face tracking data as binary UDP packets to `127.0.0.1:11573` (default). Each packet contains one or more face blocks of exactly **1785 bytes** each. Multi-face packets concatenate blocks: total = `N × 1785` bytes.

## Per-Face Byte Layout (1785 bytes)

| Offset | Size | Format | Field | Description |
|--------|------|--------|-------|-------------|
| 0 | 8 | `d` | timestamp | `time.perf_counter()`, float64 |
| 8 | 4 | `i` | face_id | Face ID, int32 |
| 12 | 4 | `f` | width | Frame width, float32 |
| 16 | 4 | `f` | height | Frame height, float32 |
| 20 | 4 | `f` | right_eye_open | Right eye blink value, float32 |
| 24 | 4 | `f` | left_eye_open | Left eye blink value, float32 |
| 28 | 1 | `B` | success | 1 if tracking OK, 0 otherwise, uint8 |
| 29 | 4 | `f` | pnp_error | PnP solve error, float32 |
| 33 | 16 | `4f` | quaternion | Head rotation (x, y, z, w), float32×4 |
| 49 | 12 | `3f` | euler | Head rotation (pitch, yaw, roll), float32×3 |
| 61 | 12 | `3f` | translation | Head position (x, y, z), float32×3 |
| 73 | 272 | `68f` | landmark_conf | 68 landmark confidence values, float32×68 |
| 345 | 544 | `136f` | landmarks_2d | 68 landmarks as (y, x) pairs — **NOTE: y first, then x** |
| 889 | 840 | `210f` | points_3d | 70 3D points as (x, -y, -z) — **NOTE: y and z negated** |
| 1729 | 56 | `14f` | features | 14 facial feature values, float32×14 |
| **1785** | | | **END** | |

## Header struct (offset 0-72, 73 bytes)

```python
HEADER_FMT = "d i f f f f B f 4f 3f 3f"
HEADER_SIZE = 73  # 8 + 4 + 4 + 4 + 4 + 4 + 1 + 4 + 16 + 12 + 12
```

**Critical:** The `B` (1-byte success flag) at offset 28 causes NO alignment padding. The next float starts at offset 29, not 32. This is because OpenSeeFace packs each field individually via `struct.pack()`.

## The 14 Feature Values

| Index | Name | Description |
|-------|------|-------------|
| 0 | eye_l | Left eye openness |
| 1 | eye_r | Right eye openness |
| 2 | eyebrow_steepness_l | Left eyebrow angle |
| 3 | eyebrow_updown_l | Left eyebrow height |
| 4 | eyebrow_quirk_l | Left eyebrow quirk |
| 5 | eyebrow_steepness_r | Right eyebrow angle |
| 6 | eyebrow_updown_r | Right eyebrow height |
| 7 | eyebrow_quirk_r | Right eyebrow quirk |
| 8 | mouth_corner_updown_l | Left mouth corner vertical |
| 9 | mouth_corner_inout_l | Left mouth corner horizontal |
| 10 | mouth_corner_updown_r | Right mouth corner vertical |
| 11 | mouth_corner_inout_r | Right mouth corner horizontal |
| 12 | mouth_open | Mouth openness |
| 13 | mouth_wide | Mouth width |

## Gotchas

1. **Byte order:** Native (little-endian on x86). No explicit endianness prefix in sender.
2. **No struct padding:** Fields packed individually, so `B` at offset 28 does not pad to 4-byte alignment.
3. **Landmark order is (y, x), not (x, y).**
4. **3D points are sign-flipped:** Sender packs `(x, -y, -z)`.
5. **70 3D points, not 68:** Two extra points (indices 68-69) are eyeball positions for gaze.
6. **Eye blink vs features:** `right_eye_open` (offset 20) and `left_eye_open` (offset 24) are raw blink values. Features[0:1] (`eye_l`, `eye_r`) are separate computed values.
7. **Quaternion order:** `(x, y, z, w)` — standard order, NOT Hamilton `(w, x, y, z)`.
8. **Only sent when detected:** Packets only sent when `detected == True`.

## Sources

- [OpenSeeFace GitHub](https://github.com/emilianavt/OpenSeeFace)
- [facetracker.py](https://github.com/emilianavt/OpenSeeFace/blob/master/facetracker.py) — sender with `struct.pack` calls
- [Unity/OpenSee.cs](https://github.com/emilianavt/OpenSeeFace/blob/master/Unity/OpenSee.cs) — C# receiver, confirms field order
