# Thymio Control 架构重构与标准化提议 (Refactor Proposal)

## 1. 背景与现状分析 (Context & Analysis)
项目目前已完成从 `thymio_tobii` 到 `thymio_control` 的核心迁移。虽然功能完备，但 `thymio_control/` 目录呈现“扁平化”结构，存在以下挑战：
- **职责混杂**：Python 核心逻辑、YAML 配置文件、ROS 2 Launch 启动脚本以及 Markdown 文档全部堆放在根目录。
- **扩展性瓶颈**：随着未来传感器（如脑电、视线、心率）的增加，文件数量将成倍增长，导致维护困难。
- **非标工程化**：未遵循 ROS 2 的标准目录结构（如 `config/`, `launch/`, `src/`），降低了工程的专业度和可移植性。

## 2. 重构目标 (Goals)
- **职责分离 (Separation of Concerns)**：实现配置、文档、启动逻辑与核心算法的物理隔离。
- **标准化**：对齐 ROS 2 Python 包的通用标准。
- **健壮性**：优化路径处理逻辑，确保在不同目录下启动脚本时路径解析依然准确。

## 3. 提议的目录结构 (Proposed Structure)
重构后的 `thymio_control/` 应如下所示：

```text
thymio_control/
├── config/                  # 存放所有实验与节点参数 (YAML)
│   ├── eeg_control_node.params.yaml
│   ├── experiment_config.yaml
│   └── launch_args.yaml
├── launch/                  # 存放 ROS 2 Launch 启动文件
│   └── eeg_thymio.launch.py
├── docs/                    # 存放实验手册与技术文档
│   ├── EEG_PIPELINE.md
│   └── ENOBIO_LAB_PREP.md
├── scripts/                 # 入口脚本与桥接工具 (Executable Scripts)
│   ├── thymio_ros.py            # 一体化控制主脚本
│   ├── eeg_control_node.py      # ROS 2 原生控制节点
│   ├── wsl_enobio_bridge.py     # 脑电桥接
│   └── wsl_tobii_bridge.py      # 视线桥接
├── thymio_control/          # 核心算法与通用逻辑包 (Python Module)
│   ├── __init__.py
│   └── eeg_control_pipeline.py  # EEG 处理管线与策略
├── CMakeLists.txt           # 需更新安装规则
└── package.xml              # 需检查依赖声明
```

## 4. 实施路线图 (Action Plan for the AI Agent)

### Step 1: 建立目录骨架
创建 `config/`, `launch/`, `docs/`, `scripts/`, `thymio_control/` 子目录。

### Step 2: 物理迁移
- 将 `.yaml` 移动至 `config/`。
- 将 `.launch.py` 移动至 `launch/`。
- 将 `.md` (除 README) 移动至 `docs/`。
- 将 `eeg_control_pipeline.py` 移动至 `thymio_control/` 并创建 `__init__.py`。
- 将其余 `.py` 移动至 `scripts/`。

### Step 3: 代码修正 (Critical)
1.  **路径引用更新**：
    - 在 `eeg_control_node.py` 和 `thymio_ros.py` 中，搜索加载 YAML 的代码，将路径硬编码（如 `./config.yaml`）改为相对于当前脚本位置的 `../config/config.yaml`。
    - 在 `eeg_thymio.launch.py` 中，更新 `Node` 的 `package` 路径以及 `parameters` 的文件路径。
2.  **Import 逻辑更新**：
    - 由于 `eeg_control_pipeline.py` 已进入子包，`eeg_control_node.py` 的导入语句需从 `from eeg_control_pipeline import ...` 改为 `from thymio_control.eeg_control_pipeline import ...`。
3.  **WSL 桥接调用**：
    - `thymio_ros.py` 中调用 `wsl_tobii_bridge.py` 的逻辑需确保路径指向 `scripts/` 目录。

### Step 4: 验证
- 运行 `colcon build` 确保包结构依然可编译。
- 使用 `ros2 run` 和 `ros2 launch` 测试节点是否能正确加载参数。

## 5. 参数系统升级 (Parameter System Upgrade)
为了减少复杂的命令行输入并为未来的 GUI 交付打下基础，重构应包含以下参数管理逻辑：

### 5.1 引入 Master YAML 模式
将散落在各处的参数（如串口、端口、策略、阈值）整合进一个层级化的配置文件（如 `config/experiment_config.yaml`）。
建议结构：
```yaml
robot:
  bus_id: "1-1"
  max_forward_speed: 0.2
  line_mode: ""  # "blackline", "whiteline"
connection:
  udp_port: 5005
  tcp_port: 6001
eeg:
  input: "mock"
  policy: "focus"
  lsl_stream_type: "EEG"
```

### 5.2 参数优先级逻辑 (Priority Hierarchy)
脚本加载参数时应遵循以下顺序（高优先级覆盖低优先级）：
1. **Command Line Arguments**: 用户手动输入的 `--port`, `--mode` 等。
2. **YAML Config File**: 通过 `--config` 参数指定的配置文件内容。
3. **Internal Defaults**: 代码中硬编码的默认安全值。

### 5.3 脚本入口调整
- `thymio_ros.py` 应增加 `--config` 参数支持。
- 实现一个 `load_config(path)` 工具函数，自动解析并分发参数给各个模块。

## 6. 注意事项 (Warnings)
- **__file__ 的依赖**：重构时务必使用 `os.path.abspath(os.path.dirname(__file__))` 来构建相对路径，严禁使用 `os.getcwd()`，因为后者依赖于用户的终端启动位置。
- **Git 历史**：建议使用 `git mv` 进行移动，以保留文件的提交历史。
- **GUI 预留**：参数结构化后，未来的 GUI 代理只需读写这个 YAML 文件即可控制全局，无需修改核心逻辑。

---

## 7. 第二阶段重构计划：彻底消除架构“缝合感” (Phase 2 Refactor Plan)

虽然第一阶段（物理目录隔离）已经完成，但核心入口 `thymio_ros.py` 内部逻辑仍然高度耦合，保留了大量的跨网络（UDP）通信和废弃的 `x/y` 坐标语义。第二阶段（当前状态）的核心目标是**彻底拥抱原生 ROS 2 架构，拆解单体脚本**。

### 7.1. 标准与核心原则 (Standards & Principles)

1. **彻底废除内部 UDP 环回通讯**：所有控制层数据传输（速度、转向意图等）必须原生地流经 ROS 2 Topic 网络，而不是依赖 `socket.socket(socket.AF_INET, socket.SOCK_DGRAM)` 这种 Hack 通信方式。
2. **遵守单一职责原则 (SRP)**：Python 业务脚本（如 `thymio_ros.py`）只负责具体的业务节点逻辑处理。**禁止**在单个 `.py` 文件中使用 `subprocess.Popen` 去管理其他兄弟进程、拉起驱动或执行 WSL 桥接程序。
3. **基于 Launch 统一管理生命周期**：所有多进程的相互启停依赖关联，必须交由 `launch/` 目录下的 `.launch.py` 文件全权管理。绝不能依赖某个 Python 程序里的 `time.sleep` 等待其他进程就绪。
4. **意图语义大统一**：彻底抛弃带有历史包袱的 `x` 和 `y` 坐标语义，全链路数据统一使用 `speed_intent` （线速度意图）和 `steer_intent`（角速度意图）。

### 7.2. 具体执行步骤 (Execution Steps)

#### 步骤一：创建标准的 ROS 2 Launch 编排文件
- **动作**：在 `launch/` 目录下创建一个“大一统”的 `experiment_core.launch.py` 文件。
- **职责**：
  1. 通过 `IncludeLaunchDescription` 去启动底层的 `thymio_driver main.launch` 硬件驱动包。
  2. 使用 `ExecuteProcess` 或 `Node` 分拆启动 WSL 数据源桥接脚本。
  3. 启动顶层的策略控制系统节点（如原生的 `eeg_control_node.py` 或未来的视线控制 Node）。
- **收益**：可以通过 `ros2 launch thymio_control experiment_core.launch.py` 一键无痛启动全套流程。

#### 步骤二：给 `thymio_ros.py` “剔骨减肥”并降级
- **动作**：移除 `thymio_ros.py` 中**所有**进程管理（`subprocess` 启动桥接、启动驱动）以及 UDP Socket 监听逻辑。
- **拆分操作**：
  - 将 USB 挂载（`usbipd`）提取成完全独立的纯种系统脚本（如 `scripts/prepare_usb.sh` 或 `.bat`），不再由 ROS 系统介入操作系统的 USB 转发层。
  - 如果依旧需要视线（Gaze）控制，新建一个标准节点 `gaze_control_node.py`，结构对标现在的 `eeg_control_node.py`：订阅包含了速度与转向意图的话题（或直接读取原始视线话题），并在处理完毕后通过 `Twist` 发布 `/cmd_vel`。
- **废弃判定**：在拆分完成后，原有的巨无霸 `thymio_ros.py` 应该被正式标记为废除（Deprecated）或者彻底删减。不留歧义。

#### 步骤三：消除冗余的“语义补丁”
- **动作**：重洗数据管线：修改 `thymio_control/thymio_control/eeg_control_pipeline.py`。
- **细节清理**：斩草除根式地删除 `with_legacy_xy()` 函数。策略层只产出且只向上层节点输送 `speed_intent` 和 `steer_intent` 字段。
- **控制逻辑直连**：下游控制端（如 `eeg_control_node.py` 的算法 `_intents_to_twist`）直接使用获得的 `speed_intent` 换算成马达的具体线速度指令，消除先将速度翻译为 `y` 甚至反转 `1.0 - speed` 的逆天扭曲逻辑。

#### 步骤四：清理异构的桥接物 (Clean Heterogeneous Bridges)
- **动作**：现在项目在使用标准 LSL 链路时，已大大减少了对私有桥接数据流的依赖。后续应当将这些特殊硬件专用脚本（如 `wsl_tobii_bridge.py`、`wsl_enobio_bridge.py`）移入一个单独的网关目录（如 `tools/bridges/`）以示隔离。
- **目的**：保证核心的 `thymio_control/` 是完全纯粹的 ROS2 + Python 算法环境，所有外部硬件数据源在进入 ROS 核心生态之前，只负责完成“格式清洗并在网络边界转化为 ROS2 Topic”，不可在 ROS 工作空间中肆意蔓延。

### 7.3. 焦点问题专录：Tobii 视线控制链路的架构迁移 (Gaze Control Migration)

**业务需求：** 在彻底改用 `ros2 launch` 和 YAML 参数解耦的全新架构后，必须继续无缝支持 Windows 端通过 UDP 将 Tobii 视线坐标发送至本地 ROS 2 控制 Thymio 的老链路，并保持使用体验的统一性。

**架构设计规划 (Architectural Design)：**
为了在不妥协新架构标准（解耦、YAML驱动）的前提下继续支持视线控制，设计如下重构映射：

1. **链路边界确立**：
   - 维持跨系统（Windows -> WSL）的 UDP 数据发送边界设计（此职能由独立的 `wsl_tobii_bridge.py` 承载，它属于外部数据网关）。
   - **绝对禁止**继续使用承担了驱动启停等脏活的胖脚本（`thymio_ros.py`）来接收这路 UDP 数据。

2. **新建专属解耦节点 (`gaze_control_node.py`)**：
   - **职责定位**：对标现有的 `eeg_control_node.py`。这是 ROS 2 侧唯一的“视线网关与指令处理器”。
   - **输入层**：专职开启非阻塞式 Socket 监听指定的 UDP 端口（原 5005），接收桥接器打包的 `x/y` JSON 数据。
   - **输出策略**：在模块内部消化所有复杂的特征映射算法（包含是否激活 `blackline/whiteline` 循线干预，及马达限速、转向映射），最终将计算结果标准化为原生 `geometry_msgs/Twist` 消息，向 `/cmd_vel` 话题广播。
   
3. **参数配置的全面 YAML 化**：
   - 彻底废弃在终端通过 `--udp-port 5005 --mode gaze` 串联启动传参的做法。为视线节点在 `config/` 建立专用的参数档案（`gaze_control_node.params.yaml`）。
   - **静态化运行时状态**：
     ```yaml
     gaze_control_node:
       ros__parameters:
         udp_port: 5005
         line_mode: "blackline" # 或空字符串关闭循线
         max_forward_speed: 0.2
         threshold_reverse: 0.8  # 原脚本中的硬编码 magic numbers 将全部配置化
     ```

4. **Launch 编排融合**：
   - 复用现有的 `eeg_thymio.launch.py` 底座，增加对于 `use_gaze:=true` 这类 `LaunchArgument` 的逻辑分支，或者为了极简维护直接平替新建一个 `gaze_thymio.launch.py`。
   - 在该 Launch 拓扑树中达成闭环：
     - 利用 `Node` Action 启动 `gaze_control_node.py` 并指派加载上文建立的 YAML 档。
     - 若有需要，直接通过 `ExecuteProcess` 或定制化 `Node`，把 `wsl_tobii_bridge.py` 视作子进程一并在后台守护拉起。
   - **交付形态**：科研人员在使用眼动仪实验时，其启动入口与 EEG 完全同构，只需运行标准口令 `ros2 launch thymio_control gaze_thymio.launch.py`，整个从 Windows 眼动采集到 Thymio 轮子动作的通路，以最优的解耦形式顺畅拉起。
