"""Launch the Gazebo camera bridge node.

The node subscribes to /image_topic (from ros_gz_bridge) and exposes
a WebSocket server at ws://127.0.0.1:8011/ws/gazebo_frame.
FastAPI backend (/ws/gazebo_frame) proxies to this endpoint.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='thymio_web_bridge',
            executable='gazebo_camera_bridge',
            name='gazebo_camera_bridge',
            output='screen',
            emulate_tty=True,
        ),
    ])
