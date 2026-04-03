# Plan 3: Fusion — OpenSeeFace + IMU Complementary Filter

> **STATUS: DEPRECATED (2026-04-03)**
>
> This plan is shelved indefinitely. The primary target is VTube Studio, which already has its own webcam face tracking. Adding OpenSeeFace fusion would only benefit non-VTS targets (VMC/VRChat), and the VTS plugin API supports per-parameter weight blending that already lets users mix IMU and camera tracking without OpenSeeFace.
>
> Reconsidering only if: (a) VMC-only users become a significant audience, or (b) VTS's built-in tracking is insufficient for a specific use case.

> **For agentic workers:** Do NOT implement this plan. It is deprecated.

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

Each face block is exactly **1785 bytes**. Multi-face packets concatenate blocks. See `docs/research/2026-03-30-openseeface-udp-protocol.md` for the full byte layout. Key fields we need:

| Offset | Size | Format | Field |
|--------|------|--------|-------|
| 0 | 8 | `d` | timestamp (float64) |
| 8 | 4 | `i` | face_id (int32) |
| 28 | 1 | `B` | success (uint8, 0 or 1) |
| 29 | 4 | `f` | pnp_error (float32) |
| 33 | 16 | `4f` | quaternion x,y,z,w (float32×4) |

**Critical parsing notes:**
- The `B` at offset 28 is 1 byte with NO alignment padding — next float is at offset 29, not 32
- Quaternion order is `(x, y, z, w)` — standard, not Hamilton
- Byte order is native (little-endian on x86), no explicit prefix

- [ ] **Step 1: Write test**

`tests/test_openseeface.py`:
```python
import struct

import pytest

from muse_vtuber.openseeface import (
    FACE_BLOCK_SIZE,
    OpenSeeFaceData,
    parse_openseeface_packet,
)


def _build_fake_packet(
    qx: float = 0.0,
    qy: float = 0.0,
    qz: float = 0.0,
    qw: float = 1.0,
    success: int = 1,
    pnp_error: float = 0.1,
) -> bytes:
    """Build a full 1785-byte fake OpenSeeFace UDP packet.

    Real format: timestamp(d) face_id(i) width(f) height(f)
    right_eye(f) left_eye(f) success(B) pnp_error(f)
    quat(4f) euler(3f) translation(3f)
    landmark_conf(68f) landmarks_2d(136f) points_3d(210f) features(14f)
    """
    header = struct.pack(
        "d i f f f f B f 4f 3f 3f",
        0.0,              # timestamp
        0,                # face_id
        640.0, 480.0,     # width, height
        0.9, 0.9,         # right_eye_open, left_eye_open
        success,          # success (uint8)
        pnp_error,        # pnp_error
        qx, qy, qz, qw,  # quaternion
        0.0, 0.0, 0.0,    # euler
        0.0, 0.0, 0.0,    # translation
    )
    # Fill landmarks + 3D points + features with zeros
    landmark_conf = struct.pack("68f", *([0.0] * 68))
    landmarks_2d = struct.pack("136f", *([0.0] * 136))
    points_3d = struct.pack("210f", *([0.0] * 210))
    features = struct.pack("14f", *([0.0] * 14))
    return header + landmark_conf + landmarks_2d + points_3d + features


def test_face_block_size():
    """Each face block is exactly 1785 bytes."""
    packet = _build_fake_packet()
    assert len(packet) == FACE_BLOCK_SIZE
    assert len(packet) == 1785


def test_parse_packet_extracts_quaternion():
    packet = _build_fake_packet(qx=0.1, qy=0.2, qz=0.3, qw=0.9)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert abs(data.qx - 0.1) < 0.001
    assert abs(data.qy - 0.2) < 0.001
    assert abs(data.qz - 0.3) < 0.001
    assert abs(data.qw - 0.9) < 0.001


def test_parse_packet_extracts_success():
    packet = _build_fake_packet(success=1)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert data.success is True

    packet_fail = _build_fake_packet(success=0)
    data_fail = parse_openseeface_packet(packet_fail)
    assert data_fail is not None
    assert data_fail.success is False


def test_parse_short_packet_returns_none():
    data = parse_openseeface_packet(b"\x00\x01\x02")
    assert data is None


def test_pnp_error_extracted():
    packet = _build_fake_packet(pnp_error=3.14)
    data = parse_openseeface_packet(packet)
    assert data is not None
    assert abs(data.pnp_error - 3.14) < 0.01
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
Each face block is exactly 1785 bytes (multi-face packets concatenate blocks).

Protocol reference: docs/research/2026-03-30-openseeface-udp-protocol.md
Source: https://github.com/emilianavt/OpenSeeFace (facetracker.py)
"""
from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

log = logging.getLogger("openseeface")

# Per-face block layout (1785 bytes total):
# timestamp(d=8) face_id(i=4) width(f=4) height(f=4)
# right_eye(f=4) left_eye(f=4) success(B=1) pnp_error(f=4)
# quaternion(4f=16) euler(3f=12) translation(3f=12)
# landmark_conf(68f=272) landmarks_2d(136f=544) points_3d(210f=840) features(14f=56)
FACE_BLOCK_SIZE = 1785

# Header format: everything before landmarks (73 bytes)
# NOTE: success is B (1 byte, uint8), NOT f (4 byte float).
# This means NO alignment padding — pnp_error starts at offset 29, not 32.
_HEADER_FMT = "d i f f f f B f 4f 3f 3f"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)  # 73 bytes


@dataclass
class OpenSeeFaceData:
    """Parsed tracking data from one OpenSeeFace face block."""

    face_id: int
    qx: float
    qy: float
    qz: float
    qw: float
    success: bool        # True if tracking succeeded
    pnp_error: float
    right_eye_open: float
    left_eye_open: float


def parse_openseeface_packet(data: bytes) -> OpenSeeFaceData | None:
    """Parse the first face from an OpenSeeFace UDP packet.

    Returns None if packet is too short (< 1785 bytes).
    For multi-face, only the first face (id=0) is used.
    """
    if len(data) < FACE_BLOCK_SIZE:
        return None
    try:
        fields = struct.unpack_from(_HEADER_FMT, data, 0)
    except struct.error:
        return None

    # Unpack field order matches _HEADER_FMT:
    # timestamp(0) face_id(1) width(2) height(3)
    # right_eye(4) left_eye(5) success(6) pnp_error(7)
    # qx(8) qy(9) qz(10) qw(11) euler_x(12-14) trans_x(15-17)
    return OpenSeeFaceData(
        face_id=fields[1],
        qx=fields[8],
        qy=fields[9],
        qz=fields[10],
        qw=fields[11],
        success=bool(fields[6]),
        pnp_error=fields[7],
        right_eye_open=fields[4],
        left_eye_open=fields[5],
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
        """Get and consume most recent tracking data (or None if nothing received)."""
        data = self.latest
        self.latest = None  # consume
        return data

    @property
    def is_connected(self) -> bool:
        """True if we've received at least one valid packet."""
        return self._transport is not None
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
                if osf_data is not None and osf_data.success:
                    webcam_q = (osf_data.qx, osf_data.qy, osf_data.qz, osf_data.qw)
                    # Confidence derived from PnP error: low error = high confidence
                    confidence = max(0.0, min(1.0, 1.0 - osf_data.pnp_error / 20.0))
                    fusion.update_webcam(webcam_q, confidence)
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
