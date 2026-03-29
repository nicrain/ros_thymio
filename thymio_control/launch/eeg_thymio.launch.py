import os
import yaml
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, SetEnvironmentVariable
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource, AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory, PackageNotFoundError

def generate_launch_description():
    """集成启动脚本：支持新一代 Gazebo (GZ Sim) + EEG 控制 + 键盘遥控"""
    gz_partition = f"thymio_{os.getpid()}"
    
    # 1. 读取 launch 参数默认值（来自 thymio_control/config/launch_args.yaml）
    try:
        _launch_args_path = os.path.join(get_package_share_directory('thymio_control'), 'config', 'launch_args.yaml')
        with open(_launch_args_path, 'r') as _f:
            _launch_defaults = yaml.safe_load(_f) or {}
    except Exception:
        _launch_defaults = {}

    def _str(v):
        if isinstance(v, bool):
            return 'true' if v else 'false'
        if v is None:
            return ''
        return str(v).lower()

    use_sim = LaunchConfiguration('use_sim')
    use_gui = LaunchConfiguration('use_gui')
    run_eeg = LaunchConfiguration('run_eeg')
    config_file = LaunchConfiguration('config_file')
    use_teleop = LaunchConfiguration('use_teleop')

    declare_use_sim = DeclareLaunchArgument(
        'use_sim', default_value=_str(_launch_defaults.get('use_sim', False)), description='Start GZ Simulation'
    )
    declare_use_gui = DeclareLaunchArgument(
        'use_gui', default_value=_str(_launch_defaults.get('use_gui', True)), description='Start Gazebo GUI (set false for server-only)'
    )
    declare_run_eeg = DeclareLaunchArgument(
        'run_eeg', default_value=_str(_launch_defaults.get('run_eeg', True)), description='Run EEG control publisher node'
    )
    declare_config_file = DeclareLaunchArgument(
        'config_file',
        default_value=os.path.join(
            get_package_share_directory('thymio_control'),
            'config',
            _launch_defaults.get('config_file', 'eeg_control_node.params.yaml')
        ),
        description='Path to EEG params'
    )
    declare_use_teleop = DeclareLaunchArgument(
        'use_teleop', default_value=_str(_launch_defaults.get('use_teleop', False)), description='Start keyboard teleop'
    )

    gz_sim_gui = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py'
            ])
        ]),
        launch_arguments={'gz_args': '-r empty.sdf'}.items(),
        condition=IfCondition(PythonExpression(["'", use_sim, "' == 'true' and '", use_gui, "' == 'true'"]))
    )

    gz_sim_headless = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py'
            ])
        ]),
        launch_arguments={'gz_args': '-r -s empty.sdf'}.items(),
        condition=IfCondition(PythonExpression(["'", use_sim, "' == 'true' and '", use_gui, "' == 'false'"]))
    )

    gz_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        arguments=[
            '/model/thymio/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist',
            '/model/thymio/odometry@nav_msgs/msg/Odometry@gz.msgs.Odometry',
            '/model/thymio/tf@tf2_msgs/msg/TFMessage@gz.msgs.Pose_V',
            '/ground/left@sensor_msgs/msg/Range@gz.msgs.Float',
            '/ground/right@sensor_msgs/msg/Range@gz.msgs.Float',
        ],
        output='screen',
        condition=IfCondition(use_sim)
    )

    try:
        real_robot_driver = IncludeLaunchDescription(
            AnyLaunchDescriptionSource([
                PathJoinSubstitution([
                    get_package_share_directory('thymio_driver'), 'launch', 'main.launch'
                ])
            ]),
            condition=UnlessCondition(use_sim)
        )
    except PackageNotFoundError:
        real_robot_driver = LogInfo(msg="Skip: thymio_driver package not found.")

    sim_model_publisher = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                get_package_share_directory('thymio_description'), 'launch', 'model.launch.py'
            ])
        ]),
        launch_arguments={
            'name': 'thymio',
            'namespace': '',
        }.items(),
        condition=IfCondition(use_sim)
    )

    sim_spawn_thymio = Node(
        package='ros_gz_sim',
        executable='create',
        arguments=['-name', 'thymio', '-topic', 'robot_description', '-x', '0.0', '-y', '0.0', '-z', '0.05'],
        output='screen',
        condition=IfCondition(use_sim)
    )

    eeg_node = Node(
        package='thymio_control',
        executable='eeg_control_node.py',
        parameters=[config_file],
        remappings=[('/cmd_vel', '/model/thymio/cmd_vel')],
        output='screen',
        condition=IfCondition(PythonExpression(["'", run_eeg, "' == 'true' and '", use_teleop, "' == 'false'"])),
    )

    teleop_node = Node(
        package='teleop_twist_keyboard',
        executable='teleop_twist_keyboard',
        name='teleop',
        remappings=[('cmd_vel', '/model/thymio/cmd_vel')],
        output='screen',
        condition=IfCondition(use_teleop)
    )

    rviz_config_file = os.path.join(
        get_package_share_directory('thymio_control'),
        'config',
        'default.rviz'
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='log'
    )

    return LaunchDescription([
        declare_use_sim,
        declare_use_gui,
        declare_run_eeg,
        declare_config_file,
        declare_use_teleop,
        SetEnvironmentVariable('GZ_PARTITION', gz_partition),
        LogInfo(msg=["GZ_PARTITION=", gz_partition]),
        LogInfo(msg=["Launch: Sim=", use_sim, ", GUI=", use_gui, ", Teleop=", use_teleop, ", EEG=", run_eeg]),
        gz_sim_gui,
        gz_sim_headless,
        sim_model_publisher,
        sim_spawn_thymio,
        gz_bridge,
        real_robot_driver,
        eeg_node,
        teleop_node,
        rviz_node
    ])
