# Enobio Lab Prep (Phase 2)

This checklist is updated for the Phase-2 architecture refactor.

## Goal

Use ROS2 launch as the only orchestration layer.

- Control semantics are now `speed_intent/steer_intent`.
- `thymio_ros.py` is deprecated and no longer used as the main workflow.
- Bridge scripts are isolated under `thymio_control/tools/bridges/`.

## 1) Pre-lab setup

### Windows side

1. Install NIC2.
2. Install Python on Windows and ensure `python.exe` is accessible from WSL.
3. Install dependency in Windows Python:

```powershell
python -m pip install --upgrade pip
python -m pip install pylsl
```

### WSL side

1. ROS2 workspace is built and sourced.
2. `ros2` command works.
3. If using physical robot via USB over WSL, run standalone helper first:

```bash
thymio_control/tools/system/prepare_usb.sh 1-1
```

## 2) Dry run without EEG device (mock)

Run bridge alone for quick validation:

```bash
python3 thymio_control/tools/bridges/wsl_enobio_bridge.py --port 5005 --mock
```

Then run control node / launch in another terminal.

## 3) Lab-day workflow (real EEG + launch orchestration)

1. Enable LSL streaming in NIC2.
2. Start orchestration from WSL:

```bash
ros2 launch thymio_control experiment_core.launch.py run_eeg:=true run_gaze:=false use_enobio_bridge:=true enobio_udp_port:=5005
```

If needed, pin an outlet name by running bridge manually:

```bash
python3 thymio_control/tools/bridges/wsl_enobio_bridge.py --port 5005 --lsl-outlet-name YOUR_OUTLET_NAME
```

## 4) Troubleshooting

- `python.exe` not found:
  - Install Python on Windows and add it to PATH.
- No LSL EEG stream found:
  - Confirm NIC2 acquisition started and LSL is enabled.
  - Use `--lsl-outlet-name` when multiple streams exist.
- Robot not moving:
  - Verify launch args (`run_eeg`, `use_enobio_bridge`, `use_sim`) are correct.
  - Check `/cmd_vel` consumers and driver status.
- Data too noisy:
  - Start with mock mode and then tune channel mapping in `wsl_enobio_bridge.py`.
