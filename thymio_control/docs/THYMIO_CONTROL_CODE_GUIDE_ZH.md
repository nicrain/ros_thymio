# Thymio Control 代码导读（初学者可完整理解版）

本文是基于当前仓库代码的“读代码说明书”。
目标不是复述重构提案，而是让你可以：
- 跑起来系统；
- 看懂每个关键文件为什么存在；
- 按固定顺序阅读并理解数据如何流动；
- 在改代码后自己验证是否改坏。

适用范围：只覆盖 `thymio_control/` 包。

---

## 1. 先建立全局地图（你要先知道系统分几层）

当前架构分成 4 层：

1. 编排层（launch）
- 统一入口：`launch/experiment_core.launch.py`
- 快捷入口：`launch/eeg_thymio.launch.py`、`launch/gaze_thymio.launch.py`

2. 控制节点层（ROS2 node）
- EEG 节点：`scripts/eeg_control_node.py`
- Gaze 网关节点：`scripts/gaze_control_node.py`

3. 算法与适配层（纯 Python 逻辑）
- EEG pipeline：`thymio_control/eeg_control_pipeline.py`

4. 外部桥接与系统脚本（非 ROS 核心）
- WSL/Windows 桥接：`tools/bridges/wsl_tobii_bridge.py`、`tools/bridges/wsl_enobio_bridge.py`
- 系统辅助：`tools/system/prepare_usb.sh`

一句话总结：
- Launch 负责“拉起谁”；
- Node 负责“实时控制”；
- Pipeline 负责“算意图”；
- Bridge 负责“跨系统拿数据”。

---

## 2. 最短可运行路径（先跑通再读）

### 2.1 统一入口（推荐）

```bash
ros2 launch thymio_control experiment_core.launch.py run_eeg:=true run_gaze:=true
```

### 2.2 只跑 EEG

```bash
ros2 launch thymio_control eeg_thymio.launch.py
```

### 2.3 只跑 Gaze

```bash
ros2 launch thymio_control gaze_thymio.launch.py
```

补充：
- 默认参数来自 `config/launch_args.yaml`。
- 当前默认是 `use_sim: true` 且 `use_teleop: true`，所以如果你要让 EEG/Gaze 真正接管运动，通常要显式设置 `use_teleop:=false`。

---

## 3. 数据流（先懂输入输出再看实现）

### 3.1 EEG 原生链路

输入源（mock/tcp_client/lsl）
-> `thymio_control/eeg_control_pipeline.py` 产出意图
-> `scripts/eeg_control_node.py` 转 Twist
-> 发布到 `cmd_topic`（仿真一般是 `/model/thymio/cmd_vel`，实机一般是 `/cmd_vel`）

### 3.2 Gaze/桥接链路

Windows 设备 SDK
-> `tools/bridges/wsl_*.py` 通过 UDP 发 JSON
-> `scripts/gaze_control_node.py` 读 UDP 并转 Twist
-> 发布到 `cmd_topic`

注意：
- 桥接脚本现在仍可能发历史格式 `x/y`。
- `gaze_control_node.py` 会兼容转换到标准语义：`speed_intent/steer_intent`。

---

## 4. 按文件读代码（推荐阅读顺序）

建议阅读顺序：
1. `launch/experiment_core.launch.py`
2. `scripts/gaze_control_node.py`
3. `scripts/eeg_control_node.py`
4. `thymio_control/eeg_control_pipeline.py`
5. `config/*.yaml`

下面逐个解释。

### 4.1 `launch/experiment_core.launch.py`（系统总导演）

它做了 5 件关键事：

1. 声明参数
- `use_sim`、`use_gui`、`use_teleop`
- `run_eeg`、`run_gaze`
- `use_tobii_bridge`、`use_enobio_bridge`
- `eeg_config_file`、`gaze_config_file`
- 桥接端口参数

2. 读取默认配置
- 从 `config/launch_args.yaml` 读取默认值。

3. 处理仿真/实机分支
- 仿真：拉起 `ros_gz_sim`、`ros_gz_bridge`、模型发布与 spawn。
- 实机：尝试 include `thymio_driver/main.launch`。

4. 启动控制节点
- `eeg_control_node.py` 和 `gaze_control_node.py` 都是条件启动。
- 当 `use_teleop=true` 时，EEG/Gaze 节点会被条件抑制（避免抢控制）。

5. 启动桥接与工具
- 可选起 `wsl_tobii_bridge.py` 与 `wsl_enobio_bridge.py`。
- 可选起 `teleop_twist_keyboard`。
- 默认起 RViz。

你读这个文件的重点不是语法，而是“条件组合”。
这决定了某个节点为什么没启动。

### 4.2 `launch/eeg_thymio.launch.py` 与 `launch/gaze_thymio.launch.py`

这两个是薄封装：
- EEG 封装：固定 `run_eeg=true`、`run_gaze=false`。
- Gaze 封装：固定 `run_eeg=false`、`run_gaze=true`，并默认启 Tobii bridge。

它们只是把参数传给 `experiment_core.launch.py`，没有额外控制逻辑。EEG 快捷入口还会默认关闭 `use_teleop`，这样 EEG 节点才不会被总入口里的条件挡掉。

补充一点：`eeg_thymio.launch.py` 读取的是 `config/eeg_control_node.params.yaml`；`config/experiment_config.yaml` 只用于 `python3 -m thymio_control.eeg_control_pipeline` 这条统一入口。也就是说，如果你是在 `ros2 launch thymio_control eeg_thymio.launch.py` 里调 `tcp_control_mode`，应该改前者，而不是后者。

#### 一眼看懂

| 运行方式 | 入口 | 读取配置 | 关键参数 |
| --- | --- | --- | --- |
| `ros2 launch thymio_control eeg_thymio.launch.py` | EEG 快捷 launch | `config/eeg_control_node.params.yaml` | `input`、`policy`、`tcp_control_mode`、`tcp_host`、`tcp_port`、`cmd_topic` |
| `ros2 launch thymio_control experiment_core.launch.py` | 总编排 launch | `config/launch_args.yaml` + `config/eeg_control_node.params.yaml` | `use_sim`、`use_gui`、`run_eeg`、`run_gaze`、`use_teleop`、`use_tobii_bridge`、`use_enobio_bridge` |
| `python3 -m thymio_control.eeg_control_pipeline` | 统一 pipeline CLI | `config/experiment_config.yaml` | `pipeline_config.source_type`、`selected_channels`、`algorithm`、`info_path`、`easy_path` |

### 4.3 `scripts/gaze_control_node.py`（UDP JSON -> Twist）

这是一个纯网关型节点，逻辑非常清晰：

1. 非阻塞读取 UDP 最新包
- 每个 timer tick 会把 socket 中的数据“读到最新”。

2. 解析 payload
- 优先读 `speed_intent` 和 `steer_intent`。
- 若没有，则兼容 `x/y`：
  - `steer_intent = x`
  - `speed_intent = 1 - y`

3. 应用控制映射
- 正常模式：
  - `speed_intent < reverse_threshold` 则倒车；
  - 否则线速度按 `max_forward_speed * speed_intent`；
  - 转向由 `steer_intent` 映射到角速度，带 `steer_deadzone`。
- 循线模式（`line_mode` 非空）
  - 订阅 `/ground/left`、`/ground/right`，按黑线/白线模式调整转向状态机。

4. 看门狗停车
- 超过 `watchdog_sec` 没新包，发布零速 Twist。

### 4.4 `scripts/eeg_control_node.py`（EEG 主控制节点）

这个节点负责"从 adapter 拉数据 -> 算意图 -> 发控制"。

核心流程在 `_tick`：

1. 调 `adapter.read_frame()` 取 `EegFrame`
2. 判断数据类型
- 若含 `alpha/theta/beta`：走 band 特征链路
  - `enrich_features` -> `policy.compute_intents`
- 若缺频段特征：回退到中性意图（`speed_intent=0.5, steer_intent=0.5`）

3. **优先分支：feature 直接控制（`tcp_control_mode=feature`）**
- 如果参数 `tcp_control_mode == "feature"` 且 frame 里有数值型 `feature`，走此分支。
- 调用 `feature_to_twist(feature_value, ...)` 将标量 feature 映射为 Twist：
  - `0.0 < feature < 0.5`：前进（`max_forward_speed`）
  - `0.5 < feature < 1.0`：后退（`max_forward_speed * -0.75`）
  - `feature == 1.0`：原地右转（`turn_angular_speed`）
  - 其他值：停止
- 发布后直接 return，不进入后续分支。
- 这是 **默认生产模式**（`config/eeg_control_node.params.yaml` 中 `tcp_control_mode: feature`）。

4. 次优分支：movement 直接控制
- 如果 frame 里有数值型 `movement`（且未走 feature 分支），走此分支：
  - `0.0 < movement < 0.5`：前进（`max_forward_speed`）
  - `0.5 < movement < 1.0`：后退（`reverse_speed`）
  - `movement == 1.0`：原地右转（`turn_angular_speed`）
  - 其他值：停止
- 发布后直接 return。

5. 正常意图映射（带频段特征时）
- `_intents_to_twist` 按参数把 `speed_intent/steer_intent` 转换为线角速度。

6. 发布与记录
- 发布 `/cmd_vel`（或 remap 后 topic）
- 发布分析 JSON 到 `analysis_topic`
- 可选 CSV 记录

7. 看门狗
- 超时时如果上一帧是 `movement` 或 `feature` 模式，会保持上次 Twist 输出；
- 否则按当前意图重发结果或停机。

### 4.5 `thymio_control/eeg_control_pipeline.py`（算法与输入适配）

这个文件是可复用"算法层"，与 ROS 解耦。

内容分 6 块：

1. Adapter
- `MockAdapter`
- `TcpClientJsonAdapter`（连接外部 TCP client 服务，支持 SOD...EOD 包解析）
- `LslAdapter`
- `KeyboardAdapter`（类存在，但 CLI choices 当前未暴露 keyboard 选项）

2. 特征工程
- `enrich_features` 计算：
  - `theta_beta`
  - `beta_alpha`
  - `beta_alpha_theta`
  - `alpha_asym`

3. Policy
- `FocusPolicy`
  - `focus_norm = clip01((beta_alpha_theta - 0.15) / 0.85)`
  - `speed_intent = focus_norm`
  - `steer_intent = clip01(0.5 + 1.1 * alpha_asym)`
- `ThetaBetaPolicy`
  - 速度与 `theta_beta` 反向映射
  - 转向同样基于 `alpha_asym`

4. `feature_to_twist`（标量特征 → Twist）
- 把单个 feature 值按离散阈值映射为 Twist，与 movement 模式约定一致。
- 由 EEG 节点在 `tcp_control_mode=feature` 时调用，也供离线管线使用。

5. 离线文件管线（`OfflineFilePipeline`）
- 依赖 `EnobioFileReader` 读取 `.info` / `.easy` 录制文件。
- 通过 `PIPELINE_ALGORITHMS`（当前支持 `theta_beta_ratio`）计算逐帧 feature。
- `iter_twists()` 迭代输出 Twist，供集成测试或离线回放使用。
- CLI 以 `--input file` 或 `pipeline_config.source_type: file` 触发此路径。

6. 独立 CLI 主程序
- 可直接运行 pipeline 发 UDP（不依赖 ROS 节点）。
- 支持 `--config`，并实现"命令行参数优先于 YAML"。
- `--input` 支持 `mock`、`tcp_client`、`lsl`、`file`（离线模式）。

---

## 5. 配置文件怎么读（你改参数主要改这里）

### 5.1 `config/launch_args.yaml`

这是 launch 默认参数来源。
当前关键默认值：
- `use_sim: true`
- `run_eeg: false`
- `run_gaze: false`
- `use_teleop: true`

含义：默认更偏“手动演示模式”。
要自动控制，需要显式开启 `run_eeg` 或 `run_gaze`，并关闭 teleop。

### 5.2 `config/eeg_control_node.params.yaml`

EEG 节点参数。
当前示例里输入模式是：
- `input: tcp_client`
- `tcp_host: 172.27.96.1`
- `tcp_port: 1234`
- `tcp_control_mode: feature`（默认；可选 `movement`）

`tcp_control_mode` 决定 EEG 节点如何处理 TCP 数据包中的控制字段：
- `feature`：读取 `feature` 字段，用 `feature_to_twist` 直接映射为 Twist（默认生产模式）。
- `movement`：读取 `movement` 字段，按离散区间映射为前进/后退/转向。

如果你在本机调试，可先改成：
- `input: mock`

### 5.3 `config/gaze_control_node.params.yaml`

Gaze 网关参数。
重点是：
- `udp_host`
- `udp_port`
- 速度与转向映射参数
- `line_mode` 与 `line_threshold`

### 5.4 `config/experiment_config.yaml`

这是 pipeline CLI 示例配置（adapter/policy_cfg/output 分层），
用于非 ROS 方式单跑 EEG pipeline 时参考。

---

## 6. 桥接脚本怎么理解（WSL 与 Windows）

### 6.1 `tools/bridges/wsl_tobii_bridge.py`

- 在 WSL 中动态生成临时 Windows Python 脚本。
- 通过 `python.exe` 在 Windows 侧运行 Tobii SDK。
- 回调里发送 UDP JSON 到 WSL。
- 当前发送格式是 `x/y`，由 ROS 侧 `gaze_control_node.py` 兼容转换。

### 6.2 `tools/bridges/wsl_enobio_bridge.py`

- 机制同上，也是在 Windows 侧执行临时脚本。
- 支持 `--mock`（无需设备，发送平滑模拟数据）。
- 真实模式依赖 `pylsl`，并从 LSL 样本估计 `x/y`。
- 同样是历史 `x/y` 输出，由 ROS 侧统一语义。

### 6.3 `tools/system/prepare_usb.sh`

- 仅做 usbipd 附加，不参与控制环。
- 目的：把系统操作从 ROS 节点逻辑里分离。

---

## 7. 初学者阅读与实验顺序（照着做就能吃透）

1. 先跑 `eeg_thymio.launch.py`（mock 输入）
2. 用 `ros2 topic echo` 看 `/cmd_vel` 和分析 topic
3. 改 `eeg_control_node.params.yaml` 的一个参数（如 `max_forward_speed`）再观察变化
4. 切到 `gaze_thymio.launch.py`，先不连硬件，手工发 UDP JSON 测试
5. 最后读 `experiment_core.launch.py` 的条件表达式，理解所有启动组合

手工发 UDP 的最小例子：

```bash
python3 - <<'PY'
import json, socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(json.dumps({"speed_intent": 0.8, "steer_intent": 0.2}).encode(), ("127.0.0.1", 5005))
print("sent")
PY
```

---

## 8. 最小回归测试清单（每次改完都跑）

1. 语法检查

```bash
python3 -m py_compile thymio_control/scripts/eeg_control_node.py
python3 -m py_compile thymio_control/scripts/gaze_control_node.py
python3 -m py_compile thymio_control/thymio_control/eeg_control_pipeline.py
python3 -m py_compile thymio_control/launch/experiment_core.launch.py
```

2. Launch 参数解析

```bash
ros2 launch thymio_control experiment_core.launch.py --show-args
ros2 launch thymio_control eeg_thymio.launch.py --show-args
ros2 launch thymio_control gaze_thymio.launch.py --show-args
```

3. EEG 路径（mock）

```bash
ros2 launch thymio_control eeg_thymio.launch.py use_teleop:=false
# 新终端
ros2 topic echo /cmd_vel --once
```

4. Gaze 路径（UDP）

```bash
ros2 launch thymio_control gaze_thymio.launch.py use_teleop:=false use_tobii_bridge:=false
# 新终端用上面的 UDP 小脚本发包
ros2 topic echo /cmd_vel --once
```

5. 看门狗
- 停止输入后等待 `watchdog_sec`，应看到速度归零或进入节点定义的安全行为。

---

## 9. 你最容易踩坑的地方

1. 以为节点没工作，其实是 `use_teleop=true` 把 EEG/Gaze 条件关掉了。
2. 以为桥接坏了，实际是端口不一致（launch 参数与 YAML 不一致）。
3. 以为算法不对，实际是仍在用 `mock` 输入。
4. 看到 `thymio_ros.py` 还在就继续用它。这个文件现在是 deprecated 兼容壳，不是主入口。
5. 以为 EEG 节点走的是 band-features 意图模式，其实默认 `tcp_control_mode: feature`，优先走 `feature_to_twist` 直控，只有当 `feature` 字段不存在时才会回退到 movement / 意图链路。

---

## 10. 版本控制建议（你改代码时这样做最稳）

```bash
git checkout -b feat/readable-change
# 做改动
python3 -m py_compile thymio_control/scripts/eeg_control_node.py
python3 -m py_compile thymio_control/scripts/gaze_control_node.py
git add -A
git commit -m "Explain and adjust control mapping"
```

如果你移动文件，尽量用 `git mv` 保留历史。

---

## 11. 一页记忆（看完后你应能回答）

1. 谁负责启动所有组件：`experiment_core.launch.py`
2. 谁负责 EEG 实时控制：`eeg_control_node.py`
3. 谁负责 UDP 视线数据接入：`gaze_control_node.py`
4. 谁负责 EEG 特征与策略：`eeg_control_pipeline.py`
5. 为什么还有 `thymio_ros.py`：仅兼容提示，不再是主流程

如果这 5 个问题你都能解释清楚，说明你已经真正理解这个包的当前架构。
