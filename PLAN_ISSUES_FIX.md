# Plan: 修复代码审查发现的 19 个问题 + TCP 文件回放功能

## Context

本次代码审查发现了 2 个 CRITICAL 级别问题（命令注入漏洞、CSV 文件句柄泄漏）、9 个 HIGH 级别问题以及 8 个 MEDIUM 级别问题。这些问题涉及安全漏洞（命令注入）、数据完整性风险（CSV 泄漏、缓冲区截断）、资源管理（socket/进程泄漏）、代码健壮性（静默吞异常、无参数校验）等多个方面。

此外，新增 **TCP 文件回放功能**需求：用户可在 Web GUI 选择 `tcp_data.txt` 文件，在 Gazebo 视窗中实时回放 Thymio 移动。

## 实施顺序

### CRITICAL（优先修复）

**1. 命令注入漏洞 — `web_gui/backend/app/command_runner.py`**
- 将 `_build_launch_command()` 改为返回 `list[str]` 而非字符串
- `start_system()` 改为直接传列表给 `_spawn_ros_command()`
- `_spawn_ros_command()` 改用 `subprocess.run()` 而非 `bash -lc` 字符串执行

**2. CSV 文件句柄泄漏 — `thymio_control/scripts/eeg_control_node.py`**
- `_close_csv()` 异常改为 `self.get_logger().error()` 记录
- `main()` 中 `try/finally` 顺序改为：先 `_close_csv()` 再 `destroy_node()`
- 添加 `_csv_flush_counter` 和 `_csv_flush_every_n = 10` 实例变量

---

### HIGH（其次修复）

**3. config_store 竞态条件 — `web_gui/backend/app/config_store.py`**
- `patch_config()` 中锁需覆盖 `_persist_config()` 调用

**4. 进程管理资源泄漏 — `command_runner.py`**
- `_stop_runtime_processes()` 改用 `process.wait(timeout=2.0)` 而非 `poll()` + `killpg()` 分离调用

**5. TCP 缓冲区截断无警告 — `thymio_control/thymio_control/eeg_control_pipeline.py`**
- 截断时使用 `logging.getLogger(__name__).warning()` 记录（**注意**：`TcpClientJsonAdapter` 不是 ROS 节点，无 `self.get_logger()`，统一用 `logging` 模块）

**6. UDP socket 永不关闭 — `eeg_control_pipeline.py`**
- 用 `with socket.socket(...) as sock:` 上下文管理器包裹

**7. CSV 每次写入都 flush — `eeg_control_node.py`**
- 三个 flush 位置改为每 10 帧 flush 一次

**8. TCP 重连时间戳逻辑错误 — `eeg_control_pipeline.py`**
- `_last_connect_attempt = now` 移到 `try` 块成功分支内（连接建立后）

---

### MEDIUM（最后修复）

**9. 看门狗误触发停车 — `eeg_control_node.py`**
- 添加 `_adapter_connected` 标志，只在标志为 True 时触发停车

**10. WebSocket 重连无退避 — `web_gui/backend/app/main.py`**
- 实现指数退避 `backoff = min(backoff * 2, 30.0)`

**11. 静默吞异常 — `eeg_control_pipeline.py`**
- 改为 `logging.getLogger(__name__)` 记录异常（**注意**：统一用 `logging` 模块，不是 `get_logger()`）

**12. CORS 起源无验证 — `main.py`**
- 添加 `_validate_origin()` 校验 http/https 前缀

**13. 通道映射接受负数索引 — `eeg_control_pipeline.py`**
- `parse_channel_map()` 中添加 `if idx < 0: raise ValueError(...)`

**14. TCP 端口默认值不一致**
- `experiment_config.yaml` 的 `tcp_port` 从 `6001` 改为 `1234`（与 `eeg_control_node.params.yaml` 一致）

**15. 速度参数无校验 — `eeg_control_node.py`**
- 添加范围钳制：`max_forward_speed = max(0.0, min(1.0, ...))`

**16. print 代替 logging — `eeg_control_pipeline.py`**
- 替换两处 `print()` 为 `logging.getLogger(__name__).info()`

---

### 新功能：TCP 文件回放

**实现思路概述：**

`tcp_data.txt` 每行格式为 `timestamp SOC/SOD...EOC/EOD`。数据帧以 `SOD` 开头、`EOD` 结尾，控制帧以 `SOC` 开头、`EOC` 结尾。播放时按文件中相邻行的时间戳差控制 sleep 时长，模拟实时数据流。

**17. 抽取解析函数 — `eeg_control_pipeline.py`**

将 `TcpClientJsonAdapter._parse_sod_packet()` 提取为模块级公开函数 `parse_sod_packet(data: str) -> dict`，供 `TcpFileAdapter` 复用。

```python
def parse_sod_packet(data: str) -> dict:
    """解析 SOD...EOD 数据帧，返回 metrics 字典。"""
    # 原有 _parse_sod_packet 逻辑移至此
```

**18. 新增 `TcpFileAdapter` — `eeg_control_pipeline.py`**

```python
class TcpFileAdapter(BaseAdapter):
    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._lines: list[str] = []
        self._index = 0
        self._last_ts: float = 0.0
        self._done = False
        self._load_file()

    def _load_file(self) -> None:
        with open(self._file_path, "r", encoding="utf-8") as f:
            self._lines = f.readlines()

    def read_frame(self) -> Optional[EegFrame]:
        if self._done:
            return None

        while self._index < len(self._lines):
            line = self._lines[self._index].strip()
            self._index += 1
            if not line:
                continue

            # 提取行首时间戳（Unix 时间戳，秒）
            parts = line.split(" ", 1)
            if len(parts) < 2:
                continue
            try:
                ts = float(parts[0])
            except ValueError:
                continue

            payload = parts[1]

            # 过滤 SOC/EOC 控制帧，只处理 SOD/EOD 数据帧
            if "SOD" not in payload or "EOD" not in payload:
                continue

            start = payload.find("SOD")
            end = payload.find("EOD")
            if start < 0 or end < 0 or end <= start:
                continue

            packet = payload[start + 3:end]  # 去掉 "SOD"
            metrics = parse_sod_packet(packet)
            if not metrics:
                continue

            # 按时间戳差控制播放节奏
            if self._last_ts > 0:
                sleep_sec = ts - self._last_ts
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

            self._last_ts = ts
            return EegFrame(ts=time.time(), source="tcp_file", metrics=metrics)

        self._done = True
        return None
```

**19. `build_adapter()` 工厂支持 tcp_file — `eeg_control_pipeline.py`**

在 `build_adapter()` 中新增分支：
```python
if args.input == "tcp_file":
    return TcpFileAdapter(args.file_path)
```

**注意**：需同时在 argparse 部分新增 `--file-path` 参数（见下方）。

**20. argparse 新增 `--file-path` — `eeg_control_pipeline.py`**

在 `add_argument` 部分添加：
```python
parser.add_argument("--file-path", type=str, default="", dest="file_path")
```

**21. ROS 节点支持 tcp_file input — `thymio_control/scripts/eeg_control_node.py`**

- `declare_parameter` 添加 `file_path`，类型 `str`，默认 `""`
- 当 `input == "tcp_file"` 时使用 `TcpFileAdapter(file_path)`

```python
self.declare_parameter("file_path", "")
# ...
file_path = self.get_parameter("file_path").value
if input_mode == "tcp_file":
    from thymio_control.eeg_control_pipeline import TcpFileAdapter
    self.adapter = TcpFileAdapter(file_path)
```

**22. Web GUI 配置支持 tcp_file — `web_gui/backend/app/models.py`**

- `EegConfig.input` 的 `Literal` 类型增加 `"tcp_file"` 选项
- `EegConfig` 增加 `file_path: str = ""` 字段

```python
input: Literal["mock", "tcp_client", "lsl", "file", "tcp_file"] = "mock"
file_path: str = ""
```

**23. config_store 持久化 file_path — `web_gui/backend/app/config_store.py`**

- `_persist_config()` 中将 `cfg.eeg.file_path` 写入 `eeg_control_node.params.yaml` 的 `file_path` 参数
- 读取时从 `ros_params` 取回 `file_path` 填充到 `cfg.eeg.file_path`

**24. 文件列表 API — `web_gui/backend/app/main.py`**

新增端点：
```python
@app.get("/api/files/tcp")
async def list_tcp_files():
    """返回 enobio_recodes/ 目录下所有 .txt 文件列表。"""
    txt_files = [
        f.name for f in Path("enobio_recodes").iterdir()
        if f.is_file() and f.suffix == ".txt"
    ]
    return {"files": txt_files}
```

**25. Web GUI 前端文件选择 UI — `web_gui/frontend/src/App.jsx`**

- `inputMap` 增加 `tcp_file: "tcp_file"` 映射
- 在现有 inputMode 下拉框中，当选择 `tcp_file` 时，显示一个文件路径输入框（或下拉列表，调用 `/api/files/tcp` 获取可用文件）
- `buildPatch()` 中当 `inputMode === "tcp_file"` 时，patch 包含 `eeg.input: "tcp_file"` 和 `eeg.file_path`
- 路径输入框初始值来自 `configEnvelope.source_files`（如有）

**26. file_path 写入 launch 命令 — `web_gui/backend/app/command_runner.py`**

`_build_launch_command()` 返回的命令列表中，当 `cfg.eeg.input == "tcp_file"` 时，需要将 `file_path` 传递给 ROS 节点。方式：在 launch 命令中添加 `file_path:=/absolute/path/to/file.txt` 参数。

```python
if cfg.eeg.input == "tcp_file" and cfg.eeg.file_path:
    cmd.append(f"file_path:={cfg.eeg.file_path}")
```

**27. eeg_control_node.params.yaml 新增 file_path 参数**

```yaml
file_path: ''
```

---

## 关键文件

| 文件 | 涉及问题/功能 |
|------|-------------|
| `web_gui/backend/app/command_runner.py` | #1, #4, #26 |
| `thymio_control/scripts/eeg_control_node.py` | #2, #7, #9, #15, #21, #27 |
| `web_gui/backend/app/config_store.py` | #3, #23 |
| `thymio_control/thymio_control/eeg_control_pipeline.py` | #5, #6, #8, #11, #13, #16, #17, #18, #19, #20 |
| `web_gui/backend/app/main.py` | #10, #12, #24 |
| `thymio_control/config/experiment_config.yaml` | #14 |
| `web_gui/backend/app/models.py` | #22 |
| `web_gui/frontend/src/App.jsx` | #25 |

## 跳过的问题（已知限制）

- **#8（原编号）**: 未使用 ROS2 LifecycleNode — 改动过大，文档记录为已知限制
- **#17（原编号）**: Python 脚本作为 ROS2 可执行文件 — 改动过大，文档记录为已知限制
- **#19（原编号）**: LSL 适配器无测试 — 需要单独设计测试用例

## 验证方法

1. 运行 `pytest thymio_control/test/test_*.py -v` 确保现有测试通过
2. 手动检查关键代码路径确认修复正确
3. 启动 Web GUI 后端确认无启动错误：`cd web_gui/backend && source ../../.venv/bin/activate && python -m app.main`
4. TCP 文件回放验证：在 Web GUI 选择 `tcp_data.txt`，观察 Gazebo 视窗中 Thymio 是否按文件内时间戳实时移动
