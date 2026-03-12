# Phase 2: Umka MQTT Bridge — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the BCI pipeline to Umka's museum kiosks and IoT lights via direct MQTT, so blinks control kiosk playback, concentration drives light color, and eyes-closed dims lights.

**Architecture:** A single `UmkaBridgeStage` (SLOW cadence) reads pipeline results (events, ConcentrationResult, EyesClosedResult) and publishes MQTT commands to Umka's Mosquitto broker. No Home Assistant. No WebSocket API. Direct MQTT topics only.

**Tech Stack:** `paho-mqtt` (already proven in Umka's `publish_discovery.py`), Python dataclasses for config, existing pipeline Stage ABC.

**Key MQTT Topics (from Umka docs):**
- Kiosk playback: `umka/kiosks/{slug}/commands/playback` → `{"action": "next"}`
- IoT toggle: `museum/{museum}/iot/{id}/command` → `{"action": "toggle"}`
- IoT color: `museum/{museum}/iot/{id}/command` → `{"action": "color", "value": "#RRGGBB"}`
- IoT brightness: `museum/{museum}/iot/{id}/command` → `{"action": "brightness", "value": N}`

---

### Task 1: Add paho-mqtt dependency

**Files:**
- Modify: `pyproject.toml` (or `requirements.txt` — whichever exists)

**Step 1: Check current dependency file**

Run: `ls pyproject.toml requirements.txt 2>/dev/null`

**Step 2: Add paho-mqtt**

Add `paho-mqtt>=2.0` to the project dependencies.

**Step 3: Install**

Run: `pip install paho-mqtt>=2.0`

**Step 4: Verify import works**

Run: `python -c "import paho.mqtt.client as mqtt; print(mqtt.CallbackAPIVersion.VERSION2)"`
Expected: `CallbackAPIVersion.VERSION2`

**Step 5: Commit**

```bash
git add pyproject.toml  # or requirements.txt
git commit -m "feat: add paho-mqtt dependency for Umka bridge"
```

---

### Task 2: UmkaBridgeConfig + CommandSafety

**Files:**
- Modify: `backend/config.py`
- Create: `backend/pipeline/stages/umka_bridge.py`
- Create: `tests/test_umka_bridge.py`

**Step 1: Write the failing tests**

```python
# tests/test_umka_bridge.py
"""Tests for Umka MQTT bridge."""

import pytest
from backend.config import UmkaBridgeConfig, Config


class TestUmkaBridgeConfig:
    def test_defaults(self):
        cfg = UmkaBridgeConfig()
        assert cfg.broker_host == "192.168.87.102"
        assert cfg.broker_port == 41883
        assert cfg.kiosk_slug == "kiosk-1-1"
        assert cfg.museum_id == "1"
        assert cfg.light_ids == []
        assert cfg.enabled is False

    def test_config_has_umka_field(self):
        cfg = Config()
        assert hasattr(cfg, "umka")
        assert isinstance(cfg.umka, UmkaBridgeConfig)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_umka_bridge.py::TestUmkaBridgeConfig -v`
Expected: FAIL — `UmkaBridgeConfig` not found

**Step 3: Add UmkaBridgeConfig to config.py**

Add to `backend/config.py`:

```python
@dataclass
class UmkaBridgeConfig:
    enabled: bool = False
    broker_host: str = "192.168.87.102"
    broker_port: int = 41883
    kiosk_slug: str = "kiosk-1-1"
    museum_id: str = "1"
    light_ids: list[str] = field(default_factory=list)  # IoT device IDs for lights
```

Add `umka` field to `Config`:

```python
@dataclass
class Config:
    board: BoardConfig = field(default_factory=BoardConfig)
    filter: FilterConfig = field(default_factory=FilterConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    zuna: ZunaConfig = field(default_factory=ZunaConfig)
    umka: UmkaBridgeConfig = field(default_factory=UmkaBridgeConfig)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_umka_bridge.py::TestUmkaBridgeConfig -v`
Expected: PASS

**Step 5: Write CommandSafety tests**

Add to `tests/test_umka_bridge.py`:

```python
import time
from unittest.mock import patch
from backend.pipeline.stages.umka_bridge import CommandSafety


class TestCommandSafety:
    def test_allows_first_command(self):
        safety = CommandSafety(debounce_sec=1.0, min_confidence=0.8)
        assert safety.allow("toggle", confidence=0.9) is True

    def test_debounce_blocks_rapid_repeat(self):
        safety = CommandSafety(debounce_sec=1.0, min_confidence=0.8)
        safety.allow("toggle", confidence=0.9)
        assert safety.allow("toggle", confidence=0.9) is False

    def test_debounce_allows_after_cooldown(self):
        safety = CommandSafety(debounce_sec=0.1, min_confidence=0.8)
        safety.allow("toggle", confidence=0.9)
        time.sleep(0.15)
        assert safety.allow("toggle", confidence=0.9) is True

    def test_low_confidence_blocked(self):
        safety = CommandSafety(debounce_sec=1.0, min_confidence=0.8)
        assert safety.allow("toggle", confidence=0.5) is False

    def test_different_commands_independent_debounce(self):
        safety = CommandSafety(debounce_sec=1.0, min_confidence=0.8)
        safety.allow("toggle", confidence=0.9)
        assert safety.allow("next_kiosk", confidence=0.9) is True

    def test_suspended_blocks_all(self):
        safety = CommandSafety(debounce_sec=0.0, min_confidence=0.0)
        safety.suspend()
        assert safety.allow("toggle", confidence=1.0) is False

    def test_resume_after_suspend(self):
        safety = CommandSafety(debounce_sec=0.0, min_confidence=0.0)
        safety.suspend()
        safety.resume()
        assert safety.allow("toggle", confidence=1.0) is True
```

**Step 6: Run tests to verify they fail**

Run: `python -m pytest tests/test_umka_bridge.py::TestCommandSafety -v`
Expected: FAIL — `CommandSafety` not found

**Step 7: Implement CommandSafety**

Create `backend/pipeline/stages/umka_bridge.py`:

```python
"""Umka MQTT bridge — connects BCI pipeline to museum kiosks and IoT lights."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger("umka_bridge")


class CommandSafety:
    """Debounce + confidence gating for BCI → MQTT commands."""

    def __init__(self, debounce_sec: float = 2.0, min_confidence: float = 0.8):
        self.debounce_sec = debounce_sec
        self.min_confidence = min_confidence
        self._last_fired: dict[str, float] = {}
        self._suspended = False

    def allow(self, command: str, confidence: float) -> bool:
        if self._suspended:
            return False
        if confidence < self.min_confidence:
            return False
        now = time.monotonic()
        last = self._last_fired.get(command, 0.0)
        if now - last < self.debounce_sec:
            return False
        self._last_fired[command] = now
        return True

    def suspend(self) -> None:
        self._suspended = True

    def resume(self) -> None:
        self._suspended = False
```

**Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_umka_bridge.py -v`
Expected: ALL PASS

**Step 9: Commit**

```bash
git add backend/config.py backend/pipeline/stages/umka_bridge.py tests/test_umka_bridge.py
git commit -m "feat: add UmkaBridgeConfig and CommandSafety"
```

---

### Task 3: MQTTClient wrapper

**Files:**
- Modify: `backend/pipeline/stages/umka_bridge.py`
- Modify: `tests/test_umka_bridge.py`

**Step 1: Write failing tests**

Add to `tests/test_umka_bridge.py`:

```python
from unittest.mock import MagicMock, patch
from backend.pipeline.stages.umka_bridge import MQTTClient
from backend.config import UmkaBridgeConfig


class TestMQTTClient:
    def test_connect_calls_paho(self):
        cfg = UmkaBridgeConfig(broker_host="localhost", broker_port=1883)
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            mock_instance.connect.assert_called_once_with("localhost", 1883)
            mock_instance.loop_start.assert_called_once()

    def test_publish_sends_json(self):
        cfg = UmkaBridgeConfig(broker_host="localhost", broker_port=1883)
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.publish("test/topic", {"action": "toggle"})
            mock_instance.publish.assert_called_once()
            call_args = mock_instance.publish.call_args
            assert call_args[0][0] == "test/topic"
            assert b'"action"' in call_args[0][1]

    def test_disconnect(self):
        cfg = UmkaBridgeConfig(broker_host="localhost", broker_port=1883)
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.disconnect()
            mock_instance.loop_stop.assert_called_once()
            mock_instance.disconnect.assert_called_once()

    def test_kiosk_next(self):
        cfg = UmkaBridgeConfig(kiosk_slug="kiosk-1-1")
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.kiosk_next()
            call_args = mock_instance.publish.call_args
            assert call_args[0][0] == "umka/kiosks/kiosk-1-1/commands/playback"
            assert b'"next"' in call_args[0][1]

    def test_light_toggle(self):
        cfg = UmkaBridgeConfig(museum_id="1")
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.light_toggle("42")
            call_args = mock_instance.publish.call_args
            assert call_args[0][0] == "museum/1/iot/42/command"
            assert b'"toggle"' in call_args[0][1]

    def test_light_color(self):
        cfg = UmkaBridgeConfig(museum_id="1")
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.light_color("42", "#FF8800")
            call_args = mock_instance.publish.call_args
            assert call_args[0][0] == "museum/1/iot/42/command"
            assert b'"color"' in call_args[0][1]
            assert b'"#FF8800"' in call_args[0][1]

    def test_light_brightness(self):
        cfg = UmkaBridgeConfig(museum_id="1")
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            client = MQTTClient(cfg)
            client.connect()
            client.light_brightness("42", 10)
            call_args = mock_instance.publish.call_args
            assert call_args[0][0] == "museum/1/iot/42/command"
            assert b'"brightness"' in call_args[0][1]
            assert b"10" in call_args[0][1]
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_umka_bridge.py::TestMQTTClient -v`
Expected: FAIL — `MQTTClient` not found

**Step 3: Implement MQTTClient**

Add to `backend/pipeline/stages/umka_bridge.py`:

```python
import json
import paho.mqtt.client as mqtt
from backend.config import UmkaBridgeConfig


class MQTTClient:
    """Thin wrapper around paho-mqtt for Umka's MQTT API."""

    def __init__(self, config: UmkaBridgeConfig):
        self.config = config
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="zyphra-bci-bridge",
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        log.info("MQTT connected to %s:%d", self.config.broker_host, self.config.broker_port)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        log.info("MQTT disconnected (rc=%s)", rc)

    def connect(self) -> None:
        self._client.connect(self.config.broker_host, self.config.broker_port)
        self._client.loop_start()

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, topic: str, payload: dict) -> None:
        self._client.publish(topic, json.dumps(payload).encode())

    # --- Convenience methods ---

    def kiosk_next(self) -> None:
        topic = f"umka/kiosks/{self.config.kiosk_slug}/commands/playback"
        self.publish(topic, {"action": "next"})
        log.info("Kiosk next: %s", topic)

    def light_toggle(self, device_id: str) -> None:
        topic = f"museum/{self.config.museum_id}/iot/{device_id}/command"
        self.publish(topic, {"action": "toggle"})
        log.info("Light toggle: %s", topic)

    def light_color(self, device_id: str, hex_color: str) -> None:
        topic = f"museum/{self.config.museum_id}/iot/{device_id}/command"
        self.publish(topic, {"action": "color", "value": hex_color})
        log.debug("Light color %s → %s", device_id, hex_color)

    def light_brightness(self, device_id: str, value: int) -> None:
        topic = f"museum/{self.config.museum_id}/iot/{device_id}/command"
        self.publish(topic, {"action": "brightness", "value": value})
        log.debug("Light brightness %s → %d", device_id, value)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_umka_bridge.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/umka_bridge.py tests/test_umka_bridge.py
git commit -m "feat: add MQTTClient wrapper for Umka MQTT API"
```

---

### Task 4: UmkaBridgeStage

**Files:**
- Modify: `backend/pipeline/stages/umka_bridge.py`
- Modify: `tests/test_umka_bridge.py`

This is the core stage. It runs at SLOW cadence and:
1. Checks for blink events → discrete commands (kiosk next, light toggle)
2. Reads ConcentrationResult → continuous light color mapping
3. Reads EyesClosedResult → dramatic dim
4. Uses CommandSafety for all discrete commands

**Step 1: Write failing tests**

Add to `tests/test_umka_bridge.py`:

```python
import numpy as np
from backend.pipeline.types import PipelineFrame, Event, Cadence
from backend.pipeline.stages.umka_bridge import UmkaBridgeStage, CommandSafety, MQTTClient
from backend.pipeline.stages.features import ConcentrationResult, EyesClosedResult
from backend.config import UmkaBridgeConfig


def _make_frame(events=None, concentration=None, eyes_closed=None):
    frame = PipelineFrame(
        eeg=np.zeros((4, 128)),
        ppg=None,
        imu=None,
        timestamp=time.time(),
    )
    if events:
        frame.events = events
    if concentration:
        frame.set(concentration)
    if eyes_closed:
        frame.set(eyes_closed)
    return frame


class TestUmkaBridgeStage:
    def _make_stage(self, light_ids=None):
        cfg = UmkaBridgeConfig(
            enabled=True,
            broker_host="localhost",
            broker_port=1883,
            kiosk_slug="kiosk-1-1",
            museum_id="1",
            light_ids=light_ids or ["42"],
        )
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client"):
            stage = UmkaBridgeStage(cfg)
        return stage

    def test_is_slow_stage(self):
        stage = self._make_stage()
        assert stage.cadence == Cadence.SLOW
        assert stage.name == "umka_bridge"

    def test_double_blink_triggers_kiosk_next(self):
        stage = self._make_stage()
        with patch.object(stage._mqtt, "kiosk_next") as mock_next:
            frame = _make_frame(events=[
                Event(kind="double_blink", timestamp=time.time(), confidence=0.95),
            ])
            stage.process(frame)
            mock_next.assert_called_once()

    def test_triple_blink_triggers_light_toggle(self):
        stage = self._make_stage(light_ids=["42"])
        with patch.object(stage._mqtt, "light_toggle") as mock_toggle:
            frame = _make_frame(events=[
                Event(kind="triple_blink", timestamp=time.time(), confidence=0.95),
            ])
            stage.process(frame)
            mock_toggle.assert_called_once_with("42")

    def test_concentration_drives_color(self):
        stage = self._make_stage(light_ids=["42"])
        with patch.object(stage._mqtt, "light_color") as mock_color:
            frame = _make_frame(
                concentration=ConcentrationResult(
                    concentration_score=1.0,
                    relaxation_score=0.0,
                ),
            )
            stage.process(frame)
            mock_color.assert_called()
            # High concentration → warm color
            hex_color = mock_color.call_args[0][1]
            assert hex_color.startswith("#")

    def test_eyes_closed_dims_lights(self):
        stage = self._make_stage(light_ids=["42"])
        with patch.object(stage._mqtt, "light_brightness") as mock_bright:
            frame = _make_frame(
                eyes_closed=EyesClosedResult(
                    eyes_closed=True,
                    alpha_ratio=2.5,
                    baseline_alpha=3.0,
                ),
            )
            stage.process(frame)
            mock_bright.assert_called_once_with("42", 10)

    def test_eyes_open_restores_brightness(self):
        stage = self._make_stage(light_ids=["42"])
        # First close eyes
        with patch.object(stage._mqtt, "light_brightness"):
            frame = _make_frame(
                eyes_closed=EyesClosedResult(eyes_closed=True, alpha_ratio=2.5, baseline_alpha=3.0),
            )
            stage.process(frame)
            stage._eyes_were_closed = True

        # Then open eyes
        with patch.object(stage._mqtt, "light_brightness") as mock_bright:
            frame = _make_frame(
                eyes_closed=EyesClosedResult(eyes_closed=False, alpha_ratio=1.1, baseline_alpha=3.0),
            )
            stage.process(frame)
            mock_bright.assert_called_once_with("42", 255)

    def test_low_confidence_blink_ignored(self):
        stage = self._make_stage()
        with patch.object(stage._mqtt, "kiosk_next") as mock_next:
            frame = _make_frame(events=[
                Event(kind="double_blink", timestamp=time.time(), confidence=0.3),
            ])
            stage.process(frame)
            mock_next.assert_not_called()

    def test_debounce_prevents_rapid_fire(self):
        stage = self._make_stage()
        with patch.object(stage._mqtt, "kiosk_next") as mock_next:
            for _ in range(3):
                frame = _make_frame(events=[
                    Event(kind="double_blink", timestamp=time.time(), confidence=0.95),
                ])
                stage.process(frame)
            # Only the first should fire
            assert mock_next.call_count == 1
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_umka_bridge.py::TestUmkaBridgeStage -v`
Expected: FAIL — `UmkaBridgeStage` not found

**Step 3: Implement UmkaBridgeStage**

Add to `backend/pipeline/stages/umka_bridge.py`:

```python
from backend.pipeline.base import Stage
from backend.pipeline.types import Cadence, PipelineFrame
from backend.pipeline.stages.features import ConcentrationResult, EyesClosedResult


def _concentration_to_hex(score: float) -> str:
    """Map concentration (0-1) to warm→cool color gradient.

    1.0 (focused)  → warm orange #FF6600
    0.5 (neutral)  → white #FFFFFF
    0.0 (relaxed)  → cool blue #0066FF
    """
    # Interpolate R, G, B
    if score >= 0.5:
        t = (score - 0.5) * 2  # 0→1
        r = 255
        g = int(255 - (255 - 102) * t)  # 255→102
        b = int(255 - 255 * t)           # 255→0
    else:
        t = score * 2  # 0→1
        r = int(255 * t)                 # 0→255
        g = int(102 + (255 - 102) * t)   # 102→255
        b = 255
    return f"#{r:02X}{g:02X}{b:02X}"


class UmkaBridgeStage(Stage):
    """Pipeline stage that bridges BCI signals to Umka MQTT commands."""

    name = "umka_bridge"
    cadence = Cadence.SLOW

    def __init__(self, config: UmkaBridgeConfig):
        self._config = config
        self._mqtt = MQTTClient(config)
        self._safety = CommandSafety(debounce_sec=2.0, min_confidence=0.8)
        self._eyes_were_closed = False
        self._last_color: str | None = None

    def connect(self) -> None:
        self._mqtt.connect()

    def disconnect(self) -> None:
        self._mqtt.disconnect()

    def process(self, frame: PipelineFrame) -> None:
        self._handle_events(frame)
        self._handle_concentration(frame)
        self._handle_eyes_closed(frame)

    def _handle_events(self, frame: PipelineFrame) -> None:
        for event in frame.events:
            if event.kind == "double_blink":
                if self._safety.allow("kiosk_next", event.confidence):
                    self._mqtt.kiosk_next()

            elif event.kind == "triple_blink":
                if self._safety.allow("light_toggle", event.confidence):
                    for lid in self._config.light_ids:
                        self._mqtt.light_toggle(lid)

    def _handle_concentration(self, frame: PipelineFrame) -> None:
        result = frame.get(ConcentrationResult)
        if result is None:
            return
        hex_color = _concentration_to_hex(result.concentration_score)
        if hex_color == self._last_color:
            return
        self._last_color = hex_color
        for lid in self._config.light_ids:
            self._mqtt.light_color(lid, hex_color)

    def _handle_eyes_closed(self, frame: PipelineFrame) -> None:
        result = frame.get(EyesClosedResult)
        if result is None:
            return
        if result.eyes_closed and not self._eyes_were_closed:
            for lid in self._config.light_ids:
                self._mqtt.light_brightness(lid, 10)
            self._eyes_were_closed = True
        elif not result.eyes_closed and self._eyes_were_closed:
            for lid in self._config.light_ids:
                self._mqtt.light_brightness(lid, 255)
            self._eyes_were_closed = False
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_umka_bridge.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add backend/pipeline/stages/umka_bridge.py tests/test_umka_bridge.py
git commit -m "feat: add UmkaBridgeStage — BCI events/concentration/eyes to MQTT"
```

---

### Task 5: Factory wiring + CLI args

**Files:**
- Modify: `backend/pipeline/factory.py`
- Modify: `backend/main.py`
- Modify: `tests/test_umka_bridge.py`

**Step 1: Write failing test for factory**

Add to `tests/test_umka_bridge.py`:

```python
from backend.pipeline.factory import create_default_pipeline
from backend.pipeline.stages.umka_bridge import UmkaBridgeStage


class TestFactoryWiring:
    def test_pipeline_has_umka_stage_when_enabled(self):
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client"):
            pipeline = create_default_pipeline(
                umka_config=UmkaBridgeConfig(enabled=True, light_ids=["1"]),
            )
        umka_stages = [s for s in pipeline.stages if isinstance(s, UmkaBridgeStage)]
        assert len(umka_stages) == 1

    def test_pipeline_no_umka_stage_when_disabled(self):
        pipeline = create_default_pipeline(
            umka_config=UmkaBridgeConfig(enabled=False),
        )
        umka_stages = [s for s in pipeline.stages if isinstance(s, UmkaBridgeStage)]
        assert len(umka_stages) == 0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_umka_bridge.py::TestFactoryWiring -v`
Expected: FAIL — `create_default_pipeline` doesn't accept `umka_config`

**Step 3: Wire UmkaBridgeStage into factory**

Modify `backend/pipeline/factory.py`:

1. Add import: `from backend.pipeline.stages.umka_bridge import UmkaBridgeStage`
2. Add import: `from backend.config import UmkaBridgeConfig`
3. Add parameter: `umka_config: UmkaBridgeConfig | None = None` to `create_default_pipeline`
4. After `EyesClosedDetector` and before `BandPowerBroadcaster`, add:

```python
if umka_config and umka_config.enabled:
    stages.append(UmkaBridgeStage(umka_config))
```

**Step 4: Run factory tests**

Run: `python -m pytest tests/test_umka_bridge.py::TestFactoryWiring -v`
Expected: PASS

**Step 5: Add CLI args to main.py**

Add these args to the argparse section in `backend/main.py`:

```python
parser.add_argument("--umka", action="store_true", help="Enable Umka MQTT bridge for museum demo")
parser.add_argument("--umka-broker", type=str, default="192.168.87.102", help="Umka MQTT broker host")
parser.add_argument("--umka-port", type=int, default=41883, help="Umka MQTT broker port")
parser.add_argument("--umka-kiosk", type=str, default="kiosk-1-1", help="Umka kiosk slug")
parser.add_argument("--umka-museum", type=str, default="1", help="Umka museum ID")
parser.add_argument("--umka-lights", type=str, nargs="+", default=[], help="IoT light device IDs")
```

Wire into config:

```python
if args.umka:
    config.umka.enabled = True
    config.umka.broker_host = args.umka_broker
    config.umka.broker_port = args.umka_port
    config.umka.kiosk_slug = args.umka_kiosk
    config.umka.museum_id = args.umka_museum
    config.umka.light_ids = args.umka_lights
```

Pass to factory:

```python
pipeline = create_default_pipeline(
    zuna_enabled=config.zuna.enabled,
    ...
    umka_config=config.umka if config.umka.enabled else None,
)
```

**Step 6: Wire connect/disconnect lifecycle**

In `EEGServer.__init__` (or wherever pipeline is created), after `create_default_pipeline`:

```python
# Connect Umka MQTT if enabled
for stage in self._pipeline.stages:
    if isinstance(stage, UmkaBridgeStage):
        stage.connect()
```

In the server shutdown path (graceful disconnect):

```python
for stage in self._pipeline.stages:
    if isinstance(stage, UmkaBridgeStage):
        stage.disconnect()
```

**Step 7: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS

**Step 8: Commit**

```bash
git add backend/pipeline/factory.py backend/main.py tests/test_umka_bridge.py
git commit -m "feat: wire UmkaBridgeStage into pipeline factory and CLI"
```

---

### Task 6: Integration test + manual verification guide

**Files:**
- Modify: `tests/test_umka_bridge.py`
- Create: `docs/guides/2026-03-12-umka-bridge-manual-test.md`

**Step 1: Write integration test**

Add to `tests/test_umka_bridge.py`:

```python
class TestIntegration:
    """End-to-end: frame with events + concentration → MQTT calls."""

    def test_full_frame_processing(self):
        """A frame with a double_blink event AND concentration should
        trigger both kiosk_next AND light_color."""
        cfg = UmkaBridgeConfig(
            enabled=True,
            broker_host="localhost",
            kiosk_slug="test-kiosk",
            museum_id="1",
            light_ids=["10", "11"],
        )
        with patch("backend.pipeline.stages.umka_bridge.mqtt.Client"):
            stage = UmkaBridgeStage(cfg)

        with patch.object(stage._mqtt, "kiosk_next") as mock_next, \
             patch.object(stage._mqtt, "light_color") as mock_color:
            frame = _make_frame(
                events=[Event(kind="double_blink", timestamp=time.time(), confidence=0.95)],
                concentration=ConcentrationResult(concentration_score=0.8, relaxation_score=0.2),
            )
            stage.process(frame)
            mock_next.assert_called_once()
            # Two lights should get color
            assert mock_color.call_count == 2

    def test_concentration_color_gradient(self):
        """Verify color mapping produces valid hex across range."""
        from backend.pipeline.stages.umka_bridge import _concentration_to_hex
        for score in [0.0, 0.25, 0.5, 0.75, 1.0]:
            color = _concentration_to_hex(score)
            assert len(color) == 7
            assert color.startswith("#")
            # Should be valid hex
            int(color[1:], 16)
```

**Step 2: Run integration tests**

Run: `python -m pytest tests/test_umka_bridge.py::TestIntegration -v`
Expected: PASS

**Step 3: Write manual verification guide**

Create `docs/guides/2026-03-12-umka-bridge-manual-test.md`:

```markdown
# Umka MQTT Bridge — Manual Verification Guide

## Prerequisites

- VPN connected to museum network (192.168.87.x)
- Mosquitto broker accessible at 192.168.87.102:41883
- At least one IoT light device ID (check Umka CMS)
- Muse 2 headband charged and paired

## Step 1: Verify MQTT connectivity

```bash
# Subscribe to all Umka topics in one terminal
mosquitto_sub -h 192.168.87.102 -p 41883 -t "umka/#" -t "museum/#" -v
```

## Step 2: Test with synthetic board

```bash
python -m backend.main --synthetic --umka --umka-lights 42 43
```

Expected: Backend starts, logs "MQTT connected to 192.168.87.102:41883"

## Step 3: Test discrete commands

With synthetic board running + mosquitto_sub watching:

1. **Can't test blinks with synthetic** — use the MQTT test script instead:

```bash
# Simulate a double blink event for kiosk next
mosquitto_pub -h 192.168.87.102 -p 41883 \
  -t "umka/kiosks/kiosk-1-1/commands/playback" \
  -m '{"action": "next"}'
```

Verify: Kiosk advances to next scene.

## Step 4: Test with real headband

```bash
python -m backend.main --mac XX:XX:XX:XX:XX:XX --umka --umka-lights 42 43
```

### Test matrix

| Action | How to trigger | Expected MQTT | Expected physical |
|--------|---------------|---------------|-------------------|
| Kiosk next | Double blink | `umka/kiosks/kiosk-1-1/commands/playback` `{"action":"next"}` | Kiosk advances scene |
| Light toggle | Triple blink | `museum/1/iot/42/command` `{"action":"toggle"}` | Light turns on/off |
| Color shift | Focus hard (mental math) | `museum/1/iot/42/command` `{"action":"color","value":"#FF6600"}` | Light goes warm orange |
| Color shift | Relax (mind wander) | `museum/1/iot/42/command` `{"action":"color","value":"#0066FF"}` | Light goes cool blue |
| Dim | Close eyes (if alpha blocks) | `museum/1/iot/42/command` `{"action":"brightness","value":10}` | Light dims to ~4% |
| Restore | Open eyes | `museum/1/iot/42/command` `{"action":"brightness","value":255}` | Light returns to full |

### Edge cases to verify

- [ ] Rapid double blinks — only first should fire (2s debounce)
- [ ] Triple blink during debounce — should be independent from double blink
- [ ] Eyes closed with no alpha blocking — nothing should happen (safe)
- [ ] Disconnect Muse — MQTT stays connected, no commands fire
- [ ] Kill backend gracefully (Ctrl+C) — MQTT disconnects cleanly
```

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: ALL PASS (including all existing 91+ tests)

**Step 5: Commit**

```bash
git add tests/test_umka_bridge.py docs/guides/2026-03-12-umka-bridge-manual-test.md
git commit -m "test: add integration tests and manual verification guide for Umka bridge"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Add `paho-mqtt` dep | `pyproject.toml` |
| 2 | `UmkaBridgeConfig` + `CommandSafety` | `config.py`, `umka_bridge.py`, `test_umka_bridge.py` |
| 3 | `MQTTClient` wrapper | `umka_bridge.py`, `test_umka_bridge.py` |
| 4 | `UmkaBridgeStage` (core logic) | `umka_bridge.py`, `test_umka_bridge.py` |
| 5 | Factory wiring + CLI args | `factory.py`, `main.py`, `test_umka_bridge.py` |
| 6 | Integration test + manual guide | `test_umka_bridge.py`, manual test guide |

**Signal → MQTT mapping:**

| Signal | Trigger | MQTT Command | Reliability |
|--------|---------|-------------|-------------|
| Double blink | `Event(kind="double_blink")` | kiosk next | 99% |
| Triple blink | `Event(kind="triple_blink")` | light toggle | 99% |
| Concentration | `ConcentrationResult.concentration_score` | light color (warm↔cool) | continuous |
| Eyes closed | `EyesClosedResult.eyes_closed` | light brightness 10 | opportunistic |
| Eyes open | `EyesClosedResult.eyes_closed=False` | light brightness 255 | automatic |
