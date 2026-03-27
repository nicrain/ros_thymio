# Thymio EEG 实验控制平台：分析与设计白皮书

## 一、 项目愿景
构建一个灵活、可扩展的 EEG 控制实验平台，支持多种 EEG 设备（通过 LSL/TCP）、多种信号处理算法及多种 Thymio 机器人行为模式，支持多对多的动态绑定与实验数据全链路记录。

## 二、 短期需求 (Short-term Focus)
1.  **EEG 优先**：以 EEG 信号控制为核心，淡化 Tobii 视线控制逻辑。
2.  **多协议接入**：稳定支持 TCP（JSON 格式）和 LSL 协议的数据读取。
3.  **控制验证**：通过专注度（Beta/Alpha+Theta 等）实时调节 Thymio 的线速度，并保留循线功能作为方向控制。
4.  **架构进化**：从单脚本逻辑向标准 ROS2 节点化过渡。

## 三、 推荐目标架构 (Proposed Architecture)

### 1. 设备接入层 (Ingestion)
- **统一 Adapter 接口**：实现 LSL、TCP、UDP 适配器。
- **输出**：标准化的 EEG 频段能量流（`/eeg/metrics`）。

### 2. 信号处理层 (Signal Processing)
- **插件化管线**：独立处理滤波、伪迹剔除。
- **特征提取**：计算比值、非对称性等指标。

### 3. 意图推断层 (Intent Inference)
- **语义转换**：将特征转换为“前进概率”、“转向倾向”、“专注度分数”。
- **置信度输出**：输出意图同时带上 Confidence 指标。

### 4. 控制策略层 (Control Strategy)
- **热切换策略**：支持规则映射、状态机或学习模型。
- **安全约束**：集成避障限速、看门狗、失联急停。

### 5. 编队与路由层 (Routing & Multi-Robot)
- **动态绑定**：支持多 EEG 实例与多 Thymio 实例的命名空间路由（Namespace Isolation）。

### 6. 实验管理层 (Experiment Management)
- **配置驱动**：所有参数（阈值、增益、通道映射）由 YAML 管理。
- **回放验证**：支持 `rosbag2` 录制，可通过回放原始 EEG 数据比较不同控制算法的性能。

## 四、 关键设计原则 (Design Principles)
1.  **配置驱动**：拒绝硬编码。
2.  **协议算法解耦**：更换数据源不影响控制算法。
3.  **消息标准化**：定义统一的消息结构（Timestamp, SourceID, SubjectID, Quality）。
4.  **时间同步**：严格的时间基准对齐。
5.  **安全至上**：看门狗逻辑必须默认开启。

## 五、 现状评估与优化方向
- **现状**：已有解耦的 Pipeline 雏形，但仍通过 UDP 环回通信，缺乏 ROS2 原生集成。
- **优化点**：
    - 将 `eeg_control_pipeline.py` 转化为原生的 ROS2 节点。
    - 引入 YAML 配置文件管理实验参数。
    - 移除 Tobii 相关冗余代码，重命名变量以符合 EEG 语境。
    - 拆分 `thymio_ros.py` 的职责，将“驱动管理”与“控制逻辑”分离。

## 六、 渐进式实施步骤
1.  **第一步**：创建标准的 ROS2 包结构，将现有逻辑拆分为 `ingest_node`、`feature_node` 和 `control_node`。
2.  **第二步**：定义标准通信接口（ROS2 Custom Messages），取代现有的 UDP JSON 包。
3.  **第三步**：引入 YAML 配置，实现被试 ID、通道映射、算法参数的一键切换。
4.  **第四步**：建立实验监控台，利用 `rqt` 实时查看 EEG 特征与机器人响应的对应曲线。

## 七、 近期执行清单（第0条 + 3条）

### 0. 先定义统一控制语义（强烈建议先做）
- **动作**：先定义统一意图语义与字段，如 speed_intent（线速度意图）、steer_intent（角速度意图）、confidence、quality、timestamp、source_id。
- **目的**：先稳定“语义层”，再重构传输层和节点形态，避免后续重复改名与协议返工。
- **落地建议**：短期在现有代码中通过数据结构或字典统一字段；中期迁移为 ROS2 消息定义。

### 1. 代码清理与变量重命名（EEG-Centric Refactor）
- **动作**：在 thymio_ros.py 与 eeg_control_pipeline.py 中，将 x/y 的内部语义替换为 speed_intent 与 steer_intent。
- **注意**：不建议一次性全局替换；先做“内部语义重命名 + 传输层兼容”。
- **兼容策略**：在过渡期允许旧字段与新字段并存，确保现有链路和脚本可继续运行。

### 2. 创建原生 ROS2 控制节点（Control Node Refactor）
- **动作**：将 eeg_control_pipeline.py 的 Adapter / Feature / Policy 逻辑迁移到 ROS2 Node 运行壳中。
- **收益**：
    - 直接发布 ROS2 话题，不再依赖本地 UDP 环回。
    - 使用 ros2 run + YAML 参数，减少改源码调参。
    - 原生接入 rosbag2，支持实验回放与参数对比分析。
- **实现建议**：采用 timer 驱动与非阻塞输入，分别控制“采样频率”和“发布频率”，并保留失联急停看门狗。

### 3. 参数外部化（Config-driven）
- **动作**：将 Adapter 类型、LSL 流名称、TCP 端口、特征映射参数（Slope/Intercept）、阈值、限速参数全部抽离到 experiment_config.yaml。
- **收益**：现场实验可快速改配置并重启节点，无需在代码中反复查找硬编码常量。
- **配置分层建议**：
    - device_config：协议、地址、端口、流名、通道映射。
    - experiment_config：特征公式、斜率截距、阈值、安全超时、策略选择。

### 推荐顺序（降低风险）
1. 先做第0条（统一语义层）。
2. 再做第3条（参数外部化）。
3. 再做第2条（ROS2 节点化）。
4. 最后完成第1条的全量清理与旧字段下线。
