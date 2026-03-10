# Docker BLE Access for BrainFlow + Muse 2

Date: 2026-03-10

## 1. How Linux BLE Works

The Linux Bluetooth stack has three layers:

```
Application (BrainFlow / SimpleBLE)
    |
    v  D-Bus IPC (system bus socket)
    |
bluetoothd daemon (BlueZ userspace)
    |
    v  Management Interface (mgmt API, since Linux 3.4)
    |
Kernel Bluetooth subsystem (/net/bluetooth/, /drivers/bluetooth/)
    |
    v  HCI (Host Controller Interface)
    |
Hardware (USB/UART Bluetooth controller, exposed as /dev/hci0)
```

Key components:
- **BlueZ** is the official Linux Bluetooth stack, included in all major distros
- **bluetoothd** is the central userspace daemon managing devices, services, pairing, scanning
- **D-Bus system bus** (`/var/run/dbus/system_bus_socket`) is the IPC mechanism -- applications never talk to the kernel directly, they talk to bluetoothd via D-Bus
- **HCI** is the standardized interface between host OS and Bluetooth controller chip
- **Management Interface** (since Linux 3.4) replaced raw HCI sockets for kernel communication
- Persistent state (paired devices, keys) stored in `/var/lib/bluetooth/`

**BrainFlow's BLE path on Linux:** BrainFlow uses **SimpleBLE** library (specifically **SimpleBluez**, a C++ D-Bus wrapper for BlueZ). So the chain is: BrainFlow -> SimpleBLE -> SimpleBluez -> D-Bus -> bluetoothd -> kernel -> hardware.

## 2. Docker BLE Options (Least to Most Privileged)

### Option A: D-Bus Passthrough (Least Privileged -- RECOMMENDED)

Share host's D-Bus socket and Bluetooth device. Host's bluetoothd manages all BLE operations.

```yaml
# docker-compose.yml
services:
  backend:
    build: .
    volumes:
      - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket
    devices:
      - /dev/hci0:/dev/hci0
    cap_add:
      - NET_ADMIN
      - NET_RAW
    group_add:
      - bluetooth
```

```bash
# Equivalent docker run
docker run \
  -v /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket \
  --device /dev/hci0:/dev/hci0 \
  --cap-add=NET_ADMIN \
  --cap-add=NET_RAW \
  myimage
```

**What each flag does:**
- `-v /var/run/dbus/system_bus_socket:...` -- lets container talk to host's bluetoothd via D-Bus
- `--device /dev/hci0` -- passes through the HCI device (Bluetooth controller)
- `--cap-add=NET_ADMIN` -- allows network admin ops (required for BLE scanning, `hciconfig up`)
- `--cap-add=NET_RAW` -- allows raw socket access (required for low-level BLE packet handling)
- `group_add: bluetooth` -- ensures container user is in the bluetooth group for D-Bus policy

**Security:** Good. Only two capabilities added (vs 37+ with --privileged). Container can manipulate network interfaces and send raw packets, but cannot access other devices, mount filesystems, or load kernel modules.

**D-Bus policy:** May need a policy file on the host at `/etc/dbus-1/system.d/bluetooth-docker.conf` to allow the container's user to talk to bluetoothd:

```xml
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
  "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <policy context="default">
    <allow send_destination="org.bluez"/>
    <allow send_interface="org.bluez.GattCharacteristic1"/>
    <allow send_interface="org.bluez.GattDescriptor1"/>
    <allow send_interface="org.freedesktop.DBus.ObjectManager"/>
    <allow send_interface="org.freedesktop.DBus.Properties"/>
  </policy>
</busconfig>
```

### Option B: D-Bus + --net=host (Medium Privilege)

Same as Option A but with `--net=host` which shares the host's network namespace entirely.

```yaml
services:
  backend:
    build: .
    network_mode: host
    volumes:
      - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket
    cap_add:
      - NET_ADMIN
      - NET_RAW
```

**When needed:** Some BLE stacks require host networking because Bluetooth uses AF_BLUETOOTH sockets which live in the network namespace. If Option A fails with "No such device" errors on BLE scan, --net=host is the fix.

**Security:** Moderate. Container shares host's entire network stack (can bind any port, see all interfaces). No network isolation.

### Option C: --privileged (Maximum Privilege -- AVOID)

```bash
docker run --privileged --net=host -v /var/run/dbus:/var/run/dbus myimage
```

**Security:** Bad. Container has full access to ALL host devices, can load kernel modules, access all hardware. Essentially no container isolation. Only use for debugging.

### Comparison Table

| Approach | Security | Complexity | Likely to work? |
|----------|----------|------------|-----------------|
| A: D-Bus + device + caps | Good | Medium | High (most BLE apps) |
| B: A + --net=host | Moderate | Low | Very high |
| C: --privileged | Bad | Lowest | Guaranteed |

## 3. BrainFlow + Docker: Known Issues & Findings

- **No official BrainFlow Docker documentation exists.** BrainFlow's CI uses device emulators instead of real hardware for testing in containers.
- **SimpleBLE (used by BrainFlow for Muse 2) talks to BlueZ via D-Bus.** This means Option A (D-Bus passthrough) should work since SimpleBLE/SimpleBluez just needs D-Bus access to the host's bluetoothd.
- **BLED112 dongle alternative:** BrainFlow also supports BLED112 USB dongle for Muse, which uses serial/USB communication instead of BLE stack. This would only need `--device /dev/ttyACM0` (much simpler), but requires buying the dongle (~$15-20).
- **libdbus requirement:** The container image must have `libdbus-1-dev` (or `libdbus-1-3` runtime) installed for SimpleBLE to work.

## 4. Security Implications Summary

| Flag/Volume | What it grants | Risk |
|-------------|---------------|------|
| `--device /dev/hci0` | Access to Bluetooth HCI device only | Low -- scoped to one device |
| `-v dbus socket` | IPC to host's D-Bus system bus | Medium -- can talk to any D-Bus service (not just BT) |
| `--cap-add NET_ADMIN` | Network admin (ifconfig, iptables, BLE scan) | Medium -- can reconfigure host networking |
| `--cap-add NET_RAW` | Raw sockets (BLE packets, packet sniffing) | Medium -- can sniff network traffic |
| `--net=host` | Full host network namespace | High -- no network isolation at all |
| `--privileged` | ALL capabilities + ALL devices | Critical -- no isolation, full host access |

**Mitigations for Option A:**
- Run container process as non-root user
- Use read-only D-Bus mount (`:ro`) if only reading BT state
- Drop all other capabilities with `--cap-drop=ALL` before adding NET_ADMIN/NET_RAW
- Use `--security-opt=no-new-privileges` to prevent privilege escalation

## 5. Recommended Approach for ZyphraExps

### Primary recommendation: Hybrid Architecture

Keep BrainFlow (BLE-dependent) on the host. Only containerize ZUNA (GPU-dependent, no BLE needed).

```
Host OS:
  backend/main.py (BrainFlow + EEGServer + WebSocket)
     |
     | sends EEG data via local socket/pipe/HTTP
     v
Docker container:
  ZUNA inference service (GPU access via nvidia-docker)
     |
     | returns reconstructed EEG
     v
Host OS:
  backend receives reconstructed data, serves to frontend
```

**Why this is better:**
1. BLE in Docker is a solved-but-fragile problem -- debugging BLE issues inside a container is painful
2. ZUNA needs GPU + specific CUDA/PyTorch versions -- perfect Docker use case
3. Muse 2 BLE connection is already finicky (see MEMORY.md: power cycles needed after disconnects). Adding Docker layer increases failure modes.
4. Separation of concerns: BLE acquisition is a host-level concern, ML inference is a compute concern

### If full containerization is required: Use Option A first

```yaml
services:
  backend:
    build: ./backend
    volumes:
      - /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket:rw
    devices:
      - /dev/hci0:/dev/hci0
    cap_add:
      - NET_ADMIN
      - NET_RAW
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges
```

Fall back to adding `network_mode: host` if BLE scanning fails.

## 6. Gotchas and Known Issues

1. **AF_BLUETOOTH sockets and network namespaces:** Bluetooth sockets (AF_BLUETOOTH family) may not be visible in isolated network namespaces. If BLE scanning returns no devices with Option A, you need `--net=host`.

2. **D-Bus authentication:** Container processes connecting to host D-Bus must be authorized. If running as non-root, need D-Bus policy file on host.

3. **bluetoothd contention:** Only one process should manage the BLE adapter. If host's bluetoothd is running AND container tries to run its own, they will conflict. Either use host's bluetoothd (via D-Bus passthrough) OR stop host's and run inside container -- never both.

4. **Device naming:** `/dev/hci0` may not exist on modern kernels using `mgmt` API. Check with `hciconfig` or `bluetoothctl`. The device might only be accessible via D-Bus, not via raw HCI.

5. **Muse-specific:** BrainFlow's Muse 2 connection already requires careful lifecycle management (no killing server while connected). Docker adds another failure mode -- container restart/crash will drop the BLE connection and may require Muse power cycle.

6. **Container image size:** Including BrainFlow + SimpleBLE + libdbus + BlueZ tools adds significant image size vs a minimal Python image.

7. **Rootless Docker:** `--device` flag may not work with rootless Docker. Need rootful Docker for device passthrough.

## Sources

- [How to run containerized Bluetooth applications with BlueZ (Thomas Huffert, Medium)](https://medium.com/omi-uulm/how-to-run-containerized-bluetooth-applications-with-bluez-dced9ab767f6)
- [Docker Bluetooth and BlueZ without --privileged --net=host (Docker Forums)](https://forums.docker.com/t/docker-bluetooth-and-bluez-without-privileged-net-host/125955)
- [Bluetooth socket can't be opened inside container (moby/moby #16208)](https://github.com/moby/moby/issues/16208)
- [How to Access a BLE Bluetooth Dongle Inside Docker (linuxvox.com)](https://linuxvox.com/blog/accessing-bluetooth-dongle-from-inside-docker/)
- [Bluetooth and Docker part 2 (Home Assistant Community)](https://community.home-assistant.io/t/bluetooth-and-docker-part-2/447334)
- [BlueZ Linux Bluetooth Stack Overview](https://naehrdine.blogspot.com/2021/03/bluez-linux-bluetooth-stack-overview.html)
- [SimpleBLE Documentation](https://simpleble.readthedocs.io/en/latest/index.html)
- [BrainFlow Muse native BLE support](https://brainflow.org/2022-05-16-muse-linux/)
- [BrainFlow Supported Boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html)
- [Bluetooth overview - Linux kernel (stm32mpu wiki)](https://wiki.st.com/stm32mpu/wiki/Bluetooth_overview)
- [Docker Security Documentation](https://docs.docker.com/engine/security/)
