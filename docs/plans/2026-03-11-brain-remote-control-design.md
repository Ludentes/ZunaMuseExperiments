# Brain Remote Control — Design Document

**Date:** 2026-03-11
**Status:** Draft

## Overview

A guide wears a Muse 2 headband during museum tours and controls room lights and kiosk content hands-free using brain signals, eye blinks, and head position. The audience sees the magic — the guide's brain activity visualized on a kiosk display, lights responding to mental state in real time.

## Controls

Four control channels, layered by reliability:

| Control | Signal | Type | Latency | Audience Effect |
|---------|--------|------|---------|-----------------|
| Double blink → next content | EOG artifact | Discrete | <500ms | Kiosk advances to next slide/video |
| Triple blink → toggle lights | EOG artifact | Discrete | <500ms | Room lights flip on/off |
| Concentration → light color | Theta/beta ratio (real BCI) | Continuous | 2-5s fade | Ambient RGB shifts blue→purple→red as focus increases |
| Eyes closed → dramatic dim | Alpha blocking (real EEG) | Sustained | 1-2s onset | Room dims smoothly; opens eyes → lights restore |

**Design principle:** Reliable signals (blinks) handle discrete pass/fail actions. Real BCI (concentration) drives gradual aesthetics where "wrong" is invisible — nobody notices if ambient color is a slightly different shade.

## Architecture

```
Muse 2 (BLE)
  |
ZyphraExps Backend (Python, single process)
  |-- Pipeline: blink detector, band powers, alpha blocking, head motion
  |-- WebSocket --> Kiosk (brain heatmap + ZUNA visualization)
  |-- HABridgeStage (new pipeline Stage, end of SLOW chain)
        |
        |--> Home Assistant WebSocket API (ws://ha:8123/api/websocket)
        |      |-- light.ambient_rgb: concentration color mapping
        |      |-- light.room_main: eyes-closed dimming, triple-blink toggle
        |
        |--> Umka MQTT Broker (mosquitto:1883)
               |-- umka/kiosks/{slug}/commands/playback: "next" on double blink
```

No new processes, no new WebSocket servers. The HA Bridge is just another Stage consuming existing pipeline output.

## HABridgeStage Implementation

```python
class HABridgeStage(Stage):
    name = "ha_bridge"
    cadence = Cadence.SLOW

    def __init__(self, config: HABridgeConfig):
        # Persistent HA WebSocket connection (async, managed externally)
        # Persistent MQTT client (paho-mqtt)
        # State: current RGB, dimmed flag, alpha baseline, debounce timers
```

### Blink Handler (discrete)
- Receives blink events from `PipelineFrame.events`
- `double_blink` → MQTT publish `umka/kiosks/{slug}/commands/playback` = `"next"`
- `triple_blink` → HA `light.toggle` on `light.room_main`
- Debounce: 2s cooldown for double blink, 3s for triple blink

### Concentration Handler (continuous)
- Reads `ConcentrationResult.concentration_score` (0.0-1.0) each SLOW tick
- Maps to HSV hue: 0.0 → blue (240deg), 1.0 → red (0deg), purple/magenta between
- EMA smoothing (alpha=0.15) on top of existing band power smoothing
- Only sends HA `light.turn_on` when RGB changes by >5 units (avoid flooding)
- HA transition time: 1s per call (smooth fades)

### Eyes-Closed Handler (sustained state)
- Tracks rolling alpha power average across AF7+AF8
- "Eyes closed" = alpha exceeds 2x baseline for >1.5s continuously
- Triggers: HA `light.turn_on` brightness=10, transition=2s
- "Eyes open" = alpha drops below 1.3x baseline
- Restores: HA `light.turn_on` brightness=255, transition=1s (faster restore feels dramatic)
- Hysteresis prevents flicker at threshold boundary
- **Must validate on existing recordings before shipping**

## Command Safety

### Debounce per command type
- Double blink: 2s cooldown after firing
- Triple blink: 3s cooldown
- Eyes-closed dim: 5s minimum before re-triggering after restore
- Concentration color: max 1 HA call/second, >5 unit color change threshold

### Confidence gating
- Blink commands only fire above confidence 0.95
- Eyes-closed requires sustained alpha >1.5s, not a momentary spike
- Concentration must be valid (not NaN, not during poor signal)

### Signal quality gate (master switch)
- `fit_status == "poor"` (3+ bad channels) → **suspend all commands**
- `fit_status == "adjust"` (1-2 bad) → disable continuous controls, keep blinks
- Quality restores → resume with 2s grace period

### Headband state machine

```
ready --(all channels rail)--> headband_off
  ^                                |
  |                          (channels return)
  |                                v
  +---(good fit 3s)----------- fitting
```

- **`headband_off`**: all 4 channels rail (>995uV or <2uV std) for >1s
- **`fitting`**: channels return to normal range, waiting for stable fit
- **`ready`**: `fit_status == "good"` for 3s continuous
- On transition to `ready`: reset alpha baseline, concentration EMA, blink refractory timers
- Kiosk shows state: green=ready, yellow=fitting, grey=off

## Kiosk Display

The existing ZyphraExps frontend at `http://{backend-ip}:3001` opened in the Umka kiosk's browse mode. Shows:

- 3D brain heatmap with ZUNA 23ch (top half — pure wow factor)
- Band power bars and electrode values (bottom half)
- Signal quality / connection status bar

Minor kiosk changes needed to load an external URL in browse mode.

## BrainFlow Battery Patch

Muse 2 sends battery telemetry via BLE GATT characteristic `273e000b` but BrainFlow ignores it. The constant is already defined, the callback is stubbed — just not wired up.

### Changes (~30 lines C++)

**`muse_constants.h`** — already has `MUSE_GATT_ATTR_TELEMETRY` defined. No change.

**`muse.h`** — add member:
```cpp
double last_battery_pct;
```

**`muse.cpp`** — three additions:
1. Free function trampoline (same pattern as all other callbacks):
```cpp
void peripheral_on_telemetry(simpleble_peripheral_t peripheral,
    simpleble_uuid_t service, simpleble_uuid_t characteristic,
    const uint8_t *data, size_t size, void *board) {
    ((Muse*)(board))->peripheral_on_status(peripheral, service,
        characteristic, data, size);
}
```

2. Subscribe in `prepare_session()` (copy-paste from any other characteristic block):
```cpp
if (strcmp(service.characteristics[j].uuid.value,
          MUSE_GATT_ATTR_TELEMETRY) == 0) {
    simpleble_peripheral_notify(muse_peripheral, service.uuid,
        service.characteristics[j].uuid,
        ::peripheral_on_telemetry, (void*)this);
    // non-fatal if subscription fails — battery is optional
}
```

3. Implement `peripheral_on_status()`:
```cpp
void Muse::peripheral_on_status(simpleble_peripheral_t peripheral,
    simpleble_uuid_t service, simpleble_uuid_t characteristic,
    const uint8_t *data, size_t size) {
    if (size < 10) return;
    // Telemetry: 5x uint16 big-endian
    // Index 1 (bytes 2-3) = battery (divide by 512 for percentage)
    uint16_t raw_battery = (data[2] << 8) | data[3];
    last_battery_pct = raw_battery / 512.0;
    // Store in ancillary buffer battery channel
    // ... (write to push_package or store for polling)
}
```

**`brainflow_boards.cpp`** — add `battery_channel` to Muse 2 ancillary preset. Bump `num_rows` from 6 to 7.

### Frontend
- Add battery percentage to dashboard top bar (next to ZUNA toggle and connection indicator)
- Read from metrics JSON (new field from pipeline)

### Alternative: thermistor
The same telemetry characteristic also sends temperature (index 4). Could expose as another channel for free. Low priority but zero extra effort once telemetry is wired.

## Experiments (not shipped in v1)

### Experiment 1: Heart Rate Reliability

**Goal:** Can Muse PPG drive real-time feedback (pulsing light, stress meter)?

**Protocol:**
1. Baseline rest 2min (seated, still)
2. Stand up (expect HR spike ~10-20bpm)
3. 20 jumping jacks (sustained elevation)
4. Sit down, recover 2min (gradual return)
5. Startle test: loud clap at random intervals (brief spikes)

**Metrics:**
- HR latency (seconds after posture change)
- Jitter at rest (bpm std dev over 30s windows)
- Dynamic range (rest-to-exercise delta)
- Ground truth comparison vs smartwatch

**If validated:** HR could drive pulsing light (breathes at heartbeat pace) or color shift on HR elevation.

### Experiment 2: Head Gesture Recognition

**Goal:** Can we detect discrete head gestures from IMU reliably?

**Protocol:**
1. Baseline rest 30s (establish gravity vector)
2. Nod yes: 10 reps, varied speed
3. Shake no: 10 reps, varied speed
4. Tilt left/right: 10 reps, hold 1s each
5. Look up/down: 10 reps
6. Walking (measure motion noise during normal guide movement)

**Metrics:**
- Gesture discrimination accuracy (nod vs shake vs tilt vs walking)
- False positive rate during normal head movement
- Detection latency

**If validated:** Head nod → confirm, head shake → cancel, tilt → select. Alternative to blinks for guides who find blinking awkward.

## Dependencies

- `paho-mqtt` — MQTT client for Umka integration
- `websockets` — already installed, for HA WebSocket API
- Home Assistant instance with RGB light entity + long-lived access token
- Umka MQTT broker (mosquitto)
- BrainFlow source + CMake toolchain (for battery patch)

## Implementation Order

1. **BrainFlow battery patch** — small C++ change, rebuild, validate
2. **Battery on dashboard** — frontend indicator
3. **Eyes-closed detector** — validate on existing recordings first
4. **HABridgeStage** — core integration (blinks + concentration + eyes-closed → HA + MQTT)
5. **Command safety** — debounce, signal quality gate, headband state machine
6. **Kiosk URL** — minor Umka change to load external URL
7. **HR experiment** — recording + analysis
8. **IMU experiment** — recording + analysis

## Not Building

- No two-player support (v2 if ever)
- No guide training sequence (guide already knows)
- No new Umka kiosk mode (just a URL)
- No mobile app
- No heart rate or head gesture controls (experiments first)
