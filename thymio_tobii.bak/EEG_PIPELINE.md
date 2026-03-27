# EEG 管线（短期实用方案）

本文档定义一个面向短期落地的 EEG 控制架构，在尽量不破坏现有脚本的前提下支持后续扩展。

## 为什么需要这套骨架

当前脚本适合快速验证，但实验维度会很快增长：

- 多种 EEG 设备
- 多种输入协议（TCP、LSL，以及后续更多协议）
- 多种特征（alpha、theta、beta、各类比值）
- 多种控制策略（专注力、阈值、状态机等）

该管线把这些关注点拆开，让你可以只替换其中一层，而不用重写整套控制链路。

## 最小架构

1. 适配层：把不同协议/设备输入统一为标准 EEG 帧
2. 特征层：计算通用派生特征（theta/beta、beta/(alpha+theta)、非对称）
3. 策略层：把特征映射为控制意图（speed_intent / steer_intent）
4. 输出层：发送语义意图；过渡期兼容旧字段 x/y

## 新增脚本

- [thymio_tobii/eeg_control_pipeline.py](thymio_tobii/eeg_control_pipeline.py)
- [thymio_tobii/eeg_control_node.py](thymio_tobii/eeg_control_node.py)
- [thymio_tobii/experiment_config.yaml](thymio_tobii/experiment_config.yaml)
- [thymio_tobii/eeg_control_node.params.yaml](thymio_tobii/eeg_control_node.params.yaml)

## 运行示例

1. 先启动现有机器人控制节点（消费 UDP x/y）

```bash
python3 thymio_tobii/thymio_ros.py --mode gaze --udp-port 5005 --no-bridge
```

2. 启动 mock EEG 管线

```bash
python3 thymio_tobii/eeg_control_pipeline.py --input mock --policy focus --udp-port 5005 --verbose
```

也可以直接读取 YAML 配置：

```bash
python3 thymio_tobii/eeg_control_pipeline.py --config thymio_tobii/experiment_config.yaml
```

3. 启动 TCP EEG 管线（每行一个 JSON）

```bash
python3 thymio_tobii/eeg_control_pipeline.py --input tcp --tcp-port 6001 --policy theta_beta --udp-port 5005
```

4. 启动 LSL EEG 管线

```bash
python3 thymio_tobii/eeg_control_pipeline.py \
  --input lsl \
  --lsl-stream-type EEG \
  --lsl-channel-map "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4" \
  --policy focus \
  --udp-port 5005
```

## TCP 数据格式

发送格式为“每行一个 JSON 对象”：

```json
{"alpha": 10.2, "theta": 6.3, "beta": 8.7, "left_alpha": 4.8, "right_alpha": 5.4}
```

说明：
- 所有数值型键都会被接收。
- 策略只使用自己需要的键，缺失键会回退到默认值。

## 意图字段说明

- `speed_intent`：线速度意图，0 表示最慢，1 表示最快。
- `steer_intent`：转向意图，0 表示最左，1 表示最右。
- 兼容字段：
  - `x` 等价于 `steer_intent`
  - `y` 与 `speed_intent` 反向（`y = 1 - speed_intent`），用于兼容旧控制链路

## 原生 ROS2 节点运行

直接运行脚本（用于开发期）：

```bash
python3 thymio_tobii/eeg_control_node.py
```

使用 ROS 参数文件：

```bash
python3 thymio_tobii/eeg_control_node.py --ros-args --params-file thymio_tobii/eeg_control_node.params.yaml
```

## 近期建议

1. 增加录制与回放模式，支持离线 A/B 对比策略。
2. 当适配器和策略增多后，拆分为独立模块。
3. 将 `eeg_control_node.py` 纳入标准 ROS2 package，支持 `ros2 run`。
