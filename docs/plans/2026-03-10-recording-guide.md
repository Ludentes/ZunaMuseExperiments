# Recording Guide: BCI Demo Experiments

## Setup

1. Put on Muse 2, ensure good contact (all 4 LEDs solid)
2. Start backend: `python -m backend.main --mac "XX:XX:XX:XX:XX:XX"` (your Muse MAC)
3. Start frontend: `cd frontend && pnpm dev`
4. Open http://localhost:3000
5. Wait for "Connected" indicator
6. Remove glasses if wearing — they interfere with temporal sensors

## Experiment A: Engagement / Attention Meter

**Goal:** Measure spectral separation between deep relaxation and intense mental effort.

### A1: Meditation (3 × 60s)

1. Select **meditation** protocol
2. Click START SESSION
3. For each trial: close eyes, breathe slowly (4s in, 6s out), count breaths silently
4. Try to stay completely still — no fidgeting, no jaw tension
5. Between trials: open eyes, stretch briefly during 10s rest

### A2: Mental Math (3 × 60s)

1. Select **mental_math** protocol
2. Click START SESSION
3. For each trial: eyes open, stare at screen, count backwards from 1000 by 7s
   - 1000, 993, 986, 979, 972, 965...
   - If you lose track, restart from the last number you remember
   - The point is sustained cognitive load, not getting the right answer
4. Keep still — resist the urge to mouth the numbers

### Tips
- Do meditation FIRST — it's easier to relax before doing math than vice versa
- Leave 2-3 minutes between A1 and A2 for your brain state to reset
- If a trial feels bad (you moved, sneezed, etc.), use DISCARD TRIAL during rest

---

## Experiment B: SSVEP (Visual Flicker)

**Goal:** Detect steady-state visual evoked potentials at ZUNA's virtual occipital channels.

**WARNING:** If you are photosensitive or have epilepsy, DO NOT run this experiment. The screen will flash rapidly.

### Recording order

Record all 5 conditions. Start with the control, then go from low to high frequency:

| # | Protocol | What happens | Duration |
|---|----------|-------------|----------|
| 1 | **ssvep_none** | Static checkerboard, no flicker | 10 × 15s |
| 2 | **ssvep_6hz** | Checkerboard inverts at 6 Hz | 10 × 15s |
| 3 | **ssvep_7hz** | Checkerboard inverts at 7.5 Hz | 10 × 15s |
| 4 | **ssvep_10hz** | Checkerboard inverts at 10 Hz | 10 × 15s |
| 5 | **ssvep_15hz** | Checkerboard inverts at 15 Hz | 10 × 15s |

**Note on monitor refresh rate:** These frequencies (6, 7.5, 10, 15 Hz) are chosen to divide cleanly into a 60Hz monitor's refresh cycle. 12Hz was excluded because it requires 2.5 frames per half-cycle at 60Hz, causing jitter that smears the spectral peak. If you have a 120Hz+ monitor, 12Hz would also work.

### For each SSVEP recording:

1. Select the protocol (e.g., **ssvep_10hz**)
2. Click START SESSION
3. Countdown starts (3-2-1)
4. When cue fires: full-screen checkerboard appears with red fixation cross
5. **FIXATE on the red cross in the center** — don't look around
6. Stay still, don't blink if possible (blinking is OK but minimize)
7. After 15s the flicker stops, 5s rest, next trial starts
8. Press ESC at any time to abort

### Tips
- Sit at a comfortable distance (~60cm from screen)
- Dim room lighting — reduces ambient light interference
- Keep monitor brightness at maximum — stronger stimulus = stronger SSVEP
- Don't wear glasses (interferes with Muse, and reflections confuse the visual stimulus)
- Between conditions (e.g., between 7hz and 10hz), take a 1-minute break
- The control (ssvep_none) shows the same full-screen checkerboard with red fixation cross, just not flickering

### What to expect
- You may see afterimages or mild visual distortion after flicker trials — this is normal
- The control (ssvep_none) shows the same checkerboard + fixation cross, just static — same visual context, no flicker
- The flicker feels less intense at higher frequencies (15Hz is near the fusion threshold)
- Each condition takes ~4 minutes (10 × 15s + 10 × 5s rest)
- Total SSVEP session: ~25 minutes including breaks

---

## After Recording

### Run Experiment A analysis:
```bash
# TODO: analysis script for meditation vs math comparison
PYTHONPATH=. python scripts/eval_engagement.py
```

### Run Experiment B analysis:
```bash
# TODO: analysis script for SSVEP detection
PYTHONPATH=. python scripts/eval_ssvep.py
```

### Run both through ZUNA and compare:
```bash
# Will be built after initial analysis of raw data
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| SSVEP flicker feels too fast | Start with 7.5Hz — it's the slowest option |
| Muse disconnects mid-recording | Power cycle Muse, restart backend, re-record that condition |
| "Recording failed" on backend | Check that recordings/ directory exists and is writable |
| Flicker doesn't appear | Make sure you selected an ssvep_* protocol, not a regular one |
| ESC doesn't stop flicker | Click the browser window first (might have lost focus) |
