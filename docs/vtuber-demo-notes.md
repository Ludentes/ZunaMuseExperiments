# VTuber Demo — Test Notes

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
