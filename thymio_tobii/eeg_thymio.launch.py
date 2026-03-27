import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory, PackageNotFoundError

def generate_launch_description():
    """集成启动脚本：支持新一代 Gazebo (GZ Sim) + EEG 控制 + 键盘遥控"""
    
    # 1. 定义配置参数
    use_sim = LaunchConfiguration('use_sim')
    config_file = LaunchConfiguration('config_file')
    use_teleop = LaunchConfiguration('use_teleop')
    
    declare_use_sim = DeclareLaunchArgument(
        'use_sim', default_value='false', description='Start GZ Simulation'
    )
    declare_config_file = DeclareLaunchArgument(
        'config_file',
        default_value=os.path.join(os.getcwd(), 'thymio_tobii', 'eeg_control_node.params.yaml'),
        description='Path to EEG params'
    )
    declare_use_teleop = DeclareLaunchArgument(
        'use_teleop', default_value='false', description='Start keyboard teleop'
    )

    # 2. 仿真环境逻辑 (适配新 Gazebo / GZ Sim)
    # 启动 GZ Sim 服务端和客户端
    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py'
            ])
        ]),
        launch_arguments={'gz_args': '-r empty.sdf'}.items(), # -r 表示启动即运行
        condition=IfCondition(use_sim)
    )

    # 话题桥接器 (ros_gz_bridge)：将 ROS 消息翻译给 Gazebo 机器人
    # 格式: /topic@ros_type@gz_type
    gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=[
            '/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist',
            '/ground/left@sensor_msgs/msg/Range@gz.msgs.Float',
            '/ground/right@sensor_msgs/msg/Range@gz.msgs.Float',
            '/model/thymio/tf@tf2_msgs/msg/TFMessage@gz.msgs.Pose_V', # 坐标变换桥接
        ],
        output='screen',
        condition=IfCondition(use_sim)
    )

    # 3. 机器人驱动 (真机模式)
    try:
        real_robot_driver = IncludeLaunchDescription(
            PythonLaunchDescriptionSource([
                PathJoinSubstitution([
                    get_package_share_directory('thymio_driver'), 'launch', 'main.launch.py'
                ])
            ]),
            condition=UnlessCondition(use_sim)
        )
    except PackageNotFoundError:
        real_robot_driver = LogInfo(msg="Skip: thymio_driver package not found.")

    # 4. EEG 控制节点
    eeg_node = Node(
        package='thymio_tobii', 
        executable=os.path.join(os.getcwd(), 'thymio_tobii', 'eeg_control_node.py'),
        name='eeg_control_node',
        parameters=[config_file],
        output='screen',
        condition=UnlessCondition(use_teleop)
    )

    # 5. 键盘控制 (测试用)
    teleop_node = Node(
        package='teleop_twist_keyboard',
        executable='teleop_twist_keyboard',
        name='teleop',
        output='screen',
        condition=IfCondition(use_teleop)
    )

    # 6. RViz 可视化
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='log'
    )

    return LaunchDescription([
        declare_use_sim,
        declare_config_file,
        declare_use_teleop,
        LogInfo(msg=["Launch: Sim=", use_sim, ", Teleop=", use_teleop]),
        gz_sim,
        gz_bridge,
        real_robot_driver,
        eeg_node,
        teleop_node,
        rviz_node
    ])
