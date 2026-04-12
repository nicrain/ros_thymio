# Thymio Web GUI

Web UI + Python backend prototype for the `ros_thymio` workspace.

## Goals

- Works on local machine even when ROS2 hardware runtime is unavailable.
- Default mock mode provides full dashboard interactions and realtime charts.
- Preserves an upgrade path to real ROS2 runtime probing and launch control.

## Directory Layout

- `backend/`: FastAPI service, WebSocket stream, config model, runtime probes.
- `frontend/`: React + Vite + ECharts dashboard.
- `DESIGN.md`: visual language reference provided by user.
- `design.md`: implementation notes mapping design reference to this prototype.

## Quick Start

### 1) Backend

```bash
cd web_gui/backend
source ../../.venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

Backend defaults to `http://localhost:8010`.

### 2) Frontend

```bash
cd web_gui/frontend
npm install
npm run dev
```

Frontend defaults to `http://localhost:5173`.

## Runtime Mode

- Mock mode is enabled by default via `WEB_GUI_MOCK_MODE=true`.
- To switch to real mode:

```bash
export WEB_GUI_MOCK_MODE=false
```

Current prototype still keeps command execution in dry-run mode by default.

## Available APIs

- `GET /api/health`
- `GET /api/config`
- `PUT /api/config`
- `GET /api/status`
- `POST /api/system/start`
- `POST /api/system/stop`
- `WS /ws/stream`

## Notes

- `PUT /api/config` currently updates backend in-memory config model.
- Real `ros2 launch` process supervision is reserved for next step.
