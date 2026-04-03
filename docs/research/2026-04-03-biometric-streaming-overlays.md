# Research: Biometric-Driven Streaming Overlays and OBS Ambient Effects

**Date:** 2026-04-03
**Sources:** 25+ sources (GitHub, OBS Forums, Pulsoid, HypeRate, VTube Studio Wiki, obs-websocket protocol docs, OBS source code)

---

## Executive Summary

Heart-rate overlays are in active, widespread production use by streamers today — the toolchain is mature and requires minimal setup. EEG/brainwave streaming overlays exist but are a curiosity (one high-profile example: Perrikaryal) rather than an ecosystem. OBS WebSocket v5 (built into OBS 30+) can control any filter's settings in real-time with sub-frame-accurate batching, making it a viable channel for ambient effect automation. The best path for this project is: EEG/BCI state → Python → obs-websocket → OBS color-correction/opacity filters, optionally also feeding VTube Studio parameters via the VTS API, which already has a shipped heart-rate plugin proving the exact pattern.

---

## Key Findings

### What streamers actually use today (heart rate, biometric overlays)

**Production-grade, widely deployed:**

- **Pulsoid** (pulsoid.net) — The dominant heart-rate-to-stream platform. Connects chest straps (Polar H10, Wahoo TICKR, CooSpo), smartwatches (Apple Watch, Wear OS, Samsung, Fitbit), and arm bands. Provides 60+ browser-source widgets, a Twitch Extension, and a REST/WebSocket API for raw BPM data. Add widget URL as OBS Browser Source, done. Has a documented API for third-party integrations. Production status: **mainstream**, used by thousands of streamers.

- **HypeRate.io** (hyperate.io) — Direct competitor to Pulsoid. Supports Fitbit, Garmin, Apple Watch, Android watches, chest belts. 100+ widget designs. Setup time claimed at 20 seconds. Also exposes a WebSocket API. Production status: **mainstream**.

- **Stromno** (stromno.com) — Focused on Apple Watch and Samsung Galaxy Watch specifically, OBS browser source. Newer entrant, smaller ecosystem.

- **HeartRateOnStream** (Android app) — Sends HR, steps, speed from a watch to OBS Studio directly. Available on Google Play.

- **StreamMyHeart** (OBS plugin) — Uses webcam-based PPG to measure heart rate without a wearable. OBS Forums resource. Accuracy limited compared to dedicated HRM hardware.

- **hr-stream** (github.com/jakelear/hr-stream) — Open-source, lightweight real-time heart-rate visualizer for OBS/XSplit. Older project but still functional.

**No native Twitch/YouTube/streaming platform biometric support.** All solutions are third-party browser sources or plugins. No platform has built this into their dashboard or encoding pipeline.

**Beyond display — reactive scene automation:**

- **Lumia Stream** (lumiastream.com) integrates with both Pulsoid and HypeRate. At configurable BPM thresholds it can: change smart light colors, trigger chat messages, play sounds, switch voices (Voicemod), and **trigger OBS filter activation/scene switches**. This is the closest existing tool to what this project wants — but it targets smart lights and alert widgets, not ambient visual effects driven by continuous EEG-band values.

- **Streamer.bot** (streamer.bot) and **Node-RED** (flows.nodered.org/flow/dc976343912bf59e3322e8a825f1c3e0) are middleware options for routing biometric WebSocket data → OBS WebSocket commands. The Node-RED OSC-to-OBS flow specifically supports scene switching, filter visibility, opacity, source visibility, and volume control.

---

### OBS WebSocket filter control — technical capabilities

obs-websocket v5 (bundled with OBS Studio 30+, previously a plugin) exposes full filter CRUD and settings control.

**Confirmed filter API calls (from protocol.md, v5.0.0+):**

| Request | What it does |
|---|---|
| `GetSourceFilterKindList` | Lists all available filter types by internal kind string |
| `GetSourceFilterList` | Lists all filters on a source with their current settings |
| `GetSourceFilter` | Gets settings for a single named filter |
| `CreateSourceFilter` | Adds a filter to a source |
| `RemoveSourceFilter` | Removes a filter |
| `SetSourceFilterName` | Renames a filter |
| `SetSourceFilterSettings` | **Updates any filter parameter(s) by key** |
| `SetSourceFilterEnabled` | Toggles a filter on/off |
| `SetSourceFilterIndex` | Reorders filters in the stack |

**`SetSourceFilterSettings` key parameters:**
```json
{
  "sourceName": "MySource",
  "filterName": "MyColorFilter",
  "filterSettings": { "brightness": 0.4, "saturation": 2.1 },
  "overlay": true
}
```
`overlay: true` merges into existing settings; `overlay: false` resets to defaults first.

**Confirmed color_filter (Color Correction) setting keys** (from OBS source, `color-correction-filter.c`):

| Key | Type | Range |
|---|---|---|
| `gamma` | float | -3.0 to 3.0 |
| `contrast` | float | -2.0 to 2.0 (SDR) / -4.0 to 4.0 (HDR) |
| `brightness` | float | -1.0 to 1.0 |
| `saturation` | float | -1.0 to 5.0 |
| `hue_shift` | float | -180.0 to 180.0 |
| `opacity` | int (SDR) / float (HDR) | 0–100 / 0.0–1.0 |
| `color` | int (ARGB packed) | color tint |
| `color_multiply` | int (ARGB packed) | multiply color |
| `color_add` | int (ARGB packed) | additive color |

Other built-in filter types (kind strings): `scroll_filter`, `crop_filter`, `render_delay_filter`, `sharpness_filter`, `noise_suppress_filter`, `noise_gate_filter`, `compressor_filter`, `limiter_filter`, `expander_filter`, `luma_key_filter`, `color_key_filter`, `chroma_key_filter`. Third-party plugins (StreamFX, obs-composite-blur) add more: blur, glow, shadow, color grade.

**Latency:**

The obs-websocket documentation specifies two execution modes for batch requests:

- `SerialRealtime` (default) — requests processed as fast as possible, typically single-digit milliseconds on localhost.
- `SerialFrame` — requests processed in sync with the OBS graphics thread, before the next frame is composited. Designed for animation. Rule of thumb: keep processing under 2ms per frame to avoid stalling the compositor. Sleep requests can pause for N frames.

For single `SetSourceFilterSettings` calls on localhost, round-trip is well under 10ms in practice. Smooth animation loops (e.g., breathing saturation) are feasible at OBS's output framerate (30 or 60fps) using `SerialFrame` batches or a Python timer loop calling the API at ~10–30Hz (which is sufficient for physiological signal timescales).

**Python libraries:**
- `obs-websocket-py` (github.com/Elektordi/obs-websocket-py) — synchronous callbacks, older but stable
- `obsws-python` (github.com/aatikturk/obsws-python, PyPI: `obsws-python`) — SDK for obs-websocket v5, snake_case method names matching the protocol

---

### EEG / brainwave streaming — existing examples

**The only prominent public example is Perrikaryal** (twitch.tv/perrikaryal):
- Uses an **Emotiv Epoc X** EEG headset + **EmotivBCI** software
- Displays a 3D brain visualization on stream using **Emotiv BrainViz** (emotiv.com/emotiv-brainviz) — a real-time visualization tool showing electrical activity as a lit 3D brain model
- Used EEG primarily as a *game input* (motor imagery → virtual Xbox controller buttons, ~60-70% accuracy), not as a passive ambient effect
- Achieved notable viral coverage (Kotaku, IEEE Spectrum, Vice, Freethink) in 2023
- Currently one of the only streamers doing this publicly and regularly

**No ecosystem exists** for EEG → streaming ambient effects. There is no plugin, no OBS resource, no dedicated tool. What Perrikaryal does is a custom integration. The visualization layer (BrainViz) is a separate app captured as an OBS source, not a filter-driven ambient effect.

**Academic research exists** ("All the Feels: A Twitch Overlay that Displays Streamers' Biometrics to Spectators", eScholarship) documenting the concept as a research prototype, not a production tool.

**Bottom line:** EEG → visual overlay is essentially uncharted territory in production streaming. No established toolchain. This project would be pioneering.

---

### VTuber ambient effects approaches

**VTube Studio built-in post-processing** (confirmed in VTS Wiki):
- VTS has a native "Visual Effects" system on Windows/macOS with: lens distortion, bloom, particles, overlays, lighting effects, and more
- These are applied within VTS's own render pipeline, not through OBS
- They are driven by **VTS parameters** (tracking values, expression states) — meaning any parameter you can inject via the VTS API can drive these effects
- VTS exports to OBS via **Spout2** (Windows/macOS) or virtual camera; when using Spout2, post-processing effects like bloom are included in the composited output

**VTuber community ambient effects in practice:**
- Most VTubers use static or audio-reactive overlays (voice-reactive PNG, scene changes triggered by alerts)
- "Mood" effects are typically manual — streamers switch OBS scenes or VTS expressions manually for horror, relaxed, etc.
- No mainstream biometric-to-ambient pipeline exists in the VTuber community as a standard practice

**The vts-heartrate plugin** (github.com/FomTarro/vts-heartrate) is directly relevant:
- Connects heart rate monitors (via Pulsoid, HypeRate, ANT+, Fitbit) to VTube Studio parameters
- Drives: custom tracking parameters, Live2D item toggles, expression triggering at BPM thresholds, Art Mesh tinting (gradually tints model skin based on HR — e.g., flushed for workouts)
- Dynamically controls VTube Studio VFX with heartbeat
- Has a Plugin API for third-party consumption
- Built on VTS-Sharp (C# VTS API wrapper)
- Status: **shipped, actively maintained**, available on itch.io

This plugin proves the architecture pattern: biometric value → VTS parameter injection → model deform + VFX. The same path works for EEG band power values in place of heart rate.

---

### Dedicated tools and plugins

| Tool | Type | Biometric Input | OBS Integration | Notes |
|---|---|---|---|---|
| Pulsoid | SaaS + API | Heart rate (HRM hardware, watches) | Browser source widget; REST+WS API | Dominant platform, 3rd-party API access |
| HypeRate | SaaS + API | Heart rate (watches, chest straps) | Browser source widget; WS API | Similar to Pulsoid, slightly smaller |
| Stromno | SaaS | Heart rate (Apple/Samsung Watch) | Browser source | Smaller, watch-focused |
| HeartRateOnStream | Android app | Watch HR | OBS plugin + OSC to VRChat | Also exports OSC |
| StreamMyHeart | OBS plugin | Webcam PPG | Native OBS plugin | No hardware needed, lower accuracy |
| Lumia Stream | Automation middleware | HR (via Pulsoid/HypeRate) | OBS filter/scene triggers | Threshold-based, not continuous |
| vts-heartrate | VTS plugin | HR (via Pulsoid/HypeRate/ANT+) | Via VTS (Spout2 to OBS) | Continuous parameter drive + tinting |
| Emotiv BrainViz | Desktop app | EEG (Emotiv headsets only) | Captured as OBS window source | Visualization only, no parameter output |
| obs-websocket-py / obsws-python | Python libraries | Any (custom) | Full OBS WebSocket v5 access | Building block for custom integrations |
| Node-RED OSC→OBS flow | Automation | Any OSC source | Filter visibility, opacity, volume | Open-source, no-code-ish wiring |

---

## Comparison table

| Capability | Heart Rate (production) | EEG (this project) | Required approach |
|---|---|---|---|
| Display widget (number/graph) | Pulsoid/HypeRate — trivial | Custom browser source | Browser source with WebSocket feed |
| OBS color filter continuous drive | Lumia Stream (threshold) or custom | Custom only | Python → obsws-python → SetSourceFilterSettings |
| VTube Studio parameter drive | vts-heartrate plugin | Custom VTS API injection | Existing muse-vtuber VTS path |
| Sub-second latency | Yes (all tools) | Yes (WebSocket path) | Local WebSocket, <10ms |
| Scene switching on threshold | Lumia Stream, Streamer.bot | Same tools if signal is websocket-fed | Feed EEG state to Lumia/Streamer.bot |
| Frame-synced animation in OBS | SerialFrame batches | Same | obsws-python + SerialFrame batch |
| No-code setup | Pulsoid + OBS browser source | Not available | Must code |

---

## Implementation path for this project

The gap to fill is: **no tool reads from a custom WebSocket (our EEG backend) and drives OBS filter parameters continuously**. Pulsoid/HypeRate are closed silos for their own hardware. Lumia Stream only does threshold triggers, not smooth continuous mapping. The good news: all the primitives exist.

**Recommended path:**

1. **Python bridge module** (`muse-vtuber/obs_bridge.py` or similar) that:
   - Connects to the EEG backend WebSocket (already outputs band power + state)
   - Connects to OBS via `obsws-python` on localhost:4455
   - Maps EEG states → filter parameter values (e.g., alpha power → saturation, theta → hue_shift, clench → brief flash via opacity)
   - Calls `SetSourceFilterSettings` in a loop at 10–30Hz

2. **Prerequisite OBS setup**: Create a Color Correction filter on a full-scene overlay source (e.g., a solid color or gradient image source at low opacity), named something predictable (e.g., `EEG_Ambient`). The Python bridge targets this by name.

3. **Optionally also drive VTube Studio parameters** for model-level effects via the existing VTS API path in muse-vtuber — the vts-heartrate plugin's approach (Art Mesh tinting) is directly replicable with EEG band data instead of BPM.

4. **SerialFrame batching** is available if smooth animation at OBS frame rate matters, but a 10Hz loop calling individual `SetSourceFilterSettings` is likely sufficient for EEG-timescale changes.

**Key filter parameters to map:**
- `saturation` (0–3): overall "energy level" ambient — maps to alpha power inverse (relaxed = desaturated, alert = vivid)
- `hue_shift` (-30 to +30): slow drift based on theta/alpha ratio — creates mood tint without obvious color
- `brightness` (±0.15): transient events (blink, clench) — brief pulse
- `opacity` (0–20 on the overlay): intensity envelope

**Latency:** OBS WebSocket on localhost is consistently under 5ms round-trip. EEG pipeline latency (256Hz BrainFlow, 4-sample epoch = ~16ms) dominates. Total pipeline latency to visible effect: ~50–100ms, adequate for ambient effects.

---

## Open Questions

1. **obsws-python async vs sync**: Does the async version of obsws-python handle a 20Hz call loop without event loop contention against the existing asyncio EEG pipeline? Needs test.

2. **OBS filter parameter discovery**: `GetSourceFilterKindList` returns kind strings; to discover what keys a specific filter accepts you currently have to read OBS source or use `GetSourceFilterList` on a pre-configured filter. There is no introspection endpoint for filter schema. This is a known gap (obsproject/obs-websocket issue #432).

3. **StreamFX / obs-composite-blur filter keys**: Third-party filter plugins (bloom glow, depth of field) are not documented in obs-websocket protocol — must be discovered empirically. Worth testing if richer effects are desired.

4. **Lumia Stream as no-code bridge**: If someone wants Muse EEG data to drive Lumia Stream (for smart light integration alongside OBS), an adapter publishing EEG band power as a fake "heart rate" BPM integer via Pulsoid's feed format might work — not explored.

5. **EEG → stream engagement data**: The eScholarship paper "All the Feels" suggests viewer engagement improves with biometric display. Is there any streaming platform considering native biometric APIs? No evidence found as of April 2026.

---

## Sources

- [Pulsoid - heart rate streaming widget](https://pulsoid.net/)
- [Pulsoid OBS Forums resource](https://obsproject.com/forum/resources/pulsoid-heart-rate-streaming.559/)
- [HypeRate.io - heart rate for OBS and Twitch](https://www.hyperate.io/)
- [HypeRate guide: heart rate on Twitch](https://www.hyperate.io/stories/heart-rate-on-twitch-the-ultimate-guide-to-stream-your-heart-rate-with-obs.html)
- [Stromno - Apple/Samsung Watch HR for OBS](https://www.stromno.com/)
- [StreamMyHeart OBS plugin (OBS Forums)](https://obsproject.com/forum/resources/streammyheart.2098/)
- [hr-stream - open source HR visualizer for OBS (GitHub)](https://github.com/jakelear/hr-stream)
- [Lumia Stream + Pulsoid integration](https://lumiastream.com/services/pulsoid)
- [Pulsoid × Lumia Stream tutorial (Pulsoid Blog)](https://blog.pulsoid.net/post/how-to-control-your-lights-and-more-with-your-heart-rate-pulsoid-x-lumia-stream-tutorial)
- [Node-RED: OSC to OBS flow](https://flows.nodered.org/flow/dc976343912bf59e3322e8a825f1c3e0)
- [obs-websocket protocol.md (GitHub master)](https://raw.githubusercontent.com/obsproject/obs-websocket/master/docs/generated/protocol.md)
- [obs-websocket GitHub repo](https://github.com/obsproject/obs-websocket)
- [SetSourceFilterSettings issue/discussion (GitHub)](https://github.com/obsproject/obs-websocket/issues/281)
- [obs-websocket SerialFrame batch commit (GitHub)](https://github.com/obsproject/obs-websocket/commit/a8d27ede9ef34c9cf502d9d9e041a1a1f13b906b)
- [OBS color-correction-filter.c source (GitHub)](https://github.com/obsproject/obs-studio/blob/master/plugins/obs-filters/color-correction-filter.c)
- [obsws-python SDK (GitHub)](https://github.com/aatikturk/obsws-python)
- [obs-websocket-py (GitHub)](https://github.com/Elektordi/obs-websocket-py)
- [vts-heartrate plugin (GitHub)](https://github.com/FomTarro/vts-heartrate)
- [vts-heartrate on itch.io](https://skeletom-ch.itch.io/vts-heartrate)
- [VTube Studio - Visual Effects Wiki](https://github.com/DenchiSoft/VTubeStudio/wiki/Visual-Effects)
- [Pulsoid + VTube Studio integration (Pulsoid Blog)](https://blog.pulsoid.net/post/make-your-heart-rate-influence-your-vtube-studio-avatar-directly)
- [Perrikaryal EEG Twitch / Elden Ring - Kotaku](https://kotaku.com/twitch-streamer-elden-ring-play-brain-eeg-perrikaryal-1850024234)
- [Perrikaryal EEG / Halo - Kotaku](https://kotaku.com/twitch-elden-ring-stream-perrikaryal-eeg-halo-1850826940)
- [Perrikaryal technical breakdown - IEEE Spectrum](https://spectrum.ieee.org/elden-ring-hands-free-controller)
- [Emotiv BrainViz](https://www.emotiv.com/emotiv-brainviz)
- ["All the Feels" biometric Twitch overlay research (eScholarship)](https://escholarship.org/uc/item/6mb4f7hb)
- [BLE heart rate → OBS with obsws-python (Python in Plain English)](https://python.plainenglish.io/the-concurrency-choreographer-making-bles-async-data-sync-with-obs-095db549d2fc)
