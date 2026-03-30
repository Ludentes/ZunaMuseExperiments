# Muse VTuber Bridge — Implementation Plans

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each plan task-by-task.

**Goal:** Standalone Python app bridging BCI hardware (Muse 2) to VTuber avatar software via VMC, VRChat OSC, and VTube Studio.

**Ship order** (each plan is independently shippable):

| # | Plan | Tier | What it delivers | Depends on |
|---|------|------|-----------------|------------|
| 0 | [Repo Setup](00-repo-setup.md) | — | Project scaffold, pipeline framework, BrainFlow source | — |
| 1 | [EEG Addon](01-eeg-addon.md) | 3 | Blink/clench/focus/relax → VMC blendshapes | 0 |
| 2 | [Head Tracking](02-head-tracking.md) | 1 | IMU head pose → VMC bone rotation | 0 |
| 3 | [Fusion](03-fusion.md) | 2 | OpenSeeFace + IMU complementary filter | 0, 2 |
| 4 | [VRChat OSC](04-vrchat-osc.md) | — | BFiVRC-compatible OSC parameters | 0, 1 |
| 5 | [VTube Studio](05-vtube-studio.md) | — | WebSocket plugin for Live2D | 0, 1 |

**After Plan 0 + 1:** User can connect Muse → see EEG blinks in VSeeFace (unique value, fastest to ship).

**After Plan 2:** Camera-free head tracking added.

**After Plan 3:** Fusion mode — best tracking quality.

**After Plans 4-5:** Full ecosystem coverage (VRChat, VTube Studio).

## Prerequisites & Testing

See [Plan 0](00-repo-setup.md) for complete setup instructions:
- **Automated tests**: No hardware needed — BrainFlow synthetic board + synthetic EEG signals
- **Manual testing by tier**: Muse 2, VSeeFace, OpenSeeFace, VTube Studio
- **Port reference**: VMC (39539), VRChat OSC (9000), VTS (8001), OpenSeeFace (11573)

## Design Spec

See `docs/superpowers/specs/2026-03-30-muse-vtuber-bridge-design.md` for full architecture.

## Source Code to Adapt

From `zyphraexps/`:
- `backend/pipeline/base.py` — Stage/Pipeline pattern
- `backend/pipeline/types.py` — PipelineFrame, Event, Cadence
- `backend/pipeline/stages/detectors.py` — BlinkDetector (~770 lines), ClenchDetector, SpeechDetector
- `backend/pipeline/stages/features.py` — BandPowerExtractor
- `backend/acquisition.py` — BrainFlow wrapper
- `frontend/src/lib/headPose.ts` — HeadPoseEstimator (port to Python)
- `frontend/src/lib/oneEuroFilter.ts` — OneEuroQuaternionFilter (port to Python)
