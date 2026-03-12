# Museum Demo Roadmap — Brain Remote Control

**Date:** 2026-03-11
**Status:** Active

## Overview

Guide wears Muse 2 during museum tours, controls room lights and kiosk content hands-free using brain signals. Audience sees brain activity visualized on kiosk, lights responding to mental state in real time.

Design doc: `docs/plans/2026-03-11-brain-remote-control-design.md`

---

## Phase 0: Foundation (done)

- [x] Muse 2 EEG acquisition + BrainFlow pipeline
- [x] BlinkDetector v5 (F1=0.95, double/triple blink)
- [x] Band power extraction + concentration score (theta/beta)
- [x] ZUNA 23ch superresolution for heatmap
- [x] 3D brain heatmap frontend
- [x] WebSocket streaming to browser

## Phase 1: Signal Readiness (~2-3 days)

Core signals that all downstream controls depend on.

1. **Eyes-closed detector** — validate alpha blocking on existing recordings, implement as pipeline stage
2. **Concentration score tuning** — verify theta/beta mapping produces usable 0→1 range in real-time (not just batch)
3. **Signal quality gate** — headband state machine (ready/fitting/off), fit_status logic

## Phase 2: Home Assistant Integration (~3-4 days)

The core bridge that connects brain signals to the physical world.

4. **HABridgeStage** — persistent HA WebSocket + MQTT client as pipeline Stage
   - Blink handler: double→Umka next, triple→light toggle
   - Concentration handler: continuous RGB color mapping
   - Eyes-closed handler: dramatic room dimming
5. **Command safety** — debounce timers, confidence gating, signal quality suspension
6. **Config** — HA token, entity IDs, MQTT broker, Umka kiosk slug (env/config file)

## Phase 3: Kiosk & Polish (~2 days)

Make it presentable for walk-up museum use.

7. **Kiosk display mode** — strip dashboard to show-only (hide recording controls, add connection status bar with headband state colors)
8. **Umka URL loading** — minor change so kiosk opens `http://backend:3001` in browse mode
9. **Battery indicator** — BrainFlow C++ patch (~30 lines) + frontend top bar

## Phase 4: Validation (~2-3 days)

Live testing with real hardware in the target environment.

10. **End-to-end dry run** — Muse on head, HA lights responding, Umka kiosk showing heatmap
11. **Latency profiling** — blink→light toggle <500ms, eyes-closed→dim <2s
12. **Failure mode testing** — headband removal/poor fit, WiFi drop, HA disconnect, MQTT down
13. **Manual verification guide** — step-by-step runbook saved to `docs/`

## Phase 5: Experiments (post-v1, deferred)

Explore additional control channels. Won't block the demo.

14. **HR reliability experiment** — can Muse PPG drive pulsing light?
15. **Head gesture experiment** — nod/shake from IMU for alternative commands

---

## Critical Path

`Eyes-closed detector → HABridgeStage → Command safety → End-to-end dry run`

## Dependencies

- Home Assistant instance with RGB light + long-lived access token
- Mosquitto MQTT broker for Umka
- BrainFlow source + CMake (Phase 3 battery patch only)

## Not Building (v1)

- No two-player support
- No guide training sequence
- No new Umka kiosk mode (just a URL)
- No mobile app
- No HR or head gesture controls (experiments first)
