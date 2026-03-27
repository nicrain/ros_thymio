import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    """生成集成启动描述，包含驱动、控制节点和可视化"""
    
    # 1. 定义命令行参数
    use_sim = LaunchConfiguration('use_sim')
    config_file = LaunchConfiguration('config_file')
    use_teleop = LaunchConfiguration('use_teleop') # 是否启动键盘控制
    
    declare_use_sim = DeclareLaunchArgument(
        'use_sim', default_value='false', description='Use simulation (Gazebo) instead of real robot'
    )
    
    declare_config_file = DeclareLaunchArgument(
        'config_file',
        default_value=os.path.join(os.getcwd(), 'thymio_tobii', 'eeg_control_node.params.yaml'),
        description='Path to EEG node parameters YAML'
    )

    declare_use_teleop = DeclareLaunchArgument(
        'use_teleop', default_value='false', description='Whether to start keyboard teleop node'
    )

    # 2. 机器人驱动部分 (引用 src/ros-thymio 中的包)
    # 真机模式：启动 thymio_driver
    real_robot_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('thymio_driver'), 'launch', 'main.launch.py'
            ])
        ]),
        condition=UnlessCondition(use_sim)
    )

    # 仿真模式：启动 thymio_gazebo (假设已安装并有对应 launch)
    sim_robot_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('thymio_gazebo'), 'launch', 'gazebo.launch.py'
            ])
        ]),
        condition=IfCondition(use_sim)
    )

    # 3. EEG 控制节点 (我们重写后的原生 ROS2 节点)
    eeg_node = Node(
        package='thymio_tobii', 
        executable=os.path.join(os.getcwd(), 'thymio_tobii', 'eeg_control_node.py'),
        name='eeg_control_node',
        parameters=[config_file],
        output='screen',
        condition=UnlessCondition(use_teleop) # 如果开启了手动键盘，则禁用 EEG 节点，避免冲突
    )

    # 4. 可视化界面 (RViz2)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='log'
    )

    # 5. 键盘控制节点 (仅当 use_teleop:=true 时启动)
    teleop_node = Node(
        package='teleop_twist_keyboard',
        executable='teleop_twist_keyboard',
        name='teleop',
        output='screen',
        # prefix='xterm -e', # 如果你有 xterm 可以取消注释，方便在独立窗口控制
        condition=IfCondition(use_teleop)
    )

    # 6. 返回启动描述
    return LaunchDescription([
        declare_use_sim,
        declare_config_file,
        declare_use_teleop,
        LogInfo(msg=["Starting Integration. Sim: ", use_sim, ", Teleop: ", use_teleop]),
        real_robot_driver,
        # sim_robot_driver,
        eeg_node,
        rviz_node,
        teleop_node
    ])
