# Research: Is There Community Demand for a Web-Based VMC Receiver/Renderer?

**Date:** 2026-03-30
**Verdict:** Weak direct demand, but a real gap exists at the intersection of Linux VTubing + external tracking. The opportunity is niche but uncontested.

---

## 1. "VMC Web" / "VMC Browser" / "VMC Receiver" — Are People Asking for This?

### Short Answer: Almost nobody is explicitly asking for a browser-based VMC receiver.

**GitHub repos implementing VMC receivers:**
- All existing VMC receivers are **desktop apps** (Windows-first): VSeeFace, Warudo, VNyan, VirtualMotionCapture
- **VMC-Websocket-OBS** (7 stars) — uses VMC protocol to control OBS via WebSocket, but does NOT render avatars in browser; it's a C# Windows executable that bridges VMC -> OBS scene switching ([GitHub](https://github.com/gpsnmeajp/VMC-Websocket-OBS))
- **VRMPlaybackClient** (8 stars) — captures/plays back VMC motion data, Windows-only Unity app ([GitHub](https://github.com/kevinjycui/VRMPlaybackClient))
- **HEVA Portal** — VMC protocol implementation for Blender, not web ([GitHub](https://github.com/scaledteam/HEVA_Portal))
- **Inochi2D/vmc-d** — VMC protocol library in D language, used by Inochi2D ([GitHub](https://github.com/Inochi2D/vmc-d))

**No web-based VMC receiver exists.** Zero GitHub repos combine three-vrm + VMC/OSC input from an external source via WebSocket.

**Forum/Reddit posts asking for browser VMC viewer:** None found explicitly. The concept doesn't seem to occur to people — they assume VMC = desktop app.

**VRChat community OSC/WebSocket request:** Issue #95 on vrchat-community/osc (9 upvotes) asks for WebSocket interface for OSC events, motivated by wanting to build server-side applications without local software. This is adjacent but not the same use case. ([GitHub Issue](https://github.com/vrchat-community/osc/issues/95))

### Conclusion: There is no explicit demand. People don't ask for what they can't imagine existing.

---

## 2. "VTuber Linux" Problems — How Big Is This Pain Point?

### Short Answer: Moderate pain, dozens of active discussions, 2+ community guides maintained. Not thousands of posts, but a persistent vocal minority.

**Evidence of pain:**
- **2 actively maintained community guides** on Codeberg: [KyloNeko's guide](https://codeberg.org/KyloNeko/Linux-Guide-to-Vtubing) and [RogueRen's guide](https://codeberg.org/RogueRen/Linux-Guide-to-Vtubing)
- **A dedicated GitHub org** with a guide site: [vtubing-on-linux.github.io](https://vtubing-on-linux.github.io/linux-vtubing-guide/)
- **Blog post** "Cold Start VTubing in Linux for 2026" describes reaching baseline as "surprisingly easy" but then hitting a cascade of compatibility issues ([source](https://letsbuildroboticswithshadow8472.com/index.php/2025/12/29/cold-start-vtubing-in-linux-for-2026/))
- **Xe Iaso's blog** (2021, but frequently referenced): VTubing on Linux is "baroque and complicated", required "several rounds of nuking ~/.wine" ([source](https://xeiaso.net/blog/vtubing-linux-2021-01-15/))
- **VTube Studio Steam discussion** on Linux compatibility: sustained thread from 2021-2025 with multiple "+1" comments. Developer stated: "Certainly not on release. Many of the libraries used in VTS do not support Linux natively." ([Steam thread](https://steamcommunity.com/app/1325860/discussions/0/3118147979136347291/))
- **Linux Mint Forums** thread on VTube Studio + VBridger + OBS ([forum](https://forums.linuxmint.com/viewtopic.php?t=435562))

**What works natively on Linux:**
- OBS Studio (native)
- OpenSeeFace (Python, native)
- SlimeVR server (Flatpak on Linux, native)
- Inochi2D (native, but going on indefinite hiatus due to funding)
- OpenVT (Godot-based, native, early stage, 2D only) ([80.lv article](https://80.lv/articles/vtube-studio-alternative-designed-for-linux-users))

**What requires Wine/Proton:**
- VTube Studio — starts under Proton but webcam detection, resolution, and PulseAudio voice don't work properly
- VSeeFace — runs under Wine64 but built-in tracking is broken, needs external OpenSeeFace
- Warudo — works with GE-Proton-10-26 + specific launch flags (`PROTON_DISABLE_NVAPI=1 PROTON_USE_WOW64=1`)
- VNyan — Windows-only, no Proton reports found
- Live2D Cubism — Wine

**What's completely broken on Linux:**
- Veadotube mini (Linux package doesn't work, need Windows version under Wine)
- VTube Studio webcam detection + voice recognition
- Wayland global hotkeys for all VTuber apps
- LeapMotion hand tracking under Wine

**Scale of the problem:** Dozens of posts and guides, not thousands. The Steam Desktop Linux user share is ~2% (steady). VTubing is niche within that. Estimated affected user base: low thousands globally who actively want to VTube on Linux.

---

## 3. three-vrm Ecosystem — What Exists for Web-Based VRM Avatar Rendering?

### Short Answer: three-vrm is mature and well-maintained. Several web VTuber apps exist, but ALL use built-in webcam tracking only. None accept external tracking input.

**three-vrm (pixiv/three-vrm):**
- 1,844 stars, 164 forks, TypeScript, actively maintained (updated 2026-03-30)
- Official VRM rendering library for Three.js by pixiv (VRoid Hub creators)
- Supports VRM 0.x and 1.0, springbones, blendshapes, bone manipulation
- Production-proven: powers VRoid Hub, Kalidoface, and many web VTuber apps
- ([GitHub](https://github.com/pixiv/three-vrm))

**Existing web VTuber apps using three-vrm:**

| Project | Stars | Tracking Input | External Input? | Status |
|---------|-------|---------------|-----------------|--------|
| Kalidoface 3D | 517 | MediaPipe webcam | No | Dormant (37 commits, 1 contributor) |
| Kalidokit | 5,612 | MediaPipe solver lib | No (library only) | Active |
| VRM Studio | 11 | MediaPipe webcam | No (roadmap: OSC) | Early, 1 contributor |
| VU-VRM (Automattic) | 100 | Microphone only | No | Modest activity |
| human-three-vrm | 96 | Human.js webcam | No | Low activity |

Sources: [Kalidoface 3D](https://github.com/yeemachine/kalidoface-3d), [Kalidokit](https://github.com/yeemachine/kalidokit), [VRM Studio](https://github.com/vucinatim/vrm-studio), [VU-VRM](https://github.com/Automattic/VU-VRM), [human-three-vrm](https://github.com/vladmandic/human-three-vrm)

**Key finding: NONE of these accept external tracking data (VMC, OSC, WebSocket).** They all do their own tracking in-browser via webcam + MediaPipe/TensorFlow.js.

**Kalidoface 3D specifically:** Built-in MediaPipe only. No plugin system, no external data input, no VMC/OSC. Dormant project with 37 total commits.

---

## 4. The "VMC Web App" Concept — Technical Feasibility and Broader Utility

### The Core Technical Problem: Browsers Cannot Receive UDP

VMC protocol runs over OSC/UDP. Browsers have no UDP socket API. This is a fundamental barrier.

**Bridge patterns that exist:**

1. **osc-js BridgePlugin** (279 stars, 535 dependents on npm) — Node.js relay: UDP <-> WebSocket. The standard solution in the music/art world for getting OSC data into browsers. Architecture: `OSC UDP sender -> Node.js bridge (port 8080 WS + configurable UDP) -> Browser WebSocket client`. ([GitHub](https://github.com/adzialocha/osc-js), [npm](https://www.npmjs.com/package/osc-js))

2. **osc.js (colinbdclark)** — Another OSC library supporting both Node.js and browser, with WebSocket transport. ([GitHub](https://github.com/colinbdclark/osc.js/))

3. **@petitatelier/osc-bridge** — Bi-directional OSC bridge between WebSocket and UDP. ([npm](https://www.npmjs.com/package/@petitatelier/osc-bridge))

4. **Custom WebSocket relay** — The simplest pattern: Python/Node server listens on UDP, parses VMC OSC messages, forwards as JSON over WebSocket to browser. This is what we'd build.

**How hard to build?**
- VMC -> WebSocket relay: ~100-200 lines of Python (python-osc + websockets)
- Browser renderer: three-vrm handles VRM loading + bone/blendshape animation. The "hard part" (VRM rendering, springbones, blendshape application) is solved.
- Integration: Parse WebSocket JSON messages, apply bone quaternions via `vrm.humanoid.getRawBoneNode('head').quaternion.set(...)`, apply blendshapes via `vrm.expressionManager.setValue('blink', value)`
- **Estimated effort: 2-3 days for a working prototype**, given three-vrm maturity

**Would this be useful beyond our Muse project?**

Potentially, for:
- **Linux VTubers** who can't run VSeeFace/Warudo natively — a browser-based renderer solves the platform problem entirely
- **SlimeVR users on Linux** — SlimeVR outputs VMC protocol, and currently they need Wine'd VSeeFace to render
- **Multi-source tracking setups** — people combining iPhone face + SlimeVR body + other inputs could use a web renderer as an alternative to Warudo
- **VR users** who want a lightweight avatar display without a full Unity app
- **Embedded/kiosk** VTuber displays (events, conventions)

But realistically, the audience for this is small. Most VTubers who use VMC already have a working Windows setup with VSeeFace or Warudo.

---

## 5. Competing Approaches — What Do External-Tracking VTubers Use?

### The Dominant Stack (Windows):
- **Face tracking:** iPhone + iFacialMocap/VTube Studio ARKit -> VMC/direct
- **Body tracking:** SlimeVR (open source IMU trackers, ~$200) -> VMC -> VSeeFace/Warudo/VNyan
- **Full mocap:** Rokoko suit ($1500-2500) -> VMC -> Warudo
- **Renderer:** VSeeFace (free), Warudo (paid, growing), VNyan (itch.io)

### On Linux:
- **Face tracking:** OpenSeeFace (Python, native) -> custom protocol to VSeeFace/VTube Studio under Wine
- **Body tracking:** SlimeVR server (has Linux Flatpak) -> VMC -> ??? (no good native renderer)
- **The gap:** There is no native Linux 3D VRM renderer that accepts VMC input. The options are:
  - VSeeFace under Wine (tracking broken, VMC receive works)
  - Warudo under GE-Proton (works but heavy, requires specific flags)
  - Nothing else

### The Actual Pain:
The biggest pain for Linux VTubers with external tracking hardware is: **SlimeVR/mocap suit -> VMC -> [no native renderer]**. They have tracking data in VMC format and nowhere native to send it. A web-based VMC receiver would directly solve this.

---

## Summary Assessment

| Question | Answer |
|----------|--------|
| Are people explicitly asking for a web VMC receiver? | **No** — zero explicit requests found |
| Does the gap exist? | **Yes** — no web-based tool accepts VMC input for VRM rendering |
| Is the Linux VTuber pain real? | **Yes** — moderate, persistent, documented across multiple guides/forums |
| Is three-vrm ready for this? | **Yes** — 1.8K stars, actively maintained, all rendering primitives exist |
| Is the bridge pattern proven? | **Yes** — osc-js (279 stars) and others have established UDP-to-WebSocket relay |
| How hard to build? | **Low** — 2-3 days for MVP given existing libraries |
| Market size for standalone product | **Small** — low thousands of Linux VTubers globally, subset use external tracking |
| Strategic value for our Muse project | **High** — we need a renderer anyway; making it generic costs little extra |

### Bottom Line

There is no explicit demand because nobody thinks to ask for it — the VTuber ecosystem assumes Windows desktop apps. But the gap is real: Linux VTubers with external tracking (SlimeVR, mocap suits, or... a Muse headband) have nowhere native to render their avatar. A web-based VMC receiver built on three-vrm would be:

1. **First of its kind** — literally no competition
2. **Trivially distributable** — just a URL, no install, works on any OS
3. **Low incremental cost** — we need a renderer for Muse anyway
4. **Good marketing** — "the first web-based VMC-compatible VTuber avatar renderer" is a compelling pitch for the Linux VTuber community, even if small

The risk is building for a small audience. The mitigation is that it also serves our core Muse use case regardless.

---

## Sources

- [pixiv/three-vrm](https://github.com/pixiv/three-vrm) — 1,844 stars, VRM on Three.js
- [yeemachine/kalidoface-3d](https://github.com/yeemachine/kalidoface-3d) — 517 stars, web VRM tracker (MediaPipe only)
- [yeemachine/kalidokit](https://github.com/yeemachine/kalidokit) — 5,612 stars, blendshape solver library
- [Automattic/VU-VRM](https://github.com/Automattic/VU-VRM) — 100 stars, mic-only VRM avatar
- [vucinatim/vrm-studio](https://github.com/vucinatim/vrm-studio) — 11 stars, browser VRM studio (MediaPipe)
- [adzialocha/osc-js](https://github.com/adzialocha/osc-js) — 279 stars, OSC with WebSocket bridge
- [gpsnmeajp/VMC-Websocket-OBS](https://github.com/gpsnmeajp/VMC-Websocket-OBS) — 7 stars, VMC-to-OBS bridge
- [VMC Protocol specification](https://protocol.vmc.info/english.html)
- [VRChat OSC WebSocket issue #95](https://github.com/vrchat-community/osc/issues/95) — 9 upvotes
- [Linux VTubing Guide (Codeberg)](https://codeberg.org/KyloNeko/Linux-Guide-to-Vtubing)
- [Linux VTubing Guide (GitHub)](https://vtubing-on-linux.github.io/linux-vtubing-guide/)
- [Cold Start VTubing in Linux for 2026](https://letsbuildroboticswithshadow8472.com/index.php/2025/12/29/cold-start-vtubing-in-linux-for-2026/)
- [VTubing on Linux (Xe Iaso)](https://xeiaso.net/blog/vtubing-linux-2021-01-15/)
- [VTube Studio Linux compatibility (Steam)](https://steamcommunity.com/app/1325860/discussions/0/3118147979136347291/)
- [VTube Studio Linux wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Running-VTS-on-Linux)
- [OpenVT (80.lv article)](https://80.lv/articles/vtube-studio-alternative-designed-for-linux-users)
- [Inochi2D](https://inochi2d.com/) — 1,656 stars, going on hiatus
- [SlimeVR](https://slimevr.dev/) — open source body tracking, Linux Flatpak
- [vladmandic/human-three-vrm](https://github.com/vladmandic/human-three-vrm) — 96 stars
- [OSC-WebSocket bridge pattern (Medium)](https://contra.medium.com/transmitting-osc-data-via-websocket-43fcc8bfade7)
