from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    core = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [PathJoinSubstitution([get_package_share_directory("thymio_control"), "launch", "experiment_core.launch.py"])]
        ),
        launch_arguments={
            "run_eeg": "false",
            "run_gaze": "true",
            "use_tobii_bridge": "true",
            "use_enobio_bridge": "false",
        }.items(),
    )
    return LaunchDescription([core])
