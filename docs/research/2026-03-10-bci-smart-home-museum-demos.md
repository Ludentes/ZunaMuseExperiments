# BCI Smart Home Control & Museum/Demo Installations

**Date:** 2026-03-10
**Purpose:** Research concrete examples of EEG-controlled smart homes, museum exhibits, and public demos. Focus on what works with 4-channel consumer EEG (Muse 2).

---

## 1. EEG + Smart Home Control: Existing Projects

### Braini.io — BCI Smart Home Platform
- Commercial platform: lights, TV, coffee machine, blinds controlled via EEG
- Tested with 12 able-bodied + 2 disabled users
- Uses motor imagery (MI) classification → device commands
- URL: https://www.braini.io/smarthouse-control

### Neuro Photonic R5 Flow Cyberdeck (Muse 2 + Raspberry Pi 5)
- **Exactly our hardware stack.** Creator used Muse 2 + RPi5 in a 3D-printed cyberdeck
- Controls light bulb brightness based on calmness level
- Calmer mind → dimmer bulb; more brain activity → brighter bulb
- Used for meditation practice — reduced bulb to 10% brightness during deep calm
- URL: https://www.xda-developers.com/traspberry-pi-project-control-bulbs-brightness-brain/

### Muse + Arduino LED Control (musearduinoLEDcontrol)
- Python script reads Muse 2014 data via OSC, sends serial commands to Arduino
- Controls 2 LEDs on pins 11 and 13
- Requires Muse-IO streaming to port 5005
- GitHub: https://github.com/them4ra/musearduinoLEDcontrol

### Johns Hopkins ALS Patient — BCI Smart Home
- Implanted BCI (not consumer EEG) controlling home devices for ALS patient
- Demonstrates the end goal; consumer EEG is the affordable approximation
- URL: https://www.hopkinsmedicine.org/news/newsroom/news-releases/2023/11/brain-computer-interface-restores-control-of-home-devices-for-johns-hopkins-patient-with-als

### Matilda / NeuroTechX
- Open-source BCI toolkit; demonstrated turning on lights with brain signals
- Part of NeuroTechX ecosystem
- URL: https://medium.com/neurotechx/you-can-literally-turn-on-the-lights-using-your-mind-matilda-is-not-science-fiction-anymore-c5851b86e6fb

### Academic BCI Smart Home Systems
- Multiple IEEE/Springer papers demonstrate EEG → home appliance control
- Common approach: SSVEP or P300 paradigm to select device, then on/off
- Emotiv Insight used for door locks + LED control for disabled users
- URL: https://www.mdpi.com/2079-9292/8/10/1101

---

## 2. Museum Exhibits Using EEG

### Exploratorium "Cognitive Technologies" (San Francisco) — USED MUSE HEADSETS
- **This is the closest precedent to what we'd build.**
- Used **Muse headbands** donated by InteraXon
- Stations included:
  - **Calibration Station**: Open/close lotus sculptures by shifting mental states (relaxation, excitement, focus)
  - **Illuminated Puzzle**: Solve by concentrating
  - **Robotic Arm Control**: Imagine movement to operate arm
  - **Emotion Training Chair**: Learn to change emotions on demand
  - **Change Your Mind**: EEG + ECG during guided meditation, visual feedback
- Key insight: "The interface has to be easy enough that someone can walk up with no previous knowledge and work the exhibit"
- Collaboration: UC Berkeley neuroscientists + Cognitive Technology group
- URL: https://www.berkeleysciencereview.com/article/2015/02/06/catch-the-brainwave-cognitive-technologies-at-the-exploratorium

### Brainlight Sculpture (Laura Jade + Emotiv)
- Large transparent perspex brain sculpture with neural network engravings
- Emotiv EPOC+ headset → real-time light control inside the sculpture
- **Color mapping:**
  - Theta (3.5-7.5 Hz) → Green (daydreaming, creativity)
  - Alpha (7.5-13 Hz) → Blue (calm, introspection)
  - Beta (16-32 Hz) → Red (alertness, intensity)
- **Audience engagement paradox**: When someone achieves blue (calm), their excitement about it immediately switches to red — people love trying to maintain blue
- Featured on ABC's Catalyst TV show
- Used at Royal Society Summer Science Exhibition
- Tested with musicians (Sydney Art Quartet) — musicians showed theta-dominant patterns vs. audience's alpha/beta variability
- Team: software engineer, neuroscientist, industrial designer, electronics engineer
- URL: https://www.interaliamag.org/articles/laura-jade-brainlight/
- Emotiv writeup: https://www.emotiv.com/blogs/news/brainlight

### The Brainarium
- Planetarium dome displaying real-time EEG data as multimedia
- Uses Brain Machine Interface technologies
- URL: https://pubmed.ncbi.nlm.nih.gov/27698660/

### Art Fund Brain Initiative (UK Museums)
- The Mill (VFX company) interprets EEG signals → 3D real-time brainwave visualizations
- Visitors view art while wearing EEG, see their brain's response visualized

### ARTECHOUSE "Life of a Neuron" (NYC)
- Immersive technology-driven installation covering neural connectivity
- URL: https://www.artechouse.com/program/life-of-a-neuron-nyc/

---

## 3. What Works for Public Audiences (Lessons Learned)

### High-Impact Demo Effects (Ranked by Wow Factor)
1. **Brain-controlled physical objects** — floating ball (Force Trainer), opening lotus flowers, robotic arm. Physical movement > screen visualization.
2. **Color-changing lights mapped to mental state** — immediate, visceral, understandable. Brainlight's theta/alpha/beta → green/blue/red is proven.
3. **Competitive/cooperative brain games** — two people trying to out-concentrate each other.
4. **Meditation challenge** — "make the light dimmer" is intuitive and engaging. The Muse+RPi5 project proved this works.
5. **Music/sound generation** — brain rhythms controlling percussion or ambient soundscapes.

### What Does NOT Work for Public Demos
- Motor imagery (needs training, unreliable on 4ch)
- SSVEP (needs flickering stimuli, uncomfortable, our own experiments confirmed failure on Muse)
- P300 (needs repetitive stimuli presentation)
- Complex multi-step selections (too slow, audience loses interest)
- Anything requiring >30 seconds of calibration

### Critical Design Principles
- **Narrative framing > technical precision.** Star Wars Force Trainer succeeded because "be a Jedi" is compelling. Raw EEG numbers are boring.
- **Manage expectations explicitly.** Children interpret "mind control" literally and get frustrated.
- **Immediate feedback is essential.** Latency > 500ms kills the magic.
- **The feedback loop paradox IS the engagement.** People trying to stay calm and failing is entertaining and educational.
- **Simplify to one axis.** Calm↔Excited (alpha power) or Focused↔Relaxed (theta/beta ratio) — don't show 5 band powers.

### What Muse 2 Can Reliably Do for Demos
Based on our own validated capabilities (from MEMORY.md):
- **Alpha blocking** (eyes open vs closed) — 90-95% reliable, 2.54x validated ratio
- **Concentration/relaxation** via theta/beta ratio — 70-80% reliable
- **Blink detection** — 99% reliable (F1=0.95)
- **Jaw clench** — 95% reliable

---

## 4. Mind-Controlled Toy Legacy (NeuroSky)

### Star Wars Force Trainer & Mattel Mindflex (2009)
- NeuroSky single-channel EEG → "concentration" score (0-100)
- Controlled fan speed to levitate a ball
- **What worked:** The Star Wars narrative wrapper made it magical
- **What failed:** Inconsistency; some claimed it worked without wearing headset
- Force Trainer II (2015) was last product; line dead by 2018
- **Lesson:** Affordable consumer EEG remains too noisy for reliable voluntary control of complex actions, but simple binary thresholds (calm vs. active) work well enough for demos
- NeuroSky dev kits still available ~$130
- Hackable: T/Rx pins on the board allow Arduino integration
- GitHub: https://github.com/kitschpatrol/Brain

---

## 5. Home Assistant Integration (Technical)

### WebSocket API Protocol

Connect to `ws://<HA_IP>:8123/api/websocket`

**Authentication flow:**
```
Server → {"type": "auth_required", "ha_version": "..."}
Client → {"type": "auth", "access_token": "YOUR_LONG_LIVED_TOKEN"}
Server → {"type": "auth_ok", "ha_version": "..."}
```

**Calling a service (e.g., turn on light):**
```json
{
  "id": 24,
  "type": "call_service",
  "domain": "light",
  "service": "turn_on",
  "service_data": {
    "color_name": "beige",
    "brightness": "101"
  },
  "target": {
    "entity_id": "light.kitchen"
  }
}
```

**Other useful services:**
- `light.turn_off` — turn off
- `light.turn_on` with `brightness` (0-255), `rgb_color` [R,G,B], `color_temp` — set color/brightness
- `switch.turn_on` / `switch.turn_off` — switches
- `automation.trigger` — trigger automations

**Subscribe to state changes:**
```json
{
  "id": 18,
  "type": "subscribe_events",
  "event_type": "state_changed"
}
```

**Get all entity states:**
```json
{"id": 1, "type": "get_states"}
```

**Ping/keepalive:**
```json
{"type": "ping"}
→ {"type": "pong"}
```

### Python Libraries
- **homeassistant_api** (PyPI: `HomeAssistant-API`): REST + WebSocket wrapper
  - Docs: https://homeassistantapi.readthedocs.io/
  - GitHub: https://github.com/GrandMoff100/HomeAssistantAPI
  - WebSocket usage: `Client('ws://ha:8123/api/websocket', 'TOKEN')` → `ws_client.trigger_service('light', 'turn_on', entity_id="light.living_room")`
- **Raw websockets**: Use Python `websockets` library for direct protocol control (better for real-time BCI loop)

### Long-Lived Access Token
Create in Home Assistant UI: Profile → Security → Long-Lived Access Tokens → Create Token

### REST API Alternative
```
POST http://<HA_IP>:8123/api/services/light/turn_on
Authorization: Bearer YOUR_TOKEN
Content-Type: application/json
{"entity_id": "light.kitchen", "brightness": 200, "rgb_color": [0, 100, 255]}
```

---

## 6. Practical Architecture: Muse 2 → Home Assistant

### Proposed Pipeline
```
Muse 2 (BLE) → BrainFlow → Python Backend → WebSocket → Home Assistant
                                  ↓
                           Pipeline stages:
                           1. Band power extraction (existing)
                           2. State classifier (calm/focused/excited)
                           3. HA command mapper
                           4. Rate limiter (don't spam HA)
```

### Concrete Demo Ideas for Our Setup

**Demo 1: "Mind Light" — Alpha-Controlled Color**
- Map alpha power to light color: high alpha (calm) → blue, low alpha (alert) → red
- Continuous smooth transition using `rgb_color` in HA
- Matches Brainlight's proven engagement model
- Uses our existing band power pipeline

**Demo 2: "Focus Lamp" — Concentration Dimmer**
- Theta/beta ratio → brightness (0-255)
- High focus → bright, distracted → dim
- Matches the Neuro Photonic R5 Cyberdeck approach
- Simple, immediate, intuitive

**Demo 3: "Blink Switch"**
- Deliberate double/triple blink → toggle light on/off
- Uses our existing BlinkDetector (F1=0.95)
- Most reliable discrete command we have
- Closest to "telekinesis" feeling

**Demo 4: "Meditation Room"**
- Full room automation: lights dim + color shift to blue as user relaxes
- Add ambient sound generation based on brain state
- Multiple HA entities (ceiling light + lamp + LED strip)
- Best for longer demo sessions

### Implementation Priority
1. Demo 3 (Blink Switch) — simplest, most reliable, most impressive
2. Demo 1 (Mind Light) — continuous feedback, proven engagement
3. Demo 2 (Focus Lamp) — good for meditation context
4. Demo 4 (Meditation Room) — requires more HA hardware

---

## Sources

- https://www.braini.io/smarthouse-control
- https://www.xda-developers.com/traspberry-pi-project-control-bulbs-brightness-brain/
- https://github.com/them4ra/musearduinoLEDcontrol
- https://www.berkeleysciencereview.com/article/2015/02/06/catch-the-brainwave-cognitive-technologies-at-the-exploratorium
- https://www.exploratorium.edu/press-office/press-releases/new-exhibition-understanding-influencing-brain-activity-opens
- https://www.interaliamag.org/articles/laura-jade-brainlight/
- https://www.emotiv.com/blogs/news/brainlight
- https://medium.com/neurotechx/you-can-literally-turn-on-the-lights-using-your-mind-matilda-is-not-science-fiction-anymore-c5851b86e6fb
- https://hackaday.com/2026/02/17/the-complicated-legacy-of-mind-controlled-toys/
- https://github.com/kitschpatrol/Brain
- https://developers.home-assistant.io/docs/api/websocket/
- https://homeassistantapi.readthedocs.io/
- https://github.com/GrandMoff100/HomeAssistantAPI
- https://www.mdpi.com/2079-9292/8/10/1101
- https://pubmed.ncbi.nlm.nih.gov/27698660/
- https://www.artechouse.com/program/life-of-a-neuron-nyc/
- https://link.springer.com/chapter/10.1007/978-3-031-42622-3_51
- https://frontiernerds.com/brain-hack
- https://www.hopkinsmedicine.org/news/newsroom/news-releases/2023/11/brain-computer-interface-restores-control-of-home-devices-for-johns-hopkins-patient-with-als
- https://blog.adafruit.com/2016/08/31/eeg-options-for-brain-control-interface-projects/
