# Enobio Lab Prep (No Device in Advance)

This checklist helps you prepare before going to the lab with limited time.

## Goal

Keep the existing robot control unchanged and only swap the data bridge.

- Existing consumer: `thymio_ros.py` expects UDP JSON packets with `{"x": 0..1, "y": 0..1}`.
- New bridge: `wsl_enobio_bridge.py`.

## 1) Pre-lab setup on your own PC

### Windows side

1. Install NIC2 (already done).
2. Install Python (Windows) and ensure `python.exe` works from WSL interop.
3. Install bridge dependencies in Windows Python:

```powershell
python -m pip install --upgrade pip
python -m pip install pylsl
```

### WSL side

1. ROS 2 workspace ready (`ros2` available).
2. Optional: verify UDP receive path later with mock mode.

## 2) Dry run without EEG device

Run Enobio bridge in mock mode (from WSL):

```bash
python3 thymio_tobii/wsl_enobio_bridge.py --port 5005 --mock
```

Then run robot controller (from WSL):

```bash
python3 thymio_tobii/thymio_ros.py --mode gaze --bridge-source enobio --udp-port 5005
```

If you only want to test ROS receiver logic (without auto-starting bridge):

```bash
python3 thymio_tobii/thymio_ros.py --mode gaze --no-bridge --udp-port 5005
```

## 3) Lab-day quick steps with real EEG

1. In NIC2 Protocol Settings, enable LSL stream.
2. Note LSL outlet name (example: `provided_name-EEG` source family).
3. Start bridge:

```bash
python3 thymio_tobii/wsl_enobio_bridge.py --port 5005
```

Or filter by outlet name:

```bash
python3 thymio_tobii/wsl_enobio_bridge.py --port 5005 --lsl-outlet-name YOUR_OUTLET_NAME
```

4. Start controller:

```bash
python3 thymio_tobii/thymio_ros.py --mode gaze --bridge-source enobio --udp-port 5005
```

## 4) Troubleshooting

- `python.exe` not found:
  - Install Python on Windows and enable PATH.
- No LSL stream found:
  - Confirm NIC2 started acquisition and LSL is enabled.
- Robot not moving:
  - Verify `/cmd_vel` subscriber readiness and USB attach for Thymio.
- Data too noisy:
  - Keep this minimal mapping first; tune channel mapping in bridge later.
