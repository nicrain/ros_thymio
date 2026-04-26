# ROS Thymio 项目整体架构与工程化改进需求说明书

## 1. 文档信息
- 文档名称: ROS Thymio 项目整体架构与工程化改进需求说明书
- 项目: ROS2 Thymio EEG/Gaze/Web 控制平台
- 版本: v2.1
- 日期: 2026-04-24
- 状态: Analysis Complete / Awaiting Execution Confirmation
- 适用对象:
  - 架构负责人、算法工程师、ROS 工程师、前后端工程师、测试工程师
  - AI Agent（代码改造、测试补齐、回归验证、文档维护）

---

## 2. 目标与背景

本项目的主要目标不是单点优化某一条链路，而是系统性完善整个代码库，确保:
1. 架构边界清晰，模块职责单一，便于长期演进。
2. 多输入源（EEG LSL、EDF 回放、TCP/UDP、Mock、Gaze）可统一接入和治理。
3. 关键控制链路具备可验证的实时性、稳定性和可回滚能力。
4. 代码质量、测试体系、配置治理和发布流程可持续运作。

本规范将原 EEG LSL/EDF 低延迟重构需求升级为项目级工程规范，EEG LSL/EDF 属于其中一个重点专题。

---

## 3. 现状问题总览（项目级）

## 3.1 架构层面
1. 输入设备判断、输入方式判断、协议处理、数据处理和控制策略在部分路径中耦合。
2. 实验代码与生产代码边界不够明确，存在“可运行但不可治理”的风险。
3. 统一的内部数据契约（raw frame / feature frame / control intent）尚未全面落地。

## 3.2 代码层面
1. 部分节点承担过多职责（采集、处理、控制、日志、持久化混在一个周期内）。
2. 不同输入源采用不同语义，导致策略复用和行为一致性较差。
3. 关键路径缺乏标准化埋点，性能瓶颈难以客观定位。

## 3.3 工程层面
1. 配置项分散，命名不统一，默认值来源不透明。
2. 测试覆盖结构不完整，尤其是跨模块集成与性能回归。
3. 文档与实现存在时序差，容易导致协作理解偏差。

## 3.4 现状模块成熟度评估（v2.1 新增）

> 基于 2026-04-24 代码审查结果。

| 模块 | 位置 | 行数 | 成熟度 | 关键发现 |
|------|------|------|--------|----------|
| EEG Pipeline | `eeg_control_pipeline.py` | 865 | 可用但臃肿 | 单文件巨石，6 种职责混杂，违反分层约束 |
| EEG Node | `eeg_control_node.py` | 487 | 可用但复杂 | `_tick()` 约 220 行，3 个控制分支大量重复 |
| Gaze Node | `gaze_control_node.py` | 202 | 较稳定 | 独立且职责清晰 |
| EDF Reader | `lsl_test/edf_reader.py` | 145 | 质量好 | API 清晰，有上下文管理器 |
| EDF-LSL Bridge | `lsl_test/edf_to_lsl.py` | 132 | 基本完成 | 缺少 chunk push 优化 |
| EEG Processor | `lsl_test/eeg_processor.py` | 173 | 核心价值 | 主链完全缺失的重计算层 |
| Tests (主链) | `thymio_control/test/` | 10 文件 | 覆盖基础场景 | 34 个测试，无性能回归 |
| Tests (实验区) | `lsl_test/test_*.py` | 4 文件 | 较完善 | 约 21 个测试 |

### 核心发现

1. 主链 LslAdapter 是薄壳 -- 只做 `pull_sample` 到 dict 映射，完全缺少从 raw EEG 到频域特征的 DSP 处理。而 `lsl_test/eeg_processor.py` 已经实现了这一层。
2. 数据契约未落地 -- RawSampleFrame / FeatureFrame / ControlFrame 仅存在于规范中，代码中只有 `EegFrame(ts, source, metrics: Dict[str, float])`。
3. 现有优势 -- Adapter 工厂模式 + Policy 策略模式 + YAML 配置分层 + 测试基础均已可用。

---

## 4. 总体改造原则

1. 分层优先
- 先建立稳定边界，再做功能扩展。

2. 契约优先
- 先冻结输入输出数据契约，再优化算法细节。

3. 可测优先
- 每次重构都必须可通过自动化测试验证。

4. 可回滚优先
- 任何主链改动必须具备 feature flag 与回滚路径。

5. 渐进迁移
- 实验区持续迭代，主链仅吸收“最小稳定内核”。

---

## 5. 目标架构（项目级）

## 5.1 六层架构模型

1. Device Profile Layer
- 作用: 描述设备能力与静态信息。
- 典型字段: device_type、channel_labels、sample_rate、schema、clock_source。

2. Input Mode Layer
- 作用: 定义数据来源方式。
- 模式: live_device、replay_file、mock。

3. Transport Layer
- 作用: 处理协议接入与连接生命周期。
- 协议: lsl、tcp、udp、file_reader。

4. Decode/Normalize Layer
- 作用: 统一数据形态与字段。
- 标准输出: RawSampleFrame / FeatureFrame / ControlFrame。

5. Processing Layer
- 作用: 根据数据形态进行重计算或轻处理。
- 分支:
  - 重计算: raw EEG -> 滤波/频域/特征提取。
  - 轻处理: 已有 feature/control 数据 -> 校验/限幅/补字段。

6. Control Layer
- 作用: 策略推理、运动控制、安全兜底。
- 输出: geometry_msgs/Twist。

## 5.2 严格边界约束
1. 设备类型判断只允许在 Device Profile Layer。
2. 输入方式判断只允许在 Input Mode Layer。
3. 协议判断只允许在 Transport Layer。
4. 复杂算法只允许在 Processing Layer。
5. 机器人控制细节只允许在 Control Layer。

---

## 6. 数据契约（统一）

## 6.1 RawSampleFrame
- 必选字段:
  - ts_acquire
  - source
  - sample_rate
  - channel_labels
  - samples（shape: channels x n_samples）
- 可选字段:
  - source_latency_ms
  - seq_id
  - quality

## 6.2 FeatureFrame
- 必选字段:
  - ts_feature
  - source
  - feature_map（alpha/theta/beta/...）
- 可选字段:
  - window_sec
  - hop_sec
  - engine（welch/iir_filterbank）

## 6.3 ControlFrame
- 必选字段:
  - ts_control
  - speed_intent
  - steer_intent
  - safety_state

契约治理规则:
1. 字段新增必须向后兼容。
2. 字段删除必须跨版本迁移。
3. 任何输入源必须先归一化到上述契约之一。

---

## 7. 专题 A: EEG LSL/EDF（低延迟 + 可演进）

## 7.1 策略定位
1. `lsl_test/` 继续作为实验区，不强制立即合入主链。
2. 主链采用"薄接入 + feature flag + 合并门禁"。
3. 满足门禁后再合并默认路径。

## 7.2 lsl_test/ 实验区现状（v2.1 新增）

### 已完成模块

| 文件 | 功能 | 对接主链的价值 |
|------|------|----------------|
| `edf_reader.py` | EDF 文件读取（pyedflib）、信号元数据、窗口迭代器 | 替代主链缺失的 EDF 回放能力 |
| `edf_to_lsl.py` | EDF→LSL 转发桥接（EEG@500Hz + ACCEL@100Hz） | 实现 `replay_file + file→lsl` 路径 |
| `eeg_processor.py` | Welch PSD + 5 频段（delta/theta/alpha/beta/gamma）能量提取 | 主链完全缺失的重计算层 |

### 已完成测试

| 测试文件 | 覆盖内容 | 测试数 |
|----------|----------|--------|
| `test_edf_reader.py` | Header 解析、信号读取、物理转换、窗口迭代 | 6 |
| `test_edf_to_lsl.py` | Stream 创建、实时/快速回放、数据一致性、E2E | 6 |
| `test_offline_analysis.py` | 频段提取、合成信号验证、脑区差异、策略对接 | 6 |
| `test_real_time_lsl.py` | LslAdapter 与 EDF→LSL 联合测试 | 3 + 1 skip |

### 待完成工作

1. **StreamingBandPowerExtractor** — `eeg_processor.py` 目前只支持离线窗口，需添加适合实时流的滑动窗口 + 增量 PSD 模式。
2. **chunk 批量推送** — `edf_to_lsl.py` 逐样本 `push_sample`，应改为 `push_chunk` 以提升效率。
3. **RawLslAdapter** — 需构建 `pull_chunk → 累积窗口 → compute_band_powers → EegFrame` 的完整适配器，与现有 LslAdapter（薄壳）共存。
4. **FileReader 接口化** — 抽取 `FileReader` 基类，`EdfFileReader` 作为第一个实现，方便未来扩展新文件格式。
5. **E2E 延迟基线** — EDF → LSL → RawLslAdapter → FocusPolicy → speed_intent，采集 p50/p95 延迟数据。

## 7.3 多设备与多格式可扩展性（v2.1 新增）

### 已知设备矩阵

| 设备 | 通道数 | 采样率 | LSL 支持 | 回放文件格式 | 状态 |
|------|--------|--------|----------|-------------|------|
| Enobio 20 | 20 (+3 accel) | 500 Hz | 是 | .edf / .easy+.info | 已有设备和数据 |
| g.tec Unicorn Hybrid Black | 8 | 250 Hz | 是 | 未知（设备未到手） | 待定 |
| g.tec BCI Core-4 Headband | 4 | 250 Hz | 是 | 未知（设备未到手） | 待定 |

### 核心设计原则：设备无关的处理层

处理层（`eeg_processor.py`）只依赖三个参数，不依赖设备类型：
- `samples: ndarray` — 形状 (n_channels, n_samples)
- `sample_rate: int` — 采样率
- `channel_labels: list[str]` — 通道标签

设备差异在以下两个薄层被抹平：
1. **LSL 读取层** — LSL 协议本身设备无关，`StreamInfo` 自带 `sample_rate` 和 `channel_count`。不同设备的 LSL 流结构相同。
2. **文件读取层** — `FileReader` 接口统一输出 `(signals, sample_rate, channel_labels)`，不同格式各自实现解析。

### FileReader 接口设计

```python
class FileReader(Protocol):
    @property
    def sample_rate(self) -> int: ...
    @property
    def channel_labels(self) -> list[str]: ...
    def read_signals(self, indices: Sequence[int]) -> np.ndarray: ...
    def iter_windows(self, indices, *, window_sec, step_sec) -> Iterator[np.ndarray]: ...
    def close(self) -> None: ...
```

当前实现: `EdfFileReader`（基于 pyedflib）。
未来扩展: 新格式只需实现此接口，无需修改处理层或上层代码。

### 未知因素的应对策略

1. **LSL 通道标签降级**: 多数设备（Enobio, g.tec）的 LSL 默认配置不一定在 `desc` 树中注入自定义的 `channel_labels` 标签。当无法从 LSL 描述中解析出明确标签时，系统会默认降级使用 `["ch0", "ch1", ...]`。此降级被视作正常行为，但在未来的设备接入时可考虑配合 `info.channel()` 进行适配补充。

| 未知项 | 应对 |
|--------|------|
| g.tec 回放文件格式 | 预留 FileReader 接口，设备到手后添加实现 |
| g.tec EDF 是否有非标字段 | EdfFileReader 基于 pyedflib，已能处理 Enobio 非标 EDF，大概率兼容 |
| 是否有非 EDF 格式（如 XDF、CSV） | FileReader 接口可扩展，不影响已有代码 |
| 不同设备的通道标签命名规范 | 通过 DeviceProfile 的 `channel_labels` 注入，处理层按索引访问 |

## 7.4 算法参数与可配置性（v2.1 新增）

当前算法参数状态: 尚未调优，使用学术标准默认值。所有参数必须可通过 YAML 配置覆盖。

| 参数 | 当前默认值 | 单位 | 说明 |
|------|-----------|------|------|
| `window_sec` | 1.0 | 秒 | PSD 窗口长度 |
| `hop_sec` / `step_sec` | 0.5 | 秒 | 窗口滑动步长 |
| `nperseg` | 256 | 样本数 | Welch 分段长度 |
| `noverlap` | 128 | 样本数 | Welch 重叠长度 |
| `delta` 频段 | 1.0 - 4.0 | Hz | |
| `theta` 频段 | 4.0 - 8.0 | Hz | |
| `alpha` 频段 | 8.0 - 13.0 | Hz | |
| `beta` 频段 | 13.0 - 30.0 | Hz | |
| `gamma` 频段 | 30.0 - 100.0 | Hz | |

设计约束:
1. 所有参数保持当前默认值，但必须可通过 `experiment_config.yaml` 的 `dsp_config` 段覆盖。
2. 实时与离线模式共用同一套参数，运行时可方便地修改 `window_sec` / `hop_sec`。
3. 频段定义支持用户自定义扩展或部分覆盖标准频段（缺失频段自动回退到默认值）。

## 7.5 流处理边角情况与性能优化路线（v2.1 新增）

在实时流处理（StreamingBandPowerExtractor）中，需遵循以下设计规约：

1. **尾部不完整窗口（Flush & Drop）**
   - 场景：当 EDF 文件回放结束（EOF），或物理 LSL 流突然断开连接时，缓冲区内可能残留不足一个 `window_sec` 的数据。
   - 策略：直接丢弃（Drop）。原因：Welch 算法需要达到最小 `nperseg`（默认 256 样本）才能保证频域分辨率。强制计算尾部碎片数据会引入失真，污染控制指令。
   - 实现：处理器需提供显式的 `flush()` 或 `reset()` 接口。

2. **滑动窗口缓冲区的零拷贝优化（Zero-copy Ring Buffer）**
   - 现状（Phase 1）：目前允许使用 Numpy 数组切片（Slicing & Copy）来实现窗口数据的滑动推进，对于现有通道数（<20通道）性能开销极低，作为骨架是可靠的。
   - 演进（Phase 5）：未来如需支持高密度脑电（如 64/128 通道）或更高采样率，若 Profile 发现数据搬移带来可观的 CPU 占用，需将底层修改为维护首尾指针的纯零拷贝环形队列（Circular Buffer）。

3. **中间处理结果丢弃与遥测策略 (Intermediate Results Dropping)**
   - 场景：在加速文件回放（如 10x 速度）或 `pull_chunk` 批量获取多份数据时，由于一次输入积累了足够长的数据，Extractor 可能会在单次 `feed_chunk` 内触发多次 hop 并生成多个中间窗口结果。
   - 策略：当前适配器 (`RawLslAdapter`) 为保证控制链路实时性，默认策略是仅提取最新结果，丢弃中间窗口。这是合理的。
   - 演进（Phase 2）：为确保系统行为可观测，应通过内部遥测 (Telemetry) 对丢弃的有效窗口数量进行统计，监测实际的丢弃率。

4. **EDF 桥接时间精度与防抖（Timer Jitter Compensation）**
   - 现状（Phase 1）：在 `EdfToLslBridge` 中使用 `time.sleep` 控制模拟数据流推送速度，但在 Windows 系统下存在约 15.6 ms 的默认 Timer Jitter，对高频推送（例如 32 ms 间隔）可能造成实际发送频率的波动。
   - 演进：若系统对测试回放的高精度定时有严苛要求，可改用 `time.sleep` + 忙等（busy-wait）或自旋锁机制补偿 Jitter。

## 7.6 合并门禁
1. 功能门禁
- raw sample 输入与 feature frame 输出契约冻结。

2. 质量门禁
- 单测、集成测试、回归测试全绿。

3. 性能门禁
- 满足第 11 章延迟指标。

4. 运维门禁
- 支持配置化开关、灰度启用、快速回滚。

## 7.7 运行路径建议
1. live_device + lsl + raw sample -> 重计算路径（DSP）。
2. replay_file + edf_replay 或 file->lsl + raw sample -> 重计算路径（DSP）。
3. tcp/udp 若直接携带上层特征或控制值 -> 轻处理路径。

## 7.8 线程与定时建议
1. 采集线程与执行器解耦。
2. 控制定时与遥测定时解耦。
3. 队列满时丢旧保新，保证控制链路新鲜度。

---

## 8. 专题 B: Gaze 控制链路

1. 维持现有稳定行为，避免与 EEG 改造互相干扰。
2. 同步接入统一数据契约（至少在 Normalize 层对齐）。
3. 复用统一的限幅、安全兜底与指标采集框架。

---

## 9. 专题 C: 输入源与协议治理

## 9.1 判定维度分离
1. 设备判定: 设备类型、通道、采样率、设备能力。
2. 输入方式判定: 实时设备、文件回放、mock。
3. 协议判定: lsl/tcp/udp/file_reader。
4. 数据形态判定: raw / feature / control。

## 9.2 路由决策表
| 输入方式 | 协议 | 数据形态 | 处理路径 |
|---|---|---|---|
| live_device | lsl | raw | 重计算 |
| replay_file | edf_replay 或 file->lsl | raw | 重计算 |
| live_device | tcp | feature/control-like | 轻处理 |
| live_device | udp | control-like | 轻处理 |
| mock | internal | synthetic | 可配置 |

核心规则:
- 重计算/轻处理由“数据形态”决定，不由“协议名称”决定。

---

## 10. 目录治理与代码组织

## 10.1 分区定义
1. 实验区
- `lsl_test/`：算法验证、离线分析、实验脚本。

2. 生产区
- `thymio_control/thymio_control/`：核心库代码（适配器、处理器、策略、契约）。
- `thymio_control/scripts/`：ROS2 节点装配与运行入口。

3. 接入区
- `thymio_control/tools/bridges/`：跨系统桥接工具，保持薄层实现。

## 10.2 目标目录结构（重构后，v2.1 新增）

```
thymio_control/thymio_control/
├── __init__.py
├── contracts.py              # RawSampleFrame / FeatureFrame / ControlFrame
├── device_profiles.py        # EEG_DEVICE_CONFIGS 设备注册表
├── adapters/
│   ├── __init__.py
│   ├── base.py               # BaseAdapter 接口
│   ├── mock.py
│   ├── tcp_client.py
│   ├── tcp_file.py
│   ├── lsl_feature.py        # 现有 LslAdapter（薄壳，接收已处理特征）
│   └── lsl_raw.py            # ← 从 lsl_test 合并（接收 raw EEG + DSP）
├── processors/
│   ├── __init__.py
│   ├── band_power.py         # ← 从 lsl_test/eeg_processor.py 合并
│   └── enrich.py             # enrich_features() 派生特征
├── policies/
│   ├── __init__.py
│   ├── base.py               # Policy 接口
│   ├── focus.py
│   └── theta_beta.py
├── pipeline.py               # 薄入口，组装各层
└── eeg_control_pipeline.py   # ← 暂时保留为兼容 fallback
```

> 注意: 重构期间 `eeg_control_pipeline.py` 保留作为回滚路径，待新架构指标达标后标记为 deprecated。

## 10.3 合并规则
1. 不直接复制实验脚本到生产区。
2. 仅迁移可复用且有测试的最小内核。
3. 每次迁移必须附带:
- 模块说明
- 单测
- 回归结果
- 回滚开关

---

## 11. 非功能指标与验收

## 11.1 延迟与稳定性
1. 端到端延迟（采样->cmd_vel）
- p50 <= 40ms
- p95 <= 80ms
- p99 <= 120ms

2. 控制稳定性
- cmd 发布频率偏差 <= 5%
- 连续运行 30 分钟无阻塞崩溃

## 11.2 资源指标
- CPU 增量目标 <= +20%（相对基线）
- 内存无持续增长趋势

## 11.3 采样方法
1. 使用 monotonic_ns/perf_counter_ns。
2. 每轮至少 30 分钟采样，>= 10,000 控制样本。
3. 必须输出原始 CSV 与汇总报告。
4. 报告须包含配置哈希、输入模式、采样率、通道数。

---

## 12. 测试策略（项目级）

## 12.1 单元测试
1. 契约测试（raw/feature/control frame）。
2. 处理器测试（窗口边界、频段能量、滤波行为）。
3. 策略测试（intent 范围、边界行为）。

## 12.2 集成测试
1. EEG: EDF->LSL->Node 全链路。
2. EEG: LSL 实时链路长时运行。
3. Gaze: UDP 输入到控制输出一致性。
4. Mixed: 多输入源并存时互不干扰。

## 12.3 回归测试
1. 现有 tcp_client/tcp_file/mock 行为保持可用。
2. 旧策略结果在容忍范围内无非预期漂移。

## 12.4 性能回归
1. 固定场景定期跑基准。
2. 指标超阈值自动告警。

---

## 13. 配置治理

1. 配置分层
- 设备配置（device profile）
- 运行配置（input/protocol/mode）
- 算法配置（dsp/policy）
- 控制配置（cmd/watchdog）
- 观测配置（telemetry/logging）

2. 配置约束
- 参数命名统一，禁止同义重复。
- 所有阈值必须有单位。
- 所有默认值必须在文档中可追溯。

3. 配置变更流程
- 变更必须带影响评估与回滚策略。

---

## 14. 可观测性与运维

1. 指标
- latency_acquisition_ms
- latency_feature_ms
- latency_control_ms
- latency_e2e_ms
- cmd_jitter_ms
- buffer_fill_ratio

2. 日志
- 控制主环仅记录必要日志。
- 详细分析日志与 CSV 走异步通道。

3. 告警
- 延迟超阈值
- 队列积压
- 输入断流
- 配置非法

---

## 15. 安全与故障处理

1. watchdog 断流保护。
2. 速度/角速度硬限幅。
3. 异常输入兜底（NaN/Inf/越界/字段缺失）。
4. 失败降级路径:
- 新路径失败时自动回退旧路径（由 feature flag 控制）。

---

## 16. 分阶段执行计划（项目级，v2.1 修订）

> 执行策略修订: 基于 v2.1 分析结论，采用「先实验区（lsl_test）→ 后主架构重构」顺序。
> 理由: (1) 实验区改动不影响主链运行，风险低；(2) 验证过的算法模块可直接填充新架构的 Processing Layer；(3) 避免架构重构后再合并导致的重复适配。

## Phase 0: 盘点与基线 ✅ 已完成
- 建立现状矩阵（§3.4）、模块成熟度评估。
- 已确认执行顺序与算法参数策略。

## Phase 1: 完成 lsl_test 实验区 ✅ 已完成
- 目标: 在不影响主链的前提下，完成设备无关的 EEG 数据处理完整链路。
- 设计约束: 多设备（Enobio/Unicorn/BCI-4）、多格式（EDF + 未来扩展）可扩展，但代码保持简洁。详见 §7.3。
- 分支: `feature/lsl-processing-pipeline`
- 工作项:
  1. 完善 `eeg_processor.py` — 添加 StreamingBandPowerExtractor（滑动窗口 + 增量 PSD），仅依赖 `sample_rate`，设备无关。
  2. 抽取 `FileReader` 接口 — 从现有 `EdfReader` 抽取 Protocol，`EdfFileReader` 作为第一个实现。
  3. 优化 `edf_to_lsl.py` — `push_chunk` 批量推送，从 `StreamInfo` 自动获取 `sample_rate`/`channel_count`（不硬编码设备参数）。
  4. 构建 RawLslAdapter — `pull_chunk → 累积窗口 → compute_band_powers → EegFrame`，通过 LSL StreamInfo 自动适配任意设备的通道数和采样率。
  5. E2E 测试 + 延迟基线 — EDF → LSL → RawLslAdapter → FocusPolicy → speed_intent，采集 p50/p95 数据。
- 产出: 可独立运行的设备无关完整链路 + 延迟基线数据。

## Phase 2: 主架构边界落地
- 目标: 拆分单文件巨石，落地 §10.2 定义的六层架构，并将 Phase 1 的实验成果并入核心。
- 工作项:
  1. 基础架构组建 — 创建 `adapters/`, `processors/`, `policies/` 目录结构。
  2. 数据契约与配置落地 — 抽取 `contracts.py`（本次暂缓重构到三大契约，保留 `EegFrame` 以平滑过渡）与 `device_profiles.py`。
  3. Processor 迁移 — 将 Phase 1 的 `StreamingBandPowerExtractor` 迁移至 `processors/band_power.py`，派生特征迁移至 `processors/enrich.py`。
  4. Policy 迁移 — 提取基础接口及具体策略实现到 `policies/`。
  5. Adapter 迁移 — 将各种数据输入源适配器（含 Phase 1 的 `RawLslAdapter`）分类存入 `adapters/`。
  6. Pipeline 组装 — 新建 `pipeline.py` 统合各模块对外提供一致接口。保留旧版 `eeg_control_pipeline.py` 作为回滚路径（feature flag 控制）。
- 产出: 分层目录 + 现有 34 个测试 + lsl_test 21 个测试全绿。

## Phase 3: lsl_test 合并到主链
- 前置条件: Phase 1 + Phase 2 均完成。
- 工作项:
  1. 将 `eeg_processor.py` 迁移为 `processors/band_power.py`。
  2. 将 RawLslAdapter 迁移为 `adapters/lsl_raw.py`。
  3. 在 `build_adapter()` 工厂中注册新适配器（feature flag 控制）。
  4. 合并门禁验证（§7.4）。
- 产出: 主链支持 raw EEG → DSP → 控制的完整路径。

## Phase 4: 协议与输入源统一治理
- tcp/udp/lsl/file_reader 路由规则收敛至 §9.2 决策表。

## Phase 5: 代码质量与测试体系完善
- 覆盖率提升、性能回归、稳定性压测。

## Phase 6: 默认路径切换与收口
- 指标达标后切换默认实现，保留回滚窗口。
- 标记旧 `eeg_control_pipeline.py` 为 deprecated。

---

## 17. 角色分工

1. 架构负责人
- 决策边界、评审变更、批准切换。

2. 算法工程师
- DSP/特征策略与参数标定。

3. ROS 工程师
- 节点编排、执行器策略、控制稳定性。

4. 平台/后端工程师
- 配置治理、日志指标、发布流程。

5. 测试工程师
- 自动化测试、回归与验收报告。

6. AI Agent
- 按阶段实施代码与测试，提交结果与风险说明。

---

## 18. AI Agent 执行规范

1. 单次 PR 仅覆盖一个子目标，避免混改。
2. 每次提交必须包含:
- 代码
- 测试
- 指标结果
- 风险与回滚说明
3. 若失败，必须输出:
- 根因
- 备选方案
- 对后续阶段影响

完成定义（DoD）:
1. 核心测试通过。
2. 指标达标或有偏差说明。
3. 文档与配置同步。
4. 可灰度、可回滚。

---

## 19. 变更日志

### v2.1（2026-04-24）
1. 新增 §3.4 现状模块成熟度评估，基于代码审查的量化分析。
2. 新增 §7.2 lsl_test 实验区详细现状（已完成模块/测试/待完成工作）。
3. 新增 §7.3 多设备与多格式可扩展性设计（设备矩阵、FileReader 接口、未知因素应对策略）。
4. 新增 §7.4 算法参数与可配置性要求，明确所有 DSP 参数必须可通过 YAML 覆盖。
5. 新增 §7.5 流处理边角情况与性能优化路线，明确尾部窗口丢弃策略和缓冲区零拷贝优化方向。
6. 新增 §10.2 目标目录结构（重构后的文件布局）。
7. 重写 §16 执行计划: 采用「Phase 1 lsl_test → Phase 2 架构重构 → Phase 3 合并」顺序。
8. 确认向后兼容策略: 重构期间保留旧 `eeg_control_pipeline.py` 作为回滚路径。
9. Phase 1 增加 FileReader 接口抽取任务，为未来 g.tec 设备文件格式预留扩展点。

### v2.0（2026-04-24）
1. 文档从“EEG LSL/EDF 专项重构”升级为“项目整体架构与工程化规范”。
2. 新增项目级分层架构、契约治理、目录治理、运维与测试要求。
3. 明确 LSL/EDF 采用“先实验区迭代，后主链合并”的渐进策略。
