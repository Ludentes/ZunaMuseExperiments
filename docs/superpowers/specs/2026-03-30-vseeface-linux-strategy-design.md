# VTuber Renderer Strategy: Warudo + Web Renderer

**Date:** 2026-03-30
**Status:** Accepted
**Context:** The muse-vtuber bridge sends VMC protocol data. We need a rendering target on Linux for development and a strategy for users.

## Problem

Our development platform is Linux. We need a VMC-receiving avatar renderer for testing and a recommendation for users.

## Market Reality (2026 Data)

| Software | Avg Concurrent | YoY Trend | Type |
|----------|---------------|-----------|------|
| VTube Studio | 10,633 | +25% | 2D (Live2D) — dominates |
| Warudo | 860 | +225% | 3D (VRM) — fastest growing |
| Animaze | 262 | -30% | 3D — dying |

- **2D (Live2D) is ~59% of the market.** VTube Studio owns it.
- **3D (VRM) is ~32%, growing at 11% CAGR.** Warudo is the clear successor to VSeeFace.
- VSeeFace last release Feb 2025, users actively migrating to Warudo/VNyan.
- **Linux VTubers are a tiny niche** (~7 GitHub stars on "Awesome VTubing on Linux"). Most use Proton.
- No web-based VMC receiver exists. Nobody asks for one. Uncontested but tiny market.

## Options Evaluated

### Option 1: Fork VSeeFace — REJECTED

Closed-source Unity binary. License prohibits modification. No source code. Not an option.

### Option 2: Warudo via Proton — RECOMMENDED FOR DEV/TESTING

- **Free on Steam** for indie VTubers (Pro is enterprise-only pricing)
- **Full VMC receiver** on port 39539
- **Works under GE-Proton** with `PROTON_DISABLE_NVAPI=1 PROTON_USE_WOW64=1 %command%`
- 93% positive Steam reviews, 860 concurrent users (+225% YoY)
- Beats VSeeFace on: audio+mocap mouth tracking, hand tracking, 500+ idle animations, node-based scripting
- **This is the primary target app for our VMC output.** The market has moved from VSeeFace to Warudo.

### Option 3: VSeeFace via Wine — DEPRECATED FALLBACK

Still works with workarounds (64-bit Wine prefix, fonts, DLL deletions) but VSeeFace is stale. Only document as fallback for users who already have it.

### Option 4: SnekStudio (Linux-native) — DOCUMENT ONLY

Godot-based, GPL-3.0, accepts VMC. But alpha quality, VRM 0.0 only. Mention in docs, don't build around it.

### Option 5: Web renderer (three-vrm) — LOW PRIORITY

- No existing demand (nobody asks for web VMC receivers)
- Technical barrier: browsers can't receive UDP, need WebSocket bridge
- Incremental cost to make our planned frontend renderer VMC-generic is small
- But VTube Studio plugin (Plan 5) reaches 12x more users — do that first

### Option 6: Custom Godot renderer — REJECTED (YAGNI)

Wrong stack, over-engineered.

## Decision

### Now: Warudo under Proton

Install Warudo via Steam with GE-Proton. Use as primary VMC rendering target for development and testing. Document setup.

### For users: recommend Warudo (Windows) or Warudo (Proton on Linux)

Warudo is free, actively developed, and the market is moving there. It's what 3D VTubers actually use in 2026.

### Deprioritize: own web renderer

The Linux VTuber market is too small to justify building a web renderer now. When/if we build one for our frontend, making it VMC-generic is cheap — but it shouldn't jump ahead of VTube Studio support (Plan 5), which reaches the largest user base.

## Priority Stack

| Priority | What | Reaches |
|----------|------|---------|
| **P0** | Warudo as primary VMC target | 860+ concurrent 3D VRM users |
| **P1** | VTube Studio plugin (Plan 5) | 10K+ Live2D users |
| **P2** | VRChat OSC output (Plan 4) | VRChat social VTubers |
| **P3** | Own web renderer (someday) | Linux users, our own frontend |

## Impact on Existing Plans

- **Plans 2-5:** Unchanged. VMC, VRChat OSC, VTube Studio outputs all remain valuable.
- **Testing workflow:** Use Warudo under Proton to visually verify VMC blendshapes.
- **Documentation:** Write Warudo setup guide for Linux dev and Windows users.
