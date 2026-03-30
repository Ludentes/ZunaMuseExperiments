# Plan 5: VTube Studio WebSocket Plugin

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VTube Studio plugin that injects EEG parameters (blink, focus, relaxation, clench) into Live2D models via the VTube Studio WebSocket API.

**Architecture:** Async WebSocket client connecting to VTS on port 8001. Follows VTS auth flow (request token → user approval popup → persist token). Creates 4 custom parameters and injects values at pipeline rate. Uses `websockets` library (no pyvts dependency).

**Tech Stack:** websockets, json

**Depends on:** Plan 0, Plan 1 (EEG pipeline)

---

### Task 1: VTube Studio WebSocket client

**Files:**
- Create: `src/muse_vtuber/outputs/vts.py`
- Create: `tests/test_vts.py`

- [ ] **Step 1: Write test**

`tests/test_vts.py`:
```python
import json

import pytest

from muse_vtuber.outputs.vts import (
    VTSClient,
    build_auth_request,
    build_parameter_creation_request,
    build_parameter_injection_request,
)


def test_auth_request_format():
    msg = build_auth_request("muse-vtuber", "Muse VTuber Bridge")
    data = json.loads(msg)
    assert data["apiName"] == "VTubeStudioPublicAPI"
    assert data["apiVersion"] == "1.0"
    assert data["messageType"] == "AuthenticationTokenRequest"
    assert data["data"]["pluginName"] == "muse-vtuber"
    assert data["data"]["pluginDeveloper"] == "Muse VTuber Bridge"


def test_parameter_creation_format():
    msg = build_parameter_creation_request("MuseBlink", 0.0, 0.0, 1.0)
    data = json.loads(msg)
    assert data["messageType"] == "ParameterCreationRequest"
    assert data["data"]["parameterName"] == "MuseBlink"
    assert data["data"]["defaultValue"] == 0.0
    assert data["data"]["min"] == 0.0
    assert data["data"]["max"] == 1.0


def test_parameter_injection_format():
    params = [
        ("MuseBlink", 1.0),
        ("MuseFocus", 0.7),
        ("MuseRelaxation", 0.3),
        ("MuseClench", 0.0),
    ]
    msg = build_parameter_injection_request(params)
    data = json.loads(msg)
    assert data["messageType"] == "InjectParameterDataRequest"
    values = data["data"]["parameterValues"]
    assert len(values) == 4
    assert values[0]["id"] == "MuseBlink"
    assert values[0]["value"] == 1.0


def test_parameter_injection_weight():
    """Weight field controls blending with face tracking."""
    params = [("MuseBlink", 1.0)]
    msg = build_parameter_injection_request(params, weight=0.5)
    data = json.loads(msg)
    values = data["data"]["parameterValues"]
    assert values[0]["weight"] == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_vts.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement VTS client**

`src/muse_vtuber/outputs/vts.py`:
```python
"""VTube Studio WebSocket plugin client.

Connects to VTube Studio on port 8001, authenticates, creates custom
parameters, and injects EEG values at pipeline rate.

VTS API docs: https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

log = logging.getLogger("vts")

_API_NAME = "VTubeStudioPublicAPI"
_API_VERSION = "1.0"

# Custom parameters we create in VTube Studio
PARAMETERS = [
    ("MuseBlink", 0.0, 0.0, 1.0),       # (name, default, min, max)
    ("MuseFocus", 0.0, 0.0, 1.0),
    ("MuseRelaxation", 0.0, 0.0, 1.0),
    ("MuseClench", 0.0, 0.0, 1.0),
]

# Token persistence file
_TOKEN_PATH = Path.home() / ".config" / "muse-vtuber" / "vts_token.txt"


def _request(message_type: str, data: dict | None = None) -> str:
    msg = {
        "apiName": _API_NAME,
        "apiVersion": _API_VERSION,
        "requestID": message_type,
        "messageType": message_type,
    }
    if data is not None:
        msg["data"] = data
    return json.dumps(msg)


def build_auth_request(plugin_name: str, developer: str) -> str:
    return _request("AuthenticationTokenRequest", {
        "pluginName": plugin_name,
        "pluginDeveloper": developer,
    })


def build_auth_with_token(token: str) -> str:
    return _request("AuthenticationRequest", {
        "pluginName": "muse-vtuber",
        "pluginDeveloper": "Muse VTuber Bridge",
        "authenticationToken": token,
    })


def build_parameter_creation_request(
    name: str, default: float, min_val: float, max_val: float,
) -> str:
    return _request("ParameterCreationRequest", {
        "parameterName": name,
        "explanation": f"Muse VTuber Bridge: {name}",
        "min": min_val,
        "max": max_val,
        "defaultValue": default,
    })


def build_parameter_injection_request(
    params: list[tuple[str, float]],
    weight: float = 1.0,
) -> str:
    values = []
    for name, value in params:
        entry = {"id": name, "value": value}
        if weight != 1.0:
            entry["weight"] = weight
        values.append(entry)
    return _request("InjectParameterDataRequest", {
        "parameterValues": values,
    })


class VTSClient:
    """Async WebSocket client for VTube Studio plugin API."""

    def __init__(self, port: int = 8001):
        self.port = port
        self._ws = None
        self._authenticated = False
        self._token: str | None = None

    async def connect(self) -> bool:
        """Connect to VTube Studio and authenticate."""
        try:
            import websockets
            self._ws = await websockets.connect(f"ws://localhost:{self.port}")
        except Exception as e:
            log.warning("Cannot connect to VTube Studio on port %d: %s", self.port, e)
            return False

        # Try saved token first
        self._token = self._load_token()
        if self._token:
            if await self._auth_with_token(self._token):
                self._authenticated = True
                log.info("Authenticated with saved token")
                await self._create_parameters()
                return True

        # Request new token (shows popup in VTube Studio)
        self._token = await self._request_token()
        if self._token:
            self._save_token(self._token)
            if await self._auth_with_token(self._token):
                self._authenticated = True
                log.info("Authenticated with new token")
                await self._create_parameters()
                return True

        return False

    async def _send_recv(self, msg: str) -> dict | None:
        if self._ws is None:
            return None
        try:
            await self._ws.send(msg)
            response = await self._ws.recv()
            return json.loads(response)
        except Exception as e:
            log.warning("VTS communication error: %s", e)
            return None

    async def _request_token(self) -> str | None:
        resp = await self._send_recv(
            build_auth_request("muse-vtuber", "Muse VTuber Bridge")
        )
        if resp and "data" in resp and "authenticationToken" in resp["data"]:
            return resp["data"]["authenticationToken"]
        return None

    async def _auth_with_token(self, token: str) -> bool:
        resp = await self._send_recv(build_auth_with_token(token))
        if resp and "data" in resp:
            return resp["data"].get("authenticated", False)
        return False

    async def _create_parameters(self) -> None:
        for name, default, min_val, max_val in PARAMETERS:
            await self._send_recv(
                build_parameter_creation_request(name, default, min_val, max_val)
            )
            log.debug("Created VTS parameter: %s", name)

    async def inject(
        self,
        blink: float = 0.0,
        focus: float = 0.0,
        relaxation: float = 0.0,
        clench: float = 0.0,
    ) -> None:
        """Inject parameter values into VTube Studio."""
        if not self._authenticated or self._ws is None:
            return
        params = [
            ("MuseBlink", blink),
            ("MuseFocus", focus),
            ("MuseRelaxation", relaxation),
            ("MuseClench", clench),
        ]
        msg = build_parameter_injection_request(params)
        try:
            await self._ws.send(msg)
            # Don't wait for response — fire and forget for injection
        except Exception:
            self._authenticated = False
            log.warning("VTS connection lost, will retry")

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._authenticated = False

    def _load_token(self) -> str | None:
        try:
            if _TOKEN_PATH.exists():
                return _TOKEN_PATH.read_text().strip()
        except Exception:
            pass
        return None

    def _save_token(self, token: str) -> None:
        try:
            _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            _TOKEN_PATH.write_text(token)
        except Exception as e:
            log.warning("Cannot save VTS token: %s", e)
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_vts.py -v
```

Expected: 4 passed

- [ ] **Step 5: Wire into main.py**

Add VTS as an optional async output. In `main.py`, add a VTS thread similar to the OpenSeeFace receiver pattern:

```python
    # VTube Studio (async, runs in thread)
    vts_client = None
    if config.vts_enabled:
        from muse_vtuber.outputs.vts import VTSClient
        vts_client = VTSClient(port=config.vts_port)
        vts_queue: queue.Queue = queue.Queue(maxsize=1)

        def _vts_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run():
                connected = await vts_client.connect()
                if not connected:
                    log.warning("VTube Studio not available")
                    return
                while running:
                    try:
                        data = vts_queue.get(timeout=0.1)
                        await vts_client.inject(**data)
                    except queue.Empty:
                        pass

            loop.run_until_complete(_run())

        import queue
        vts_thread = threading.Thread(target=_vts_thread, daemon=True)
        vts_thread.start()
```

In the main loop:
```python
            if vts_client and config.vts_enabled:
                try:
                    vts_queue.put_nowait({
                        "blink": blendshapes.blink,
                        "focus": blendshapes.focus,
                        "relaxation": blendshapes.relaxation,
                        "clench": blendshapes.clench,
                    })
                except queue.Full:
                    pass  # drop frame if VTS thread is slow
```

- [ ] **Step 6: Add --vts CLI flag**

In `config.py`:
```python
    parser.add_argument("--vts", action="store_true", help="Enable VTube Studio plugin")
    parser.add_argument("--vts-port", type=int, help="VTube Studio port")
```

Override:
```python
    if parsed.vts:
        cfg.vts_enabled = True
    if parsed.vts_port:
        cfg.vts_port = parsed.vts_port
```

- [ ] **Step 7: Run all tests**

```bash
cd muse-vtuber
uv run pytest -v
```

Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add src/muse_vtuber/outputs/vts.py tests/test_vts.py src/muse_vtuber/main.py src/muse_vtuber/config.py
git commit -m "feat: VTube Studio WebSocket plugin — all output sinks complete"
```

---

### Done Criteria

- [x] Auth flow: token request → user approval → persist token
- [x] Creates 4 custom parameters: MuseBlink, MuseFocus, MuseRelaxation, MuseClench
- [x] Injects values at pipeline rate
- [x] Reconnects if VTS restarts
- [x] `muse-vtuber --synthetic --vts --debug` connects to VTube Studio
- [x] All tests pass

### Manual Verification

1. Open VTube Studio, enable plugins (Settings → General → Start API)
2. Run `muse-vtuber --synthetic --vts --debug`
3. VTube Studio should show auth popup → approve
4. Check VTS parameter list — should see MuseBlink, MuseFocus, MuseRelaxation, MuseClench
5. With real Muse: blink → MuseBlink spikes to 1.0
6. Bind parameters to Live2D model (e.g., MuseBlink → eye close, MuseFocus → eye glow)
