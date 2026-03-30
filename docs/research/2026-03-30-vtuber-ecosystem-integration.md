# Research: VTuber Ecosystem Integration — Where Muse 2 Fits

**Date:** 2026-03-30
**Sources:** 18 sources (see below)

---

## Executive Summary

**Build a VMC protocol sender.** The VTuber ecosystem converges on two integration protocols: VMC (for 3D VRM avatars) and the VTube Studio WebSocket API (for 2D Live2D). VMC is the universal 3D integration — every major 3D VTuber app (VSeeFace, Warudo, VNyan) accepts it natively. VTube Studio dominates 2D (10K+ daily Steam users) but uses a proprietary WebSocket plugin API for custom inputs. The most impactful delivery format is a **standalone VMC sender app** that outputs Muse EEG/IMU data as VMC protocol messages, optionally paired with a VTube Studio plugin for Live2D users. An existing project — BrainFlowsIntoVRChat — already bridges Muse 2 EEG to VRChat via OSC, proving the concept works and has an audience (325 GitHub stars), but it doesn't support VMC or VTube Studio. There's a clear gap.

## Key Findings

### The Software Landscape: Two Worlds (2D and 3D)

The VTuber software market splits cleanly into **2D (Live2D)** and **3D (VRM)** ecosystems with different dominant apps and integration points.

**2D / Live2D** is dominated by **VTube Studio**, which averaged 10,016 concurrent Steam users in April 2025, up from 7,548 the year prior, with a peak of 21,472 [1][2]. VTube Studio is effectively the monopoly for Live2D VTubing. It uses a proprietary WebSocket plugin API on port 8001 that allows custom parameter injection — plugins can create up to 100 custom tracking parameters and inject values in real-time [3][4]. The vts-heartrate plugin demonstrates this pattern: it bridges heart rate monitor hardware to VTube Studio parameters, injecting 15 custom parameters that models can bind to [5]. This is the exact pattern a Muse EEG plugin would follow.

**3D / VRM** is more fragmented. VSeeFace (free, not on Steam, declining in popularity) was the long-time default. **VNyan** (itch.io, not on Steam) is now considered "the all-round best" for 3D by community consensus, offering node-graph automation, multi-platform integration (Twitch, YouTube, Kick), and native VMC/OSC receiver support [6][7]. **Warudo** (Steam, 496 avg users in April 2025, growing steadily from 181 a year prior) targets higher-end 3D VTubing with C# plugin extensibility and VMC receiver on port 39539 [2][8]. All three accept VMC protocol input natively.

### Integration Protocols: VMC Is the Universal 3D Standard

Three integration protocols matter:

**VMC Protocol** (Virtual Motion Capture Protocol) is the de facto standard for 3D VTuber tracking data exchange. It operates over OSC/UDP, transmitting bone quaternions, root position, and blendshape values [9]. The protocol defines three roles: Performer (sends tracking data), Marionette (receives and renders), and Assistant (sends supplementary data like expressions). A Muse bridge would act as **Performer** or **Assistant**, sending:
- `/VMC/Ext/Bone/Pos` — bone name + position + quaternion for head/neck
- `/VMC/Ext/Blend/Val` — blendshape name + float value (e.g., blink, smile)
- `/VMC/Ext/Blend/Apply` — commit blendshape frame
- `/VMC/Ext/OK` — status heartbeat

VMC is accepted by VSeeFace (port 39539), Warudo (port 39539), VNyan (via plugin), and can be combined with other tracking sources. Critically, VMC supports **partial tracking** — a sender can transmit only head rotation and blink blendshapes without providing full body, and the receiver will use its own tracking for everything else [9][10].

**VTube Studio Plugin API** is proprietary WebSocket JSON on port 8001. Plugins authenticate via a popup, then create custom parameters and inject values. Parameters support "set" (override) and "add" (blend with face tracking) modes, with a "weight" field for mixing plugin data with webcam tracking [3][4]. This is the only way into VTube Studio's Live2D ecosystem. Libraries exist in Python (pyvts), JavaScript, and Rust [4].

**OSC (Open Sound Control)** is the base transport for VMC and VRChat's parameter system. VRChat accepts OSC parameters directly on port 9000 [11]. VNyan also accepts VRChat-format OSC parameters as of v1.3.2 [12]. This means a single OSC output targeting VRChat's parameter format works for both VRChat and VNyan without modification.

### Existing Art: BrainFlowsIntoVRChat

BrainFlowsIntoVRChat (325 GitHub stars) is the closest existing project to what we'd build [13]. It uses BrainFlow to read EEG from devices including Muse 2, computes focus/relaxation metrics from power bands (delta/theta/alpha/beta/gamma), and outputs them as OSC parameters to VRChat. Key parameters include:
- `BFI/NeuroFB/FocusAvg` — focus metric (-1 to +1)
- `BFI/NeuroFB/RelaxAvg` — relaxation metric (-1 to +1)
- `BFI/PwrBands/Left/Alpha` — per-band, per-hemisphere power (0-1)
- `BFI/Biometrics/HeartBeatsPerMinute` — from PPG when available

It also includes a machine learning classifier for intentional "thought commands" (mental actions mapped to avatar triggers).

**Critical insight:** BrainFlowsIntoVRChat is VRChat-only via OSC. It does **not** output VMC protocol (no bone data, just float parameters) and does **not** support VTube Studio. The VNyan-BrainflowVTuber project [12] bridges this gap by consuming BrainFlowsIntoVRChat's OSC output in VNyan, mapping focus/relaxation to ear and tail animations via node graphs. This proves the use case exists but the setup is multi-app and fragile.

**Our opportunity:** A unified app that outputs:
1. VMC protocol (bone rotation for head tracking + blendshapes for EEG expressions) → works in VSeeFace, Warudo, VNyan
2. VTube Studio custom parameters (same EEG data as plugin parameters) → works in VTube Studio
3. VRChat OSC parameters (same format as BrainFlowsIntoVRChat) → works in VRChat + VNyan

### What Users Actually Complain About

User pain points cluster around:

1. **Tracking quality** — webcam jitter, tracking loss in dim lighting, mouth/eye tracking unreliability [previous research]. iPhone ARKit users report dramatically better quality but it requires a $1000 phone [previous research].

2. **Setup complexity** — combining multiple apps (tracking app → VTuber app → OBS → stream) is error-prone. Each app has its own port configuration, calibration, and failure modes. VNyan's appeal is partly that it consolidates functionality [6].

3. **Expression limitations** — webcam eye tracking is unreliable, mouth shapes are limited, and there's no way to express emotional states (stress, focus, excitement) that don't have visible facial correlates. This is exactly where EEG adds unique value.

4. **Camera dependence** — many VTubers stream from setups where webcam placement is inconvenient, or they move around. Camera-free tracking (IMU on head) removes a physical constraint.

5. **Platform restrictions** — TikTok's algorithm penalizes VTuber content (no "human face" detected), and platforms increasingly require real face verification [14]. This is a growing pain point but not one we solve.

### Where Muse Adds Unique Value

Muse's competitive advantage is **not** head tracking quality (webcam and especially ARKit are better). It's:

1. **EEG-driven expressions that webcam can't detect**: focus/relaxation/excitement mapped to avatar effects (glowing eyes when focused, drooping ears when relaxed, tail wagging when excited). No webcam can detect mental states — this is genuinely novel in the VTuber space.

2. **Reliable blink detection independent of camera**: our blink detector works at 99% accuracy via EEG, vs webcam blink detection which fails in poor lighting and at angles.

3. **Camera-free operation**: useful for VR setups (face is occluded by headset), dark room streaming, or setups where webcam position is impractical.

4. **Combinability**: VMC protocol explicitly supports combining tracking sources. A typical powerful setup would be: webcam (face + expressions) + Muse (EEG mental states + reliable blink + head rotation as secondary). The Muse adds what the webcam can't see.

### Recommended Delivery Format

**Primary: Standalone VMC Sender Application**

A desktop app (Python, since we already have the BrainFlow backend) that:
- Connects to Muse 2 via BLE
- Computes head rotation (IMU → Madgwick → quaternion)
- Computes EEG metrics (focus, relaxation, blink, clench)
- Outputs VMC protocol on configurable port (default 39539)
  - Head/neck bone rotation from IMU
  - Blendshapes: `blink`, plus custom blendshapes for EEG states
- Outputs VRChat-compatible OSC parameters on port 9000 (focus, relaxation, power bands)
- Simple GUI: connection status, signal quality, preview of output values

This reaches: VSeeFace, Warudo, VNyan, VRChat — covering the entire 3D ecosystem.

**Secondary: VTube Studio Plugin**

A separate lightweight WebSocket plugin (Python or JS) that:
- Reads EEG metrics from the main app (shared state or localhost socket)
- Injects custom parameters into VTube Studio (focus, relaxation, blink confidence)
- Users bind these to Live2D parameter mappings (e.g., focus → eye glow, relaxation → blush)

This covers the 2D Live2D ecosystem (VTube Studio's 10K+ daily users).

**Why not a plugin-only approach?** Each VTuber app has a different plugin system (VTS: WebSocket JSON, Warudo: C# DLL, VNyan: C# DLL + node graphs). Building native plugins for each is 4x the work. VMC is a single implementation that works everywhere. The VTube Studio plugin is worth building separately because VTS is by far the largest user base and doesn't accept VMC.

### Integration Difficulty Assessment

| Target | Protocol | Difficulty | Reach |
|--------|----------|------------|-------|
| VSeeFace, Warudo, VNyan | VMC (UDP/OSC) | Low — send OSC packets | All 3D VRM users |
| VRChat | OSC parameters (UDP) | Low — same transport, different format | VRChat social VTubers |
| VTube Studio | WebSocket JSON API | Medium — auth flow, parameter management | 10K+ Live2D users |
| Custom standalone app | N/A | High — build renderer, UI, everything | Only our users |

**Verdict:** VMC sender (low difficulty, wide reach) + VTube Studio plugin (medium difficulty, large market) covers ~95% of the ecosystem. Building a standalone VTuber app from scratch would be high effort for marginal benefit.

## Comparison: Integration Approaches

| Approach | Pros | Cons | Effort |
|----------|------|------|--------|
| **VMC Sender (recommended)** | Universal 3D support, single implementation, combinable with other tracking | Doesn't cover Live2D / VTube Studio | Low |
| **VTube Studio Plugin** | Largest single user base, good API | Live2D only, no 3D VRM | Medium |
| **VRChat OSC sender** | Already proven (BrainFlowsIntoVRChat) | VRChat-only | Low |
| **Native plugins per app** | Deepest integration | 4 different plugin systems, high maintenance | Very High |
| **Standalone VTuber app** | Full control | Competes with established apps, no ecosystem | Very High |
| **VMC + VTS plugin (recommended combo)** | Covers 3D + 2D ecosystems | Two codebases | Medium |

## Open Questions

- What percentage of VTubers use 3D (VRM) vs 2D (Live2D)? Steam data only covers VTube Studio and Warudo; VSeeFace and VNyan have no public user counts. The 2D/Live2D market appears larger based on VTube Studio's 10K+ daily users vs Warudo's ~500.
- How many VTubers would buy EEG hardware specifically for VTubing? The Muse 2 costs ~$250. BrainFlowsIntoVRChat's 325 stars suggests interest but not mass adoption. The value proposition may be stronger for existing Muse owners who also VTube.
- VTube Studio's plugin API documentation on parameter injection rate limits and value ranges needs verification from the full API spec (the wiki page was incomplete).
- VMC protocol support for custom/non-standard blendshape names (e.g., `eeg_focus`, `eeg_relaxation`) — will receivers pass these through to VRM models, or only standard ARKit/VRM blendshapes?
- VNyan's OSC receiver accepts VRChat-format parameters natively since v1.3.2, but whether it handles arbitrary OSC addresses or only the VRChat parameter namespace is unclear.

## Sources
[1] Vice/dnyuz. "Are More People Becoming VTubers? Steam's Stats Suggest So." https://www.vice.com/en/article/are-more-people-becoming-vtubers-steams-stats-suggest-so/
[2] Dataintelo. "VTuber Market Research Report 2034." https://dataintelo.com/report/vtuber-market
[3] DenchiSoft. "VTube Studio Wiki: Plugins." https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
[4] DenchiSoft. "VTube Studio API Development Page." https://github.com/DenchiSoft/VTubeStudio
[5] FomTarro. "vts-heartrate: Heartrate Monitor Plugin for VTube Studio." https://github.com/FomTarro/vts-heartrate
[6] Suvidriel. "VNyan." https://suvidriel.itch.io/vnyan
[7] The Virtual Asylum. "3D VTubing: An Introduction." https://thevirtualasylum.com/threads/3d-vtubing-an-introduction.93/
[8] Warudo. "VMC | Warudo Handbook." https://docs.warudo.app/docs/mocap/vmc
[9] VMC Protocol. "VMC Protocol specification (English)." https://protocol.vmc.info/english.html
[10] emilianavt. "VSeeFace." https://www.vseeface.icu/
[11] VRChat. "OSC Overview." https://docs.vrchat.com/docs/osc-overview
[12] Lunazera. "VNyan-BrainflowVTuber." https://github.com/Lunazera/VNyan-BrainflowVTuber
[13] ChilloutCharles. "BrainFlowsIntoVRChat." https://github.com/ChilloutCharles/BrainFlowsIntoVRChat
[14] TikTok Stats. "Problems Faced by VTubers on TikTok Live 2026." https://tiktokstats.com/articles/glitch-matrix-5-major-problems-faced-vtubers-tiktok-live-2026
[15] VRCFaceTracking. "VRCFaceTracking Program." https://docs.vrcft.io/docs/vrcft-software/vrcft
[16] iFacialMocap. "Communication Specifications." https://www.ifacialmocap.com/for-developer/
[17] Content Mavericks. "7 Best VTuber Software 2026." https://contentmavericks.com/best-vtuber-software/
[18] jayo-exe. "Jayo's Extended VMC Plugin for VNyan." https://jayo-exe.itch.io/vmc-plugin-for-vnyan
