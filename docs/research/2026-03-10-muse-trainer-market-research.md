# Research: Muse Third-Party Trainer Market Opportunity

**Date:** 2026-03-10
**Sources:** 12 sources (see bottom)

---

## Executive Summary

The Muse ecosystem has a clear gap: the official app focuses on guided meditation content (500+ sessions behind a $95/yr paywall), while power users and researchers want raw data access, custom neurofeedback protocols, and integration with external systems. Third-party apps exist (Mind Monitor $20 one-time, Myndlift clinical platform) but are either visualization-only or expensive clinical tools. There is no open-source, self-hosted neurofeedback trainer that lets users define custom protocols with real-time feedback. Legally, Interaxon discontinued their SDK in 2017 and shifted to a subscription model, but BrainFlow connects to Muse via native Bluetooth without using any Muse SDK — operating in an unregulated gray area that multiple commercial apps (Mind Monitor, Myndlift) already exploit.

## Key Findings

### 1. What the Official Muse App Offers

The official Muse app provides guided meditation with real-time audio feedback (birds chirp when calm, rain when distracted). Premium subscription costs $12.99/month or $94.99/year [1]. Premium features include:

- 500+ guided meditations (stress, sleep, focus)
- "Alpha Peak" cognitive performance score
- Personalized coaching dashboard
- Sleep tracking (Muse S/Athena)
- Monthly new content releases

The free tier provides basic meditation sessions with the headband. The app is mobile-only (iOS/Android) and English-only [2]. The Athena model ($475-520) adds fNIRS for blood flow measurement [3].

The official app does NOT offer: raw data export, custom neurofeedback protocols, real-time visualization, integration with external systems (Home Assistant, OSC, etc.), or any developer-facing features.

### 2. Existing Third-Party Apps

| App | Price | Platform | Key Feature | Limitation |
|-----|-------|----------|-------------|------------|
| **Mind Monitor** | ~$20 CAD one-time | iOS/Android | Raw EEG visualization, CSV export, OSC streaming | Visualization only, no neurofeedback loop |
| **Myndlift** | Clinical pricing (bundled with Muse) | iOS/Android | Clinical neurofeedback protocols, ADHD training | Expensive, clinician-oriented, not self-serve |
| **Muse Direct** | Included (research) | Desktop | Raw data streaming | Windows only, no feedback, research tool |
| **EEG 101** | Free/open-source | Android | Educational BCI demos | Outdated, limited features |
| **NeuroVisual** | Unknown | Unknown | Visualization | Small project, limited info |

Mind Monitor is the most successful third-party app [4]. It provides professional-grade spectrograms, raw microvolt display, CSV recording, and OSC streaming to desktop software — features the official app completely lacks. However, it is purely a monitoring/recording tool with no neurofeedback training functionality.

Myndlift is a clinical neurofeedback platform that recently partnered with Interaxon to offer free access with Muse headbands [5]. It provides structured neurofeedback protocols used by clinicians for ADHD, anxiety, and focus training. However, it targets the clinical/therapeutic market, not self-directed users.

### 3. Gaps Not Covered

**Clear gaps in the market:**

1. **Custom neurofeedback protocols** — No app lets users define their own training targets (e.g., "increase theta/beta ratio at AF7," "maintain alpha above threshold for 30s"). Mind Monitor shows data but doesn't close the feedback loop. Muse app only offers their proprietary "calm score."

2. **Integration with smart home / IoT** — No app connects brain state to external systems (lights, music, Home Assistant). This is a natural extension: dim lights as you relax, change music based on focus level.

3. **Web-based dashboard** — All existing solutions are mobile apps. A web app running on a laptop/desktop with a larger screen would suit power users, researchers, and therapists who want richer visualization alongside feedback.

4. **Open-source / self-hosted** — No maintained open-source neurofeedback trainer exists. Several GitHub projects ([6], [7]) provide basic streaming/visualization but none offer a complete training experience.

5. **Multi-state detection beyond "calm"** — The official app only detects calm vs. not-calm. Our experiments show theta/beta ratio can distinguish meditation, drowsy, and mental effort at 94%+ accuracy — three distinct states from the same hardware.

6. **Session comparison and progress tracking** — Mind Monitor records CSVs but provides no analysis. The official app tracks "meditation minutes" but not spectral progression over weeks/months.

### 4. Delivery Format

**Web app is the strongest choice for several reasons:**

- No app store approval needed (avoids Apple/Google review and 30% cut)
- Works on any device with a browser (but needs Web Bluetooth or a local bridge for Muse connection)
- Larger screen for richer visualization (spectrograms, topographic maps)
- Easier to update and iterate
- Can run locally (self-hosted) or as SaaS

**Limitation:** Web Bluetooth API is supported in Chrome/Edge but not Safari/Firefox. For Muse connection from a web app, you'd need either:
- Chrome on Android/desktop with Web Bluetooth
- A local Python/Node bridge process that handles BrainFlow and streams to the browser via WebSocket (this is what our current architecture does)

**Mobile app** would reach more users but requires app store presence, native BLE handling, and platform-specific builds. A React Native or Flutter wrapper around a web core is possible but adds complexity.

**Our current architecture (Python backend + React frontend via WebSocket) is already the right shape** for this product.

### 5. Legal / EULA Analysis

**Interaxon discontinued their official SDK in 2017** and shifted to a consumer subscription model [8]. The SDK FAQ page still exists but states the SDK is available for "commercial and non-commercial use" with different license tiers [9].

**BrainFlow does NOT use the Muse SDK.** BrainFlow connects to Muse devices via native Bluetooth (BLE GATT protocol), bypassing any Interaxon software entirely [10]. This is analogous to how any Bluetooth device can be accessed by third-party software — the Bluetooth protocol is an open standard.

**Legal risk assessment:**

| Concern | Risk Level | Notes |
|---------|------------|-------|
| Using BrainFlow to connect | **Low** | BrainFlow is open-source, uses native BLE, doesn't use Muse SDK. Multiple commercial apps (Mind Monitor, Myndlift) do this already without legal issues |
| Building a competing app | **Low-Medium** | The EULA restricts the "Software" (Muse's own app), not the hardware. You can't reverse-engineer their app, but connecting to the hardware via standard Bluetooth is not restricted by the EULA |
| Commercial distribution | **Low** | Mind Monitor has been commercially available for years ($20, thousands of users) with no legal action from Interaxon. Myndlift is a VC-funded company built entirely on Muse hardware |
| Using "Muse" in marketing | **Medium** | Trademark issue. Must say "compatible with Muse" not "Muse trainer." Standard compatibility claim under nominative fair use |
| Patent infringement | **Unknown** | Interaxon may hold patents on specific neurofeedback methods. Unlikely to be an issue for basic band-power feedback but worth checking |

**Key precedent:** Interaxon actually **partnered** with Myndlift rather than suing them, suggesting they welcome ecosystem growth. They also list "SDK Partners" on their website [11], indicating openness to third-party development.

## Open Questions

- What specific neurofeedback protocols would users pay for? (ADHD focus training? Sleep optimization? Peak performance?)
- What's the pricing sweet spot? (Mind Monitor: $20 one-time. Muse Premium: $95/yr. Myndlift: clinical pricing)
- Does Interaxon's patent portfolio cover any of the features we'd build?
- Would Interaxon partner or compete if we gained traction?

## Sources

[1] Muse. "Premium Subscription." https://choosemuse.com/pages/premium-subscription
[2] Cybernews. "I've Tested Muse S Athena for a Month: My Full Review 2026." https://cybernews.com/health-tech/muse-s-review/
[3] Athletech News. "Muse Launches Athena, a Next-Gen Brain-Training Wearable." https://athletechnews.com/muse-s-athena-brain-wearable/
[4] Mind Monitor. https://mind-monitor.com/
[5] Myndlift. "Free Access to Myndlift with a Muse Headband." https://www.myndlift.com/post/free-access-to-myndlift-with-a-muse-headband-unlock-your-brain-s-full-potential
[6] GitHub. "muse-headband topic." https://github.com/topics/muse-headband
[7] GitHub. "eeg_neurofeedback — Open-source EEG neurofeedback for meditation." https://github.com/poddubnyoleg/eeg_neurofeedback
[8] GitHub Issue. "The worst case happened: Interaxon does no longer offer the Muse SDK." https://github.com/sccn/labstreaminglayer/issues/30
[9] Muse. "Muse Software Development Kit (SDK) FAQs." https://choosemuse.my.site.com/s/article/Muse-Software-Development-Kit-SDK-FAQs
[10] BrainFlow. "Supported Boards." https://brainflow.readthedocs.io/en/stable/SupportedBoards.html
[11] Muse. "SDK Partners." https://choosemuse.com/pages/sdk-partners
[12] Muse. "Developers." https://choosemuse.com/pages/developers
