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

## 5. 注意事项 (Warnings)
- **__file__ 的依赖**：重构时务必使用 `os.path.abspath(os.path.dirname(__file__))` 来构建相对路径，严禁使用 `os.getcwd()`，因为后者依赖于用户的终端启动位置。
- **Git 历史**：建议使用 `git mv` 进行移动，以保留文件的提交历史。
