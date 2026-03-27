cmake_minimum_required(VERSION 3.16)
project(thymio_control)

find_package(ament_cmake REQUIRED)

install(FILES
  eeg_thymio.launch.py
  launch_args.yaml
  eeg_control_node.params.yaml
  eeg_control_node.py
  eeg_control_pipeline.py
  experiment_config.yaml
  EEG_PIPELINE.md
  ENOBIO_LAB_PREP.md
  wsl_enobio_bridge.py
  wsl_tobii_bridge.py
  thymio_ros.py
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
