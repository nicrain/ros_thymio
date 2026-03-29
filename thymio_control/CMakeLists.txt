cmake_minimum_required(VERSION 3.16)
project(thymio_control)

find_package(ament_cmake REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(PYTHON_INSTALL_DIR "lib/python${Python3_VERSION_MAJOR}.${Python3_VERSION_MINOR}/site-packages")

install(DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)
install(DIRECTORY docs/
  DESTINATION share/${PROJECT_NAME}/docs
)

install(PROGRAMS
  scripts/eeg_control_node.py
  scripts/thymio_ros.py
  scripts/wsl_enobio_bridge.py
  scripts/wsl_tobii_bridge.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY thymio_control/
  DESTINATION ${PYTHON_INSTALL_DIR}/thymio_control
  FILES_MATCHING PATTERN "*.py"
)

ament_package()
