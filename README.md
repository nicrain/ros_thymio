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
- 使用 `usbipd` 将 USB 设备（如 Thymio）转发到 WSL（已拆分为独立系统脚本）

Phase 2 后不再使用一体化胖脚本作为主入口，统一改为 `ros2 launch` 编排：

- EEG: `ros2 launch thymio_control eeg_thymio.launch.py`
- Gaze: `ros2 launch thymio_control gaze_thymio.launch.py`
- 统一编排: `ros2 launch thymio_control experiment_core.launch.py`

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

常见用法是通过 `thymio_control/launch/eeg_thymio.launch.py` 启动仿真或驱动。这个快捷入口默认会关闭 teleop，确保 EEG 节点会真正启动；如果你手动改过 `use_teleop`，EEG 节点会被条件抑制。

注意：这个 launch 读取的是 `thymio_control/config/eeg_control_node.params.yaml`，不是 `experiment_config.yaml`。如果你想让 `eeg_thymio.launch.py` 下的 ROS2 节点切到 `feature`，要改前者里的 `tcp_control_mode` 和 `tcp_host` / `tcp_port`。

### 入口与配置对照

| 运行方式 | 入口文件 | 读取的配置 | 适合改的参数 |
| --- | --- | --- | --- |
| ROS2 EEG launch | `thymio_control/launch/eeg_thymio.launch.py` | `thymio_control/config/eeg_control_node.params.yaml` | `input`、`policy`、`tcp_control_mode`、`tcp_host`、`tcp_port`、`cmd_topic` |
| ROS2 总编排 launch | `thymio_control/launch/experiment_core.launch.py` | `thymio_control/config/eeg_control_node.params.yaml` + `thymio_control/config/launch_args.yaml` | `use_sim`、`use_gui`、`run_eeg`、`run_gaze`、`use_teleop`、`use_tobii_bridge`、`use_enobio_bridge` |
| 统一 EEG pipeline CLI | `python3 -m thymio_control.eeg_control_pipeline` | `thymio_control/config/experiment_config.yaml` | `pipeline_config.source_type`、`selected_channels`、`algorithm`、`info_path`、`easy_path` |

配置优先级（从高到低）：

1. `ros2 launch ... key:=value` 的启动参数
2. `thymio_control/config/eeg_control_node.params.yaml` 等参数文件
3. Web GUI 后端配置（`/api/config`）

Web GUI 当前已支持把配置变更持久化写回：

- `thymio_control/config/launch_args.yaml`
- `thymio_control/config/eeg_control_node.params.yaml`
- `thymio_control/config/experiment_config.yaml`

注意：Web 启动命令不会再拼接 `tcp_host/tcp_port` 作为 launch CLI 参数；该类参数应通过 `eeg_control_node.params.yaml` 管理。

```bash
ros2 launch thymio_control eeg_thymio.launch.py use_sim:=true use_gui:=true
```

如果你要使用 EEG 管线的统一入口，当前支持这几种模式：

- `--input mock`：本地模拟数据
- `--input tcp_client`：连接外部 TCP EEG 服务
- `--input lsl`：LSL 实时输入
- `--input file`：离线 Enobio 录制文件回放

其中 `file` 模式也可以直接由配置文件中的 `pipeline_config.source_type: file` 触发。

Gaze 控制推荐入口：

```bash
# 1) 标准 gaze 控制（包含 Tobii bridge）
ros2 launch thymio_control gaze_thymio.launch.py

# 2) 统一编排下同时启动 EEG + Gaze（按需）
ros2 launch thymio_control experiment_core.launch.py run_eeg:=true run_gaze:=true
```


## 短期 EEG 优先工作流（支持 TCP client / LSL）

对于 EEG 控制实验，建议使用新的管线骨架：

- 适配层：从 `mock`、`tcp_client`、`lsl` 读取 EEG
- 特征层：计算比值和非对称特征
- 策略层：将特征映射到 `speed_intent/steer_intent`
- 输出层：发送语义意图（`speed_intent/steer_intent`）

详细说明见 [thymio_control/docs/EEG_PIPELINE.md](thymio_control/docs/EEG_PIPELINE.md)。

快速启动：

```bash
# 终端 A：运行 ROS2 控制节点（消费 UDP speed/steer 意图）
python3 thymio_control/scripts/eeg_control_node.py --ros-args --params-file thymio_control/config/eeg_control_node.params.yaml

# 终端 B：运行 EEG 管线（mock 输入，优先使用新路径）
python3 -m thymio_control.eeg_control_pipeline --input mock --policy focus --udp-port 5005 --verbose

```

TCP client 模式（连接外部 EEG server）：

```bash
python3 -m thymio_control.eeg_control_pipeline --input tcp_client --tcp-host 127.0.0.1 --tcp-port 6001 --policy theta_beta --udp-port 5005
```

LSL 模式：

```bash
python3 -m thymio_control.eeg_control_pipeline \
  --input lsl \
  --lsl-stream-type EEG \
  --lsl-channel-map "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4" \
  --policy focus \
  --udp-port 5005
```

配置文件模式：

```bash
python3 -m thymio_control.eeg_control_pipeline --config thymio_control/config/experiment_config.yaml
```

原生 ROS2 控制节点（直接发布 /cmd_vel）：

```bash
python3 thymio_control/scripts/eeg_control_node.py --ros-args --params-file thymio_control/config/eeg_control_node.params.yaml
```

### 桥接与系统工具

- Tobii bridge: `thymio_control/tools/bridges/wsl_tobii_bridge.py`
- Enobio bridge: `thymio_control/tools/bridges/wsl_enobio_bridge.py`
- USB attach helper: `thymio_control/tools/system/prepare_usb.sh`
- `thymio_control/scripts/thymio_ros.py` 已保留为 deprecated 兼容入口（仅提示迁移命令）。

### 离线文件回放模式（Enobio 录制文件）

如果你想用 `enobio_recodes/` 下的录制文件回放 EEG 数据，可以在配置文件里把 `pipeline_config.source_type` 设为 `file`。默认会读取仓库内置示例录音，也可以在 YAML 中显式指定 `info_path` 和 `easy_path`。

推荐优先使用配置文件控制录制文件来源，因为这样可以同时固定 `selected_channels` 和 `algorithm`：

```yaml
pipeline_config:
  source_type: file
  info_path: enobio_recodes/20260330123659_Patient01.info
  easy_path: enobio_recodes/20260330123659_Patient01.easy
  selected_channels: [0, 1, 2]
  algorithm: theta_beta_ratio
```

示例用法：

```bash
# 直接使用配置文件启用离线文件模式（推荐）
python3 -m thymio_control.eeg_control_pipeline --config thymio_control/config/experiment_config.yaml

# 也可以显式指定 file 输入模式，入口会优先走离线文件回放路径
python3 -m thymio_control.eeg_control_pipeline --config thymio_control/config/experiment_config.yaml --input file
```

如果你希望在自定义配置中指定录音文件路径，建议保持 `experiment_config.yaml` 只放这一类 pipeline 字段：

```yaml
pipeline_config:
  source_type: file
  info_path: enobio_recodes/20260330123659_Patient01.info
  easy_path: enobio_recodes/20260330123659_Patient01.easy
  selected_channels: [0, 1, 2]
  algorithm: theta_beta_ratio
```

该模式会按采样率回放每一行样本，并走统一的特征提取与 `Twist` 映射逻辑。

如果你打算手动调试，可直接用仓库内置示例：

```bash
python3 -m thymio_control.eeg_control_pipeline \
  --config thymio_control/config/experiment_config.yaml \
  --input file
```

只要 `pipeline_config.source_type` 是 `file`，这个入口会自动读取 `info_path` / `easy_path`，并把相对路径按配置文件所在目录解析。

## 仓库结构

- `src/ros-thymio/`：Thymio 相关 ROS/ROS2 包（驱动、消息、描述等）
- `src/ros-aseba/`：Aseba/Thymio 桥接相关包
- `docs/archived/old_test_scripts/`：历史实验脚本归档（已弃用，不参与当前主流程）
- `build/`、`install/`、`log/`：`colcon build` 生成目录

## 备注

- `test.urdf` 为由 `xacro` 生成的文件，不建议直接编辑
- 修改机器人模型请编辑 `src/ros-thymio/thymio_description/urdf/` 下对应 `.xacro`
