# Enobio Lab Prep (No Device in Advance)

This checklist is optimized for limited lab time.

## Goal

Run only one command from the main controller and keep old behavior unchanged.

- Existing consumer: thymio_ros.py expects UDP JSON packets with {"x": 0..1, "y": 0..1}
- Enobio bridge is auto-started by thymio_ros.py when bridge-source is enobio

## Defaults (you usually do not need to set these)

- mode default: gaze
- udp-port default: 5005
- bridge-source default: tobii

So for Enobio testing, you only need to override bridge-source (and optional Enobio options).

## 1) Pre-lab setup on your own PC

### Windows side

1. Install NIC2.
2. Install Python on Windows and ensure python.exe is accessible from WSL interop.
3. Install dependency in Windows Python (needed for real LSL mode):

```powershell
python -m pip install --upgrade pip
python -m pip install pylsl
```

### WSL side

1. ROS 2 workspace ready and sourced.
2. Verify ros2 is available in PATH.

## 2) Dry run without EEG device (recommended before lab)

Use only the main controller script in the new layout (bridge is auto-started in mock mode):

```bash
python3 thymio_control/scripts/thymio_ros.py --bridge-source enobio --enobio-mock
```

Expected behavior:

- No real EEG device required
- Mock x/y data drives the existing gaze control path
- Good for end-to-end validation of ROS + UDP + motion pipeline

## 3) Lab-day quick steps with real EEG (NIC2 LSL)

1. In NIC2 Protocol Settings, enable LSL streaming.
2. If possible, note the EEG outlet name.
3. Start from WSL with one command:

```bash
python3 thymio_control/scripts/thymio_ros.py --bridge-source enobio
```

If multiple EEG streams exist, pin by outlet name:

```bash
python3 thymio_control/scripts/thymio_ros.py --bridge-source enobio --enobio-lsl-outlet-name YOUR_OUTLET_NAME
```

## 4) Optional advanced/debug usage

Disable auto bridge and run your own external sender:

```bash
python3 thymio_control/scripts/thymio_ros.py --bridge-source enobio --no-bridge
```

Run bridge alone only for debugging (not required in normal workflow):

```bash
python3 thymio_control/scripts/wsl_enobio_bridge.py --port 5005 --mock
python3 thymio_control/scripts/wsl_enobio_bridge.py --port 5005 --lsl-outlet-name YOUR_OUTLET_NAME
```

## 5) Troubleshooting

- python.exe not found:
  - Install Python on Windows and enable PATH.
- No LSL EEG stream found:
  - Confirm NIC2 acquisition started and LSL is enabled.
  - Try enobio-lsl-outlet-name if multiple outlets are present.
- Robot not moving:
  - Verify /cmd_vel subscriber readiness and Thymio USB attach.
  - Run test mode once to validate robot driver path.
- Data too noisy:
  - Keep minimal mapping first, then tune channel mapping in wsl_enobio_bridge.py.
