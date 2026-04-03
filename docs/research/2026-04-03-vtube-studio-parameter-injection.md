# Research: VTube Studio Parameter Injection & Multi-Source Blending

**Date:** 2026-04-03
**Sources:** VTube Studio official API docs — github.com/DenchiSoft/VTubeStudio

---

## Background

When our plugin injects head tracking parameters (FaceAngleX/Y/Z) via the VTS WebSocket API while the user also has camera tracking enabled, the two sources can conflict. This research documents how VTS resolves that conflict.

---

## Parameter Priority Hierarchy

VTube Studio resolves Live2D parameter values through a six-tier priority system:

| Priority | Source |
|----------|--------|
| P0 | Default Live2D parameter value |
| P1 | Idle Animation values |
| P2 | Face Tracking (webcam/iOS/Android) |
| P3 | One-Time Animation values (while active) |
| P4 | Live2D Expression values (while active) |
| P5 | Physics System values |

Plugin injection via the WebSocket API sits **above** camera tracking (P2) by default — it overrides.

---

## `InjectParameterDataRequest` — Key Fields

```json
{
  "parameterValues": [
    {
      "id": "FaceAngleX",
      "value": 15.0,
      "weight": 1.0,
      "mode": "set"
    }
  ],
  "faceFound": true
}
```

### `weight` (float, 0.0–1.0, default 1.0)

**True blend formula:**
```
Final Value = (Plugin Value × weight) + (Camera Tracking Value × (1 - weight))
```

- `weight=1.0` (default): Plugin fully overrides camera tracking
- `weight=0.5`: 50% plugin, 50% camera
- `weight=0.0`: Plugin sends nothing useful; camera tracking drives 100%

This is a **true blend between sources**, not just scaling the injected value.

### `mode` ("set" | "add", default "set")

- **`set`**: Exclusive. Only one plugin can use `set` on a given parameter at a time. Camera tracking suppressed while plugin sends data. Plugin must re-send at least once per second or camera tracking resumes.
- **`add`**: Additive. Multiple plugins can stack deltas. Adds to whatever the current base value is (camera tracking or otherwise). `weight` is ignored in `add` mode.

### `faceFound` (bool, optional)

Controls "tracking lost" animations independently of parameter value injection. Set `true` to suppress "face lost" overlays even if your values are uncertain.

---

## Conflict Behavior

When a plugin injects `FaceAngleX` (a default VTS parameter) while camera tracking is active:

- **Default (`weight=1.0`)**: Plugin **completely overrides** camera tracking for that parameter
- Plugin must send updates at least every 1 second — if it stops, camera tracking automatically resumes
- Only one plugin can hold `set` mode on a parameter at a time (second plugin gets an error)

---

## Strategies for Our Plugin

| Strategy | Implementation | Use case |
|----------|---------------|----------|
| **EEG-only** | Custom params only, skip FaceAngle | User has VTS camera tracking; we add EEG signals only |
| **IMU head tracking override** | Inject FaceAngleX/Y/Z, `weight=1.0` | User has no webcam or has disabled VTS tracking |
| **IMU blend** | Inject FaceAngleX/Y/Z, `weight=0.1–0.3` | IMU provides subtle correction on top of camera tracking |
| **IMU as enhancement** | Use `mode="add"` with small values | Camera drives base pose; IMU adds small offsets |

### Current state (as of 2026-04-03)

Our VTS output (`outputs/vts.py`) injects FaceAngleX/Y/Z with default `weight=1.0`. This overrides camera tracking for all users — wrong behavior for typical VTS users who have their webcam enabled.

### Recommended fix

Gate FaceAngle injection behind a CLI flag (e.g., `--head-tracking`). Default mode should be EEG-only custom params (`MuseBlink`, `MuseFocus`, `MuseRelaxation`, `MuseClench`). Users without webcam opt in to head tracking injection.

---

## Custom vs Default Parameters

| Aspect | Custom Parameters | Default Parameters (e.g., FaceAngleX) |
|--------|-------------------|---------------------------------------|
| Created by | Plugins | Built into VTube Studio |
| Deletable | Yes (auto-deleted if plugin auth revoked) | No |
| Injection modes | Same set/add/weight | Same set/add/weight |
| Conflict with tracking | No (camera doesn't drive them) | Yes (camera drives these natively) |

---

## Sources

- [DenchiSoft/VTubeStudio API Wiki](https://github.com/DenchiSoft/VTubeStudio)
- [Interaction between Animations, Tracking, Physics, etc.](https://github.com/DenchiSoft/VTubeStudio/wiki/Interaction-between-Animations,-Tracking,-Physics,-etc.)
- [Plugins documentation](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins)
