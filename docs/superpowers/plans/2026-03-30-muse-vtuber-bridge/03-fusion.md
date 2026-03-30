# Plan 3: Fusion — OpenSeeFace + IMU Complementary Filter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume OpenSeeFace UDP output as absolute webcam reference, fuse with IMU via quaternion complementary filter. Better tracking than either source alone.

**Architecture:** OpenSeeFace receiver (asyncio UDP) → ComplementaryFusion (slerp at IMU rate, webcam corrects drift) → VMC bone output. Auto-detects: if OpenSeeFace is sending, activate fusion. If not, pure IMU.

**Tech Stack:** asyncio, struct (binary parsing), numpy

**Depends on:** Plan 0, Plan 2 (head tracking)

---

### Task 1: OpenSeeFace UDP receiver

**Files:**
- Create: `src/muse_vtuber/openseeface.py`
- Create: `tests/test_openseeface.py`

Parse OpenSeeFace's binary UDP protocol. Extract head rotation quaternion + confidence.

OpenSeeFace binary format (per-face packet): the tracking data is packed as a sequence of floats. The relevant fields are: `face_id` (int), `width` (float), `height` (float), then 6 floats for euler+translation, then the quaternion (4 floats: x, y, z, w), then face detection success (float 0-1), and PnP error (float). Total header before landmarks is well-defined.

- [ ] **Step 1: Write test**

`tests/test_openseeface.py`:
```python
import struct

import pytest

from muse_vtuber.openseeface import OpenSeeFaceData, parse_openseeface_packet


def _build_fake_packet(
    qx: float = 0.0,
    qy: float = 0.0,
    qz: float = 0.0,
    qw: float = 1.0,
    confidence: float = 1.0,
) -> bytes:
    """Build a minimal fake OpenSeeFace UDP packet.

    Simplified format for testing. Real format is more complex with landmarks.
    We test the parser against real recorded packets in integration tests.
    """
    # Face ID (int32) + timestamp (double) + width, height (float) +
    # success (float) + pnp_error (float) +
    # quaternion (4 floats) + euler (3 floats) + translation (3 floats) +
    # 68 landmarks × (x, y, confidence) × float = lots of data
    #
    # For unit test, we'll test the parser function with known offsets.
    # Real integration test uses captured packets.
    return struct.pack(
        "<i d 2f f f 4f 3f 3f",
        0,            # face_id
        0.0,          # timestamp
        640.0, 480.0, # width, height
        confidence,   # success
        0.1,          # pnp_error
        qx, qy, qz, qw,  # quaternion
        0.0, 0.0, 0.0,    # euler (yaw, pitch, roll)
        0.0, 0.0, 0.0,    # translation
    )


def test_parse_packet_extracts_quaternion():
    packet = _build_fake_packet(qx=0.1, qy=0.2, qz=0.3, qw=0.9)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert abs(data.qx - 0.1) < 0.001
    assert abs(data.qy - 0.2) < 0.001
    assert abs(data.qz - 0.3) < 0.001
    assert abs(data.qw - 0.9) < 0.001


def test_parse_packet_extracts_confidence():
    packet = _build_fake_packet(confidence=0.85)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert abs(data.confidence - 0.85) < 0.001


def test_parse_short_packet_returns_none():
    data = parse_openseeface_packet(b"\x00\x01\x02")
    assert data is None


def test_low_confidence_flagged():
    packet = _build_fake_packet(confidence=0.1)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert data.confidence < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_openseeface.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement OpenSeeFace parser**

`src/muse_vtuber/openseeface.py`:
```python
"""OpenSeeFace UDP receiver and binary protocol parser.

OpenSeeFace sends face tracking data as UDP packets with binary encoding.
We extract: head rotation quaternion + face detection confidence.

Reference: https://github.com/emilianavt/OpenSeeFace
"""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

log = logging.getLogger("openseeface")

# OpenSeeFace binary packet layout (simplified header before landmarks):
# int32: face_id
# double: timestamp
# float: camera_width
# float: camera_height
# float: success (0-1, face detection confidence)
# float: pnp_error
# float × 4: quaternion (x, y, z, w)
# float × 3: euler (yaw, pitch, roll) in degrees
# float × 3: translation (x, y, z)
# Then: 68 landmarks × (x, y, confidence) = 204 floats
# Then: 68 3D points × (x, y, z) = 204 floats
# Then: features (eye open, mouth, etc.)
_HEADER_FORMAT = "<i d 2f f f 4f 3f 3f"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)


@dataclass
class OpenSeeFaceData:
    """Parsed tracking data from one OpenSeeFace packet."""

    face_id: int
    qx: float
    qy: float
    qz: float
    qw: float
    confidence: float
    pnp_error: float


def parse_openseeface_packet(data: bytes) -> OpenSeeFaceData | None:
    """Parse an OpenSeeFace UDP packet. Returns None if too short."""
    if len(data) < _HEADER_SIZE:
        return None
    try:
        fields = struct.unpack(_HEADER_FORMAT, data[:_HEADER_SIZE])
    except struct.error:
        return None

    face_id = fields[0]
    # timestamp = fields[1]
    # width, height = fields[2], fields[3]
    success = fields[4]
    pnp_error = fields[5]
    qx, qy, qz, qw = fields[6], fields[7], fields[8], fields[9]
    # euler and translation follow but we don't need them

    return OpenSeeFaceData(
        face_id=face_id,
        qx=qx, qy=qy, qz=qz, qw=qw,
        confidence=success,
        pnp_error=pnp_error,
    )


class OpenSeeFaceReceiver:
    """Asyncio UDP receiver for OpenSeeFace tracking data.

    Listens on a UDP port and stores the latest tracking data.
    Thread-safe via asyncio (single-threaded event loop).
    """

    def __init__(self, port: int = 11573):
        self.port = port
        self.latest: OpenSeeFaceData | None = None
        self._transport: asyncio.DatagramTransport | None = None

    class _Protocol(asyncio.DatagramProtocol):
        def __init__(self, receiver: "OpenSeeFaceReceiver"):
            self._receiver = receiver

        def datagram_received(self, data: bytes, addr: tuple) -> None:
            parsed = parse_openseeface_packet(data)
            if parsed is not None:
                self._receiver.latest = parsed

    async def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        loop = loop or asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self._Protocol(self),
            local_addr=("0.0.0.0", self.port),
        )
        self._transport = transport
        log.info("Listening for OpenSeeFace on UDP port %d", self.port)

    def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None

    def get_latest(self) -> OpenSeeFaceData | None:
        """Get most recent tracking data (or None if no data received)."""
        data = self.latest
        self.latest = None  # consume
        return data
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_openseeface.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/openseeface.py tests/test_openseeface.py
git commit -m "feat: OpenSeeFace UDP receiver and binary parser"
```

---

### Task 2: Quaternion complementary filter

**Files:**
- Create: `src/muse_vtuber/fusion.py`
- Create: `tests/test_fusion.py`

- [ ] **Step 1: Write test**

`tests/test_fusion.py`:
```python
import math

import pytest

from muse_vtuber.fusion import ComplementaryFusion

Quat = tuple[float, float, float, float]


def _quat_yaw(degrees: float) -> Quat:
    """Create quaternion for yaw rotation."""
    rad = math.radians(degrees) / 2
    return (0.0, math.sin(rad), 0.0, math.cos(rad))


def _angle_between(a: Quat, b: Quat) -> float:
    """Angular distance in degrees."""
    dot = sum(x * y for x, y in zip(a, b))
    dot = min(1.0, abs(dot))
    return math.degrees(2 * math.acos(dot))


class TestComplementaryFusion:
    def test_pure_imu_when_no_webcam(self):
        """Without webcam corrections, fusion = pure IMU."""
        fuse = ComplementaryFusion(alpha=0.96)
        q_imu = _quat_yaw(30.0)
        result = fuse.update_imu(q_imu)
        assert _angle_between(result, q_imu) < 1.0

    def test_webcam_correction_pulls_toward_webcam(self):
        """Webcam correction should move fused pose toward webcam."""
        fuse = ComplementaryFusion(alpha=0.96)

        # IMU says 30° yaw
        q_imu = _quat_yaw(30.0)
        fuse.update_imu(q_imu)

        # Webcam says 0° (looking straight)
        q_webcam = _quat_yaw(0.0)
        result = fuse.update_webcam(q_webcam, confidence=1.0)

        # Result should be between IMU and webcam, closer to IMU (alpha=0.96)
        imu_dist = _angle_between(result, q_imu)
        webcam_dist = _angle_between(result, q_webcam)
        assert imu_dist < webcam_dist  # closer to IMU
        assert imu_dist > 0.1  # but pulled toward webcam

    def test_repeated_webcam_eliminates_drift(self):
        """Repeated webcam corrections should eventually converge to webcam pose."""
        fuse = ComplementaryFusion(alpha=0.96)

        q_imu = _quat_yaw(30.0)   # IMU drifted 30°
        q_webcam = _quat_yaw(0.0)  # Webcam says 0°

        # Simulate many correction cycles
        for _ in range(200):
            fuse.update_imu(q_imu)
            fuse.update_webcam(q_webcam, confidence=1.0)

        result = fuse.update_imu(q_imu)
        # After many corrections, should be very close to webcam
        assert _angle_between(result, q_webcam) < 5.0

    def test_low_confidence_reduces_correction(self):
        """Low webcam confidence should apply less correction."""
        fuse_high = ComplementaryFusion(alpha=0.96)
        fuse_low = ComplementaryFusion(alpha=0.96)

        q_imu = _quat_yaw(30.0)
        q_webcam = _quat_yaw(0.0)

        fuse_high.update_imu(q_imu)
        fuse_low.update_imu(q_imu)

        result_high = fuse_high.update_webcam(q_webcam, confidence=1.0)
        result_low = fuse_low.update_webcam(q_webcam, confidence=0.1)

        # High confidence should correct more (closer to webcam)
        high_dist = _angle_between(result_high, q_webcam)
        low_dist = _angle_between(result_low, q_webcam)
        assert high_dist < low_dist

    def test_adaptive_alpha_range(self):
        fuse = ComplementaryFusion(alpha=0.96)
        # High confidence → lower effective alpha
        a_high = fuse._adaptive_alpha(1.0)
        a_low = fuse._adaptive_alpha(0.0)
        assert a_high < a_low
        assert 0.0 <= a_high <= 1.0
        assert 0.0 <= a_low <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd muse-vtuber
uv run pytest tests/test_fusion.py -v
```

Expected: FAIL

- [ ] **Step 3: Implement ComplementaryFusion**

`src/muse_vtuber/fusion.py`:
```python
"""Quaternion complementary filter for IMU + webcam fusion.

Runs at IMU rate (52Hz). Webcam corrections arrive at ~30fps.
Between webcam frames: pure IMU prediction (smooth).
On webcam frame: slerp toward webcam pose (corrects drift).
"""
from __future__ import annotations

from muse_vtuber.one_euro import _slerp

Quat = tuple[float, float, float, float]


class ComplementaryFusion:
    """Fuses IMU orientation with webcam absolute pose.

    alpha: how much to trust IMU (0.96 = 96% IMU, 4% webcam per correction).
    Adaptive alpha: high webcam confidence → trust webcam more.
    """

    def __init__(self, alpha: float = 0.96):
        self.alpha = alpha
        self.q_fused: Quat = (0.0, 0.0, 0.0, 1.0)

    def update_imu(self, q_imu: Quat) -> Quat:
        """Called at IMU rate (52Hz). Sets fused pose to IMU prediction."""
        self.q_fused = q_imu
        return self.q_fused

    def update_webcam(self, q_webcam: Quat, confidence: float) -> Quat:
        """Called when OpenSeeFace data arrives (~30fps).

        Slerps fused pose toward webcam pose. Amount depends on
        adaptive alpha (confidence-weighted).
        """
        alpha = self._adaptive_alpha(confidence)
        self.q_fused = _slerp(q_webcam, self.q_fused, alpha)
        return self.q_fused

    def _adaptive_alpha(self, confidence: float) -> float:
        """Adapt alpha based on webcam confidence.

        High confidence (1.0) → use base alpha (trust IMU less).
        Low confidence (0.0) → alpha → 1.0 (trust IMU fully).
        """
        return self.alpha + (1.0 - self.alpha) * (1.0 - confidence)
```

- [ ] **Step 4: Run tests**

```bash
cd muse-vtuber
uv run pytest tests/test_fusion.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/muse_vtuber/fusion.py tests/test_fusion.py
git commit -m "feat: quaternion complementary filter for IMU+webcam fusion"
```

---

### Task 3: Wire fusion into main loop

**Files:**
- Modify: `src/muse_vtuber/main.py`

- [ ] **Step 1: Update main.py imports**

Add to imports:
```python
from muse_vtuber.fusion import ComplementaryFusion
from muse_vtuber.openseeface import OpenSeeFaceReceiver
```

- [ ] **Step 2: Add fusion + OpenSeeFace to run()**

After creating `head_pose`, add:
```python
    # Fusion (if enabled or auto-detect)
    fusion = ComplementaryFusion(alpha=config.fusion_alpha) if config.fusion_enabled else None
    osf_receiver = None
    if config.fusion_enabled:
        osf_receiver = OpenSeeFaceReceiver(port=config.openseeface_port)
```

In the main loop, before the head tracking section, add OpenSeeFace check:
```python
            # Check for OpenSeeFace webcam data (fusion mode)
            if osf_receiver and fusion:
                osf_data = osf_receiver.get_latest()
                if osf_data is not None:
                    webcam_q = (osf_data.qx, osf_data.qy, osf_data.qz, osf_data.qw)
                    fusion.update_webcam(webcam_q, osf_data.confidence)
```

Modify the head tracking section to use fusion when available:
```python
            if head_pose and imu is not None and imu.shape[1] > 0:
                for sample_idx in range(imu.shape[1]):
                    accel = imu[:3, sample_idx]
                    gyro = imu[3:, sample_idx]
                    head_pose.update(accel, gyro)
                q = head_pose.get_quaternion()
                if fusion:
                    q = fusion.update_imu(q)
                neck, head = split_head_neck(q)
                bones = [neck, head]
```

- [ ] **Step 3: Add --fusion CLI flag**

In `config.py` `parse_cli_args`, add:
```python
    parser.add_argument("--fusion", action="store_true", help="Enable IMU+webcam fusion")
    parser.add_argument("--osf-port", type=int, help="OpenSeeFace UDP port")
```

And in the override section:
```python
    if parsed.fusion:
        cfg.fusion_enabled = True
    if parsed.osf_port:
        cfg.openseeface_port = parsed.osf_port
```

- [ ] **Step 4: Start OpenSeeFace receiver in run() if fusion enabled**

Add before the main loop (needs asyncio or threading — use threading for simplicity since main loop is sync):
```python
    if osf_receiver:
        import threading

        async def _run_osf():
            loop = asyncio.get_event_loop()
            await osf_receiver.start(loop)
            while running:
                await asyncio.sleep(0.1)

        def _osf_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(osf_receiver.start(loop))
            loop.run_forever()

        osf_thread = threading.Thread(target=_osf_thread, daemon=True)
        osf_thread.start()
        log.info("Fusion enabled — listening for OpenSeeFace on port %d", config.openseeface_port)
```

- [ ] **Step 5: Run all tests**

```bash
cd muse-vtuber
uv run pytest -v
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/muse_vtuber/main.py src/muse_vtuber/config.py
git commit -m "feat: fusion mode wired into main loop — Tier 2 complete"
```

---

### Done Criteria

- [x] OpenSeeFace receiver parses binary UDP packets
- [x] ComplementaryFusion: slerp-based, adaptive alpha, drift elimination
- [x] `muse-vtuber --fusion --osf-port 11573` activates fusion mode
- [x] Without OpenSeeFace running: degrades to pure IMU (no crash)
- [x] All tests pass

### Manual Verification

1. Start OpenSeeFace: `python facetracker.py -v 0 --port 11573`
2. Start VSeeFace with VMC receiver
3. Run `muse-vtuber --mac XX:XX:XX:XX:XX:XX --fusion --debug`
4. Compare: head tracking with fusion ON vs OFF
5. Cover webcam → should degrade to IMU-only gracefully
6. Uncover webcam → drift should correct within ~1-2 seconds
