# ros_thymio

本仓库是一个用于 Thymio 机器人的 ROS/ROS2 工作区，主要包含：

- `thymio_driver`、`thymio_description`、`thymio_msgs` 等包
- 通过 `ros-aseba` 与 Aseba 的集成
- Gazebo 仿真资源（URDF、mesh、传感器）

## 快速开始

## 环境要求

该工作区面向 ROS2 + Thymio 开发，建议具备以下环境：

- **操作系统**：Windows + WSL（示例使用 Ubuntu 24.04，ROS2 在 WSL 内运行）
- **ROS2**：已安装并可 `source` 的发行版（如 Kilted / Humble / Iron）
- **Python**：3.12+
- **Thymio 机器人**（真机运行时需要）
- **Aseba Runtime**（`ros-aseba` 与 Thymio 通信需要）
- **Tobii Pro SDK**（仅 gaze 控制需要，运行在 Windows）

## 架构说明

### Windows + WSL 模式（支持 Tobii）

- ROS2 运行在 WSL
- Tobii Pro SDK 运行在 Windows
- 视线数据通过 UDP 从 Windows 发回 WSL
- 使用 `usbipd` 将 USB 设备（如 Thymio）转发到 WSL

主脚本 [thymio_tobii/thymio_ros.py](thymio_tobii/thymio_ros.py) 启动时会自动尝试 USB attach（默认 Bus ID `1-1`）。

如需在 Windows PowerShell 手动安装或管理：

```powershell
# 安装 usbipd（如果尚未安装）
winget install --id Microsoft.usbipd

# 查看并手动 attach/detach 设备
usbipd wsl list
usbipd wsl attach --busid <busid>
usbipd wsl detach --busid <busid>
```

## 1) 准备环境

本仓库按 ROS/ROS2 的 `colcon` 工作区组织，要求：

- 已安装可用的 ROS2 发行版（如 Humble / Iron）
- 已 `source` ROS2 环境（确保 `ros2` 命令可用）

### 安装 ROS2 Kilted（Ubuntu 24.04 示例）

参考官方文档：

- https://docs.ros.org/en/kilted/Installation/Ubuntu-Install-Debians.html

安装后执行：

```bash
source /opt/ros/kilted/setup.bash
```

### 安装 ROS-Aseba / ROS-Thymio 依赖

可参考上游安装说明：

- https://jeguzzi.github.io/ros-aseba/installation.html#

> 如你使用其他 ROS2 发行版（如 Humble），请将命令中的 `kilted` 替换为对应发行版名称。

本仓库对 `ros-aseba` 有一处小补丁以适配新工具链：

- `aseba/common/msg/TargetDescription.h`：添加 `#include <cstdint>`

### （可选）Python 虚拟环境

仓库中已有 `.venv/`，也可自行重建：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools
```

### 安装 ROS 包依赖

在工作区根目录执行：

```bash
rosdep update
rosdep install --from-paths src --ignore-src -r -y
```

## 2) 构建

在工作区根目录执行：

```bash
colcon build --symlink-install
```

构建完成后：

```bash
source install/setup.bash
```

## 3) 运行

运行任意节点前，请先 `source` 当前工作区：

```bash
source install/setup.bash
```

常见用法是通过 `src/ros-thymio` 下的 launch 文件启动仿真或驱动。

如果直接运行高级控制脚本 [thymio_tobii/thymio_ros.py](thymio_tobii/thymio_ros.py)：

```bash
# 1) 标准 gaze 控制（左右控制转向，上下控制前后）
python3 thymio_tobii/thymio_ros.py

# 2) 循线模式（黑线）+ gaze 速度控制
python3 thymio_tobii/thymio_ros.py --line blackline
```

## 短期 EEG 优先工作流（支持 TCP/LSL）

对于 EEG 控制实验，建议使用新的管线骨架：

- 适配层：从 `mock`、`tcp`、`lsl` 读取 EEG
- 特征层：计算比值和非对称特征
- 策略层：将特征映射到 `speed_intent/steer_intent`
- 输出层：发送语义意图，过渡期兼容 `x/y`

详细说明见 [thymio_tobii/EEG_PIPELINE.md](thymio_tobii/EEG_PIPELINE.md)。

快速启动：

```bash
# 终端 A：运行机器人控制节点，消费 UDP x/y
python3 thymio_tobii/thymio_ros.py --mode gaze --udp-port 5005 --no-bridge

# 终端 B：运行 EEG 管线（mock 输入）
python3 thymio_tobii/eeg_control_pipeline.py --input mock --policy focus --udp-port 5005 --verbose
```

TCP 模式（每行一个 JSON）：

```bash
python3 thymio_tobii/eeg_control_pipeline.py --input tcp --tcp-port 6001 --policy theta_beta --udp-port 5005
```

LSL 模式：

```bash
python3 thymio_tobii/eeg_control_pipeline.py \
  --input lsl \
  --lsl-stream-type EEG \
  --lsl-channel-map "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4" \
  --policy focus \
  --udp-port 5005
```

配置文件模式：

```bash
python3 thymio_tobii/eeg_control_pipeline.py --config thymio_tobii/experiment_config.yaml
```

原生 ROS2 控制节点（直接发布 /cmd_vel）：

```bash
python3 thymio_tobii/eeg_control_node.py --ros-args --params-file thymio_tobii/eeg_control_node.params.yaml
```

### [thymio_tobii/thymio_ros.py](thymio_tobii/thymio_ros.py) 关键特性

- **Auto-attach USB**：启动前自动调用 `usbipd` attach（可通过 `--busid` 调整）
- **Line-follow 模式**：地面传感器负责循线，gaze 的 y 轴作为“油门”
- **稳健循环结构**：非阻塞 UDP + ROS2 timer/spin，降低桥接阻塞风险

## 仓库结构

- `src/ros-thymio/`：Thymio 相关 ROS/ROS2 包（驱动、消息、描述等）
- `src/ros-aseba/`：Aseba/Thymio 桥接相关包
- `build/`、`install/`、`log/`：`colcon build` 生成目录

## 备注

- `test.urdf` 为由 `xacro` 生成的文件，不建议直接编辑
- 修改机器人模型请编辑 `src/ros-thymio/thymio_description/urdf/` 下对应 `.xacro`
