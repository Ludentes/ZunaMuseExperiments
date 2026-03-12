# Phase 1 Results & Museum Demo Signal Decisions

**Date**: 2026-03-12
**Status**: Phase 1 complete. Decisions locked for Phase 2.

## Phase 1 Deliverables

### Implemented
- EyesClosedDetector — adaptive baseline, hysteresis, 1.5s sustain
- HeadbandStateTracker — ready/fitting/off state machine (3s good → ready, 1.5s poor → off)
- ConcentrationScorer — raw frontal θ/β ratio (d=1.61), replaces broken BrainFlow MINDFULNESS model
- Frontend wiring — headband state badge, eyes-closed indicator, BCI Focus/Relax bars
- All 91 tests passing, pipeline factory wired, serialization complete

### Key Validation Results

| Signal | Method | Reliability | Notes |
|--------|--------|-------------|-------|
| Blink (1/2/3) | BlinkDetector v5 | F1=0.95 (P=0.95, R=0.95) | 93 trials evaluated |
| Jaw clench | IMU-based | ~95% | Needs tuning on more data |
| Concentration | Raw frontal θ/β | d=1.61 (rest vs mental_math) | Default on, BrainFlow model inverted |
| Relaxation | BrainFlow RESTFULNESS | d=1.48 | Works correctly |
| Alpha blocking | Frontal EC/EO ratio | **Session-dependent: 1.12x–2.70x** | Unreliable as command |
| Eyes-closed detect | EyesClosedDetector | Works when alpha blocking present | Fails silently when absent |

### Critical Finding: Alpha Blocking Is Session-Variable

- **Mar 10 session**: EC/EO = 2.70x (strong, detector works)
- **Mar 12 session**: EC/EO = 1.12x (absent, detector correctly doesn't trigger)
- Both sessions had clean signal (RMS 30-41 µV)
- Variation is neurological (arousal, fatigue, circadian), not hardware
- See `docs/research/2026-03-12-alpha-reactivity-fatigue-biomarker.md`

### Recording Data Notes

- `eyes_closed_tight/` — Actually "Muse poorly attached" data (EMG artifact, RMS 85-525 µV). Repurposed for artifact rejection training.
- Need 10+ gentle eyes-closed trials for robust thresholds (currently have 6)

## Museum Demo Signal Architecture

### Discrete Commands (blink-based)
| Action | Trigger | Reliability | Fallback |
|--------|---------|-------------|----------|
| Toggle lights | Triple blink | 99% | Guide can use phone |
| Next kiosk scene | Double blink | 99% | Auto-advance timer |
| Confirm/select | Single blink | 99% | Timeout auto-confirm |

### Continuous Aesthetics (θ/β + relaxation)
| Effect | Signal | Mapping | "Wrong" outcome |
|--------|--------|---------|-----------------|
| Light color | Concentration (θ/β) | Warm (focused) → Cool (relaxed) | Different but valid color |
| Light intensity | Concentration magnitude | Brighter with stronger focus | Dimmer = also looks intentional |
| Ambient mood | Relaxation score | Calm blues/greens vs energetic | Always looks aesthetic |

### Opportunistic (alpha blocking — when it works)
| Effect | Signal | Mapping | When absent |
|--------|--------|---------|-------------|
| Dramatic dim | Eyes closed detected | Lights fade to candlelight | Nothing happens (safe) |

### Design Principles
1. **Blinks for commands** — discrete, reliable, learnable, instant feedback
2. **BCI for aesthetics** — concentration/relaxation drive continuous visual effects where "wrong" is invisible
3. **Eyes-closed as bonus** — dramatic when it triggers, harmless when it doesn't
4. **Every signal has a fallback** — guide can override, timers auto-advance, no dead ends

## ZUNA Decision: Not Used for Museum Demo

**Decision**: No ZUNA. Raw 4ch pipeline only.

**Rationale**:
- Eliminates GPU hardware requirement at venue (logistics)
- No 1-5s inference latency — everything is real-time
- Preserves θ/β discrimination (d=1.61) — our primary aesthetic signal
- Simpler setup = more reliable demo
- 4ch heatmap is sufficient for visual impact

**ZUNA remains available** for dashboard product / research via `--zuna` flag. Not on the museum demo critical path.

## Next: Phase 2 (HA Integration)

Plan: `docs/plans/2026-03-11-phase2-ha-integration.md` (10 tasks)

Critical path: HABridgeConfig → CommandSafety → HAClient → MQTTClient → HABridgeStage → factory wiring → serialization → integration tests → manual verification
