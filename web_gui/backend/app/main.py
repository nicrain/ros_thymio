from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .command_runner import start_system, stop_system
from .config_store import get_config_envelope, init_store, patch_config
from .mock_stream import MockSignalGenerator
from .models import CommandRequest, ConfigPatch
from .ros_probe import probe_system

app = FastAPI(title="Thymio Web GUI Backend", version="0.1.0")

frontend_origin = os.getenv("WEB_GUI_FRONTEND_ORIGIN", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin, "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mock_mode = os.getenv("WEB_GUI_MOCK_MODE", "true").lower() in {"1", "true", "yes"}
_generator = MockSignalGenerator()


@app.on_event("startup")
async def _startup() -> None:
    init_store()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "mock_mode": mock_mode}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return get_config_envelope().model_dump()


@app.put("/api/config")
def update_config(req: ConfigPatch) -> dict[str, Any]:
    return patch_config(req.patch).model_dump()


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    return probe_system(mock_mode).model_dump()


@app.post("/api/system/start")
def api_start(req: CommandRequest) -> dict[str, Any]:
    cfg = get_config_envelope().config
    return start_system(cfg, dry_run=req.dry_run).model_dump()


@app.post("/api/system/stop")
def api_stop(req: CommandRequest) -> dict[str, Any]:
    return stop_system(dry_run=req.dry_run).model_dump()


@app.websocket("/ws/stream")
async def ws_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            frame = _generator.next()
            payload = {
                "status": probe_system(mock_mode).model_dump(),
                "channels": frame["channels"],
                "features": frame["features"],
                "control": frame["control"],
                "timestamp": frame["timestamp"],
            }
            await websocket.send_json(payload)
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return


# --------------------------------------------------------------------------- #
# /ws/gazebo_frame — proxies frames from the Gazebo camera bridge node
# (ros2 run thymio_web_bridge gazebo_camera_bridge → ws://127.0.0.1:8011)
# Frontend connects here to avoid CORS and direct port exposure.
# --------------------------------------------------------------------------- #
CAMERA_BRIDGE_URL = os.getenv("CAMERA_BRIDGE_URL", "ws://127.0.0.1:8011/ws/gazebo_frame")


@app.websocket("/ws/gazebo_frame")
async def ws_gazebo_frame(websocket: WebSocket) -> None:
    """Proxy WebSocket → upstream camera bridge. Falls back gracefully if bridge
    is not running (e.g. Gazebo not started yet)."""
    await websocket.accept()
    try:
        import websockets
        async with websockets.connect(CAMERA_BRIDGE_URL, ping_interval=None) as upstream:
            while True:
                data = await upstream.recv()
                await websocket.send(data)
    except (websockets.exceptions.InvalidURI, websockets.exceptions.ConnectionClosedError):
        await websocket.send_json({"error": "camera_bridge_unavailable"})
    except OSError:
        await websocket.send_json({"error": "camera_bridge_offline"})
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8010, reload=False)
