# Alpha Reactivity as a Cognitive State Biomarker

**Date**: 2026-03-12
**Status**: Initial finding, needs replication
**Key insight**: Cross-session alpha blocking variability is an objective measure of cognitive state — not a bug in our detector.

## Discovery

While validating the EyesClosedDetector for the museum demo, we compared eyes-closed (EC) vs eyes-open (EO) alpha power across two sessions. Alpha blocking (the EC/EO ratio) varies dramatically between sessions, and this variation itself is the signal.

## Raw Data

### Cross-Session Band Power Comparison (EO condition)

| Band | Mar 10 EO | Mar 12 EO | Change |
|------|-----------|-----------|--------|
| Delta | 51.0 | 9.4 | -82% |
| Theta | 9.2 | 3.5 | -62% |
| Alpha | 2.7 | 1.6 | -41% |
| Beta | 0.8 | 0.9 | +13% |
| Gamma | 10.4 | 3.4 | -67% |
| θ/β ratio | 11.2 | 4.1 | -63% |
| RMS (µV) | 35 | 34 | same |

### Alpha Reactivity (EC/EO ratio)

| Session | EC Alpha | EO Alpha | Ratio | Interpretation |
|---------|----------|----------|-------|----------------|
| Mar 10 | 7.4 | 2.7 | **2.70x** | Strong reactivity |
| Mar 12 | 1.8 | 1.6 | **1.12x** | Absent reactivity |

### Signal Quality

Both sessions have normal RMS (30-41 µV), ruling out electrode contact issues. The difference is neurological, not artifactual.

## Interpretation

### What alpha reactivity tells us

Alpha reactivity (Berger effect) — the increase in alpha power when eyes are closed — is one of the oldest known EEG phenomena. Its strength varies with:

1. **Cognitive fatigue / time-on-task**: Reduced alpha reactivity correlates with mental exhaustion
2. **Arousal level**: Over-arousal (stress, caffeine) suppresses alpha production
3. **Sleep pressure**: Accumulated sleep debt reduces alpha amplitude
4. **Individual state**: Mood, meditation experience, recent physical activity

### Why this matters

A Muse headband worn during work can periodically measure alpha reactivity (e.g., prompt user to close eyes for 10 seconds every 30-60 minutes). The trend of EC/EO ratio across the day gives an objective cognitive depletion curve. When the ratio drops below a threshold (e.g., < 1.3x), it's time for a break.

**This is not a subjective self-report. It's a neurophysiological measurement.**

### Cross-session profile (all conditions, Mar 10 vs Mar 12)

```
Mar 10 (strong reactivity):
  eyes_closed:  δ=233  θ=36.4  α=7.4  β=1.8  θ/β=20.6
  eyes_open:    δ= 51  θ= 9.2  α=2.7  β=0.8  θ/β=11.2
  mental_math:  δ= 64  θ=11.9  α=3.4  β=1.0  θ/β=11.5
  meditation:   δ= 12  θ= 3.8  α=2.7  β=0.6  θ/β= 6.5

Mar 12 (weak reactivity):
  eyes_closed:  δ= 12  θ= 3.3  α=1.8  β=0.7  θ/β= 4.7
  eyes_open:    δ=  9  θ= 3.5  α=1.6  β=0.9  θ/β= 4.1
```

Notable: Mar 10 has universally higher slow-wave power (delta, theta) across ALL conditions. This could indicate a different baseline brain state (more relaxed? more fatigued? different circadian phase?). The higher theta on Mar 10 alongside stronger alpha reactivity is consistent with a "relaxed but responsive" state vs Mar 12's "alert but flat" state.

## Potential Continuous Fatigue Metrics (no eyes-closed test needed)

For passive monitoring without periodic eyes-closed prompts:

| Metric | What it tracks | Muse feasibility | Evidence strength |
|--------|---------------|-------------------|-------------------|
| Frontal theta trend | Task fatigue accumulates as theta rises | Good (AF7/AF8) | Strong |
| θ/β ratio drift | Engagement declining over time | Good (have it) | Strong |
| Blink rate | Fatigue increases blink frequency | Good (BlinkDetector) | Moderate |
| Alpha power trend | Alpha suppression with fatigue | Moderate (frontal weak) | Moderate |
| Beta suppression | Sustained attention declining | Moderate | Moderate |
| HRV trend | Autonomic fatigue | Poor (Muse PPG unreliable) | Strong in general |

### Recommended approach for break detection

1. **Primary**: Track frontal θ/β ratio trend over 30+ minute windows. Rising trend = cognitive depletion.
2. **Secondary**: Track blink rate (already have BlinkDetector). Increasing blink rate = fatigue.
3. **Calibration**: Periodic eyes-closed alpha reactivity check (10s every 30-60 min) for ground truth.
4. **Composite**: Combine all three into a "cognitive stamina" score.

## Recording Notes

- `recordings/eyes_closed/20260310*/` — Session with strong alpha blocking (3 trials)
- `recordings/eyes_closed/20260312*/` — Session with absent alpha blocking (3 trials)
- `recordings/eyes_open/20260310*/` — Paired baseline (3 trials)
- `recordings/eyes_open/20260312*/` — Paired baseline (3 trials)
- `recordings/eyes_closed_tight/` — NOT alpha data. Muse poorly attached due to facial tension. Useful for artifact rejection training.

## Next Steps

- [ ] Replicate: Record EC/EO at start of work session, after 2h, after 4h
- [ ] Implement θ/β trend tracker (30-min rolling window, slope = fatigue rate)
- [ ] Add blink rate tracking to pipeline (count blinks per minute)
- [ ] Build composite "cognitive stamina" score
- [ ] Correlate with subjective fatigue (1-10 self-report after each EC/EO test)
