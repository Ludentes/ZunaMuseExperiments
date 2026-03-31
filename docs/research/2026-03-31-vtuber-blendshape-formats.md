# Research: VTuber Blendshape & Parameter Format Landscape

**Date:** 2026-03-31
**Purpose:** Understand which parameter format to target for a BCI-to-VTuber bridge that needs to work across VTube Studio (Live2D), VRM/3D models (VMC protocol), and potentially VRChat.
**Sources:** 25+ (see bottom)

---

## Executive Summary

**Target ARKit blendshape names for 3D/VMC and VTS built-in parameter names for Live2D.** The VTuber ecosystem has four overlapping parameter systems: ARKit (52 blendshapes, the de facto hardware standard), VTube Studio (its own ~30 built-in parameter names, different from ARKit), Live2D Cubism (internal model parameter IDs like `ParamAngleX`), and VRM (high-level expression presets like `happy`, `Blink`). For our muse-vtuber bridge:

1. **VMC output (3D):** Send ARKit-named blendshapes (e.g., `eyeBlinkLeft`, `jawOpen`). This is what "Perfect Sync" models expect, and Warudo/VSeeFace/VNyan all consume ARKit names via VMC. Custom EEG parameters should use a clear prefix (`muse_focus`, `muse_relaxation`).
2. **VTS output (2D):** Use VTS built-in parameter names (`FaceAngleX`, `EyeOpenLeft`, `MouthSmile`) for standard tracking, and custom `Muse`-prefixed parameters for EEG data. VTS handles the mapping from its input params to Live2D output params internally -- model creators bind them in the VTS editor.
3. **Do NOT target Live2D parameter IDs directly** (like `ParamAngleX`). VTS abstracts these away; you never inject `ParamAngleX` via the API.
4. **Do NOT target VRM preset expressions** (`happy`, `sad`, `blink`). These are high-level model-defined clips, not individual tracking parameters. They are useful only for composite expression triggers, not continuous tracking.

Our current implementation is **mostly correct** but could be improved: we send `FaceAngleX/Y/Z` (correct for VTS) and custom `MuseBlink/Focus/Relaxation/Clench` (correct for VTS). For VMC, we send `Blink` (correct VRM name) and `muse_*` custom names (fine). We should additionally send `EyeOpenLeft`/`EyeOpenRight` in VTS mode for blink, since that is what Live2D models actually bind to.

---

## 1. ARKit Blendshapes (Apple's 52 Face Parameters)

### Overview

Apple ARKit defines 52 named blendshape locations for TrueDepth face tracking (iPhone X and later). Each is a float in the range **[0.0, 1.0]** where 0.0 = neutral and 1.0 = fully activated. This has become the **de facto standard** for high-fidelity face tracking in the VTuber ecosystem, used by iFacialMocap, FaceMotion3D, VTube Studio (iOS), and MeowFace (Android, approximates ARKit via MediaPipe).

### Complete List (52 blendshapes)

**Eyes (14):**

| # | Name | Description |
|---|------|-------------|
| 1 | eyeBlinkLeft | Left eye close |
| 2 | eyeLookDownLeft | Left eye look down |
| 3 | eyeLookInLeft | Left eye look toward nose |
| 4 | eyeLookOutLeft | Left eye look away from nose |
| 5 | eyeLookUpLeft | Left eye look up |
| 6 | eyeSquintLeft | Left eye squint |
| 7 | eyeWideLeft | Left eye wide open |
| 8 | eyeBlinkRight | Right eye close |
| 9 | eyeLookDownRight | Right eye look down |
| 10 | eyeLookInRight | Right eye look toward nose |
| 11 | eyeLookOutRight | Right eye look away from nose |
| 12 | eyeLookUpRight | Right eye look up |
| 13 | eyeSquintRight | Right eye squint |
| 14 | eyeWideRight | Right eye wide open |

**Jaw (4):**

| # | Name | Description |
|---|------|-------------|
| 15 | jawForward | Jaw thrust forward |
| 16 | jawLeft | Jaw shift left |
| 17 | jawRight | Jaw shift right |
| 18 | jawOpen | Jaw open |

**Mouth (23):**

| # | Name | Description |
|---|------|-------------|
| 19 | mouthClose | Lips close (oppose jawOpen) |
| 20 | mouthFunnel | Lips funnel (O shape) |
| 21 | mouthPucker | Lips pucker (kiss) |
| 22 | mouthLeft | Mouth shift left |
| 23 | mouthRight | Mouth shift right |
| 24 | mouthSmileLeft | Left corner smile |
| 25 | mouthSmileRight | Right corner smile |
| 26 | mouthFrownLeft | Left corner frown |
| 27 | mouthFrownRight | Right corner frown |
| 28 | mouthDimpleLeft | Left dimple |
| 29 | mouthDimpleRight | Right dimple |
| 30 | mouthStretchLeft | Left corner stretch |
| 31 | mouthStretchRight | Right corner stretch |
| 32 | mouthRollLower | Lower lip roll in |
| 33 | mouthRollUpper | Upper lip roll in |
| 34 | mouthShrugLower | Lower lip shrug out |
| 35 | mouthShrugUpper | Upper lip shrug out |
| 36 | mouthPressLeft | Left lip press |
| 37 | mouthPressRight | Right lip press |
| 38 | mouthLowerDownLeft | Lower left lip down |
| 39 | mouthLowerDownRight | Lower right lip down |
| 40 | mouthUpperUpLeft | Upper left lip up |
| 41 | mouthUpperUpRight | Upper right lip up |

**Brow (5):**

| # | Name | Description |
|---|------|-------------|
| 42 | browDownLeft | Left brow down |
| 43 | browDownRight | Right brow down |
| 44 | browInnerUp | Inner brows raise |
| 45 | browOuterUpLeft | Left outer brow raise |
| 46 | browOuterUpRight | Right outer brow raise |

**Cheek (3):**

| # | Name | Description |
|---|------|-------------|
| 47 | cheekPuff | Both cheeks puff |
| 48 | cheekSquintLeft | Left cheek squint |
| 49 | cheekSquintRight | Right cheek squint |

**Nose & Tongue (3):**

| # | Name | Description |
|---|------|-------------|
| 50 | noseSneerLeft | Left nostril raise |
| 51 | noseSneerRight | Right nostril raise |
| 52 | tongueOut | Tongue protrude |

### Key Properties
- **Naming:** camelCase, starting with lowercase letter
- **Range:** 0.0 to 1.0 for all parameters
- **Symmetry:** Left/Right variants for eyes, mouth corners, brows, cheeks, nose
- **No head rotation:** ARKit provides head pose separately as a 4x4 matrix, not as blendshapes
- **Stable since 2017:** The 52 blendshapes have not changed since iOS 11. tongueOut (#52) was added with ARKit 2 (iOS 12, 2018) and is sometimes considered separate

### Which VTuber Apps Support ARKit Natively
- **VTube Studio** (iOS app): Native ARKit tracking, sends all 52 blendshapes internally
- **iFacialMocap**: Streams ARKit data over network; used by VTube Studio, VSeeFace, Warudo
- **FaceMotion3D**: Alternative iOS ARKit streamer
- **VSeeFace**: Receives ARKit via iFacialMocap, uses for Perfect Sync VRM models
- **Warudo**: Receives ARKit via iFacialMocap/ARKit, maps to VRM blendshapes by name
- **VNyan**: Receives ARKit via iFacialMocap

---

## 2. VTube Studio Parameter System

### Built-in (Default) Input Parameters

VTube Studio defines its own parameter naming convention, distinct from both ARKit and Live2D. These are the names used in the VTS API when injecting parameter data via `InjectParameterDataRequest`.

**Face Position & Rotation (6):**

| Parameter | Description | Typical Range |
|-----------|-------------|---------------|
| FacePositionX | Horizontal face position | -1 to 1 |
| FacePositionY | Vertical face position | -1 to 1 |
| FacePositionZ | Distance from camera | -1 to 1 |
| FaceAngleX | Face yaw (left/right rotation) | -30 to 30 (degrees) |
| FaceAngleY | Face pitch (up/down rotation) | -30 to 30 (degrees) |
| FaceAngleZ | Face roll (tilt rotation) | -30 to 30 (degrees) |

**Eyes (6):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| EyeOpenLeft | Left eye openness | 0-1 |
| EyeOpenRight | Right eye openness | 0-1 |
| EyeLeftX | Left eye horizontal gaze | -1 to 1 |
| EyeLeftY | Left eye vertical gaze | -1 to 1 |
| EyeRightX | Right eye horizontal gaze | -1 to 1 |
| EyeRightY | Right eye vertical gaze | -1 to 1 |

**Mouth (3):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| MouthSmile | Smile amount | 0-1 |
| MouthOpen | Mouth openness | 0-1 |
| MouthX | Mouth horizontal shift | -1 to 1 |

**Brows (3):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| Brows | Both brows combined up/down | 0-1 (0.5=neutral) |
| BrowLeftY | Left brow up/down | 0-1 |
| BrowRightY | Right brow up/down | 0-1 |

**Other Face (3):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| CheekPuff | Cheek puff detection | 0-1 |
| TongueOut | Tongue protrusion | 0-1 |
| FaceAngry | Angry expression (experimental, unreliable) | 0-1 |

**Voice / Audio (8):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| VoiceVolume | Microphone volume level | 0-1 |
| VoiceFrequency | Voice pitch frequency | 0-1 |
| VoiceVolumePlusMouthOpen | Combined volume + tracking | 0-1 |
| VoiceFrequencyPlusMouthSmile | Combined frequency + tracking | 0-1 |
| VoiceA | "A" vowel detection | 0-1 |
| VoiceI | "I" vowel detection | 0-1 |
| VoiceU | "U" vowel detection | 0-1 |
| VoiceE | "E" vowel detection | 0-1 |
| VoiceO | "O" vowel detection | 0-1 |
| VoiceSilence | Silence detection | 0-1 |

**Input Devices (2):**

| Parameter | Description | Range |
|-----------|-------------|-------|
| MousePositionX | Mouse/finger X position | configurable |
| MousePositionY | Mouse/finger Y position | configurable |

**Total: ~33 built-in parameters** (exact count varies with VTS version and tracking source; iOS exposes more than webcam)

### VTS vs ARKit Naming Comparison

VTS does NOT use ARKit names directly. It has its own simplified naming:

| VTS Name | ARKit Equivalent(s) | Notes |
|----------|---------------------|-------|
| FaceAngleX | (head pose matrix) | ARKit: separate head transform; VTS: degrees |
| FaceAngleY | (head pose matrix) | Same |
| FaceAngleZ | (head pose matrix) | Same |
| EyeOpenLeft | 1.0 - eyeBlinkLeft | VTS: 1=open, ARKit: 1=closed (inverted!) |
| EyeOpenRight | 1.0 - eyeBlinkRight | Same inversion |
| MouthSmile | avg(mouthSmileLeft, mouthSmileRight) | VTS combines L/R |
| MouthOpen | jawOpen | Roughly equivalent |
| MouthX | mouthLeft - mouthRight | VTS combines into single axis |
| Brows | browInnerUp (approx) | VTS simplifies to single value |
| BrowLeftY | browOuterUpLeft - browDownLeft | VTS computes from ARKit |
| BrowRightY | browOuterUpRight - browDownRight | Same |
| CheekPuff | cheekPuff | Direct match |
| TongueOut | tongueOut | Direct match |

**Critical difference:** VTS `EyeOpenLeft` = 1.0 means eye fully open, while ARKit `eyeBlinkLeft` = 1.0 means eye fully closed. They are inverted.

### VTS Plugin API: Injecting Parameters

The `InjectParameterDataRequest` supports two modes:

- **"set" mode (default):** Overrides the parameter value. Only one plugin can "set" a parameter at a time.
- **"add" mode:** Adds the plugin's value to the current tracking value. Multiple plugins can use "add" simultaneously.

The **"weight"** field (0.0-1.0) in "set" mode blends between plugin value and face tracking value. Weight=1.0 means pure plugin control; weight=0.5 means 50/50 blend.

Custom parameters (up to 100 per plugin) are created via `ParameterCreationRequest` with a name, min, max, and default. These appear alongside built-in parameters in the VTS model settings UI.

### Implications for Muse Bridge

- Inject `FaceAngleX/Y/Z` for head tracking (already doing this correctly)
- Inject `EyeOpenLeft`/`EyeOpenRight` for blink (value = 1.0 - blink_confidence; 0 = closed, 1 = open)
- Use custom parameters `MuseFocus`, `MuseRelaxation`, `MuseClench` for EEG data
- Consider using **"add" mode** with low weight for blending with webcam tracking

---

## 3. Live2D Cubism Parameters

### Standard Parameter IDs

Live2D models use internal parameter IDs that follow the `Param` prefix convention. These are the output-side parameters that VTube Studio maps to. **You never inject these directly via the VTS API** -- VTS handles the input-to-output mapping.

| ID | Name | Default Range | Description |
|----|------|--------------|-------------|
| ParamAngleX | Angle X | -30 to 30 | Face left/right rotation |
| ParamAngleY | Angle Y | -30 to 30 | Face up/down rotation |
| ParamAngleZ | Angle Z | -30 to 30 | Face tilt rotation |
| ParamEyeLOpen | Left Eye Open | 0 to 1 | Left eye openness |
| ParamEyeROpen | Right Eye Open | 0 to 1 | Right eye openness |
| ParamEyeLSmile | Left Eye Smile | 0 to 1 | Left eye squint/smile |
| ParamEyeRSmile | Right Eye Smile | 0 to 1 | Right eye squint/smile |
| ParamEyeBallX | Eye Ball X | -1 to 1 | Eye horizontal gaze |
| ParamEyeBallY | Eye Ball Y | -1 to 1 | Eye vertical gaze |
| ParamBrowLY | Left Brow Y | -1 to 1 | Left brow position |
| ParamBrowRY | Right Brow Y | -1 to 1 | Right brow position |
| ParamBrowLX | Left Brow X | -1 to 1 | Left brow angle |
| ParamBrowRX | Right Brow X | -1 to 1 | Right brow angle |
| ParamBrowLAngle | Left Brow Angle | -1 to 1 | Left brow rotation |
| ParamBrowRAngle | Right Brow Angle | -1 to 1 | Right brow rotation |
| ParamBrowLForm | Left Brow Form | -1 to 1 | Left brow shape |
| ParamBrowRForm | Right Brow Form | -1 to 1 | Right brow shape |
| ParamMouthForm | Mouth Form | -1 to 1 | Smile (+1) to frown (-1) |
| ParamMouthOpenY | Mouth Open Y | 0 to 1 | Mouth openness |
| ParamCheek | Cheek | 0 to 1 | Cheek puff |
| ParamBodyAngleX | Body Angle X | -10 to 10 | Body left/right |
| ParamBodyAngleY | Body Angle Y | -10 to 10 | Body forward/back |
| ParamBodyAngleZ | Body Angle Z | -10 to 10 | Body tilt |
| ParamBreath | Breath | 0 to 1 | Breathing cycle |
| ParamHairFront | Hair Front | -1 to 1 | Front hair physics |
| ParamHairSide | Hair Side | -1 to 1 | Side hair physics |
| ParamHairBack | Hair Back | -1 to 1 | Back hair physics |
| ParamHandL | Left Hand | 0 to 1 | Left hand gesture |
| ParamHandR | Right Hand | 0 to 1 | Right hand gesture |
| ParamArmLA | Left Arm A | 0 to 1 | Left arm position A |
| ParamArmRA | Right Arm A | 0 to 1 | Right arm position A |
| ParamArmLB | Left Arm B | 0 to 1 | Left arm position B |
| ParamArmRB | Right Arm B | 0 to 1 | Right arm position B |

### Key Properties
- **Naming:** PascalCase with `Param` prefix
- **Ranges:** Vary per parameter (not uniform 0-1)
- **Model-specific:** Not all models implement all standard parameters. Model creators choose which to include.
- **Custom parameters:** Models can define arbitrary additional parameters beyond the standard list
- **Cubism 2.x vs 3+:** Older models used `PARAM_ANGLE_X` (uppercase with underscores). Cubism 3+ standardized to `ParamAngleX`

### VTS Input-to-Live2D Output Mapping

VTS maps its input parameters to Live2D output parameters in the model settings UI. The default mapping for a standard model is:

| VTS Input | Live2D Output | Notes |
|-----------|--------------|-------|
| FaceAngleX | ParamAngleX | 1:1 |
| FaceAngleY | ParamAngleY | 1:1 |
| FaceAngleZ | ParamAngleZ | 1:1 |
| EyeOpenLeft | ParamEyeLOpen | 1:1 |
| EyeOpenRight | ParamEyeROpen | 1:1 |
| MouthSmile | ParamMouthForm | 0-1 mapped to -1 to 1 typically |
| MouthOpen | ParamMouthOpenY | 1:1 |
| Brows | ParamBrowLY + ParamBrowRY | Split to both |
| EyeLeftX | ParamEyeBallX | Combined or per-eye |

Model creators can remap these freely. Custom plugin parameters can be bound to any Live2D output parameter.

---

## 4. VRM Blendshapes / Expressions

### VRM 0.x BlendShapePreset Names

| Preset | Purpose | Notes |
|--------|---------|-------|
| Neutral | Default face | |
| A | Mouth shape "ah" | Lip sync |
| I | Mouth shape "ee" | Lip sync |
| U | Mouth shape "oo" | Lip sync |
| E | Mouth shape "eh" | Lip sync |
| O | Mouth shape "oh" | Lip sync |
| Blink | Both eyes close | |
| Blink_L | Left eye wink | |
| Blink_R | Right eye wink | |
| Joy | Happy expression | |
| Angry | Angry expression | |
| Sorrow | Sad expression | |
| Fun | Relaxed/comfortable | |
| LookUp | Eyes look up | |
| LookDown | Eyes look down | |
| LookLeft | Eyes look left | |
| LookRight | Eyes look right | |

### VRM 1.0 Expression Preset Names

VRM 1.0 renamed several presets:

| VRM 0.x | VRM 1.0 | Change |
|---------|---------|--------|
| Joy | happy | Renamed, lowercase |
| Angry | angry | Lowercase |
| Sorrow | sad | Renamed |
| Fun | relaxed | Renamed |
| (none) | surprised | Added new |
| A | aa | Renamed |
| I | ih | Renamed |
| U | ou | Renamed |
| E | ee | Renamed |
| O | oh | Renamed |
| Blink | blink | Lowercase |
| Blink_L | blinkLeft | Renamed |
| Blink_R | blinkRight | Renamed |
| LookUp | lookUp | Lowercase |
| LookDown | lookDown | Lowercase |
| LookLeft | lookLeft | Lowercase |
| LookRight | lookRight | Lowercase |
| Neutral | neutral | Lowercase |

### VRM "Perfect Sync" (ARKit Blendshapes on VRM)

"Perfect Sync" refers to adding all 52 ARKit blendshapes to a VRM model as individual BlendShapeClips (VRM 0.x) or Expressions (VRM 1.0). When a model has Perfect Sync:

- The 52 clips are named using **ARKit camelCase names** (`eyeBlinkLeft`, `jawOpen`, etc.)
- VMC senders transmit these names via `/VMC/Ext/Blend/Val`
- Receivers (Warudo, VSeeFace, VNyan) match by name (case-sensitive!)
- This enables high-fidelity facial tracking from iPhone ARKit

**Without** Perfect Sync, VRM models only have the ~17 preset blendshapes listed above. Face tracking is lower fidelity because multiple ARKit parameters must be combined into a single `Blink` or `Joy` clip.

### VRoid Studio Naming (Common Variant)

Models exported from VRoid Studio use a different convention with `Fcl_` prefix:
- `Fcl_EYE_Close` (instead of `Blink`)
- `Fcl_MTH_Joy` (instead of expression names)
- Warudo and VSeeFace recognize this convention as an alternative

### VMC Protocol: What Names to Send

The VMC protocol transmits blendshape values as:
```
/VMC/Ext/Blend/Val (string){name} (float){value}
```
followed by:
```
/VMC/Ext/Blend/Apply
```

The `name` field is **case-sensitive** and must match what the VRM model defines. In practice:

- For Perfect Sync models: send **ARKit names** (`eyeBlinkLeft`, `jawOpen`, etc.)
- For standard VRM models: send **VRM preset names** (`Blink`, `Joy`, `A`, etc. for 0.x; `blink`, `happy`, `aa`, etc. for 1.0)
- For custom/EEG parameters: use any name with a clear prefix (e.g., `muse_focus`). These will only work if the model has matching BlendShapeClips

**Receivers handle arbitrary names.** Warudo, VSeeFace, and VNyan will pass through any blendshape name received via VMC -- but it only drives the avatar if the VRM model has a matching clip. Custom names like `muse_focus` require the model creator to add a corresponding clip.

---

## 5. Cross-Format Compatibility Matrix

### Parameter Name Mapping: ARKit ↔ VTS ↔ Live2D ↔ VRM

| Concept | ARKit Name | VTS Input Name | Live2D Param | VRM 0.x | VRM 1.0 |
|---------|-----------|---------------|-------------|---------|---------|
| Left eye close | eyeBlinkLeft | EyeOpenLeft (inverted!) | ParamEyeLOpen | Blink / Blink_L | blink / blinkLeft |
| Right eye close | eyeBlinkRight | EyeOpenRight (inverted!) | ParamEyeROpen | Blink / Blink_R | blink / blinkRight |
| Jaw open | jawOpen | MouthOpen | ParamMouthOpenY | A (lip sync) | aa |
| Smile L | mouthSmileLeft | MouthSmile (combined) | ParamMouthForm | Joy | happy |
| Smile R | mouthSmileRight | MouthSmile (combined) | ParamMouthForm | Joy | happy |
| Cheek puff | cheekPuff | CheekPuff | ParamCheek | (none) | (none) |
| Tongue out | tongueOut | TongueOut | (custom) | (none) | (none) |
| Head yaw | (head transform) | FaceAngleX | ParamAngleX | (bone rotation) | (bone rotation) |
| Head pitch | (head transform) | FaceAngleY | ParamAngleY | (bone rotation) | (bone rotation) |
| Head roll | (head transform) | FaceAngleZ | ParamAngleZ | (bone rotation) | (bone rotation) |
| Eye gaze L horiz | eyeLookOutLeft - eyeLookInLeft | EyeLeftX | ParamEyeBallX | LookLeft/LookRight | lookLeft/lookRight |
| Brow up L | browOuterUpLeft | BrowLeftY | ParamBrowLY | (none standard) | (none standard) |
| Brow down L | browDownLeft | BrowLeftY (inverted) | ParamBrowLY | Angry (partial) | angry (partial) |

### Key Compatibility Notes

1. **ARKit ↔ VTS:** VTS internally converts ARKit data to its own parameter names. The conversion is lossy -- VTS combines L/R smile into one `MouthSmile`, simplifies brows, and inverts eye open/close semantics.

2. **ARKit ↔ VRM (Perfect Sync):** Direct 1:1 mapping. ARKit names used as-is for VRM BlendShapeClips. This is the highest fidelity path.

3. **ARKit ↔ VRM (Standard):** Many-to-one. Multiple ARKit parameters combine into single VRM presets. E.g., both `mouthSmileLeft` and `mouthSmileRight` contribute to VRM `Joy`/`happy`.

4. **VTS ↔ Live2D:** VTS maps its input parameters to Live2D output parameters. This is user-configurable in the VTS model settings editor. The default mapping is predictable but model creators can customize it.

5. **VRM ↔ Live2D:** These are separate ecosystems. VRM is for 3D mesh models; Live2D is for 2D layered art. They do not share parameter formats. A VTuber bridge targets one or both, not a mapping between them.

### Coverage Gaps by Format

| Feature | ARKit | VTS | Live2D | VRM (std) | VRM (PerfSync) |
|---------|-------|-----|--------|-----------|----------------|
| Per-eye blink | Yes | Yes | Yes | Yes | Yes |
| Per-side smile | Yes | No (combined) | Yes | No | Yes |
| Eye gaze | Yes (6 params) | Yes (4 params) | Yes | Yes (4 presets) | Yes |
| Tongue | Yes | Yes | Custom | No | Yes |
| Cheek puff | Yes | Yes | Yes | No | Yes |
| Head rotation | Separate | Yes (degrees) | Yes (degrees) | Bones | Bones |
| Nose sneer | Yes | No | No | No | Yes |
| Custom/EEG params | No | Yes (custom) | Yes (custom) | No standard | Custom clips |

---

## 6. VTS Version History & Stability

### API Stability

- **VTS Plugin API v1.0** has been stable since its introduction (~2021). The core `InjectParameterDataRequest` format has not changed.
- **No breaking parameter name changes** have been found. Parameters like `FaceAngleX`, `EyeOpenLeft`, and `MouthSmile` have remained consistent across all versions.
- **Additions, not removals:** VTS has added parameters over time (e.g., voice phoneme parameters `VoiceA/I/U/E/O` were added later), but has not removed or renamed existing ones.
- **Live2D 5.0 support** was added in v1.27.5 (2024) without API changes.
- **Current version:** 1.32.71 (March 2026). Mobile and desktop versions now synchronized.

### Notable Milestones

| Version | Date | Change |
|---------|------|--------|
| ~1.5 | 2021 | Plugin API introduced (WebSocket on port 8001) |
| ~1.9 | 2021 | iOS ARKit face tracking support |
| ~1.20 | 2023 | Advanced phoneme lip sync parameters added |
| 1.27.5 | 2024 | Live2D Cubism 5.0 SDK support |
| 1.32.71 | 2026-03 | Current version, desktop/mobile sync |

### Risk Assessment

Low risk of breaking changes. The VTS API has been remarkably stable. Custom parameter names (`MuseBlink`, etc.) created via `ParameterCreationRequest` are plugin-defined and under our control. Built-in parameter names are unlikely to change given the large ecosystem of models and plugins depending on them.

---

## 7. Recommendations for Muse-VTuber Bridge

### What to Send: VTube Studio (Live2D) Output

| Muse Signal | VTS Parameter | Mode | Value Mapping |
|-------------|--------------|------|---------------|
| Blink detected | EyeOpenLeft, EyeOpenRight | "set", weight=1.0 | 0.0 during blink, 1.0 open |
| Head yaw | FaceAngleX | "set", weight=1.0 | Degrees from IMU |
| Head pitch | FaceAngleY | "set", weight=1.0 | Degrees from IMU |
| Head roll | FaceAngleZ | "set", weight=1.0 | Degrees from IMU |
| Focus (EEG) | MuseFocus (custom) | "set" | 0.0 to 1.0 |
| Relaxation (EEG) | MuseRelaxation (custom) | "set" | 0.0 to 1.0 |
| Jaw clench (EEG) | MuseClench (custom) | "set" | 0.0 to 1.0 |

**Improvement over current code:** Add `EyeOpenLeft`/`EyeOpenRight` injection for blink. Currently we only send `MuseBlink` which requires model creators to manually bind it. If we also drive `EyeOpenLeft`/`EyeOpenRight`, blink works out-of-the-box with any standard Live2D model.

**When combining with webcam tracking:** Use `"add"` mode or `"set"` with `weight < 1.0` for head angles to blend with webcam tracking rather than override it.

### What to Send: VMC Protocol (3D/VRM) Output

| Muse Signal | VMC Blendshape Name | Value |
|-------------|-------------------|-------|
| Blink detected | Blink (VRM) or eyeBlinkLeft + eyeBlinkRight (ARKit) | 0.0 to 1.0 |
| Focus (EEG) | muse_focus | 0.0 to 1.0 |
| Relaxation (EEG) | muse_relaxation | 0.0 to 1.0 |
| Jaw clench (EEG) | muse_clench or jawOpen | 0.0 to 1.0 |
| Head rotation | /VMC/Ext/Bone/Pos "Head" (quaternion) | Quaternion from IMU |

**Improvement over current code:** Send **both** `Blink` (for standard VRM models) and `eyeBlinkLeft`/`eyeBlinkRight` (for Perfect Sync models). This maximizes compatibility. Also consider sending `jawOpen` for clench in addition to `muse_clench`, since `jawOpen` will work with Perfect Sync models without custom clips.

### Recommended Parameter Naming Strategy

1. **Standard tracking (head, blink):** Use the native names for each target:
   - VTS: `FaceAngleX`, `EyeOpenLeft`, etc.
   - VMC: ARKit names for Perfect Sync, VRM names for standard models
2. **Custom EEG parameters:** Use `Muse` prefix for VTS (`MuseFocus`), `muse_` prefix for VMC (`muse_focus`). Keep names short and descriptive.
3. **Future-proofing:** If we ever add more ARKit-like parameters (e.g., jaw clench mapped to `jawOpen`), use the standard names on both sides. Custom names only for things that have no ARKit/VRM equivalent.

### Summary: Optimal Target Matrix

| Output Target | Naming Convention | Head Tracking | Blink | EEG Custom |
|---------------|-------------------|---------------|-------|------------|
| VTube Studio | VTS built-in names | FaceAngleX/Y/Z | EyeOpenLeft/Right | MuseFocus, MuseRelaxation, MuseClench |
| VMC (Perfect Sync VRM) | ARKit camelCase | /VMC/Ext/Bone/Pos | eyeBlinkLeft/Right | muse_focus, muse_relaxation, muse_clench |
| VMC (Standard VRM) | VRM preset names | /VMC/Ext/Bone/Pos | Blink | muse_focus, muse_relaxation, muse_clench |
| VRChat OSC | VRChat parameter format | Head rotation params | Blink | BCI/Focus, BCI/Relaxation |

---

## Sources

- [ARFaceAnchor.BlendShapeLocation | Apple Developer Documentation](https://developer.apple.com/documentation/arkit/arfaceanchor/blendshapelocation)
- [ARKit 52 Facial Blendshapes: The Ultimate Guide](https://pooyadeperson.com/the-ultimate-guide-to-creating-arkits-52-facial-blendshapes/)
- [ARKit Blendshapes Reference | DeepWiki](https://deepwiki.com/shun126/livelinkface_arkit_receiver/5.5-arkit-blendshapes-reference)
- [arkit-face-blendshapes.com](https://arkit-face-blendshapes.com/)
- [VTS Model Settings | DenchiSoft Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings)
- [VTube Studio Settings | DenchiSoft Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/VTube-Studio-Settings)
- [VTube Studio API | GitHub](https://github.com/DenchiSoft/VTubeStudio)
- [Plugins | DenchiSoft Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins)
- [VTube-IFacial-Link-Sharp | GitHub](https://github.com/xuan25/VTube-IFacial-Link-Sharp)
- [Standard Parameter List | Live2D Editor Manual](https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/)
- [Live2D Model Requirements | Animaze](https://www.animaze.us/manual/gettingstarted2d/paramlist)
- [BlendShape Setting | VRM](https://vrm.dev/en/univrm/blendshape/univrm_blendshape/)
- [VRMC_vrm-1.0 Expressions Spec | GitHub](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/expressions.md)
- [VRM 0.0 Specification | GitHub](https://github.com/vrm-c/vrm-specification/blob/master/specification/0.0/README.md)
- [Perfect Sync | VMagicMirror](https://malaybaku.github.io/VMagicMirror/en/tips/perfect_sync/)
- [3D VTubing Primer | Warudo Handbook](https://docs.warudo.app/docs/tutorials/3d-primer)
- [Customizing Face Tracking | Warudo Handbook](https://docs.warudo.app/docs/mocap/face-tracking)
- [VMC Protocol Specification](https://protocol.vmc.info/english.html)
- [VSeeFace Manual | GitHub](https://github.com/emilianavt/VSeeFaceManual/blob/master/README.md)
- [VBridger Manual](https://cdn.steamstatic.com/steam/apps/1898830/manuals/VBridger_Manual_1.06.pdf)
- [VRMExpressionPresetName | three-vrm](https://pixiv.github.io/three-vrm/docs/types/three-vrm.VRMExpressionPresetName.html)
- [Add ARKit to BlendShapeAvatar | Hai~](https://docs.hai-vr.dev/docs/products/prefabulous/vrm/add-arkit-to-blendshapeavatar)
- [DenchiSoft VTS Documentation v1.8.5](https://denchisoft.com/wp-content/uploads/2021/05/VTube_Studio_Documentation_1_8_5_c.pdf)
- [ARKit to FACS Cheat Sheet](https://melindaozel.com/arkit-to-facs-cheat-sheet/)
- [VTube Studio on Steam](https://store.steampowered.com/app/1325860/VTube_Studio/)
