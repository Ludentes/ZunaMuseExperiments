# VSeeFace on Linux: Strategy Design

**Date:** 2026-03-30
**Status:** Draft
**Context:** The muse-vtuber bridge sends VMC protocol data. We need a rendering target on Linux.

## Problem

VSeeFace is the most popular free VRM avatar renderer for VTubers but is Windows-only. Our development platform is Linux. We need to decide how to handle avatar rendering during development and what to recommend to users.

## Constraints

- Development platform: Linux (no Windows available)
- Bridge already outputs VMC protocol (UDP, `/VMC/Ext/Blend/Val`)
- Plans 4 and 5 add VRChat OSC and VTube Studio outputs
- The zyphraexps frontend already has a React/TanStack Start SPA
- YAGNI: we should not build a full renderer unless there's no viable alternative

## Options Evaluated

### Option 1: Fork VSeeFace — REJECTED

VSeeFace is **closed-source** (Unity binary). The license explicitly prohibits modification of core files. There is no source code to fork. The open-source component (OpenSeeFace) is only the face tracker, not the renderer. The author (emilianavt) appears inactive — last release was February 2023.

**Verdict:** Technically and legally impossible. Not an option.

### Option 2: Wine/Proton — RECOMMENDED FOR DEV/TESTING

VSeeFace and Warudo both work under Wine/Proton on Linux with workarounds.

**VSeeFace under Wine:**
- Requires 64-bit Wine prefix, Arial font, `vcrun2015`, DLL deletions (`GPUManagementPlugin.dll`, `LeapCV5.dll`)
- Webcam tracking broken (irrelevant — we send VMC data, not use its tracker)
- Flags: `--background-color '#00FF00' --disable-wine-mode`
- Virtual camera and Spout2 do not work

**Warudo under Proton:**
- Reportedly the most polished option. Launch options: `PROTON_DISABLE_NVAPI=1 PROTON_USE_WOW64=1 %command%`
- Accepts VMC on port 39539 natively
- Active development (unlike VSeeFace)

**Trade-offs:**
- (+) VSeeFace/Warudo are mature, well-tested renderers with full VRM support
- (+) No code to write — just document the setup
- (-) Friction: Wine prefix setup, font installs, DLL cleanup
- (-) VSeeFace is stale; Warudo is commercial ($50 for Pro features)
- (-) Not a product strategy — just a development aid

### Option 3a: SnekStudio — VIABLE AS DOCUMENTED TARGET

Godot 4.6-based, GPL-3.0, Linux-native. Accepts VMC, renders VRM 0.0.

- (+) Native Linux, open source, active development (v0.1.5, Sep 2025)
- (-) Alpha quality, VRM 0.0 only (many models use 1.0+)
- (-) Not mature enough to depend on

**Verdict:** Document as a "works with" option. Do not build around it.

### Option 3b: Web-based renderer (three-vrm) — RECOMMENDED LONG-TERM

Build a VRM renderer in the existing React frontend using `@pixiv/three-vrm`.

- (+) Runs everywhere (Linux, Mac, Windows, mobile)
- (+) No Wine, no native deps, no third-party app dependency
- (+) Already have WebSocket backend — send blendshapes directly, skip VMC for own UI
- (+) three-vrm is mature (pixiv-maintained, MIT, active)
- (+) Full control over UX: show EEG debug overlays, parameter tuning UI
- (-) Effort: need to implement VRM loading, spring bone physics, blendshape application
- (-) Performance: WebGL vs native — adequate for single avatar, not for complex scenes

### Option 3c: Custom Godot renderer — REJECTED (YAGNI)

GodotXRVmcTracker + godot-vrm addons could create a native Linux VMC receiver.

- (+) Native performance, VRM 0.x and 1.x support
- (-) Introduces a new technology stack (GDScript/Godot) into the project
- (-) Higher effort than web approach for similar results
- (-) Maintaining a Godot app is a new product, not a feature

**Verdict:** Over-engineered for our needs. YAGNI.

## Recommendation

**Two-phase approach:**

### Phase 1: Wine/Proton for development (now)

Use Warudo under Proton (preferred) or VSeeFace under Wine as the VMC rendering target during development. Write a setup guide in `docs/` covering:

1. Warudo Proton setup (Steam, launch options)
2. VSeeFace Wine setup (prefix, fonts, DLLs, flags)
3. VMC port configuration (39539)
4. Verification: run muse-vtuber with `--synthetic --debug`, confirm blendshapes appear

This gets us a working visual feedback loop with zero code changes.

### Phase 2: Web renderer in React frontend (future plan)

Add a VRM avatar viewer to the existing React frontend. Architecture:

```
Python backend → WebSocket → React frontend → three-vrm renderer
                                              ↓
                                         VRM avatar with blendshapes
```

This eliminates the third-party app dependency entirely. The frontend already exists and connects to the backend via WebSocket. Adding three-vrm is a natural extension.

**Scope for Phase 2:**
- VRM 0.x model loading via `@pixiv/three-vrm`
- Blendshape application from WebSocket data (blink, clench, focus, relaxation)
- Head rotation from IMU quaternion data
- OBS-compatible transparent background (CSS `background: transparent` + OBS browser source)
- Simple UI: model selector, parameter sliders for tuning

**Not in scope (YAGNI):**
- VRM 1.x support (add when needed)
- Hand tracking
- Physics customization
- Scene editor

## Impact on Existing Plans

- **Plans 2-5 (VMC, VRChat OSC, VTube Studio):** Unchanged. These output protocols target third-party apps and remain valuable for users who prefer them.
- **Phase 1 (Wine setup guide):** New deliverable, documentation only, no code.
- **Phase 2 (web renderer):** New plan needed. Would become Plan 6 or a new tier.

## Decision Summary

| Question | Answer |
|----------|--------|
| Fork VSeeFace? | No — closed source, legally impossible |
| Use Wine? | Yes — for dev/testing, with documented setup |
| Pivot away? | Partially — keep VMC output for third-party apps, build own web renderer long-term |
| Build Godot renderer? | No — YAGNI, wrong stack |
| Build web renderer? | Yes — future plan, leverages existing frontend |
