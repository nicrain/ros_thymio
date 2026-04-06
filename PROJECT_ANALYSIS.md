# Thymio 混合控制平台 (EEG & Gaze)：架构与任务追踪白皮书

> **文档受众**: 本文档专为后续接手的 **AI Coding Agent** 编写。请严格按照本文档的架构规范、状态标记和任务清单进行代码理解和开发。
> **核心工作流警告**: **绝不允许一次性实现所有功能！** 本环境可能无法进行全链路物理测试。你必须严格遵循“编写一小块 -> 编写对应的 pytest 单元测试 -> 运行验证 -> 暂停并向用户汇报结果”的“稳扎稳打”策略。

---

## 零、 核心设计原则 (AI Agent 必读)
1. **纯粹的配置驱动 (Config-driven)**：拒绝一切硬编码。设备端口、通道数、特征映射公式、算法选择必须通过 YAML (`experiment_config.yaml` 等) 注入。
2. **策略模式 (Strategy Pattern)**：处理不同数据源（TCP/LSL/File）和不同算法时，使用工厂或策略模式动态加载，保证“数据摄入 - 信号处理 - 小车控制”三层严格解耦。
3. **安全与防呆**：对于不定长的 EEG 数据、不稳定的网络流，必须加入异常捕获、数组越界检查（动态通道切片时）以及失联急停（Watchdog）。
4. **规范化测试驱动 (Standardized Test-Driven in Non-Execution Env)**：
   - 由于无法随时启动物理小车进行端到端测试，你必须在实现业务代码的同时，编写**单元测试 (Unit Tests)**。
   - **测试框架与规范**：全盘采用 Python 业界的标准框架 `pytest`。
   - **目录结构**：所有的测试代码**绝不能**散落在源码目录中。你必须在项目包内（`thymio_control/test/`）建立专门的测试目录（如果不存在则新建，并添加空的 `__init__.py`），所有测试文件严格以 `test_*.py` 命名。
   - **验证流程**：每完成一个小需求，通过编写带有 `assert` 断言的 mock 数据测试用例来证明其逻辑的正确性，随后使用命令 `python3 -m pytest thymio_control/test/test_xxx.py -v` 执行测试，并在测试绿灯通过后，方可向用户汇报并进入下一个任务。

---

## 一、 项目现状与架构演进记录 (Status & Deviations)

### 1. 已实现部分 (Status: ✅ Done)
- **ROS2 节点化转型**：已成功从单脚本迁移为标准的 ROS2 节点架构。
- **参数外部化**：引入了统一的 YAML 配置目录 `thymio_control/config/`，分别控制通用参数与特定节点参数。
- **模块解耦**：将核心处理管线抽离为 `thymio_control/thymio_control/eeg_control_pipeline.py`，将通信桥梁独立为 `tools/bridges/`。

### 2. 与最初设想的偏差记录 (Deviations from Original Plan)
- **关于 Tobii Gaze 控制**：采取了**平行节点双规运行**的策略，重构为独立的 `gaze_control_node.py`，实现了物理和逻辑隔离。
- **通信桥接架构**：引入了专用的 Bridge 脚本以应对 WSL 环境的数据转发，而非全部逻辑都在单一 ROS 节点内完成。

---

## 二、 待处理核心新需求与架构设计 (Status: ⏳ Pending)

> **AI Agent 执行指令**: 以下任务必须**按顺序、逐一**完成。每完成一个 `[ ]` 下的任务，必须在 `thymio_control/test/` 下编写标准的 `pytest` 用例，执行通过后，暂停并询问用户是否可以进行下一步。

> **实现约束补充**:
> - 除非任务明确要求修改桥接脚本，否则优先在 `thymio_control/thymio_control/eeg_control_pipeline.py` 中完成协议解析、策略生成和配置读取逻辑。
> - 新增配置项默认采用向后兼容原则：未配置时应回退到当前已存在的行为，不得因为缺省配置直接中断启动。
> - 每个测试都应覆盖正常路径和至少一个失败路径。失败路径必须使用明确异常或明确的空值约定，禁止静默吞错。

### 📌 需求 2: TCP 模式控制字段扩展 (Feature Field Control)
**背景**：现有的 TCP 控制仅使用了 JSON/数据包中的 `movement` 字段。现需增加对 `feature` 字段（数据包中按分隔符拆分的第 4 个字段，即 index 3）的支持。这部分改动最小，作为热身任务首先执行。

- [x] **Task 2.1: TCP 消息解析升级**
  - **位置**: 优先修改 `eeg_control_pipeline.py` 中现有 TCP 解析逻辑；仅当上游桥接脚本已固定输出同一协议时，才同步调整 `tools/bridges/wsl_enobio_bridge.py`。
  - **逻辑**: 明确以“分隔后第 4 段字段”为 `feature` 来源，即 index `3`。解析结果必须是 `float`。若字段缺失、索引越界或无法转换为数值，应抛出可区分的异常（建议 `ValueError` 或 `IndexError`），不能返回伪造默认值。
  - **验证策略 (Validation)**: 在 `thymio_control/test/test_tcp_parser.py` 中编写 `test_tcp_feature_extraction()`。Mock 传入一段完整的 TCP 字符串，`assert` 解析函数返回的 `feature` 浮点数符合预期；再补一个缺字段或越界样例，`assert` 触发预期异常。
- [x] **Task 2.2: 增加控制模式配置**
  - **位置**: `experiment_config.yaml`
  - **逻辑**: 新增顶层配置键 `tcp_control_mode: "movement" | "feature"`。若未显式配置，默认保持 `movement` 以兼容旧行为。
  - **验证策略 (Validation)**: 在 `thymio_control/test/test_config_loader.py` 中编写用例，读取该 YAML 文件，`assert` 加载出的 `tcp_control_mode` 存在且属于允许取值集合。
- [x] **Task 2.3: 实现 Feature 到 Twist 的映射策略**
  - **位置**: `eeg_control_pipeline.py` 中的控制策略生成部分。
  - **逻辑**: 如果 `tcp_control_mode` 为 `feature`，将提取出的标量值转换为 `geometry_msgs/Twist` (`cmd_vel`) 发送给小车。映射公式需要是单一、可测试、可配置的函数，且结果必须经过速度上限与转向上限裁剪；空帧情况下必须复用 `last_mode` 和 `last_twist`，不能回退到全速默认值。
  - **验证策略 (Validation)**: 在 `thymio_control/test/test_feature_mapping.py` 编写测试，Mock 输入 `feature = 0.1` 和 `feature = 0.9`，调用策略函数后，`assert` 生成的 `cmd_vel.linear.x` 和 `.angular.z` 符合映射公式和阈值限制；再补一个空帧或异常输入样例，验证回退行为。

### 📌 需求 3: LSL 实时控制与高度动态化处理管线 (LSL & Dynamic Pipeline)
**背景**：无论哪种数据源（LSL/TCP/File），其实际传输的通道数不定，我们需要用于计算的通道不定，提取的特征算法也不定。

- [x] **Task 3.1: YAML 定义高度动态化管线**
  - **位置**: `experiment_config.yaml`
  - **逻辑**: 定义 `pipeline_config`，包含 `source_type` ("lsl"/"tcp"/"file")、`selected_channels` (如 `[0, 2, 5]`)、`algorithm` (如 `"theta_beta_ratio"`)。`selected_channels` 的元素必须是从 `0` 开始的整数索引，算法名必须对应后续工厂中的注册键。
- [x] **Task 3.2: 实现“特征提取器”策略工厂**
  - **位置**: `eeg_control_pipeline.py`
  - **逻辑**: 获取全量数据数组后，第一时间执行切片过滤 `filtered_data = raw_data[selected_channels]`。然后通过字典或类映射动态实例化 `algorithm` 对应的计算函数。若通道索引越界，必须立即抛出异常；若算法名未注册，也必须抛出异常，而不是退回到默认算法。
  - **验证策略 (Validation)**: 在 `thymio_control/test/test_dynamic_pipeline.py` 中编写测试。构建一个包含 20 个通道随机数据的 mock numpy 数组。加载配置后，`assert` 程序能准确切片出 `selected_channels` 并算出正确的 `theta_beta_ratio` 标量值。**必须编写一个 `test_channel_out_of_bounds()` 验证在 `selected_channels` 配置错误（如索引超过 19）时，系统抛出明确异常而不是静默崩溃。** 同时补一个未注册算法名的失败测试。
- [x] **Task 3.3: 集成 LSL 接收流 (可选依赖测试)**
  - **位置**: 在 `eeg_control_pipeline.py` 中新增 LSL Adapter，依赖 `pylsl`。
  - **验证策略 (Validation)**: 编写 `test_lsl_adapter.py`。启动一个本地的 mock `pylsl.StreamOutlet` 发送假数据，验证 Adapter 的 `pull_sample` 能否稳定读取数据流（可通过 pytest 设置超时机制）。如果环境未安装 `pylsl`，测试应明确跳过并说明原因，而不是假通过。

### 📌 需求 1: Enobio 离线文件回放模式 (Offline File Playback)
**背景**：利用 `enobio_recodes/` 下成对出现的 `.info` (配置) 和 `.easy` (时间序列数据) 模拟实时流。

- [x] **Task 1.1: 创建 EnobioFileReader 动态解析模块**
  - **位置**: 新建 `thymio_control/thymio_control/enobio_file_reader.py`。
  - **逻辑**: 解析 `.info` 提取采样率和 EEG 通道数；读取 `.easy`。如果文件格式不完整或关键字段缺失，应抛出明确异常，并保留原始错误上下文，方便定位录制文件问题。
  - **验证策略 (Validation)**: 在 `thymio_control/test/test_enobio_file_reader.py` 中编写测试。在 `test/mock_data/` 目录下伪造一个极小的 `.info` 和 `.easy` 文件。测试解析模块能否正确提取 `Channels` 和 `Sample Rate`（`assert rate == 250` 等），并补一个缺失字段样例。
- [x] **Task 1.2: 模拟实时流发布器**
  - **位置**: 类似 Adapter 形式接入管线。
  - **逻辑**: 根据采样率按时间戳间隔逐行“喂”给下游。若调用方要求非实时模式，应支持以无 sleep 的方式快速回放，便于测试。
  - **验证策略 (Validation)**: 结合 `pytest-mock` 或简单的时间戳比对验证，测试模拟器产生的相邻两次 `yield` 或回调调用的时间间隔是否符合预期的采样率倒数（允许适当误差）。
- [ ] **Task 1.3: 管线大一统测试**
  - **逻辑**: 将 `source_type` 设为 `"file"`，配合之前写的动态通道切片（Task 3）和特征控制（Task 2）。
  - **验证策略 (Validation)**: 编写端到端 (E2E) 测试 `test_pipeline_integration.py`。将一小段离线 mock 数据输入 Pipeline 主类，拦截末端的输出，`assert` 生成的一系列 `Twist` 指令不为空且数值在安全限制之内。测试应明确固定输入配置、算法名和通道选择，避免依赖随机性。

---

## 三、 附录：历史架构踩坑避南 (Architecture Lessons Learned)
> **AI Agent 必读**：以下是在上一轮重构中解决的核心隐患记录。在处理新的 LSL 或 TCP 输入流时，务必避免重复踩坑。

### ⚠️ 避坑 1：TCP 链路中的累积延迟 (Buffer Bloat Fix)
- **根因**：生产端高频发包，ROS 端低频消费。如果不排干缓存，会导致严重控制延迟。
- **解决原则**：必须废弃超时阻塞，在每个单周期内**彻底排干缓存池 (Drain the Buffer)**。使用 `while True:` 和非阻塞 `recv()` 持续读取直到抛出 `BlockingIOError`。只提取本周期收到的**倒数最后一个完整数据包**传入算法层。

### ⚠️ 避坑 2：空缺轮次 (Empty-tick) 的硬编码污染
- **根因**：设备帧率低于 ROS 轮询频率时，无数据输入，旧版管线缺乏最后状态缓存，错误地生成满速前行指令。
- **解决原则**：控制策略必须具备**降级与状态保持 (Fallback)** 功能。遇到有效空帧时，应当复用记录的 `last_mode` 和 `last_twist` 作为短时保持，绝不能使用默认极值。