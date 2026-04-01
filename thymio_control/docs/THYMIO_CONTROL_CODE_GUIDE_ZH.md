# Thymio Control 代码与架构全讲解（初学者版）

本文目标：
- 你读完后能说清楚本包的架构、数据流、启动流程。
- 你能定位每个文件、每个函数的职责。
- 你能在不破坏系统的前提下自己改参数、改控制逻辑、改输入源。

范围说明：
- 只讲 `thymio_control` 文件夹内的内容。
- 重点是 Python 代码（launch + scripts + pipeline）和关键配置文件（yaml/sdf/cmake/package）。

---

## 1. 先用一句话理解系统

这个包做的事是：
- 把 EEG（或 Tobii、或 mock）信号转成机器人可执行的速度命令；
- 通过 ROS 2 发到 `/cmd_vel`；
- 支持仿真（Gazebo）和实机（thymio_driver）；
- 提供桥接脚本解决 WSL/Linux 与 Windows 设备 SDK 的兼容问题。

---

## 2. 架构图（逻辑层）

```text
[Windows: Tobii/Enobio SDK]
        |
        | UDP(JSON x/y) via wsl_*_bridge.py
        v
[WSL/Linux: thymio_ros.py 或 eeg_control_node.py]
        |
        | ROS 2 Twist
        v
            /cmd_vel
        |
        +--> 仿真路径: ros_gz_bridge -> Gazebo 中的 thymio 模型
        |
        +--> 实机路径: thymio_driver -> Thymio 机器人底盘
```

另一路（更“原生 EEG”）是：

```text
EEG 输入（mock/tcp/tcp_client/lsl）
    -> eeg_control_pipeline.py (特征+策略)
    -> eeg_control_node.py (ROS 节点，发布 /cmd_vel)
```

---

## 3. 目录与角色

- `launch/eeg_thymio.launch.py`
  - 整体启动入口（仿真、EEG 节点、teleop、rviz）。
- `scripts/eeg_control_node.py`
  - ROS 2 控制节点，核心生产命令速度。
- `thymio_control/eeg_control_pipeline.py`
  - 输入适配层 + 特征工程 + 控制策略。
- `scripts/thymio_ros.py`
  - 一体化启动器（启动 driver、桥接、控制环）。
- `scripts/wsl_tobii_bridge.py`
  - WSL 拉起 Windows Python 子进程，读取 Tobii，回传 UDP。
- `scripts/wsl_enobio_bridge.py`
  - 同上，但数据源是 Enobio/LSL 或 mock。
- `config/*.yaml`
  - 启动参数、实验参数、Gazebo 桥接参数。
- `config/thymio_world.sdf`
  - Gazebo 世界。
- `CMakeLists.txt`, `package.xml`
  - ROS 包安装与依赖说明。

---

## 4. 启动入口逐段讲解：launch/eeg_thymio.launch.py

### 4.1 import 区

- `import os`, `import yaml`
  - 文件路径拼接与 YAML 读取。
- `import rclpy`
  - 这里实际上没直接使用（可视为冗余 import，不影响运行）。
- `from launch ...`
  - ROS2 Launch 框架核心类型：参数声明、条件执行、包含子 launch。
- `from launch_ros.actions import Node`
  - 在 launch 中声明 ROS 节点。
- `get_package_share_directory`, `PackageNotFoundError`
  - 找 ROS 包资源目录，缺包时优雅降级。

### 4.2 `generate_launch_description()` 整体逻辑

1. `gz_partition = f"thymio_{os.getpid()}"`
   - 给 Gazebo 通信分区一个唯一名，避免多实例互相串话。

2. 读取 `config/launch_args.yaml`
   - try/except 包裹，任何错误就回退空配置。
   - 优点：配置文件缺失时也能启动。

3. 内部函数 `_str(v)`
   - 把 bool/None/其他类型统一转换成 launch 参数需要的字符串。

4. `LaunchConfiguration(...)`
   - 声明运行时可替换参数：`use_sim/use_gui/run_eeg/config_file/use_teleop`。

5. `DeclareLaunchArgument(...)`
   - 给上面的参数设默认值与说明。
   - 默认值优先来自 `launch_args.yaml`。

6. 路径配置
   - `world_file_name = 'thymio_world.sdf'`
   - `bridge_config_file = .../gz_bridge.yaml`

7. `SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH', ...)`
   - 关键：让 Gazebo 能找到世界文件与机器人模型。

8. `gz_sim_gui` 与 `gz_sim_headless`
   - 都是 include `ros_gz_sim/launch/gz_sim.launch.py`。
   - 区别是 `gz_args`：
     - GUI：`-r world`
     - 无头：`-r -s world`
   - 通过条件表达式控制是否启用。

9. `gz_bridge` 节点
   - 启动 `ros_gz_bridge/parameter_bridge`。
   - 加载 `gz_bridge.yaml`，完成 ROS 与 GZ topic 类型映射。

10. `real_robot_driver`
   - 当不是仿真时，include `thymio_driver/main.launch`。
   - 若包不存在，不抛异常，打印提示继续。

11. `sim_model_publisher` + `sim_spawn_thymio`
   - 仿真时发布模型并把 Thymio 实体生成到场景里。

12. `eeg_node`
   - 启动 `thymio_control` 包内脚本 `eeg_control_node.py`。
   - 加载外部参数文件。
   - remap `/cmd_vel -> /model/thymio/cmd_vel`（仿真模型用该 topic）。
   - 条件：`run_eeg=true 且 use_teleop=false`。

13. `teleop_node`
   - 键盘控制节点；开启时同样 remap 到模型 cmd_vel。

14. `rviz_node`
   - 加载 `default.rviz`，并强制 `use_sim_time=True`。

15. `return LaunchDescription([...])`
   - 把所有动作按顺序注册。

你应该记住：
- 这不是“执行顺序脚本”，而是“声明一个系统图”，launch runtime 再并发调度。

---

## 5. 核心 ROS 节点：scripts/eeg_control_node.py

### 5.1 顶部 import

- `csv/json/os/time`
  - 记录日志、序列化分析、路径操作、看门狗计时。
- `rclpy`, `Twist`, `Range`, `String`
  - ROS2 节点 API + 控制/传感消息类型。
- 从 `thymio_control.eeg_control_pipeline` 导入：
  - `POLICIES`: 策略注册表
  - `build_adapter`: 输入适配器工厂
  - `with_legacy_xy`: 兼容旧坐标语义
  - `enrich_features`: 派生特征计算

### 5.2 类 `_AdapterArgs`

作用：
- `build_adapter` 需要一组参数，这个类是最小参数容器。

构造函数里每行都是“字段赋值”，没有业务逻辑。

### 5.3 类 `EegControlNode(Node)`

#### 5.3.1 `__init__` 的参数声明

这部分是最重要的“可配置面板”：

- 输入参数
  - `input`: `mock/tcp/tcp_client/lsl`
  - `policy`: `focus/theta_beta`
  - `tcp_host/tcp_port`
  - `lsl_stream_type/lsl_timeout/lsl_channel_map`

- 输出参数
  - `cmd_topic`, `analysis_topic`
  - `publish_hz`
  - `watchdog_sec`
  - `verbose`, `analysis_verbose`
  - `record_csv`, `csv_path`

- 速度映射参数
  - `max_forward_speed`
  - `reverse_speed`
  - `turn_forward_speed`
  - `turn_angular_speed`

- 循线参数
  - `line_mode`: `'' | blackline | whiteline`

#### 5.3.2 策略与适配器初始化

- 取 `policy_name`，若不在 `POLICIES`，直接抛 `RuntimeError`。
- 用 `_AdapterArgs` 收集参数。
- `self.adapter = build_adapter(...)`。
- `self.policy = POLICIES[policy_name]()`。

#### 5.3.3 Publisher 初始化

- `self.pub`: 发布 `Twist` 到运动命令 topic。
- `self.analysis_pub`: 发布分析 JSON 到 `analysis_topic`。

#### 5.3.4 CSV 记录初始化

当 `record_csv=true`：
- 自动创建目录。
- 追加写入 CSV。
- `fieldnames` 明确定义每列。
- 若文件为空则写 header。

#### 5.3.5 循线模式初始化

- `line_mode == blackline`
  - `on_line = lambda v: v > 0.5`
- `line_mode == whiteline`
  - `on_line = lambda v: v < 0.5`
- 否则 `on_line` 恒 `False`。

若开启循线：
- 订阅 `/ground/left` 和 `/ground/right`。
- 用回调更新 `self.ground`。

#### 5.3.6 状态变量

- `self.last_msg_ts`: 最近一次收到有效输入时间。
- `self.last_intents`: 最近一次意图（看门狗超时前可继续沿用）。

#### 5.3.7 定时器

- `self.create_timer(1.0 / hz, self._tick)`
- `_tick` 每周期执行一次控制主循环。

### 5.4 `_close_csv`

- 关闭文件句柄并清空 writer 引用。
- 容错处理，避免 shutdown 报错。

### 5.5 地面传感器回调 `_ground_left_cb/_ground_right_cb`

- 每次收到 `Range`，只做一件事：更新缓存值。

### 5.6 控制主循环 `_tick`（必须理解）

逻辑分 4 层：

1. 读输入
- `frame = self.adapter.read_frame()`
- 有新帧：走“更新控制”分支。
- 无新帧：走“看门狗或沿用上次意图”分支。

2. 新帧分支
- 判断 `movement` 字段是否存在。
- 判断是否有频段特征 `alpha/theta/beta`。
- 若有频段特征：`features = enrich_features(...)` 并算 `self.last_intents`。
- 若没有：退回中性意图 `{0.5, 0.5}`。

3. 两种控制模式
- `movement` 模式（优先级更高）
  - 按 `movement` 值直接映射 Twist：
    - `0 < m < 0.5` 前进
    - `0.5 < m < 1.0` 后退
    - `m == 1.0` 原地转
    - 其他情况停
- `band_features` 模式
  - 用策略输出 intents，后续由 `_intents_to_twist` 转 Twist。

4. 统一发布分析信息
- 构建 `analysis` 字典并 `json.dumps` 发到分析 topic。
- 可选打印；可选写 CSV。

5. 无新帧时
- 若超过 `watchdog_sec`：直接发零速 Twist（安全停）。
- 否则：用上次 intents 继续输出（控制平滑）。

### 5.7 `_intents_to_twist`

先 `with_legacy_xy`，拿到：
- `x`: 转向意图
- `y`: 速度意图的旧语义（越小越快）

分两套映射：

1. 循线模式
- 根据左右地面传感器是否“在线上”，更新 `state_dir`。
- `state_dir` 含义：
  - `0`: 正常前进
  - `1/-1`: 轻微偏离，边走边纠偏
  - `2/-2`: 丢线后旋转找线
  - `10`: 未知状态兜底旋转
- 再根据状态设置 `twist.linear.x` 与 `twist.angular.z`。

2. 非循线模式
- `y > 0.8`：后退
- `x < 0.3`：左转
- `x > 0.7`：右转
- 否则前进

### 5.8 `main`

- `rclpy.init` 初始化。
- 创建节点并 `rclpy.spin`。
- finally 块保证：
  - 销毁节点
  - 关闭 CSV
  - 尝试 `rclpy.shutdown`

---

## 6. 算法与输入适配核心：thymio_control/eeg_control_pipeline.py

这个文件可拆成 6 个概念层。

### 6.1 基础工具与数据结构

- `@dataclass EegFrame`
  - 标准帧结构：`ts/source/metrics`。
- `clip01(v)`
  - 截断到 `[0,1]`。
- `safe_div(a,b,eps)`
  - 防止除零。
- `BaseAdapter.read_frame`
  - 统一输入接口。

### 6.2 SOD/EOD 数据解析 `_parse_sod_packet`

输入格式示例（字符串）：
- `SOD ... EOD`

步骤：
1. 去空白并检查头尾。
2. 切正文，按 `;` 分割。
3. 解析前 3 项：`packet_no/feature_count/movement`。
4. 校验长度 `expected_len`。
5. 逐个提取 `feature_i`。
6. 提取 `artifact/current_y_unused`（失败给默认）。
7. 若只有一个特征，附加 `feature_value`。

这是 `tcp_client` 路径的关键。

### 6.3 各类 Adapter

#### MockAdapter
- 生成平滑 sin 波 EEG 数据。
- 用于离线联调，不依赖硬件。

#### TcpJsonAdapter
- 本机作为 TCP 服务端，等待一个客户端。
- 收按行 JSON，转数值字典。
- 断开连接会重置状态。

#### TcpClientJsonAdapter
- 本机作为 TCP 客户端连外部 EEG 服务。
- 支持断线重连。
- 从 buffer 中提取 `SOD...EOD` 包。

#### LslAdapter
- 依赖 `pylsl`。
- 按 stream type 发现流，按 channel_map 取指标。

#### KeyboardAdapter
- 目前实现是占位 mock（返回固定 metrics）。
- 说明：类注释写了 W/S/A/D，但当前代码里没有按键监听逻辑。

### 6.4 特征工程 `enrich_features`

输入原始 metrics，补充：
- `theta_beta = theta / beta`
- `beta_alpha = beta / alpha`
- `beta_alpha_theta = beta / (alpha+theta)`
- `alpha_asym = (right-left)/(right+left)`

这些比值用于降低策略耦合。

### 6.5 策略层

#### `Policy` 抽象类
- 要求实现 `compute_intents(features)`。

#### `FocusPolicy`
- `focus = beta_alpha_theta`
- 粗归一化：`focus_norm = clip01((focus - 0.15) / 0.85)`
- 输出：
  - `speed_intent = 1 - focus_norm`
  - `steer_intent = 0.5 + 1.1 * alpha_asym`

#### `ThetaBetaPolicy`
- `ratio = theta_beta`
- 比值高表示注意弱 -> 速度低。
- 输出类似，但速度映射公式不同。

#### `with_legacy_xy`
- 给新意图添加兼容字段：
  - `x = steer_intent`
  - `y = 1 - speed_intent`

### 6.6 配置与 CLI 主程序

- `POLICIES`：策略名到类的映射。
- `parse_channel_map`
  - 支持字典或 `k=v,k=v` 字符串。
- `load_yaml_config`
  - 读取 YAML 并校验根对象是字典。
- `flatten_config`
  - 把分层 yaml（adapter/policy_cfg/output）摊平到 argparse 同名键。
- `apply_config_to_args`
  - 原则：命令行显式参数优先，配置文件仅填默认值位点。

#### `build_adapter(args)`
- 根据 `args.input` 返回对应 Adapter。
- `lsl` 模式强制要求 channel map。

#### `main()`
1. 建 argparse。
2. 可选加载 config 并 merge。
3. `adapter + policy` 实例化。
4. 建 UDP socket，进入循环：
   - 有 frame -> 特征 + 策略 -> 可选 legacy xy -> 发 UDP
   - 无 frame -> sleep 一个周期
5. Ctrl+C 退出。

---

## 7. 一体化控制器：scripts/thymio_ros.py

这个脚本偏“工程集成”，不是单纯算法。

### 7.1 辅助函数

- `run_cmd(cmd, **kwargs)`
  - subprocess.Popen 包装。
- `stream_output(proc, buffer, label)`
  - 异步打印子进程输出，同时写 buffer（用于失败后回放日志）。
- `ros2_topic_has_subscriber(topic)`
  - 调 `ros2 topic info` 检查订阅者数量。
- `wait_for_cmd_vel_ready(timeout)`
  - 轮询直到 `/cmd_vel` 有订阅者。

### 7.2 Bridge 启动函数

- `start_wsl_bridge(udp_port, source, extra_args)`
  - `source=tobii/enobio` 选择不同桥接脚本。
  - 启动桥脚本子进程 + 后台线程打印输出。
- `start_wsl_tobii_bridge`
  - 只是兼容包装，内部调用 `start_wsl_bridge`。

### 7.3 意图解析

- `parse_control_intents(payload)`
  - 兼容新旧格式：
    - 新：`speed_intent/steer_intent`
    - 旧：`x/y`
  - 统一返回 `(speed_intent, steer_intent)`。

### 7.4 测试模式发布 `publish_test_cmd_vel`

- 2 秒前进 + 2 秒停止。
- 用来验证 `/cmd_vel` 通路是否通。

### 7.5 真实控制环 `publish_intent_cmd_vel`

关键流程：
1. 初始化 ROS 节点与 `/cmd_vel` publisher。
2. UDP 非阻塞监听 `udp_port`。
3. 每 0.05s 的 timer 回调：
   - 把 socket 里缓存包读空，只保留“最新包”。
   - 解析 JSON。
   - 转成 `speed_intent/steer_intent`。
   - 如果是循线模式：地面传感器状态机控制。
   - 否则：旧 gaze 阈值规则控制。
   - 发布 Twist。
4. 看门狗：超过 0.5s 没新包，发布零速。

注意：
- 这里用了大量 `try/except: pass`，追求“不中断控制环”。
- 代价是调试时异常信息会被吞掉。

### 7.6 USB 附加 `attach_thymio_usb`

- 用 `usbipd.exe` 把 Windows USB 设备挂载进 WSL。
- 失败时打印提示，但不抛异常。

### 7.7 `main()` 启动编排

做了 4 件事：

1. 解析大量命令行参数（设备、模式、仿真、桥接来源、线模式等）。
2. 非仿真时尝试 `attach_thymio_usb`。
3. 启动 `ros2 launch thymio_driver main.launch ...`。
4. 等待 `/cmd_vel` ready 后：
   - test 模式：跑固定速度测试；
   - gaze 模式：可自动起桥 + 进入 UDP 控制环。

最后在 `finally` 中总是清理 launch 进程。

---

## 8. Windows 桥接脚本

## 8.1 scripts/wsl_tobii_bridge.py

核心思路：
- 在 WSL 里动态生成一个临时 Python 脚本字符串。
- 用 `python.exe` 在 Windows 解释器运行这个脚本。
- 子脚本里调用 `tobii_research` 订阅 gaze 数据。
- 每次回调把 `(x,y)` 通过 UDP 发回 WSL。

关键函数：
- `_get_wsl_ip()`
  - 用 `ip route get` 提取 WSL 当前 IP。
- `_to_windows_path()`
  - `wslpath -w` 转 Windows 路径。
- `_spawn_process()`
  - 子进程启动 + stdout/stderr 双线程实时打印。
- `_run_python_bridge(port)`
  - 组装脚本模板替换变量并启动。
- `main()`
  - 解析 `--port`，守护子进程生命周期。

## 8.2 scripts/wsl_enobio_bridge.py

结构和 Tobii 桥几乎一样，但模板脚本分两模式：

1. `--mock`
- 不依赖设备。
- 正弦波生成平滑 `(x,y)`，20Hz 发 UDP。

2. 真实 LSL 模式
- `pylsl` 发现 EEG stream。
- 可按 `--lsl-outlet-name` 过滤。
- 从 sample 粗略提取 left/right alpha 与 beta 代理量。
- 做窗口平滑后发 `(x,y)`。

你要注意：
- 这里是“快速可用映射”，不是严谨脑电算法。
- 如果你做论文级实验，要把通道映射改成你设备的真实 montage。

---

## 9. 配置文件逐个解释

## 9.1 config/launch_args.yaml

- `use_sim: true`
  - 默认仿真。
- `use_gui: true`
  - 默认开 Gazebo GUI。
- `run_eeg: false`
  - 默认不跑 EEG 节点。
- `use_teleop: true`
  - 默认跑键盘遥控。
- `config_file: eeg_control_node.params.yaml`
  - EEG 节点参数文件。

结论：当前默认更偏“手动遥控演示”，不是 EEG 自动控制。

## 9.2 config/eeg_control_node.params.yaml

定义了 `eeg_control_node.py` 的运行参数：
- 输入默认是 `tcp_client` 连 `172.27.96.1:1234`。
- 策略 `focus`。
- 发布到 `/cmd_vel`，分析到 `/eeg_analysis`。
- 控制频率 20Hz，看门狗 0.5s。
- 速度参数和转向参数都在这里可调。
- `line_mode` 默认空字符串（关闭循线）。

## 9.3 config/experiment_config.yaml

用于 `eeg_control_pipeline.py --config`：
- `adapter` 分组设置输入来源。
- `policy_cfg` 设置策略。
- `output` 设置 UDP 目标与发送频率。

## 9.4 config/gz_bridge.yaml

声明 ROS/GZ topic 映射：
- `/model/thymio/cmd_vel` <-> `gz.msgs.Twist`
- `/clock`, `/odom`, `/tf`
- `/ground/left`, `/ground/right`

重点：
- `ground` 这里把 `gz.msgs.LaserScan` 映射到 `sensor_msgs/Range`。
- 实际上属于“自定义近似映射”，运行中要关注是否有字段兼容问题。

## 9.5 config/thymio_world.sdf

- 基础物理系统插件、光照、地面。
- GUI 相机初始位姿固定。
- 是一个简化 world，适合控制链路调试。

## 9.6 config/default.rviz

- 显示 Grid、RobotModel、TF。
- Fixed Frame 设置为 `thymio/odom`。

---

## 10. 构建与安装文件

## 10.1 CMakeLists.txt

逐段看：

1. `find_package(ament_cmake REQUIRED)`
   - ROS2 ament 构建基础。
2. `find_package(Python3 REQUIRED COMPONENTS Interpreter)`
   - 获取 Python 主版本用于安装目录。
3. `install(DIRECTORY config/ launch/ docs/)`
   - 把资源装到 share 路径。
4. `install(PROGRAMS scripts/*.py DESTINATION lib/${PROJECT_NAME})`
   - 让脚本变 ROS 可执行项。
5. `install(DIRECTORY thymio_control/ ... PATTERN "*.py")`
   - 安装 Python 包模块。
6. `ament_package()`
   - 包收尾声明。

## 10.2 package.xml

你只要抓住三件事：
- 包名：`thymio_control`
- build tool：`ament_cmake`
- 运行依赖：
  - ROS 消息与框架：`rclpy`, `geometry_msgs`, `sensor_msgs`, `launch_ros`...
  - 仿真：`ros_gz_sim`, `ros_gz_bridge`, `rviz2`
  - 控制：`teleop_twist_keyboard`
  - 上游包：`thymio_description`, `thymio_driver`

---

## 11. 你最需要掌握的 3 条数据流

## 数据流 A：仿真 + 键盘

1. 启动 `eeg_thymio.launch.py`
2. `use_sim=true`, `use_teleop=true`
3. `teleop_twist_keyboard` 发布 cmd_vel
4. `ros_gz_bridge` 转发到 Gazebo 模型

## 数据流 B：EEG 原生节点

1. `eeg_control_node.py` 从 adapter 读帧
2. `enrich_features` + `policy` 算意图
3. `_intents_to_twist` 产生命令
4. 发 `/cmd_vel`，可选发 `/eeg_analysis` 和 CSV

## 数据流 C：Windows 设备桥

1. WSL 脚本拉起 Windows Python
2. Windows SDK 拿设备数据
3. UDP 发 `x/y` 到 WSL
4. `thymio_ros.py` 收 UDP，映射 Twist 并发布 `/cmd_vel`

---

## 12. 初学者改代码安全指南（高频需求）

## 12.1 改速度但不改架构

改 `eeg_control_node.params.yaml`：
- `max_forward_speed`
- `reverse_speed`
- `turn_forward_speed`
- `turn_angular_speed`

## 12.2 换 EEG 输入源

- `input: mock`（无设备）
- `input: tcp_client`（外部 TCP 服务）
- `input: lsl`（LSL）

并同步 host/port 或 channel_map。

## 12.3 调策略而不动控制环

在 `eeg_control_pipeline.py`：
- 新建 `class MyPolicy(Policy)`
- 实现 `compute_intents`
- 注册到 `POLICIES`
- 参数里把 `policy` 改为新名字

## 12.4 想快速排错

- 打开 `verbose=true`
- 打开 `analysis_verbose=true`
- 打开 `record_csv=true`

---

## 13. 当前代码里你应知道的限制

1. `KeyboardAdapter` 注释说支持 W/S/A/D，但当前未实现按键读取。
2. 多处 `except Exception: pass` 会吞掉错误，调试期可临时打印异常。
3. Enobio 映射是简化启发式，不是严格生理指标模型。
4. `launch/eeg_thymio.launch.py` 里 `import rclpy` 未使用，可清理。

---

## 14. 建议你的学习顺序（最稳）

1. 先跑通仿真键盘路径（确认 ROS/Gazebo 环境正确）。
2. 再跑 `mock` EEG（确认控制节点逻辑正确）。
3. 再切 `tcp_client` 或 `lsl`（确认设备路径）。
4. 最后再改策略函数。

---

## 15. 你现在应该能回答的 10 个问题

1. `/cmd_vel` 是谁发布、谁消费？
2. `run_eeg` 和 `use_teleop` 的互斥关系是什么？
3. `watchdog_sec` 如何保证安全停机？
4. `speed_intent` 与旧 `y` 的关系为什么是反向？
5. `line_mode` 如何改变控制规则？
6. 为什么需要 `gz_bridge.yaml`？
7. 为什么要桥接到 Windows Python？
8. `mock` 路径适合做什么？
9. 改策略最小改动点在哪里？
10. 你如何在不接硬件时完成链路联调？

如果你能完整解释这 10 个问题，说明你已经达到“可独立修改并向别人解释”的水平。

---

## 16. 附：最小命令参考

```bash
# 仿真 + teleop
ros2 launch thymio_control eeg_thymio.launch.py use_sim:=true use_teleop:=true run_eeg:=false

# 启动 EEG 控制节点（参数文件）
ros2 run thymio_control eeg_control_node.py --ros-args --params-file \
  $(ros2 pkg prefix thymio_control)/share/thymio_control/config/eeg_control_node.params.yaml

# 一体化脚本（Enobio mock）
python3 thymio_control/scripts/thymio_ros.py --bridge-source enobio --enobio-mock
```

---

## 17. 总结

这套代码本质是“信号输入适配 + 策略决策 + ROS 控制输出”的三层结构。
你以后改代码时，先判断你在改哪一层：
- 输入层（Adapter/Bridge）
- 决策层（Feature/Policy）
- 输出层（Twist 映射/Launch/Topic 桥接）

按层改，风险最小，定位问题也最快。
