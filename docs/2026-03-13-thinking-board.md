# Thinking Board — 2026-03-13

Post office demo brain dump. Not a roadmap, not prioritized. Just getting it all down.

---

## The fitting problem is real

Office demo: 5/7 coworkers got POOR signal quality. Nobody knew how to put the Muse on properly. Glasses are a huge problem — push the headband up. Some people have smaller heads and the band doesn't sit right. Even when it looks good, a head nod or shake can shift it.

This isn't a nice-to-have. If we can't solve fitting, nothing else matters.

Need a full setup procedure:
- Step-by-step fitting guide (ears first, then forehead, check RMS)
- Real-time fit quality indicator (RMS per channel, green/yellow/red)
- Calibration protocol: "please blink 5 times", "please clench jaw", "please nod", "please shake head"
- Use calibration to learn the person's blink shape, amplitude, baseline
- **Detectors must degrade gracefully without calibration** — calibration improves accuracy, absence doesn't break it

## Blink detection in the wild

Real-life blink detection is WAY harder than the literature suggests. Our F1=0.95 on our own data dropped to "hard to tell" on coworker data with bad fits.

But: a human looking at the raw waveform can still see blinks, even in noisy sessions. The shape is there. The problem IS solvable per-session. We just need smarter methods.

We researched advanced approaches (docs/research/2026-03-12-advanced-blink-detection-methods.md) but haven't implemented any:
- MAD-based robust statistics (replace mean/std with median/MAD)
- Wavelet coefficient thresholding
- DTW template matching against per-session learned template

Need to stop researching and start getting concrete numbers on these. Pick one, implement it, run through the eval harness on both our clean data AND the office demo data.

Take early test results seriously. If something scores poorly on 33 clean office trials, it will score worse in production.

## What are we actually measuring?

We throw around "focus", "relaxation", "fatigue" but what do the formulas actually compute?

- **Focus**: theta/beta ratio? What does BrainFlow's MINDFULNESS model actually use? Can we do better with our channels?
- **Relaxation**: alpha power? Alpha/beta ratio? RESTFULNESS model?
- **Fatigue**: what EEG signatures? Theta increase? Alpha decrease? Microsleep patterns?

Need a research doc that maps: concept → EEG signature → formula → what channels → validated on Muse? → our accuracy.

Without this we're building on vibes.

## Brain Fry detector

CNN article (2026-03-13): https://edition.cnn.com/2026/03/13/business/ai-brain-fry-nightcap

"AI Brain Fry" is entering mainstream vocabulary. People relate to it — I definitely get it after long sessions.

Positioning opportunity: "Is your brain actually fried or are you just bored? Wear this and find out."

Need:
- Fatigue EEG signature research (see above)
- Recording protocol: work session → measure over time → correlate with subjective fatigue reports
- Record myself during a long AI session as initial data
- Probably needs theta/alpha ratio trending over 30+ minute windows, not instantaneous

This could be the "killer feature" hook for content marketing. Relatable, timely, slightly provocative.

## Productization

Why does this project exist? Who is it for? What's the killer feature?

Current capabilities:
- Real-time EEG visualization (cool but niche)
- Blink detection (works on well-fitted devices, unreliable otherwise)
- Concentration/relaxation metrics (moderate accuracy)
- Museum brain remote control demo (specific use case)

Possible angles:
- Developer tool / BCI experimentation platform (small market, us + hobbyists)
- Brain Fry / cognitive fatigue monitor (mass market hook, needs validation)
- Museum/exhibition interactive brain control (niche but impressive demos)
- Meditation/focus trainer (crowded market — Muse app, Calm, etc.)

Need to pick one and commit, or at least pick a primary angle for content.

## Music

Brainstorm needed. What can we do with music + EEG?
- Music that responds to brain state? (relaxing music when stressed, energizing when drowsy)
- Measure music's effect on brain? (which songs increase focus?)
- Brain-controlled music generation?
- DJ set that responds to audience brain state? (wild demo potential)

This is fuzzy. Needs a proper brainstorming session.

## ZUNA

Current status: only validated value is alpha blocking at virtual O1/O2. Hurts most other things.

Need to:
- Check if there are new ZUNA releases or papers
- Ask about discretisation (whatever that means in their context)
- Reassess whether ZUNA adds value for any of our new directions (fatigue? music response?)

Don't sink more time here unless there's a clear use case.

## BrainFlow battery fix

Still on the list. Patch C++ source to subscribe to Muse telemetry GATT `273e000b`. Not urgent but would be nice for the setup procedure (low battery = bad signal).

## Content marketing / blog

Start writing about this stuff publicly. Even if the product isn't ready, the journey is interesting.

Possible first posts:
- "I tried to detect blinks with a $250 headband — here's what actually works"
- "Your coworkers can't put on an EEG headband (and what that means for consumer BCI)"
- "Is AI Brain Fry real? I'm going to measure it"
- "What can you actually do with a Muse 2? (honest review from a developer)"

Blog gives us: SEO, credibility, user feedback, potential early adopters.

## Office demo data

7 sessions from coworkers. Mostly garbage signal quality but that's the point — real world data.

- S2 and S7: OK quality, ~33 usable blink trials → add to eval corpus
- S1, S3, S4, S5, S6: POOR quality → use for artifact rejection training, fit detection development
- Mental math: unusable, needs re-recording with proper fit

Don't delete any of it. Bad data teaches us about failure modes.

---

*Next actions are not defined here on purpose. This is for thinking, not doing.*
