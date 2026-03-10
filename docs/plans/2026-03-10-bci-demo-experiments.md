# BCI Demo Experiment Candidates

**Date:** 2026-03-10
**Goal:** Find a contrast with high separation (>0.8) for a compelling real-time demo, ideally one where ZUNA provides a measurable advantage over raw Muse 4ch.

**Baseline reference:** Eyes-open vs eyes-closed gave 0.25–0.48 separation. Not enough for a demo.

---

## Experiment 1: Meditation vs Mental Arithmetic

**EEG mechanism:** Meditation increases frontal theta + occipital alpha. Mental arithmetic increases frontal beta, suppresses alpha, increases frontal theta asymmetry. This is the widest spectral contrast in cognitive neuroscience — much bigger than eyes-open/closed.

**Protocol:**
- 3 × 60s guided relaxation (slow breathing, eyes closed, count breaths)
- 3 × 60s mental arithmetic (count backwards from 1000 by 7s, eyes open)

**What to measure:** Theta/beta ratio, alpha power, frontal theta, occipital alpha

**ZUNA angle:** Virtual Fz for frontal midline theta (classic meditation marker). Virtual O1/O2 for occipital alpha. Neither available on raw Muse.

**Probability of working:** 75–85%. This is the standard neurofeedback contrast. Large effect size in literature. Should give separation >0.5 easily, possibly >0.8 with good features.

**Wow factor:** Medium. "I can tell if you're doing math in your head." Interesting but not mind-blowing.

---

## Experiment 2: SSVEP (Steady-State Visual Evoked Potentials)

**EEG mechanism:** Staring at a flickering stimulus (e.g., 10Hz) produces a sustained frequency peak at that exact frequency in visual cortex (O1/O2). Different flicker rates → different frequency peaks → multiple commands. This is the basis of the fastest BCIs in existence (>100 bits/min).

**Protocol:**
- Display flickering patterns on screen at specific frequencies (6Hz, 7.5Hz, 10Hz, 15Hz — chosen to divide cleanly into 60Hz refresh)
- 10 × 10s trials per frequency, eyes fixated on pattern
- Control: stare at static pattern (no flicker)

**What to measure:** Power spectral density at the target frequency at O1/O2 vs baseline

**ZUNA angle:** THIS IS THE KEY ONE. SSVEP is strongest at occipital electrodes — Muse has none. Previous research said "not viable on Muse." But ZUNA gives us virtual O1/O2 that we've proven carry real spatial information. SSVEP is a sustained spectral phenomenon (not a transient), so ZUNA should preserve it. If SSVEP is detectable at virtual O1/O2, this is a capability that's genuinely impossible without ZUNA.

**Probability of working:** 40–50%. The signal is real but we're asking ZUNA to reconstruct a specific frequency response at electrodes it's never measured. The diffusion model might preserve it (spectral features work) or might smooth it away (it's a narrow-band peak, not broadband). High risk, highest reward.

**Wow factor:** VERY HIGH if it works. "I can tell which button you're looking at, using brain electrodes that don't physically exist." This is publishable.

---

## Experiment 3: Bright Light / Visual Stimulus Detection

**EEG mechanism:** Bright light strongly suppresses alpha across visual cortex. Flash stimuli produce visual evoked potentials (VEPs). Sustained bright screen = strong alpha suppression + pupil constriction → SNS activation.

**Protocol:**
- Alternate: 10 × 15s bright white screen, 10 × 15s dark/black screen
- Eyes open for both conditions
- Control for eye adaptation (1s transition ignored)

**What to measure:** Alpha suppression (bright vs dark), occipital alpha power

**ZUNA angle:** Same as eyes-open/closed but with a bigger stimulus contrast. Expected to give better separation because the visual stimulus is more extreme.

**Probability of working:** 70%. Essentially an amplified version of our alpha blocking experiment. Should beat 0.48 separation. But it's not fundamentally different from eyes-open/closed.

**Wow factor:** Medium-low. "Computer knows if the screen is white" — could be done with a light sensor. Not impressive unless framed well.

---

## Experiment 4: Frontal Alpha Asymmetry (Emotion Valence)

**EEG mechanism:** Left frontal activation (lower alpha at F3/AF7) correlates with approach/positive emotions. Right frontal activation (lower alpha at F4/AF8) correlates with withdrawal/negative emotions. This is the Davidson model, heavily researched since the 1990s.

**Protocol:**
- Show 10 positive images (puppies, sunsets, loved ones) × 15s each
- Show 10 negative images (spiders, injuries, threats) × 15s each
- Show 10 neutral images (furniture, tools) × 15s each
- OR: listen to happy vs sad music clips

**What to measure:** Alpha asymmetry: ln(alpha_right) - ln(alpha_left) at F3/F4 and AF7/AF8

**ZUNA angle:** Gives us F3/F4 (standard FAA electrodes). Muse has AF7/AF8 which are close but not canonical. ZUNA's F3/F4 might give cleaner asymmetry.

**Probability of working:** 20–30%. Frontal alpha asymmetry has tiny effect sizes (Cohen's d ~0.2–0.3) even in lab settings with research-grade EEG. Meta-analyses show high variability. With Muse + ZUNA reconstruction, the signal-to-noise is probably too low. Academic groups with 64-channel systems struggle with this.

**Wow factor:** VERY HIGH if it worked. "Computer reads your emotions." But it almost certainly won't work reliably enough for a demo.

---

## Experiment 5: Pain / Somatosensory Detection

**EEG mechanism:** Pain increases theta (4–8Hz) and gamma (>30Hz), decreases alpha. Chronic pain shows altered frontal theta and reduced alpha. Acute pain (e.g., cold pressor test — hand in ice water) produces measurable changes.

**Protocol:**
- Baseline: 60s rest
- Stimulus: hold ice cube / hand in cold water for 60s
- Recovery: 60s rest
- Compare alpha/theta before vs during pain

**What to measure:** Alpha suppression, theta increase, frontal theta/alpha ratio

**ZUNA angle:** More channels = more spatial information about pain processing (somatosensory cortex C3/C4, frontal theta Fz). But pain EEG signatures are subtle.

**Probability of working:** 15–25%. Pain EEG changes are real but small and highly variable between subjects. Clinical pain detection from EEG is an active research area with mediocre results even on research hardware. Not realistic for a demo.

**Wow factor:** Extremely high if it worked. "Computer detects pain." But won't work.

---

## Experiment 6: Auditory Attention (Cocktail Party)

**EEG mechanism:** When attending to one of two simultaneous audio streams, the attended stream's envelope is tracked by auditory cortex (temporal electrodes). Alpha lateralization also shifts.

**Protocol:**
- Play two spoken streams (left ear / right ear via headphones)
- Instruct to attend left vs attend right
- 10 × 30s trials each direction

**What to measure:** Alpha asymmetry (temporal), cross-correlation with attended stream envelope

**ZUNA angle:** Gives us T3/T4/T5/T6 (temporal virtual channels). Muse has TP9/TP10 which are close. Marginal ZUNA benefit.

**Probability of working:** 25–35%. Works in research settings with 64+ channels. With 4 real channels, probably not enough spatial resolution even with ZUNA.

**Wow factor:** High. "Computer knows which voice you're listening to." But unlikely to work on Muse.

---

## Recommendation: Priority Order

| Priority | Experiment | P(works) | Wow if works | ZUNA advantage | Time to run |
|----------|-----------|----------|-------------|---------------|-------------|
| **1** | SSVEP | 40–50% | Very high | **Critical** (needs O1/O2) | 30 min |
| **2** | Meditation vs math | 75–85% | Medium | Moderate (Fz, O1/O2) | 15 min |
| **3** | Bright vs dark screen | 70% | Low-medium | Minor | 10 min |
| **4** | Emotion (FAA) | 20–30% | Very high | Moderate (F3/F4) | 20 min |
| **5** | Auditory attention | 25–35% | High | Minor (T3/T4) | 30 min |
| **6** | Pain detection | 15–25% | Extreme | Minor | 15 min |

### Recommended plan

**Start with #2 (meditation vs math)** — highest probability of a working demo, establishes that brain state detection works. This is our "reliable A" demo.

**Then try #1 (SSVEP)** — this is the moonshot. If ZUNA can detect SSVEP at virtual O1/O2, it's a genuine novel finding. Multiple BCI commands from a 4-channel headband, enabled by AI upsampling. If it works, everything else is secondary.

**Skip #4–#6** unless we have extra time — probability too low for a demo.
