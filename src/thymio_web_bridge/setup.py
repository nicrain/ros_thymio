from setuptools import setup

setup(
    name='thymio_web_bridge',
    version='0.1.0',
    packages=['thymio_web_bridge'],
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/thymio_web_bridge']),
        ('share/thymio_web_bridge', ['package.xml']),
        ('share/thymio_web_bridge/launch', ['launch/camera_bridge.launch.py']),
    ],
    install_requires=['setuptools', 'websockets'],
    zip_safe=True,
    maintainer='robot',
    maintainer_email='robot@example.com',
    description='Bridges Gazebo camera image from ROS2 to FastAPI WebSocket',
    license='MIT',
    entry_points={
        'console_scripts': [
            'gazebo_camera_bridge = thymio_web_bridge.gazebo_camera_bridge:main',
        ],
    },
)
