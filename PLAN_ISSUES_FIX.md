# Plan: 修复代码审查发现的 19 个问题 + TCP 文件回放功能

> **状态更新**：所有问题（除已知限制外）和功能均已完成并 push。记录附后。

## Context

本次代码审查发现了 2 个 CRITICAL 级别问题（命令注入漏洞、CSV 文件句柄泄漏）、9 个 HIGH 级别问题以及 8 个 MEDIUM 级别问题。此外新增 **TCP 文件回放功能**需求。

## 完成状态

### CRITICAL

| # | 问题 | 状态 | 提交 |
|---|------|------|------|
| 1 | 命令注入漏洞 — `command_runner.py` | ✅ 完成 | `bcb8cc9` |
| 2 | CSV 文件句柄泄漏 — `eeg_control_node.py` | ✅ 完成 | `39081e9` |

### HIGH

| # | 问题 | 状态 | 提交 |
|---|------|------|------|
| 3 | config_store 竞态条件 — `config_store.py` | ✅ 完成 | `bcb8cc9` |
| 4 | 进程管理资源泄漏 — `command_runner.py` | ✅ 完成 | `bcb8cc9` |
| 5 | TCP 缓冲区截断无警告 — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |
| 6 | UDP socket 永不关闭 — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |
| 7 | CSV 每帧 flush → 每 10 帧 flush | ✅ 完成 | `39081e9` |
| 8 | TCP 重连时间戳逻辑错误 — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |

### MEDIUM

| # | 问题 | 状态 | 提交 |
|---|------|------|------|
| 9 | 看门狗加 `_adapter_connected` 标志 — `eeg_control_node.py` | ✅ 完成 | `39081e9` |
| 10 | WebSocket 指数退避 — `main.py` | ✅ 完成 | `bcb8cc9` |
| 11 | 静默吞异常 → logging — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |
| 12 | CORS 起源验证 — `main.py` | ✅ 完成 | `bcb8cc9` |
| 13 | 通道映射负数索引校验 — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |
| 14 | TCP 端口默认值统一为 1234 | ✅ 完成 | `bcb8cc9` |
| 15 | 速度参数范围钳制 — `eeg_control_node.py` | ✅ 完成 | `bcb8cc9` |
| 16 | print → logging — `eeg_control_pipeline.py` | ✅ 完成 | `bcb8cc9` |

### 新功能：TCP 文件回放

| # | 内容 | 状态 | 提交 |
|---|------|------|------|
| 17 | `parse_sod_packet()` 抽取为公开函数 | ✅ 完成 | `bcb8cc9` |
| 18 | `TcpFileAdapter` 类实现 | ✅ 完成 | `bcb8cc9` |
| 19 | `build_adapter()` 支持 `tcp_file` | ✅ 完成 | `bcb8cc9` |
| 20 | argparse 新增 `--file-path` | ✅ 完成 | `bcb8cc9` |
| 21 | ROS 节点支持 `tcp_file` input | ✅ 完成 | `bcb8cc9` |
| 22 | `models.py` 增加 `tcp_file` 和 `file_path` | ✅ 完成 | `bcb8cc9` |
| 23 | `config_store` 持久化 `file_path` | ✅ 完成 | `bcb8cc9` |
| 24 | `/api/files/tcp` 文件列表 API | ✅ 完成 | `bcb8cc9` |
| 25 | 前端 `tcp_file` UI 和 `inputMap` | ✅ 完成 | `bcb8cc9` |
| 26 | launch 命令写入 `file_path` | ✅ 完成 | `bcb8cc9` |
| 27 | `eeg_control_node.params.yaml` 新增 `file_path` | ✅ 完成 | `bcb8cc9` |

### 后续额外修复（copilot 实现后补充）

| # | 修复内容 | 提交 |
|---|---------|------|
| A | `shlex.quote` 恢复（路径含空格保护）— `command_runner.py` | `4ed7aa8` |
| B | `TcpFileAdapter` 文件不存在时抛出 `FileNotFoundError`（含候选路径） | `6af5d11` |
| C | `TcpFileAdapter._load_file()` 相对路径解析增强（repo 根目录 / enobio_recodes 两路径） | `da3b7dc` |
| D | `launch` 新增 `file_path` launch 参数传递 | `da3b7dc` |
| E | WebSocket `Origin` 头校验（两个 WebSocket 端点均加） | `da3b7dc` |
| F | ROS 环境变量缓存（`_load_ros_env()` 避免重复 sourcing） | `da3b7dc` |

### 已知限制（未实现）

| 原编号 | 问题 | 原因 |
|--------|------|------|
| #8 | 未使用 ROS2 LifecycleNode | 改动过大 |
| #17 | Python 脚本作为 ROS2 可执行文件 | 改动过大 |
| #19 | LSL 适配器无测试 | 需单独设计测试用例 |

---

## 验证方法

1. 运行 `pytest thymio_control/test/test_*.py -v` 确保现有测试通过（34 个测试全部通过）
2. 启动 Web GUI 后端确认无启动错误：`cd web_gui/backend && source ../../.venv/bin/activate && python -m app.main`
3. TCP 文件回放验证：在 Web GUI 选择 `tcp_data.txt`，观察 Gazebo 视窗中 Thymio 是否按文件内时间戳实时移动

## 注意事项

- `eeg_control_node.params.yaml` 中 `input: tcp_file`、`file_path: tcp_data.txt` 为用户要求的默认配置。如果所选文件不存在，节点启动时会抛出 `FileNotFoundError`。
- `launch_args.yaml` 中 `run_eeg: true`、`use_teleop: false` 为用户要求的默认行为。
