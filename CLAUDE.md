# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a ROS2-based Thymio robot control platform for EEG and gaze-control experiments, developed primarily on **Windows + WSL2** (Ubuntu 24.04 with ROS2 Kilted). The system bridges EEG/gaze input devices to Thymio robot control via ROS2 topics.

## Build & Run Commands

### ROS2 Packages
```bash
colcon build --symlink-install
source install/setup.bash
```

### Launch Files
| Command | Purpose |
|---|---|
| `ros2 launch thymio_control eeg_thymio.launch.py` | EEG control only |
| `ros2 launch thymio_control gaze_thymio.launch.py` | Gaze control only |
| `ros2 launch thymio_control experiment_core.launch.py` | Unified orchestration |

### Tests
```bash
pytest thymio_control/test/test_*.py -v
```

### Web GUI
```bash
# Backend (FastAPI, port 8010)
cd web_gui/backend && source ../../.venv/bin/activate && python -m app.main

# Frontend (Vite, port 5173)
cd web_gui/frontend && npm install && npm run dev
```

## Architecture

Four main components communicate via ROS2 topics, WebSockets, and UDP/TCP:

```
web_gui (React + FastAPI) ←REST/WebSocket→ thymio_web_bridge (Gazebo camera)
                                        ↓ ROS2 topics
                              thymio_control (EEG/Gaze processing)
                                        ↓ /cmd_vel
                              Gazebo sim OR Real Thymio (asebaros)
```

WSL ↔ Windows bridges handle Tobii eye-tracker (UDP) and Enobio EEG (TCP).

### Key Files
- `thymio_control/thymio_control/eeg_control_pipeline.py` — Core EEG signal processing pipeline
- `thymio_control/launch/experiment_core.launch.py` — Main launch orchestration
- `thymio_control/config/experiment_config.yaml` — Pipeline config (source type, channels, algorithm)
- `thymio_control/config/eeg_control_node.params.yaml` — ROS2 node parameters

### Data Flow
1. Enobio EEG device → TCP → `eeg_control_pipeline.py` parses and computes features
2. Features mapped to `geometry_msgs/Twist` via swappable strategy algorithms
3. Published to `/cmd_vel` → robot moves

### Key ROS2 Topics
- `/cmd_vel` — velocity commands (Twist)
- `/eeg_analysis` — EEG feature analysis output
- `/camera/image_raw` — camera feed from Gazebo or real robot

## Key Design Principles

From PROJECT_ANALYSIS.md:

1. **Config-driven**: All device ports, channel mappings, algorithms are YAML-injected, never hardcoded
2. **Strategy Pattern**: `POLICIES` dict in `eeg_control_pipeline.py` for swappable control algorithms
3. **Adapter Pattern**: `build_adapter()` factory creates TCP/LSL/File/Mock data adapters
4. **Watchdog (0.5s)**: If no EEG data received, reuse last known Twist — NOT default to full speed
5. **Buffer Drain**: TCP reads use non-blocking `recv()` in a loop until `BlockingIOError`, keeping only the last complete packet per cycle
6. **Fail-fast**: Missing fields or out-of-bounds channel indices must raise explicit exceptions, not silently default

## Testing Strategy

Given the difficulty of physical robot testing, the project uses **test-driven development with pytest**:
- All tests live in `thymio_control/test/` as `test_*.py` files
- Each new feature requires a unit test in the same directory
- Tests use mock data to verify logic correctness
- Run tests: `pytest thymio_control/test/test_<name>.py -v`

## Source Types

`experiment_config.yaml` controls the data source via `pipeline_config.source_type`:
- `"tcp_client"` — live Enobio EEG via TCP
- `"lsl"` — Lab Streaming Layer
- `"file"` — offline `.easy`/`.info` Enobio recordings in `enobio_recodes/`
- `"mock"` — simulated data for testing

## Development Guidelines

Based on [Andrej Karpathy's coding principles](https://github.com/forrestchang/andrej-karpathy-skills), adapted for ROS2/robotics projects.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

- State assumptions explicitly — especially about ROS2 topic timing, hardware handshake, or data format assumptions
- If multiple interpretations exist, present them before implementing
- If a simpler approach exists, say so
- If something is unclear (e.g., EEG channel mapping, Gazebo world behavior), stop and ask

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was requested
- No abstractions for single-use code — the `POLICIES` dict and `build_adapter()` factory are the exceptions (justified by the strategy/adapter patterns)
- No "flexibility" not in the YAML config
- If you write 200 lines and it could be 50, rewrite it

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting
- Don't refactor things that aren't broken
- Match existing style
- When your changes create unused imports/variables, remove them — but don't touch pre-existing dead code
- The test: every changed line should trace directly to the user's request

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```

- "Add a new EEG algorithm" → "Write tests with mock EEG data, verify output Twist, then integrate"
- "Fix the TCP buffer drain" → "Confirm last complete packet is kept, no data corruption"
- "Add a new launch file" → "Verify all topics remapped and parameters loaded correctly"

---

**These guidelines work if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation.

## Environment

- ROS2 Kilted (or Humble/Iron) on Ubuntu 24.04 inside WSL2
- Python 3.12+, uses `.venv` virtual environment (not system Python)
- Aseba Runtime for real Thymio hardware communication
