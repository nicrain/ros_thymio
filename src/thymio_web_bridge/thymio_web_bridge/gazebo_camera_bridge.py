"""
gazebo_camera_bridge — ROS2 node that subscribes to /image_topic (Gazebo camera,
bridged via ros_gz_bridge) and pushes JPEG frames via WebSocket to connected
web clients.

Run:  ros2 run thymio_web_bridge gazebo_camera_bridge

WebSocket default: ws://127.0.0.1:8011/ws/gazebo_frame
"""

import asyncio
import base64
import json
import queue
import threading
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from sensor_msgs.msg import Image as SensorImage
from std_msgs.msg import String


# --------------------------------------------------------------------------- #
# Shared frame queue — written by ROS thread, read by WS thread
# --------------------------------------------------------------------------- #
_frame_queue: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=2)
_latest_frame: Optional[bytes] = None


# --------------------------------------------------------------------------- #
# ROS2 subscription
# --------------------------------------------------------------------------- #
class GazeboCameraBridge(Node):
    def __init__(self) -> None:
        super().__init__('gazebo_camera_bridge')
        cb_group = ReentrantCallbackGroup()
        self.sub = self.create_subscription(
            SensorImage,
            '/image_topic',
            self._on_image,
            1,
            callback_group=cb_group,
        )
        self.get_logger().info('GazeboCameraBridge started — listening on /image_topic')

    def _on_image(self, msg: SensorImage) -> None:
        """Convert sensor_msgs/Image → JPEG bytes, push to queue."""
        global _latest_frame
        try:
            import cv_bridge
            bridge = cv_bridge.CvBridge()
            cv_img = bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            import cv2
            _, jpg_bytes = cv2.imencode('.jpg', cv_img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            jpg_bytes = jpg_bytes.tobytes()
            if _frame_queue.full():
                try:
                    _frame_queue.get_nowait()
                except queue.Empty:
                    pass
            _frame_queue.put_nowait(jpg_bytes)
            _latest_frame = jpg_bytes
        except Exception as e:
            self.get_logger().warn(f'Image conversion failed: {e}', throttle_duration_sec=5)


# --------------------------------------------------------------------------- #
# Async WebSocket server — serves the latest frame to connected browsers
# --------------------------------------------------------------------------- #
async def ws_server(host: str = '127.0.0.1', port: int = 8011) -> None:
    import websockets
    clients: set = set()

    async def relay(websocket) -> None:
        path = getattr(websocket.request, 'path', '')
        if path != '/ws/gazebo_frame':
            await websocket.send(json.dumps({'error': 'unknown path'}))
            await websocket.close()
            return
        clients.add(websocket)
        try:
            # Send latest frame immediately if available
            if _latest_frame is not None:
                b64 = base64.b64encode(_latest_frame).decode('ascii')
                await websocket.send(json.dumps({'image': b64, 'format': 'jpeg'}))
            # Then stream new frames as they arrive
            while True:
                try:
                    # Run blocking queue read in a worker thread so the
                    # websocket event loop stays responsive to new handshakes.
                    frame = await asyncio.to_thread(_frame_queue.get, True, 5.0)
                except queue.Empty:
                    # Send ping to keep connection alive
                    await websocket.ping()
                    continue
                if frame is None:
                    break
                b64 = base64.b64encode(frame).decode('ascii')
                await websocket.send(json.dumps({'image': b64, 'format': 'jpeg'}))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            clients.discard(websocket)

    async with websockets.serve(relay, host, port):
        print(f'WebSocket server running on ws://{host}:{port}/ws/gazebo_frame')
        await asyncio.Future()  # run forever


def run_ws() -> None:
    asyncio.run(ws_server())


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main(args=None) -> None:
    rclpy.init(args=args)

    # Start ROS node in background thread
    ros_node = GazeboCameraBridge()
    executor = rclpy.executors.MultiThreadedExecutor(num_threads=2)
    executor.add_node(ros_node)

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    try:
        executor.spin()
    finally:
        ros_node.destroy_node()
        rclpy.shutdown()
