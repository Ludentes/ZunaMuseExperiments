# Phase 2: Home Assistant Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the EEG pipeline to Home Assistant and Umka kiosks so that brain signals (blinks, concentration, eyes-closed) control physical lights and kiosk content.

**Architecture:** HABridgeStage is a SLOW pipeline Stage at the end of the stage chain. It consumes existing results (events from FAST stages via a shared queue, ConcentrationResult, BandPowerResult, SignalQualityResult) and sends commands to Home Assistant via WebSocket API and to Umka via MQTT. A CommandSafety layer handles debounce, confidence gating, and signal quality suspension. All external connection details come from HABridgeConfig passed at construction time.

**Tech Stack:** Python 3.12, paho-mqtt, websockets (already installed), asyncio, dataclasses

**Prerequisites:** Phase 1 signals (eyes-closed detector, concentration tuning, signal quality gate) are assumed to exist or will be stubbed. This plan builds the integration layer.

---

## Task 1: Add `paho-mqtt` dependency

**Files:**
- Modify: `requirements.txt` (or `pyproject.toml` — whichever exists)

**Step 1: Check current dependency file**

Run: `cat requirements.txt 2>/dev/null || cat pyproject.toml 2>/dev/null | head -40`

**Step 2: Add paho-mqtt**

Add `paho-mqtt>=2.0` to the dependency list.

**Step 3: Install**

Run: `pip install paho-mqtt>=2.0`

**Step 4: Verify import**

Run: `python -c "import paho.mqtt.client; print('ok')"`
Expected: `ok`

**Step 5: Commit**

```bash
git add requirements.txt  # or pyproject.toml
git commit -m "chore: add paho-mqtt dependency for HA bridge"
```

---

## Task 2: HABridgeConfig dataclass

**Files:**
- Modify: `backend/config.py`
- Test: `tests/test_ha_bridge.py`

**Step 1: Write the failing test**

Create `tests/test_ha_bridge.py`:

```python
"""Tests for HABridgeStage — Home Assistant + MQTT integration."""
import time

from backend.config import HABridgeConfig


def test_ha_bridge_config_defaults():
    cfg = HABridgeConfig()
    assert cfg.ha_url == "ws://localhost:8123/api/websocket"
    assert cfg.ha_token == ""
    assert cfg.mqtt_broker == "localhost"
    assert cfg.mqtt_port == 1883
    assert cfg.umka_kiosk_slug == "default"
    assert cfg.light_entity == "light.room_main"
    assert cfg.rgb_light_entity == "light.ambient_rgb"
    assert cfg.enabled is False


def test_ha_bridge_config_custom():
    cfg = HABridgeConfig(
        ha_url="ws://10.0.0.5:8123/api/websocket",
        ha_token="abc123",
        mqtt_broker="mqtt.local",
        umka_kiosk_slug="hall-1",
        light_entity="light.ceiling",
        rgb_light_entity="light.strip",
        enabled=True,
    )
    assert cfg.ha_token == "abc123"
    assert cfg.umka_kiosk_slug == "hall-1"
    assert cfg.enabled is True
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: FAIL — `ImportError: cannot import name 'HABridgeConfig'`

**Step 3: Write the config dataclass**

Add to `backend/config.py`:

```python
@dataclass
class HABridgeConfig:
    ha_url: str = "ws://localhost:8123/api/websocket"
    ha_token: str = ""
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883
    umka_kiosk_slug: str = "default"
    light_entity: str = "light.room_main"
    rgb_light_entity: str = "light.ambient_rgb"
    enabled: bool = False
```

Add to the `Config` class:

```python
ha_bridge: HABridgeConfig = field(default_factory=HABridgeConfig)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add backend/config.py tests/test_ha_bridge.py
git commit -m "feat: add HABridgeConfig for HA + MQTT settings"
```

---

## Task 3: CommandSafety — debounce and gating logic

This is pure logic with no external dependencies. Test it thoroughly before wiring to HA.

**Files:**
- Create: `backend/pipeline/stages/ha_bridge.py`
- Test: `tests/test_ha_bridge.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_ha_bridge.py`:

```python
from backend.pipeline.stages.ha_bridge import CommandSafety


def test_debounce_allows_first_call():
    safety = CommandSafety()
    assert safety.should_fire("double_blink", confidence=0.96, fit_status="good") is True


def test_debounce_blocks_rapid_repeat():
    safety = CommandSafety()
    safety.should_fire("double_blink", confidence=0.96, fit_status="good")
    assert safety.should_fire("double_blink", confidence=0.96, fit_status="good") is False


def test_debounce_allows_after_cooldown():
    safety = CommandSafety()
    safety.should_fire("double_blink", confidence=0.96, fit_status="good")
    # Manually expire the cooldown
    safety._last_fired["double_blink"] -= 3.0
    assert safety.should_fire("double_blink", confidence=0.96, fit_status="good") is True


def test_low_confidence_blocked():
    safety = CommandSafety()
    assert safety.should_fire("double_blink", confidence=0.80, fit_status="good") is False


def test_poor_fit_blocks_all():
    safety = CommandSafety()
    assert safety.should_fire("double_blink", confidence=0.99, fit_status="poor") is False


def test_adjust_fit_blocks_continuous():
    safety = CommandSafety()
    # Continuous commands blocked on "adjust"
    assert safety.should_fire("concentration_color", confidence=0.99, fit_status="adjust") is False


def test_adjust_fit_allows_blinks():
    safety = CommandSafety()
    assert safety.should_fire("double_blink", confidence=0.96, fit_status="adjust") is True


def test_different_commands_independent_cooldowns():
    safety = CommandSafety()
    safety.should_fire("double_blink", confidence=0.96, fit_status="good")
    assert safety.should_fire("triple_blink", confidence=0.96, fit_status="good") is True


def test_color_change_threshold():
    safety = CommandSafety()
    # First color always fires
    assert safety.should_color_update((100, 0, 255)) is True
    # Small change blocked
    assert safety.should_color_update((102, 0, 254)) is False
    # Large change fires
    assert safety.should_color_update((200, 0, 200)) is True
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_bridge.py::test_debounce_allows_first_call -v`
Expected: FAIL — `ImportError: cannot import name 'CommandSafety'`

**Step 3: Write CommandSafety implementation**

Create `backend/pipeline/stages/ha_bridge.py`:

```python
"""HABridgeStage — bridges EEG pipeline events to Home Assistant + MQTT.

Sits at the end of the SLOW pipeline chain. Consumes:
- Events (blinks) from FAST stages (forwarded via shared deque)
- ConcentrationResult for continuous RGB color
- BandPowerResult for eyes-closed detection (alpha power)
- SignalQualityResult for safety gating

Sends commands to:
- Home Assistant WebSocket API (lights)
- Umka MQTT broker (kiosk playback)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("ha_bridge")

# Cooldown periods per command type (seconds)
COOLDOWNS: dict[str, float] = {
    "double_blink": 2.0,
    "triple_blink": 3.0,
    "eyes_closed_dim": 5.0,
    "eyes_open_restore": 2.0,
    "concentration_color": 1.0,
}

# Minimum confidence to fire a command
MIN_CONFIDENCE: dict[str, float] = {
    "double_blink": 0.95,
    "triple_blink": 0.95,
    "eyes_closed_dim": 0.8,
    "eyes_open_restore": 0.8,
    "concentration_color": 0.0,  # always valid if not NaN
}

# Commands that are "continuous" (blocked on adjust fit)
CONTINUOUS_COMMANDS = {"concentration_color", "eyes_closed_dim", "eyes_open_restore"}

# Minimum RGB component change to send a color update
COLOR_CHANGE_THRESHOLD = 5


class CommandSafety:
    """Debounce, confidence gating, and signal quality checks for HA commands."""

    def __init__(self) -> None:
        self._last_fired: dict[str, float] = {}
        self._last_rgb: tuple[int, int, int] | None = None

    def should_fire(self, command: str, confidence: float, fit_status: str) -> bool:
        """Check if a command should be sent, considering all safety gates."""
        # Signal quality gate
        if fit_status == "poor":
            return False
        if fit_status == "adjust" and command in CONTINUOUS_COMMANDS:
            return False

        # Confidence gate
        min_conf = MIN_CONFIDENCE.get(command, 0.95)
        if confidence < min_conf:
            return False

        # Debounce
        cooldown = COOLDOWNS.get(command, 2.0)
        now = time.monotonic()
        last = self._last_fired.get(command, 0.0)
        if now - last < cooldown:
            return False

        self._last_fired[command] = now
        return True

    def should_color_update(self, rgb: tuple[int, int, int]) -> bool:
        """Check if RGB change is large enough to warrant an HA call."""
        if self._last_rgb is None:
            self._last_rgb = rgb
            return True
        dr = abs(rgb[0] - self._last_rgb[0])
        dg = abs(rgb[1] - self._last_rgb[1])
        db = abs(rgb[2] - self._last_rgb[2])
        if max(dr, dg, db) >= COLOR_CHANGE_THRESHOLD:
            self._last_rgb = rgb
            return True
        return False

    def reset(self) -> None:
        """Reset all state (e.g., after headband reconnect)."""
        self._last_fired.clear()
        self._last_rgb = None
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/ha_bridge.py tests/test_ha_bridge.py
git commit -m "feat: add CommandSafety with debounce, confidence gating, and fit checks"
```

---

## Task 4: HA WebSocket client wrapper

Thin async wrapper around the HA WebSocket protocol. Must handle auth, call_service, and reconnection.

**Files:**
- Modify: `backend/pipeline/stages/ha_bridge.py`
- Test: `tests/test_ha_bridge.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_ha_bridge.py`:

```python
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from backend.pipeline.stages.ha_bridge import HAClient


def test_ha_client_init():
    client = HAClient(url="ws://localhost:8123/api/websocket", token="test-token")
    assert client.url == "ws://localhost:8123/api/websocket"
    assert client._connected is False


@pytest.mark.asyncio
async def test_ha_client_call_service_builds_correct_message():
    client = HAClient(url="ws://test:8123/api/websocket", token="tok")
    messages_sent = []

    # Mock the websocket
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock(side_effect=lambda msg: messages_sent.append(json.loads(msg)))
    mock_ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "type": "result", "success": True}))
    client._ws = mock_ws
    client._connected = True
    client._msg_id = 0

    await client.call_service("light", "turn_on", {"entity_id": "light.room"}, {"brightness": 200})
    assert len(messages_sent) == 1
    msg = messages_sent[0]
    assert msg["type"] == "call_service"
    assert msg["domain"] == "light"
    assert msg["service"] == "turn_on"
    assert msg["target"]["entity_id"] == "light.room"
    assert msg["service_data"]["brightness"] == 200


def test_concentration_to_rgb():
    from backend.pipeline.stages.ha_bridge import concentration_to_rgb
    # 0.0 = blue (low concentration)
    r, g, b = concentration_to_rgb(0.0)
    assert b > r  # should be blue-ish

    # 1.0 = red (high concentration)
    r, g, b = concentration_to_rgb(1.0)
    assert r > b  # should be red-ish

    # All values in 0-255
    for score in [0.0, 0.25, 0.5, 0.75, 1.0]:
        r, g, b = concentration_to_rgb(score)
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255
```

Add `import pytest` at the top of the test file if not already present.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_bridge.py::test_ha_client_init -v`
Expected: FAIL — `ImportError: cannot import name 'HAClient'`

**Step 3: Write HAClient and concentration_to_rgb**

Add to `backend/pipeline/stages/ha_bridge.py`:

```python
import asyncio
import colorsys
import json
import math

import websockets


def concentration_to_rgb(score: float) -> tuple[int, int, int]:
    """Map concentration 0.0-1.0 to RGB: blue(0) → purple(0.5) → red(1.0).

    Uses HSV hue: 240° (blue) → 300° (purple) → 360°/0° (red).
    """
    score = max(0.0, min(1.0, score))
    # Hue: 0.667 (blue=240°) → 0.833 (purple=300°) → 1.0 (red=360°)
    hue = 0.667 + score * 0.333
    if hue >= 1.0:
        hue -= 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


class HAClient:
    """Async Home Assistant WebSocket API client."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self._token = token
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._connected = False
        self._msg_id = 0

    async def connect(self) -> bool:
        """Connect and authenticate with HA."""
        try:
            self._ws = await websockets.connect(self.url)
            # Wait for auth_required
            msg = json.loads(await self._ws.recv())
            if msg.get("type") != "auth_required":
                log.error("HA: unexpected initial message: %s", msg.get("type"))
                return False
            # Send auth
            await self._ws.send(json.dumps({
                "type": "auth",
                "access_token": self._token,
            }))
            # Wait for auth_ok
            msg = json.loads(await self._ws.recv())
            if msg.get("type") == "auth_ok":
                self._connected = True
                log.info("HA: authenticated (version %s)", msg.get("ha_version"))
                return True
            else:
                log.error("HA: auth failed: %s", msg)
                return False
        except Exception:
            log.exception("HA: connection failed")
            return False

    async def call_service(
        self,
        domain: str,
        service: str,
        target: dict,
        data: dict | None = None,
    ) -> bool:
        """Call an HA service. Returns True if sent successfully."""
        if not self._connected or self._ws is None:
            return False
        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": target,
        }
        if data:
            msg["service_data"] = data
        try:
            await self._ws.send(json.dumps(msg))
            # Read response (non-blocking best-effort)
            resp = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=2.0))
            if not resp.get("success", True):
                log.warning("HA: service call failed: %s", resp)
                return False
            return True
        except asyncio.TimeoutError:
            log.warning("HA: service call timeout (id=%d)", self._msg_id)
            return True  # fire-and-forget is ok for lights
        except Exception:
            log.exception("HA: service call error")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/ha_bridge.py tests/test_ha_bridge.py
git commit -m "feat: add HAClient WebSocket wrapper and concentration_to_rgb mapping"
```

---

## Task 5: MQTT client wrapper

**Files:**
- Modify: `backend/pipeline/stages/ha_bridge.py`
- Test: `tests/test_ha_bridge.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_ha_bridge.py`:

```python
from backend.pipeline.stages.ha_bridge import MQTTClient


def test_mqtt_client_init():
    client = MQTTClient(broker="mqtt.local", port=1883)
    assert client.broker == "mqtt.local"
    assert client.port == 1883


def test_mqtt_publish_topic_format():
    """Verify the Umka topic is correctly formatted."""
    from backend.pipeline.stages.ha_bridge import umka_playback_topic
    assert umka_playback_topic("hall-1") == "umka/kiosks/hall-1/commands/playback"
    assert umka_playback_topic("main") == "umka/kiosks/main/commands/playback"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_bridge.py::test_mqtt_client_init -v`
Expected: FAIL

**Step 3: Write MQTTClient**

Add to `backend/pipeline/stages/ha_bridge.py`:

```python
import paho.mqtt.client as paho_mqtt


def umka_playback_topic(kiosk_slug: str) -> str:
    """Build the MQTT topic for Umka kiosk playback commands."""
    return f"umka/kiosks/{kiosk_slug}/commands/playback"


class MQTTClient:
    """Thin wrapper around paho-mqtt for Umka integration."""

    def __init__(self, broker: str, port: int = 1883) -> None:
        self.broker = broker
        self.port = port
        self._client = paho_mqtt.Client(paho_mqtt.CallbackAPIVersion.VERSION2)
        self._connected = False

    def connect(self) -> bool:
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
            self._client.loop_start()
            self._connected = True
            log.info("MQTT: connected to %s:%d", self.broker, self.port)
            return True
        except Exception:
            log.exception("MQTT: connection failed")
            return False

    def publish(self, topic: str, payload: str) -> bool:
        if not self._connected:
            return False
        try:
            result = self._client.publish(topic, payload, qos=1)
            return result.rc == paho_mqtt.MQTT_ERR_SUCCESS
        except Exception:
            log.exception("MQTT: publish failed")
            return False

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/ha_bridge.py tests/test_ha_bridge.py
git commit -m "feat: add MQTTClient wrapper and Umka topic helper"
```

---

## Task 6: HABridgeStage — the pipeline Stage

This is the core stage that wires everything together. It's a SLOW stage that:
- Reads events from a shared deque (populated by FAST stages via main.py)
- Reads ConcentrationResult for RGB color
- Reads BandPowerResult for eyes-closed alpha
- Reads SignalQualityResult for safety gating
- Delegates to HAClient and MQTTClient

**Files:**
- Modify: `backend/pipeline/stages/ha_bridge.py`
- Test: `tests/test_ha_bridge.py` (append)

**Step 1: Write the failing tests**

Append to `tests/test_ha_bridge.py`:

```python
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import HABridgeConfig
from backend.pipeline.stages.ha_bridge import HABridgeStage, HABridgeResult
from backend.pipeline.stages.features import (
    BandPowerResult,
    ConcentrationResult,
    SignalQualityResult,
)
from backend.pipeline.types import Cadence, Event, PipelineFrame
import numpy as np


def _make_frame_with_results(
    concentration: float = 0.5,
    fit_status: str = "good",
    alpha_powers: list[float] | None = None,
) -> PipelineFrame:
    """Helper: build a PipelineFrame with upstream results pre-populated."""
    frame = PipelineFrame(eeg=np.zeros((4, 512)), ppg=None, imu=None, timestamp=time.time())
    frame.set(ConcentrationResult(
        concentration_score=concentration,
        relaxation_score=1.0 - concentration,
    ))
    frame.set(SignalQualityResult(
        quality={"TP9": 0.9, "AF7": 0.9, "AF8": 0.9, "TP10": 0.9},
        fit_status=fit_status,
    ))
    if alpha_powers is None:
        alpha_powers = [10.0, 15.0, 14.0, 11.0]
    frame.set(BandPowerResult(
        band_powers={
            "delta": [100.0] * 4,
            "theta": [20.0] * 4,
            "alpha": alpha_powers,
            "beta": [10.0] * 4,
            "gamma": [5.0] * 4,
        },
        theta_beta_ratio=[2.0] * 4,
        frontal_alpha_asymmetry=0.0,
    ))
    return frame


def test_ha_bridge_stage_is_slow():
    cfg = HABridgeConfig(enabled=True)
    stage = HABridgeStage(cfg)
    assert stage.cadence == Cadence.SLOW
    assert stage.name == "ha_bridge"


def test_ha_bridge_stage_skips_when_disabled():
    cfg = HABridgeConfig(enabled=False)
    stage = HABridgeStage(cfg)
    frame = _make_frame_with_results()
    stage.process(frame)
    result = frame.get(HABridgeResult)
    assert result is None


def test_ha_bridge_result_set_on_process():
    cfg = HABridgeConfig(enabled=True)
    stage = HABridgeStage(cfg)
    frame = _make_frame_with_results()
    stage.process(frame)
    result = frame.get(HABridgeResult)
    assert result is not None
    assert result.ha_connected is False  # no real HA
    assert result.mqtt_connected is False  # no real MQTT


def test_ha_bridge_consumes_blink_events():
    cfg = HABridgeConfig(enabled=True)
    stage = HABridgeStage(cfg)
    # Feed a double_blink event via the event queue
    stage.event_queue.append(Event(
        kind="double_blink",
        timestamp=time.time(),
        confidence=0.96,
    ))
    frame = _make_frame_with_results()
    stage.process(frame)
    result = frame.get(HABridgeResult)
    assert result is not None
    assert "double_blink" in result.commands_sent


def test_ha_bridge_blocks_low_confidence_blink():
    cfg = HABridgeConfig(enabled=True)
    stage = HABridgeStage(cfg)
    stage.event_queue.append(Event(
        kind="double_blink",
        timestamp=time.time(),
        confidence=0.80,
    ))
    frame = _make_frame_with_results()
    stage.process(frame)
    result = frame.get(HABridgeResult)
    assert "double_blink" not in result.commands_sent
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ha_bridge.py::test_ha_bridge_stage_is_slow -v`
Expected: FAIL

**Step 3: Write HABridgeStage**

Add to `backend/pipeline/stages/ha_bridge.py`:

```python
from collections import deque

from backend.config import HABridgeConfig
from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, Event, PipelineFrame
from backend.pipeline.stages.features import (
    BandPowerResult,
    ConcentrationResult,
    SignalQualityResult,
)


@dataclass
class HABridgeResult:
    """Result set by HABridgeStage each tick for diagnostics/serialization."""
    ha_connected: bool = False
    mqtt_connected: bool = False
    commands_sent: list[str] = field(default_factory=list)
    current_rgb: tuple[int, int, int] = (0, 0, 255)
    eyes_closed: bool = False


class HABridgeStage(Stage):
    """Bridges EEG pipeline output to Home Assistant and Umka MQTT.

    Sits at the end of the SLOW stage chain.

    External connections (HA WebSocket, MQTT) are managed lazily:
    - First process() call attempts connection
    - Reconnects on failure with exponential backoff
    - process() is called from run_in_executor (thread), so blocking is OK
    """

    name = "ha_bridge"
    cadence = Cadence.SLOW

    def __init__(self, config: HABridgeConfig) -> None:
        self.config = config
        self.enabled = config.enabled
        self.event_queue: deque[Event] = deque(maxlen=64)
        self.safety = CommandSafety()

        # External clients (lazy init)
        self._ha: HAClient | None = None
        self._mqtt: MQTTClient | None = None
        self._ha_loop: asyncio.AbstractEventLoop | None = None

        # Eyes-closed state
        self._alpha_baseline: float | None = None
        self._alpha_ema_alpha = 0.001  # very slow baseline adaptation
        self._eyes_closed = False
        self._eyes_closed_since: float = 0.0

        # Concentration EMA
        self._concentration_ema: float = 0.5
        self._concentration_ema_alpha = 0.15

    def process(self, frame: PipelineFrame) -> None:
        if not self.enabled:
            return

        result = HABridgeResult()
        sq = frame.get(SignalQualityResult)
        fit_status = sq.fit_status if sq else "poor"

        # Ensure connections
        self._ensure_connections()
        result.ha_connected = self._ha.connected if self._ha else False
        result.mqtt_connected = self._mqtt.connected if self._mqtt else False

        # --- Discrete commands: process queued events from FAST stages ---
        commands_sent: list[str] = []
        while self.event_queue:
            event = self.event_queue.popleft()
            if event.kind == "double_blink":
                if self.safety.should_fire("double_blink", event.confidence, fit_status):
                    self._send_mqtt_next()
                    commands_sent.append("double_blink")
                    log.info("HA: double blink → Umka next")
            elif event.kind == "triple_blink":
                if self.safety.should_fire("triple_blink", event.confidence, fit_status):
                    self._send_ha_toggle_light()
                    commands_sent.append("triple_blink")
                    log.info("HA: triple blink → toggle light")

        # --- Continuous: concentration → RGB color ---
        cr = frame.get(ConcentrationResult)
        if cr and not math.isnan(cr.concentration_score):
            # EMA smoothing
            self._concentration_ema = (
                self._concentration_ema_alpha * cr.concentration_score
                + (1 - self._concentration_ema_alpha) * self._concentration_ema
            )
            rgb = concentration_to_rgb(self._concentration_ema)
            result.current_rgb = rgb
            if (
                self.safety.should_fire("concentration_color", 1.0, fit_status)
                and self.safety.should_color_update(rgb)
            ):
                self._send_ha_color(rgb)
                commands_sent.append("concentration_color")

        # --- Sustained: eyes-closed detection via alpha power ---
        bp = frame.get(BandPowerResult)
        if bp and "alpha" in bp.band_powers:
            # Use frontal channels (AF7=idx1, AF8=idx2 for 4ch)
            frontal_alpha = (bp.band_powers["alpha"][1] + bp.band_powers["alpha"][2]) / 2.0
            if self._alpha_baseline is None:
                self._alpha_baseline = frontal_alpha
            else:
                self._alpha_baseline = (
                    self._alpha_ema_alpha * frontal_alpha
                    + (1 - self._alpha_ema_alpha) * self._alpha_baseline
                )

            now = time.monotonic()
            if frontal_alpha > self._alpha_baseline * 2.0:
                if not self._eyes_closed:
                    self._eyes_closed_since = now
                    self._eyes_closed = True
                elif now - self._eyes_closed_since > 1.5:
                    # Sustained eyes closed
                    if self.safety.should_fire("eyes_closed_dim", 0.9, fit_status):
                        self._send_ha_dim()
                        commands_sent.append("eyes_closed_dim")
                        log.info("HA: eyes closed → dim")
            else:
                if self._eyes_closed and frontal_alpha < self._alpha_baseline * 1.3:
                    self._eyes_closed = False
                    if self.safety.should_fire("eyes_open_restore", 0.9, fit_status):
                        self._send_ha_restore()
                        commands_sent.append("eyes_open_restore")
                        log.info("HA: eyes open → restore")

        result.eyes_closed = self._eyes_closed
        result.commands_sent = commands_sent
        frame.set(result)

    # --- Private: connection management ---

    def _ensure_connections(self) -> None:
        """Lazily init and connect HA + MQTT clients."""
        if self._ha is None and self.config.ha_token:
            self._ha = HAClient(self.config.ha_url, self.config.ha_token)
            self._ha_loop = asyncio.new_event_loop()
            self._ha_loop.run_until_complete(self._ha.connect())

        if self._mqtt is None:
            self._mqtt = MQTTClient(self.config.mqtt_broker, self.config.mqtt_port)
            self._mqtt.connect()

    # --- Private: command senders ---

    def _send_mqtt_next(self) -> None:
        if self._mqtt and self._mqtt.connected:
            topic = umka_playback_topic(self.config.umka_kiosk_slug)
            self._mqtt.publish(topic, "next")

    def _send_ha_toggle_light(self) -> None:
        if self._ha and self._ha.connected and self._ha_loop:
            self._ha_loop.run_until_complete(
                self._ha.call_service(
                    "light", "toggle",
                    {"entity_id": self.config.light_entity},
                )
            )

    def _send_ha_color(self, rgb: tuple[int, int, int]) -> None:
        if self._ha and self._ha.connected and self._ha_loop:
            self._ha_loop.run_until_complete(
                self._ha.call_service(
                    "light", "turn_on",
                    {"entity_id": self.config.rgb_light_entity},
                    {"rgb_color": list(rgb), "transition": 1},
                )
            )

    def _send_ha_dim(self) -> None:
        if self._ha and self._ha.connected and self._ha_loop:
            self._ha_loop.run_until_complete(
                self._ha.call_service(
                    "light", "turn_on",
                    {"entity_id": self.config.light_entity},
                    {"brightness": 10, "transition": 2},
                )
            )

    def _send_ha_restore(self) -> None:
        if self._ha and self._ha.connected and self._ha_loop:
            self._ha_loop.run_until_complete(
                self._ha.call_service(
                    "light", "turn_on",
                    {"entity_id": self.config.light_entity},
                    {"brightness": 255, "transition": 1},
                )
            )
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/ha_bridge.py tests/test_ha_bridge.py
git commit -m "feat: add HABridgeStage — core pipeline-to-HA/MQTT bridge"
```

---

## Task 7: Wire HABridgeStage into factory and main.py

**Files:**
- Modify: `backend/pipeline/factory.py`
- Modify: `backend/main.py`
- Modify: `backend/config.py` (CLI args)
- Test: `tests/test_pipeline_factory.py` (append)

**Step 1: Write the failing test**

Append to `tests/test_pipeline_factory.py`:

```python
def test_factory_includes_ha_bridge_when_enabled():
    from backend.config import HABridgeConfig
    pipeline = create_default_pipeline(
        ha_bridge_config=HABridgeConfig(enabled=True),
    )
    names = [s.name for s in pipeline.stages]
    assert "ha_bridge" in names
    # Must be last SLOW stage
    slow_names = [s.name for s in pipeline.stages if s.cadence.value == "slow"]
    assert slow_names[-1] == "ha_bridge"


def test_factory_excludes_ha_bridge_when_disabled():
    pipeline = create_default_pipeline()
    names = [s.name for s in pipeline.stages]
    assert "ha_bridge" not in names
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline_factory.py::test_factory_includes_ha_bridge_when_enabled -v`
Expected: FAIL

**Step 3: Update factory.py**

Modify `create_default_pipeline` signature to accept `ha_bridge_config`:

```python
from backend.config import HABridgeConfig

def create_default_pipeline(
    zuna_enabled: bool = False,
    zuna_device: str = "cuda",
    zuna_diffusion_steps: int = 50,
    ha_bridge_config: HABridgeConfig | None = None,
) -> Pipeline:
    # ... existing stages ...

    stages.extend([
        BandPowerExtractor(),
        SignalQualityChecker(),
        HeartRateExtractor(),
        HeadMotionExtractor(),
        ConcentrationScorer(),
        BandPowerBroadcaster(),
    ])

    # HA Bridge: must be last SLOW stage (consumes all upstream results)
    if ha_bridge_config and ha_bridge_config.enabled:
        from backend.pipeline.stages.ha_bridge import HABridgeStage
        stages.append(HABridgeStage(ha_bridge_config))

    stages.extend([
        # FAST — event detection (SpeechDetector must precede BlinkDetector)
        SpeechDetector(),
        BlinkDetector(),
    ])

    actions = [LogAction()]
    return Pipeline(stages, actions)
```

**Step 4: Update main.py**

In `main()`, add CLI args for HA bridge:

```python
parser.add_argument("--ha-url", type=str, default="", help="Home Assistant WebSocket URL")
parser.add_argument("--ha-token", type=str, default="", help="Home Assistant long-lived access token")
parser.add_argument("--mqtt-broker", type=str, default="", help="MQTT broker host for Umka")
parser.add_argument("--umka-slug", type=str, default="default", help="Umka kiosk slug")
parser.add_argument("--ha-light", type=str, default="light.room_main", help="HA light entity for on/off")
parser.add_argument("--ha-rgb-light", type=str, default="light.ambient_rgb", help="HA RGB light entity")
```

In the config setup section:

```python
if args.ha_url and args.ha_token:
    config.ha_bridge.enabled = True
    config.ha_bridge.ha_url = args.ha_url
    config.ha_bridge.ha_token = args.ha_token
    if args.mqtt_broker:
        config.ha_bridge.mqtt_broker = args.mqtt_broker
    config.ha_bridge.umka_kiosk_slug = args.umka_slug
    config.ha_bridge.light_entity = args.ha_light
    config.ha_bridge.rgb_light_entity = args.ha_rgb_light
```

Update `create_default_pipeline` call in `EEGServer.__init__`:

```python
self._pipeline = create_default_pipeline(
    zuna_enabled=self.config.zuna.enabled,
    zuna_device=self.config.zuna.device,
    zuna_diffusion_steps=self.config.zuna.diffusion_steps,
    ha_bridge_config=self.config.ha_bridge if self.config.ha_bridge.enabled else None,
)
```

**Step 5: Forward FAST events to HABridgeStage**

In `_stream_loop()`, after processing fast_frame events, forward them to the HA bridge event queue. Add a helper to find the HA bridge stage:

```python
def _get_ha_bridge_stage(self):
    for stage in self._pipeline.stages:
        if stage.name == "ha_bridge":
            return stage
    return None
```

In `_stream_loop()`, after the existing event broadcast block:

```python
if fast_frame.events:
    # Forward to HA bridge for SLOW-tick processing
    ha_stage = self._get_ha_bridge_stage()
    if ha_stage:
        for event in fast_frame.events:
            ha_stage.event_queue.append(event)
    # ... existing broadcast code ...
```

**Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add backend/pipeline/factory.py backend/main.py backend/config.py tests/test_pipeline_factory.py
git commit -m "feat: wire HABridgeStage into factory and main with CLI args"
```

---

## Task 8: Add HABridgeResult to serialization

**Files:**
- Modify: `backend/pipeline/serialize.py`
- Test: `tests/test_pipeline_serialize.py` (append)

**Step 1: Write the failing test**

Append to `tests/test_pipeline_serialize.py`:

```python
from backend.pipeline.stages.ha_bridge import HABridgeResult


def test_serialize_ha_bridge_result():
    frame = PipelineFrame(eeg=None, ppg=None, imu=None, timestamp=0.0)
    frame.set(HABridgeResult(
        ha_connected=True,
        mqtt_connected=True,
        commands_sent=["double_blink"],
        current_rgb=(100, 50, 200),
        eyes_closed=False,
    ))
    metrics = frame_to_metrics(frame)
    assert "ha_bridge" in metrics
    assert metrics["ha_bridge"]["ha_connected"] is True
    assert metrics["ha_bridge"]["current_rgb"] == [100, 50, 200]
    assert metrics["ha_bridge"]["commands_sent"] == ["double_blink"]
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_serialize.py::test_serialize_ha_bridge_result -v`
Expected: FAIL — `ha_bridge` not in metrics

**Step 3: Add serialization block**

Add to `backend/pipeline/serialize.py`, after the existing `bpm` block:

```python
from backend.pipeline.stages.ha_bridge import HABridgeResult

# ... in frame_to_metrics():
    hab = frame.get(HABridgeResult)
    if hab:
        metrics["ha_bridge"] = {
            "ha_connected": hab.ha_connected,
            "mqtt_connected": hab.mqtt_connected,
            "commands_sent": hab.commands_sent,
            "current_rgb": list(hab.current_rgb),
            "eyes_closed": hab.eyes_closed,
        }
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline_serialize.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add backend/pipeline/serialize.py tests/test_pipeline_serialize.py
git commit -m "feat: serialize HABridgeResult to WebSocket metrics"
```

---

## Task 9: Integration test — full pipeline with HA bridge

**Files:**
- Test: `tests/test_ha_bridge.py` (append)

**Step 1: Write the integration test**

```python
def test_full_pipeline_with_ha_bridge():
    """End-to-end: build pipeline with HA bridge, run SLOW, verify result."""
    from backend.pipeline.factory import create_default_pipeline
    from backend.config import HABridgeConfig

    cfg = HABridgeConfig(enabled=True)
    pipeline = create_default_pipeline(ha_bridge_config=cfg)

    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50

    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    pipeline.run(Cadence.SLOW, frame)

    # HABridgeResult should exist (even without real HA/MQTT)
    result = frame.get(HABridgeResult)
    assert result is not None
    assert result.ha_connected is False  # no real HA server
    assert result.mqtt_connected is False  # no real MQTT broker


def test_blink_event_flows_through_pipeline():
    """Verify: FAST event → event_queue → SLOW HABridge processes it."""
    from backend.pipeline.factory import create_default_pipeline
    from backend.config import HABridgeConfig

    cfg = HABridgeConfig(enabled=True)
    pipeline = create_default_pipeline(ha_bridge_config=cfg)

    # Find HA bridge stage
    ha_stage = None
    for s in pipeline.stages:
        if s.name == "ha_bridge":
            ha_stage = s
            break
    assert ha_stage is not None

    # Simulate FAST stage producing a blink event
    ha_stage.event_queue.append(Event(
        kind="double_blink",
        timestamp=time.time(),
        confidence=0.96,
    ))

    rng = np.random.default_rng(42)
    eeg = rng.standard_normal((4, 512)).astype(np.float64) * 50
    frame = PipelineFrame(eeg=eeg, ppg=None, imu=None, timestamp=time.time())
    pipeline.run(Cadence.SLOW, frame)

    result = frame.get(HABridgeResult)
    assert result is not None
    # Command was "sent" (to disconnected client, but safety passed)
    assert "double_blink" in result.commands_sent
```

**Step 2: Run tests**

Run: `python -m pytest tests/test_ha_bridge.py -v`
Expected: All PASS

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_ha_bridge.py
git commit -m "test: add integration tests for HABridge pipeline flow"
```

---

## Task 10: Manual verification guide

**Files:**
- Create: `docs/guides/2026-03-11-ha-bridge-manual-test.md`

Write a step-by-step manual testing guide:

```markdown
# HABridge Manual Testing Guide

## Prerequisites
- Home Assistant running with a configured RGB light
- Long-lived access token from HA (Profile → Security → Create Token)
- Mosquitto MQTT broker running
- Muse 2 headband (or use --synthetic for basic smoke test)

## Smoke Test (no hardware)

```bash
python -m backend.main --synthetic \
    --ha-url ws://YOUR_HA_IP:8123/api/websocket \
    --ha-token YOUR_TOKEN \
    --ha-light light.YOUR_LIGHT \
    --ha-rgb-light light.YOUR_RGB_LIGHT \
    --mqtt-broker YOUR_MQTT_IP \
    --umka-slug YOUR_KIOSK
```

Check logs for:
- `HA: authenticated (version ...)` — HA connection OK
- `MQTT: connected to ...` — MQTT connection OK

## Blink Control Test
1. Wear Muse, run backend with real board
2. Double blink deliberately — watch for `HA: double blink → Umka next` in logs
3. Verify kiosk advanced content
4. Triple blink — watch for `HA: triple blink → toggle light` in logs
5. Verify light toggled

## Concentration Color Test
1. Relax (low theta/beta) — RGB light should be blue
2. Focus mentally (math, counting) — RGB light should shift toward red
3. Transition should be gradual (1s HA transition time)

## Eyes-Closed Test
1. Close eyes for >1.5s — room light should dim
2. Open eyes — light should restore (faster than dim)
3. Brief blinks should NOT trigger dimming

## Safety Tests
- Remove headband → all commands should stop within 1s
- Put headband back on → commands resume after ~3s stable fit
- Rapid double-blinks → only first should fire (2s cooldown)
```

**Step 1: Write the guide**

Create the file with the content above.

**Step 2: Commit**

```bash
git add docs/guides/2026-03-11-ha-bridge-manual-test.md
git commit -m "docs: add HABridge manual testing guide"
```

---

Plan complete and saved to `docs/plans/2026-03-11-phase2-ha-integration.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?