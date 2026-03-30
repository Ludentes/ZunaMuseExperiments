# Plan 4: VRChat OSC Output (BFiVRC Compatible)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Output EEG metrics as VRChat-compatible OSC parameters on port 9000. Compatible with BrainFlowsIntoVRChat avatar prefabs. Also works with VNyan (accepts VRChat OSC since v1.3.2).

**Architecture:** Single `VRChatOSCOutput` class that converts pipeline results to OSC messages using `python-osc`. Sends neurofeedback (focus/relax per hemisphere), power bands, and status info.

**Tech Stack:** python-osc

**Depends on:** Plan 0, Plan 1 (EEG pipeline)

---

### Task 1: VRChat OSC output

**Files:**
- Create: `src/muse_vtuber/outputs/osc_vrchat.py`
- Create: `tests/test_osc_vrchat.py`

- [ ] **Step 1: Write test**

`tests/test_osc_vrchat.py`:
```python
import pytest

from muse_vtuber.outputs.osc_vrchat import VRChatOSCOutput, VRChatOSCFrame


def test_builds_neurofeedback_params():
    osc = VRChatOSCOutput(host="127.0.0.1", port=0)
    frame = VRChatOSCFrame(
        focus_left=0.3, focus_right=0.5, focus_avg=0.4,
        relax_left=-0.2, relax_right=-0.1, relax_avg=-0.15,
        focus_avg_unsigned=0.7, relax_avg_unsigned=0.425,
        band_powers_left={"alpha": 5.0, "beta": 3.0, "theta": 4.0, "delta": 8.0, "gamma": 1.0},
        band_powers_right={"alpha": 5.5, "beta": 3.2, "theta": 4.1, "delta": 7.8, "gamma": 1.1},
        band_powers_avg={"alpha": 5.25, "beta": 3.1, "theta": 4.05, "delta": 7.9, "gamma": 1.05},
        device_connected=True,
    )
    messages = osc.build_messages(frame)
    addresses = [m.address for m in messages]

    # Check BFiVRC parameter format
    assert "/avatar/parameters/BFI/NeuroFB/FocusAvg" in addresses
    assert "/avatar/parameters/BFI/NeuroFB/RelaxAvg" in addresses
    assert "/avatar/parameters/BFI/NeuroFB/FocusLeft" in addresses
    assert "/avatar/parameters/BFI/NeuroFB/FocusRight" in addresses
    assert "/avatar/parameters/BFI/NeuroFB/FocusAvg+" in addresses
    assert "/avatar/parameters/BFI/NeuroFB/RelaxAvg+" in addresses

    # Power bands
    assert "/avatar/parameters/BFI/PwrBands/Avg/Alpha" in addresses
    assert "/avatar/parameters/BFI/PwrBands/Left/Beta" in addresses

    # Status
    assert "/avatar/parameters/BFI/Info/DeviceConnected" in addresses


def test_focus_values_match():
    osc = VRChatOSCOutput(host="127.0.0.1", port=0)
    frame = VRChatOSCFrame(
        focus_avg=0.42,
        focus_left=0.0, focus_right=0.0,
        relax_left=0.0, relax_right=0.0, relax_avg=0.0,
        focus_avg_unsigned=0.71, relax_avg_unsigned=0.5,
        band_powers_left={}, band_powers_right={}, band_powers_avg={},
        device_connected=True,
    )
    messages = osc.build_messages(frame)
    focus_msgs = [m for m in messages if m.address == "/avatar/parameters/BFI/NeuroFB/FocusAvg"]
    assert len(focus_msgs) == 1
    assert abs(focus_msgs[0].params[0] - 0.42) < 0.001


def test_band_power_normalization():
    """Band powers should be normalized to 0-1 range."""
    osc = VRChatOSCOutput(host="127.0.0.1", port=0)
    frame = VRChatOSCFrame(
        focus_avg=0.0, focus_left=0.0, focus_right=0.0,
        relax_avg=0.0, relax_left=0.0, relax_right=0.0,
        focus_avg_unsigned=0.5, relax_avg_unsigned=0.5,
        band_powers_left={"alpha": 50.0},
        band_powers_right={"alpha": 30.0},
        band_powers_avg={"alpha": 40.0},
        device_connected=True,
    )
    messages = osc.build_messages(frame)
    alpha_msgs = [m for m in messages if "Alpha" in m.address]
    for msg in alpha_msgs:
        val = msg.params[0]
        assert 0.0 <= val <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_osc_vrchat.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement VRChat OSC output**

`src/muse_vtuber/outputs/osc_vrchat.py`:
```python
"""VRChat-compatible OSC parameter output.

Sends EEG metrics as avatar parameters on port 9000.
Compatible with BrainFlowsIntoVRChat avatar prefabs.
Also works with VNyan (accepts VRChat OSC since v1.3.2).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.udp_client import SimpleUDPClient

log = logging.getLogger("osc_vrchat")

_PREFIX = "/avatar/parameters/BFI"

# Band power normalization: log-scale mapping to 0-1.
# These are empirical values from Muse 2 sessions.
_BAND_POWER_LOG_MIN = -2.0   # log10 of minimum expected power
_BAND_POWER_LOG_MAX = 3.0    # log10 of maximum expected power


@dataclass
class VRChatOSCFrame:
    """All values needed for one VRChat OSC update."""

    # Neurofeedback (signed -1 to 1)
    focus_left: float = 0.0
    focus_right: float = 0.0
    focus_avg: float = 0.0
    relax_left: float = 0.0
    relax_right: float = 0.0
    relax_avg: float = 0.0

    # Unsigned variants (0 to 1)
    focus_avg_unsigned: float = 0.5
    relax_avg_unsigned: float = 0.5

    # Band powers per hemisphere (raw values — will be normalized)
    band_powers_left: dict[str, float] = field(default_factory=dict)
    band_powers_right: dict[str, float] = field(default_factory=dict)
    band_powers_avg: dict[str, float] = field(default_factory=dict)

    # Status
    device_connected: bool = False
    battery_level: float = -1.0  # -1 = unknown


def _normalize_band_power(power: float) -> float:
    """Normalize band power to 0-1 using log scale."""
    if power <= 0:
        return 0.0
    log_val = math.log10(power)
    normalized = (log_val - _BAND_POWER_LOG_MIN) / (_BAND_POWER_LOG_MAX - _BAND_POWER_LOG_MIN)
    return max(0.0, min(1.0, normalized))


def _param(address: str, value: float | bool) -> OscMessage:
    builder = OscMessageBuilder(address=address)
    if isinstance(value, bool):
        builder.add_arg(value)
    else:
        builder.add_arg(float(value))
    return builder.build()


class VRChatOSCOutput:
    """Send EEG metrics as VRChat OSC parameters."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9000):
        self.host = host
        self.port = port
        self._client: SimpleUDPClient | None = None
        if port > 0:
            self._client = SimpleUDPClient(host, port)

    def build_messages(self, frame: VRChatOSCFrame) -> list[OscMessage]:
        """Build all OSC messages for one frame."""
        msgs: list[OscMessage] = []

        # Neurofeedback (signed)
        msgs.append(_param(f"{_PREFIX}/NeuroFB/FocusLeft", frame.focus_left))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/FocusRight", frame.focus_right))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/FocusAvg", frame.focus_avg))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/RelaxLeft", frame.relax_left))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/RelaxRight", frame.relax_right))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/RelaxAvg", frame.relax_avg))

        # Unsigned
        msgs.append(_param(f"{_PREFIX}/NeuroFB/FocusAvg+", frame.focus_avg_unsigned))
        msgs.append(_param(f"{_PREFIX}/NeuroFB/RelaxAvg+", frame.relax_avg_unsigned))

        # Band powers per hemisphere (normalized)
        for hemisphere, powers in [
            ("Left", frame.band_powers_left),
            ("Right", frame.band_powers_right),
            ("Avg", frame.band_powers_avg),
        ]:
            for band, power in powers.items():
                band_name = band.capitalize()
                msgs.append(_param(
                    f"{_PREFIX}/PwrBands/{hemisphere}/{band_name}",
                    _normalize_band_power(power),
                ))

        # Status
        msgs.append(_param(f"{_PREFIX}/Info/DeviceConnected", frame.device_connected))
        if frame.battery_level >= 0:
            msgs.append(_param(f"{_PREFIX}/Info/BatteryLevel", frame.battery_level))

        return msgs

    def send(self, frame: VRChatOSCFrame) -> None:
        """Send all parameters over UDP."""
        if self._client is None:
            return
        for msg in self.build_messages(frame):
            self._client.send(msg)
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_osc_vrchat.py -v
```

Expected: 3 passed

- [ ] **Step 5: Wire into main.py**

In `main.py`, add import:
```python
from muse_vtuber.outputs.osc_vrchat import VRChatOSCFrame, VRChatOSCOutput
```

After creating `vmc_output`:
```python
    osc_output = VRChatOSCOutput(config.osc_host, config.osc_port) if config.osc_enabled else None
```

In the main loop, after sending VMC:
```python
            if osc_output:
                focus_result = frame.get(FocusRelaxResult)
                bp_result = frame.get(BandPowerResult)
                osc_frame = VRChatOSCFrame(
                    focus_left=focus_result.focus_left if focus_result else 0.0,
                    focus_right=focus_result.focus_right if focus_result else 0.0,
                    focus_avg=focus_result.focus_avg if focus_result else 0.0,
                    relax_left=focus_result.relax_left if focus_result else 0.0,
                    relax_right=focus_result.relax_right if focus_result else 0.0,
                    relax_avg=focus_result.relax_avg if focus_result else 0.0,
                    focus_avg_unsigned=focus_result.focus_avg_unsigned if focus_result else 0.5,
                    relax_avg_unsigned=focus_result.relax_avg_unsigned if focus_result else 0.5,
                    band_powers_left=bp_result.band_powers_left if bp_result else {},
                    band_powers_right=bp_result.band_powers_right if bp_result else {},
                    band_powers_avg=bp_result.band_powers_avg if bp_result else {},
                    device_connected=True,
                )
                osc_output.send(osc_frame)
```

- [ ] **Step 6: Run all tests**

```bash
cd muse-vtuber
uv run pytest -v
```

Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/muse_vtuber/outputs/osc_vrchat.py tests/test_osc_vrchat.py src/muse_vtuber/main.py
git commit -m "feat: VRChat OSC output with BFiVRC-compatible parameters"
```

---

### Done Criteria

- [x] OSC parameters match BFiVRC naming: `BFI/NeuroFB/FocusAvg`, `BFI/PwrBands/Left/Alpha`, etc.
- [x] Band powers normalized to 0-1 (log scale)
- [x] Status params: DeviceConnected, BatteryLevel
- [x] `muse-vtuber --synthetic --osc --debug` sends OSC on port 9000
- [x] All tests pass
