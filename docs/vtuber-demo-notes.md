# VTuber Demo — Test Notes

## Setup (Required Before First Run)

The VRM model file is not committed (11MB binary). Download it before running:

```bash
curl -L -o frontend/public/models/default-avatar.vrm \
  "https://github.com/pixiv/three-vrm/raw/release/packages/three-vrm/examples/models/VRM1_Constraint_Twist_Sample.vrm"
```

Then start the backend and frontend:
```bash
# Terminal 1
python -m backend.main --synthetic   # or --mac "XX:XX:XX:XX:XX:XX"

# Terminal 2
cd frontend && pnpm dev
```

Open: http://localhost:3000/vtuber

## Known Gaps (Demo Phase)

- **Yaw drift**: No magnetometer on Muse 2, so left/right turns drift over time. Use the Recenter button or triple-blink to reset. Planned fix in production phase: slow decay toward home yaw when head is still.
- **Coordinate mapping**: The raw Madgwick quaternion is applied directly to VRM bones without axis remapping. With real Muse hardware, axes may be inverted or swapped — tune empirically.
- **VRM model blink**: The bundled model (`VRM1_Constraint_Twist_Sample.vrm`) is a constraint demo model, not a VRoid character. Verify it has a `blink` expression before relying on blink detection. If not, replace with an AvatarSample_A model from VRoid.

## Synthetic Mode Observations
- [ ] Model loads correctly
- [ ] Head responds to IMU data (jitter from noise expected)
- [ ] Blink expression triggers on bci_event
- [ ] Recenter button works
- [ ] No console errors
- [ ] Frame rate acceptable

## Real Muse Observations (fill in during hardware test)
- [ ] Coordinate mapping correct? (nod = pitch, turn = yaw, tilt = roll)
- [ ] Axes inverted? Which ones?
- [ ] Yaw drift rate (degrees per minute estimate)
- [ ] Madgwick beta value that feels best
- [ ] Blink animation timing vs detection latency
- [ ] Overall latency feel (responsive? laggy?)
- [ ] Any motion artifacts?
- [ ] Does the VRM model's blink expression actually work?
