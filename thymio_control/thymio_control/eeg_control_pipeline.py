#!/usr/bin/env python3
"""EEG 控制管线（短期可落地骨架）。

目标：
- 从 TCP / LSL / mock 输入读取 EEG 指标。
- 统一到标准帧结构，便于后续算法复用。
- 通过可插拔策略输出 speed_intent / steer_intent（范围 [0, 1]）。
- 以 UDP 发送到 ROS2 gaze_control_node 的输入链路。

该文件保持单文件自包含，便于快速迭代实验。
"""

import argparse
import json
import logging
import math
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional, Sequence

try:
    import yaml
except ImportError:
    yaml = None

from thymio_control.enobio_file_reader import EnobioFileReader

# ---------------------------------------------------------------------------
# Multi-device EEG configuration registry
# ---------------------------------------------------------------------------

EEG_DEVICE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "enobio-20": {
        "label": "Enobio 20",
        "n_channels": 20,
        "sample_rate": 500,
        "channel_labels": [
            "Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4",
            "O1", "O2", "F7", "F8", "T7", "T8", "P7", "P8",
            "Fz", "Cz", "Pz", "Oz",
        ],
        "default_lsl_channel_map": {
            "Fp1": 0, "Fp2": 1, "F3": 2, "F4": 3,
            "C3": 4, "C4": 5, "P3": 6, "P4": 7,
            "O1": 8, "O2": 9, "F7": 10, "F8": 11,
            "T7": 12, "T8": 13, "P7": 14, "P8": 15,
            "Fz": 16, "Cz": 17, "Pz": 18, "Oz": 19,
        },
    },
    "unicorn-8": {
        "label": "Unicorn Hybrid Black",
        "n_channels": 8,
        "sample_rate": 250,
        "channel_labels": ["Fz", "C3", "Cz", "C4", "Pz", "PO7", "Oz", "PO8"],
        "default_lsl_channel_map": {
            "Fz": 0, "C3": 1, "Cz": 2, "C4": 3,
            "Pz": 4, "PO7": 5, "Oz": 6, "PO8": 7,
        },
    },
    "unicorn-4": {
        "label": "Unicorn BCI Core-4 Headband",
        "n_channels": 4,
        "sample_rate": 250,
        "channel_labels": ["Fz", "Cz", "Pz", "Oz"],
        "default_lsl_channel_map": {
            "Fz": 0, "Cz": 1, "Pz": 2, "Oz": 3,
        },
    },
}


def get_device_config(device_key: str) -> Dict[str, Any]:
    """Return the device configuration dict for a given device key.

    Raises ValueError if the device key is not recognized.
    """
    key = str(device_key).strip().lower()
    if key not in EEG_DEVICE_CONFIGS:
        valid = ", ".join(sorted(EEG_DEVICE_CONFIGS))
        raise ValueError(f"Unknown EEG device: {device_key!r} (valid: {valid})")
    return EEG_DEVICE_CONFIGS[key]

try:
    from geometry_msgs.msg import Twist  # type: ignore
except ImportError:
    @dataclass
    class _Vector3:
        x: float = 0.0
        y: float = 0.0
        z: float = 0.0

    class Twist:  # type: ignore
        def __init__(self) -> None:
            self.linear = _Vector3()
            self.angular = _Vector3()


@dataclass
class EegFrame:
    """下游逻辑统一使用的 EEG 标准帧。"""

    ts: float
    source: str
    metrics: Dict[str, float]


def clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def safe_div(a: float, b: float, eps: float = 1e-9) -> float:
    return float(a) / float(b + eps)


class BaseAdapter:
    def read_frame(self) -> Optional[EegFrame]:
        raise NotImplementedError


def parse_sod_packet(packet: str) -> Dict[str, float]:
    """解析 SOD...EOD 包，提取序号、特征数、运动值和特征值。可复用于 TcpFileAdapter。"""

    packet = packet.strip()
    if not packet.startswith("SOD") or not packet.endswith("EOD"):
        return {}

    body = packet[3:-3].strip()
    if not body:
        return {}

    parts = [part.strip() for part in body.split(";") if part.strip() != ""]
    if len(parts) < 5:
        return {}

    try:
        packet_no = int(float(parts[0]))
        feature_count = int(float(parts[1]))
        movement = float(parts[2])
    except Exception:
        return {}

    try:
        feature = extract_tcp_feature(packet)
    except (IndexError, ValueError):
        return {}

    expected_len = 5 + feature_count
    if len(parts) < expected_len:
        return {}

    metrics: Dict[str, float] = {
        "packet_no": float(packet_no),
        "feature_count": float(feature_count),
        "movement": movement,
        "feature": feature,
    }

    feature_values = parts[3 : 3 + feature_count]
    for idx, value in enumerate(feature_values, start=1):
        try:
            metrics[f"feature_{idx}"] = float(value)
        except Exception:
            continue

    try:
        metrics["artifact"] = float(parts[3 + feature_count])
    except Exception:
        metrics["artifact"] = 0.0

    try:
        metrics["current_y_unused"] = float(parts[4 + feature_count])
    except Exception:
        metrics["current_y_unused"] = -1.0

    if feature_count == 1 and "feature_1" in metrics:
        metrics["feature_value"] = metrics["feature_1"]

    return metrics


# Backward compatibility alias
def _parse_sod_packet(packet: str) -> Dict[str, float]:
    return parse_sod_packet(packet)


def extract_tcp_feature(packet: str) -> float:
    """从 SOD/TCP 数据包中严格提取第 4 个字段作为 feature。

    该函数用于单元测试和上游协议兼容验证：
    - 只接受完整的 SOD...EOD 包
    - 只提取分隔后的 index 3 字段
    - 字段缺失、越界或不可转换为数值时直接抛出异常
    """

    packet = packet.strip()
    if not packet.startswith("SOD") or not packet.endswith("EOD"):
        raise ValueError("TCP packet must start with SOD and end with EOD")

    body = packet[3:-3].strip()
    if not body:
        raise ValueError("TCP packet payload is empty")

    parts = [part.strip() for part in body.split(";")]
    if len(parts) <= 3:
        raise IndexError("TCP packet does not contain feature field at index 3")

    try:
        return float(parts[3])
    except ValueError as exc:
        raise ValueError(f"TCP feature field at index 3 is not numeric: {parts[3]!r}") from exc


def _clone_twist(twist: Twist) -> Twist:
    cloned = Twist()
    cloned.linear.x = float(getattr(twist.linear, "x", 0.0))
    cloned.linear.y = float(getattr(twist.linear, "y", 0.0))
    cloned.linear.z = float(getattr(twist.linear, "z", 0.0))
    cloned.angular.x = float(getattr(twist.angular, "x", 0.0))
    cloned.angular.y = float(getattr(twist.angular, "y", 0.0))
    cloned.angular.z = float(getattr(twist.angular, "z", 0.0))
    return cloned


def feature_to_twist(
    feature: Optional[float],
    *,
    max_forward_speed: float = 0.2,
    turn_angular_speed: float = 1.2,
    steer_deadzone: float = 0.1,
    last_twist: Optional[Twist] = None,
) -> Twist:
    """把 TCP feature 标量映射为 Twist。

    映射约定：
    - feature 按 movement 同样的离散阈值处理
    - 0.0 < feature < 0.5: 前进
    - 0.5 < feature < 1.0: 后退
    - feature == 1.0: 原地右转
    - 其他值: 停止
    - feature 缺失或不可转换时，优先回退到 last_twist
    """

    try:
        value = float(feature)
    except Exception:
        if last_twist is not None:
            return _clone_twist(last_twist)
        return Twist()

    twist = Twist()

    if 0.0 < value < 0.5:
        twist.linear.x = float(max_forward_speed)
    elif 0.5 < value < 1.0:
        twist.linear.x = float(max_forward_speed) * -0.75
    elif value == 1.0:
        twist.angular.z = float(turn_angular_speed)
    elif value < 0.0:
        pass
    else:
        pass

    return twist


class MockAdapter(BaseAdapter):
    def __init__(self) -> None:
        self.t0 = time.time()

    def read_frame(self) -> Optional[EegFrame]:
        t = time.time() - self.t0
        # 生成平滑的模拟频段数据，用于快速联调。
        alpha = 12.0 + 3.0 * math.sin(0.8 * t)
        theta = 7.0 + 2.0 * math.sin(0.5 * t + 1.2)
        beta = 9.0 + 2.5 * math.sin(1.1 * t + 0.5)
        left_alpha = alpha * (0.95 + 0.08 * math.sin(0.4 * t))
        right_alpha = alpha * (1.05 + 0.08 * math.sin(0.4 * t + 2.2))
        return EegFrame(
            ts=time.time(),
            source="mock",
            metrics={
                "alpha": alpha,
                "theta": theta,
                "beta": beta,
                "left_alpha": left_alpha,
                "right_alpha": right_alpha,
            },
        )


class TcpClientJsonAdapter(BaseAdapter):
    """作为 TCP 客户端连接到外部 EEG 服务，并读取按行分隔的数据。"""

    def __init__(self, host: str, port: int, reconnect_sec: float = 1.0) -> None:
        self._host = host
        self._port = int(port)
        self._reconnect_sec = max(0.1, float(reconnect_sec))
        self._sock: Optional[socket.socket] = None
        self._buf = ""
        self._last_connect_attempt = 0.0

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None
        self._buf = ""

    def _connect_if_needed(self) -> None:
        if self._sock is not None:
            return

        now = time.time()
        if now - self._last_connect_attempt < self._reconnect_sec:
            return

        try:
            sock = socket.create_connection((self._host, self._port), timeout=2.0)
            sock.setblocking(False)
            self._sock = sock
            self._last_connect_attempt = now
            logging.getLogger(__name__).info(f"connected to {self._host}:{self._port}")
        except Exception:
            self._sock = None

    def _extract_all_packets(self) -> list[str]:
        packets: list[str] = []
        while True:
            start = self._buf.find("SOD")
            if start < 0:
                if len(self._buf) > 65536:
                    self._buf = self._buf[-1024:]
                return packets

            if start > 0:
                self._buf = self._buf[start:]

            end = self._buf.find("EOD", 3)
            if end < 0:
                return packets

            # If there's another SOD before this EOD, we should discard the garbage before it.
            next_sod = self._buf.find("SOD", 3, end)
            if next_sod > 0:
                self._buf = self._buf[next_sod:]
                continue

            packets.append(self._buf[: end + 3])
            self._buf = self._buf[end + 3 :]

    def _drain_socket(self) -> bool:
        if self._sock is None:
            return False

        got_data = False
        while True:
            try:
                data = self._sock.recv(4096)
                if not data:
                    logging.getLogger(__name__).info(f"disconnected from {self._host}:{self._port}")
                    self._close_socket()
                    return False
                self._buf += data.decode("utf-8", errors="ignore")
                got_data = True
            except BlockingIOError:
                break
            except OSError:
                self._close_socket()
                return False
        return got_data

    def read_frame(self) -> Optional[EegFrame]:
        self._connect_if_needed()
        if self._sock is None:
            return None

        self._drain_socket()
        packets = self._extract_all_packets()
        if not packets:
            return None

        # 丢弃旧包，仅保留本周期最后一个结构完整且可解析的包
        if len(packets) > 1:
            logging.getLogger(__name__).warning(f"buffer truncation: discarded {len(packets)-1} old packets")
        for packet in reversed(packets):
            metrics = _parse_sod_packet(packet)
            if metrics:
                return EegFrame(ts=time.time(), source="tcp_client", metrics=metrics)
        return None


class LslAdapter(BaseAdapter):
    """从 LSL 流读取 EEG 指标。

    适配器假设样本为数值数组，并按索引映射通道。
    通道映射示例：
      "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4"
    """

    def __init__(self, stream_type: str, timeout: float, channel_map: Dict[str, int]) -> None:
        try:
            from pylsl import StreamInlet, resolve_byprop  # type: ignore
        except ImportError as e:
            raise RuntimeError("pylsl is required for LSL mode") from e

        streams = resolve_byprop("type", stream_type, timeout=timeout)
        if not streams:
            raise RuntimeError(f"No LSL stream found for type={stream_type}")

        self._inlet = StreamInlet(streams[0], max_chunklen=32)
        self._channel_map = channel_map
        info = self._inlet.info()
        logging.getLogger(__name__).info(
            f"connected stream name={info.name()} type={info.type()} channels={info.channel_count()}"
        )

    def read_frame(self) -> Optional[EegFrame]:
        sample, _ = self._inlet.pull_sample(timeout=0.05)
        if sample is None:
            return None

        arr = [float(v) for v in sample]
        metrics: Dict[str, float] = {}
        for name, idx in self._channel_map.items():
            if idx < 0 or idx >= len(arr):
                raise ValueError(f"LSL channel '{name}' index {idx} out of bounds (array length {len(arr)})")
            metrics[name] = arr[idx]

        if not metrics:
            return None

        return EegFrame(ts=time.time(), source="lsl", metrics=metrics)


class TcpFileAdapter(BaseAdapter):
    """从 TCP 数据文件回放，按时间戳控制节奏。
    
    文件格式：每行 "timestamp SOD...EOD" 或 "timestamp SOC...EOC"
    """

    def __init__(self, file_path: str) -> None:
        self._file_path = file_path
        self._lines: list[str] = []
        self._index = 0
        self._last_ts: float = 0.0
        self._done = False
        self._load_file()

    def _load_file(self) -> None:
        path = Path(self._file_path).expanduser()
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            candidate_repo = (repo_root / path).resolve()
            candidate_recode = (repo_root / "enobio_recodes" / path).resolve()
            if candidate_repo.exists():
                path = candidate_repo
            elif candidate_recode.exists():
                path = candidate_recode
            else:
                raise FileNotFoundError(
                    f"TCP replay file not found: '{self._file_path}' "
                    f"(tried {candidate_repo} and {candidate_recode})"
                )

        with open(path, "r", encoding="utf-8") as f:
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

            packet = payload[start:end + 3]  # 包含 SOD...EOD
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


def enrich_features(metrics: Dict[str, float]) -> Dict[str, float]:
    """补充通用派生特征，降低策略实现复杂度。"""

    f = dict(metrics)
    alpha = f.get("alpha", 0.0)
    theta = f.get("theta", 0.0)
    beta = f.get("beta", 0.0)
    left_alpha = f.get("left_alpha", alpha * 0.5)
    right_alpha = f.get("right_alpha", alpha * 0.5)

    f["theta_beta"] = safe_div(theta, beta)
    f["beta_alpha"] = safe_div(beta, alpha)
    f["beta_alpha_theta"] = safe_div(beta, alpha + theta)
    f["alpha_asym"] = safe_div(right_alpha - left_alpha, right_alpha + left_alpha)
    return f


def _sequence_mean(values: Any) -> float:
    try:
        iterator = iter(values)
    except TypeError:
        return float(values)

    total = 0.0
    count = 0
    for value in iterator:
        total += float(value)
        count += 1

    if count == 0:
        raise ValueError("cannot compute mean of an empty sequence")

    return total / count


def _select_channels(raw_data: Any, selected_channels: Sequence[int]) -> Any:
    if not selected_channels:
        raise ValueError("selected_channels must not be empty")

    total_channels = len(raw_data)
    for index in selected_channels:
        if index < 0 or index >= total_channels:
            raise IndexError(f"selected channel index out of bounds: {index}")

    try:
        return raw_data[list(selected_channels)]
    except Exception:
        return [raw_data[index] for index in selected_channels]


def _theta_beta_ratio_algorithm(filtered_data: Any) -> float:
    if len(filtered_data) < 2:
        raise ValueError("theta_beta_ratio requires at least two selected channels")

    theta_channel = filtered_data[0]
    beta_channel = filtered_data[1]
    return safe_div(_sequence_mean(theta_channel), _sequence_mean(beta_channel))


PIPELINE_ALGORITHMS: Dict[str, Callable[[Any], float]] = {
    "theta_beta_ratio": _theta_beta_ratio_algorithm,
}


def compute_pipeline_feature(raw_data: Any, selected_channels: Sequence[int], algorithm_name: str) -> float:
    """按配置切片通道并动态执行特征算法。"""

    filtered_data = _select_channels(raw_data, selected_channels)
    algorithm = PIPELINE_ALGORITHMS.get(str(algorithm_name))
    if algorithm is None:
        raise ValueError(f"Unsupported pipeline algorithm: {algorithm_name}")
    return float(algorithm(filtered_data))


class OfflineFilePipeline:
    """End-to-end pipeline for offline Enobio recordings.

    It connects the file reader, dynamic feature pipeline, and feature-to-Twist
    mapping in a single deterministic runner used by integration tests.
    """

    def __init__(
        self,
        *,
        info_path: str,
        easy_path: str,
        pipeline_config: Dict[str, Any],
        max_forward_speed: float = 0.2,
        turn_angular_speed: float = 1.2,
        steer_deadzone: float = 0.1,
    ) -> None:
        source_type = str(pipeline_config.get("source_type", "")).strip()
        if source_type != "file":
            raise ValueError("OfflineFilePipeline requires pipeline_config.source_type == 'file'")

        self.reader = EnobioFileReader(info_path, easy_path)
        self.selected_channels = list(pipeline_config.get("selected_channels", []))
        self.algorithm_name = str(pipeline_config.get("algorithm", "")).strip()
        self.max_forward_speed = float(max_forward_speed)
        self.turn_angular_speed = float(turn_angular_speed)
        self.steer_deadzone = float(steer_deadzone)

    def iter_twists(self, *, limit: Optional[int] = None) -> Iterator[Twist]:
        metadata = self.reader.read_info()
        samples = self.reader.read_easy_samples()

        produced = 0
        for sample in samples:
            if len(sample) < metadata.channels:
                raise ValueError(
                    f"Enobio sample has {len(sample)} values but metadata declares {metadata.channels} channels"
                )

            channel_major_data = [[sample[index]] for index in range(metadata.channels)]
            feature = compute_pipeline_feature(channel_major_data, self.selected_channels, self.algorithm_name)
            twist = feature_to_twist(
                feature,
                max_forward_speed=self.max_forward_speed,
                turn_angular_speed=self.turn_angular_speed,
                steer_deadzone=self.steer_deadzone,
            )
            yield twist

            produced += 1
            if limit is not None and produced >= limit:
                break


class Policy:
    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        raise NotImplementedError


class FocusPolicy(Policy):
    """将专注相关分数映射为速度，将 alpha 非对称映射为转向。

    输出语义：
    - speed_intent 越大，前进意图越强
    - steer_intent < 0.5 偏左，> 0.5 偏右
    """

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        focus = features.get("beta_alpha_theta", 0.0)
        # 比值范围因设备与采集设置而异，这里用可调的粗归一化。
        focus_norm = clip01((focus - 0.15) / 0.85)

        asym = features.get("alpha_asym", 0.0)
        steer_intent = clip01(0.5 + 1.1 * asym)
        speed_intent = clip01(focus_norm)
        return {"speed_intent": speed_intent, "steer_intent": steer_intent}


class ThetaBetaPolicy(Policy):
    """使用 theta/beta 比值控制速度，使用 alpha 非对称控制转向。"""

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        ratio = features.get("theta_beta", 1.0)
        # 比值越高通常代表注意力越弱，对应更慢（speed_intent 更低）。
        speed_intent = clip01(1.0 - (ratio - 0.5) / 2.0)
        steer_intent = clip01(0.5 + 1.1 * features.get("alpha_asym", 0.0))
        return {"speed_intent": speed_intent, "steer_intent": steer_intent}


POLICIES = {
    "focus": FocusPolicy,
    "theta_beta": ThetaBetaPolicy,
}


def parse_channel_map(text: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if isinstance(text, dict):
        for k, v in text.items():
            idx = int(v)
            if idx < 0:
                raise ValueError(f"channel map index must be non-negative: {k}={idx}")
            out[str(k)] = idx
        return out
    if not text:
        return out
    for item in text.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        idx = int(v.strip())
        if idx < 0:
            raise ValueError(f"channel map index must be non-negative: {k}={idx}")
        out[k.strip()] = idx
    return out


def load_yaml_config(path: str) -> Dict[str, Any]:
    if not path:
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML is required for --config. Install with: pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f) or {}
    if not isinstance(obj, dict):
        raise RuntimeError("Config root must be a mapping")
    return obj


def extract_pipeline_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    pipeline_cfg = cfg.get("pipeline_config") if isinstance(cfg, dict) else None
    if not isinstance(pipeline_cfg, dict):
        pipeline_cfg = {}

    selected_channels = pipeline_cfg.get("selected_channels")
    if not isinstance(selected_channels, list) or not selected_channels:
        selected_channels = [0, 1, 2]

    try:
        selected_channels = [int(index) for index in selected_channels]
    except Exception:
        selected_channels = [0, 1, 2]

    return {
        "source_type": str(pipeline_cfg.get("source_type", "tcp_client")).strip() or "tcp_client",
        "selected_channels": selected_channels,
        "algorithm": str(pipeline_cfg.get("algorithm", "theta_beta_ratio")).strip() or "theta_beta_ratio",
        "info_path": str(pipeline_cfg.get("info_path", "")).strip(),
        "easy_path": str(pipeline_cfg.get("easy_path", "")).strip(),
        "realtime": bool(pipeline_cfg.get("realtime", False)),
        "eeg_device": str(pipeline_cfg.get("eeg_device", "enobio-20")).strip() or "enobio-20",
    }


def resolve_pipeline_file_paths(pipeline_config: Dict[str, Any], config_path: str = "") -> tuple[str, str]:
    repo_root = Path(__file__).resolve().parents[2]
    config_dir = Path(config_path).resolve().parent if config_path else repo_root
    default_info = repo_root / "enobio_recodes" / "20260330123659_Patient01.info"
    default_easy = repo_root / "enobio_recodes" / "20260330123659_Patient01.easy"

    def _resolve(raw_path: str, default_path: Path) -> str:
        candidate = Path(raw_path).expanduser() if raw_path else default_path
        if not candidate.is_absolute():
            candidate = config_dir / candidate
        return str(candidate.resolve())

    return _resolve(str(pipeline_config.get("info_path", "")), default_info), _resolve(
        str(pipeline_config.get("easy_path", "")),
        default_easy,
    )


def flatten_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """把分层配置展开成 argparse 同名键。"""

    flat = dict(cfg)
    sections = {
        "adapter": ["input", "tcp_host", "tcp_port", "lsl_stream_type", "lsl_timeout", "lsl_channel_map"],
        "policy_cfg": ["policy"],
        "output": ["udp_host", "udp_port", "hz", "verbose"],
        "pipeline_config": ["eeg_device"],
    }
    for sec, keys in sections.items():
        sub = cfg.get(sec)
        if isinstance(sub, dict):
            for k in keys:
                if k in sub:
                    flat[k] = sub[k]
    return flat


def apply_config_to_args(args: argparse.Namespace, parser: argparse.ArgumentParser, cfg: Dict[str, Any]) -> argparse.Namespace:
    """将配置写入参数；命令行显式值优先于配置。"""

    defaults = {
        action.dest: action.default
        for action in parser._actions
        if action.dest != "help"
    }
    flat = flatten_config(cfg)
    for k, v in flat.items():
        if not hasattr(args, k):
            continue
        current = getattr(args, k)
        if current == defaults.get(k):
            setattr(args, k, v)
    return args


class KeyboardAdapter(BaseAdapter):
    """通过键盘按键模拟控制意图。
    W/S: 增减速度意图, A/D: 增减转向意图, Space: 归零。
    """
    def __init__(self) -> None:
        self.metrics = {"alpha": 0.5, "theta": 0.5, "beta": 0.5, "left_alpha": 0.5, "right_alpha": 0.5}
        self.speed_intent = 0.5
        self.steer_intent = 0.5
        logging.getLogger(__name__).info("Initialized. Use W/S/A/D to simulate EEG intent, Space to reset.")

    def read_frame(self) -> Optional[EegFrame]:
        return EegFrame(
            ts=time.time(),
            source="keyboard",
            metrics=self.metrics
        )


def build_adapter(args: Any) -> BaseAdapter:
    if args.input == "mock":
        return MockAdapter()
    if args.input == "keyboard":
        return KeyboardAdapter()
    if args.input == "tcp_client":
        return TcpClientJsonAdapter(args.tcp_host, args.tcp_port)
    if args.input == "tcp_file":
        file_path = getattr(args, "file_path", "")
        if not file_path:
            raise RuntimeError("tcp_file mode requires --file-path")
        return TcpFileAdapter(file_path)
    if args.input == "lsl":
        channel_map = parse_channel_map(args.lsl_channel_map)
        if not channel_map:
            # Auto-populate from device defaults
            eeg_device = getattr(args, "eeg_device", "enobio-20")
            try:
                dev_cfg = get_device_config(eeg_device)
                channel_map = dict(dev_cfg["default_lsl_channel_map"])
                logging.getLogger(__name__).info(
                    f"Using default LSL channel map for {dev_cfg['label']} ({len(channel_map)} channels)"
                )
            except ValueError as e:
                raise RuntimeError(
                    "LSL mode requires --lsl-channel-map or a valid --eeg-device"
                ) from e
        return LslAdapter(args.lsl_stream_type, args.lsl_timeout, channel_map)
    raise RuntimeError(f"Unsupported input mode: {args.input}")


def run_offline_file_pipeline(args: argparse.Namespace, pipeline_config: Dict[str, Any], config_path: str = "") -> int:
    info_path, easy_path = resolve_pipeline_file_paths(pipeline_config, config_path)
    pipeline = OfflineFilePipeline(
        info_path=info_path,
        easy_path=easy_path,
        pipeline_config=pipeline_config,
        max_forward_speed=float(getattr(args, "max_forward_speed", 0.2)),
        turn_angular_speed=float(getattr(args, "turn_angular_speed", 1.2)),
        steer_deadzone=float(getattr(args, "steer_deadzone", 0.1)),
    )

    for twist in pipeline.iter_twists():
        if getattr(args, "verbose", False):
            print(f"[offline-file] linear_x={twist.linear.x:.3f} angular_z={twist.angular.z:.3f}")
        else:
            print(json.dumps({"linear_x": twist.linear.x, "angular_z": twist.angular.z}))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="EEG -> UDP intent pipeline for Thymio")
    parser.add_argument("--config", default="", help="Path to YAML config file")
    parser.add_argument("--input", choices=["mock", "tcp_client", "tcp_file", "lsl", "file"], default="mock")
    parser.add_argument("--policy", choices=sorted(POLICIES.keys()), default="focus")
    parser.add_argument(
        "--eeg-device",
        choices=sorted(EEG_DEVICE_CONFIGS.keys()),
        default="enobio-20",
        help="EEG device type (default: enobio-20)",
    )

    parser.add_argument("--tcp-host", default="0.0.0.0", help="TCP client connect host")
    parser.add_argument("--tcp-port", type=int, default=6001, help="TCP client connect port")
    parser.add_argument("--file-path", default="", help="Path to TCP data file for replay")

    parser.add_argument("--lsl-stream-type", default="EEG", help="LSL stream type")
    parser.add_argument("--lsl-timeout", type=float, default=8.0, help="LSL discovery timeout")
    parser.add_argument(
        "--lsl-channel-map",
        default="",
        help="Channel map, e.g. alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4",
    )

    parser.add_argument("--udp-host", default="127.0.0.1", help="UDP target host for intent packets")
    parser.add_argument("--udp-port", type=int, default=5005, help="UDP target port")
    parser.add_argument("--hz", type=float, default=20.0, help="Output max rate")
    parser.add_argument("--verbose", action="store_true", help="Print feature and output details")
    args = parser.parse_args()
    cfg: Dict[str, Any] = {}

    if args.config:
        if yaml is None:
            logging.getLogger(__name__).error("PyYAML is required to load config")
            return 1
        try:
            cfg = load_yaml_config(args.config)
            args = apply_config_to_args(args, parser, cfg)
        except Exception as e:
            logging.getLogger(__name__).error(f"cannot load config: {e}")
            return 1

    pipeline_config = extract_pipeline_config(cfg)
    # Propagate eeg_device from config to args (command-line already took priority via apply_config_to_args)
    if not getattr(args, "eeg_device", None) or args.eeg_device == "enobio-20":
        args.eeg_device = pipeline_config.get("eeg_device", "enobio-20")

    if args.input == "file" or pipeline_config.get("source_type") == "file":
        try:
            return run_offline_file_pipeline(args, pipeline_config, args.config)
        except Exception as e:
            logging.getLogger(__name__).error(f"cannot run offline file pipeline: {e}")
            return 1

    adapter = build_adapter(args)
    policy = POLICIES[args.policy]()

    target = (args.udp_host, int(args.udp_port))
    hz = float(args.hz)
    period = 1.0 / max(1.0, hz)
    is_polling_adapter = isinstance(adapter, (MockAdapter, KeyboardAdapter))

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            while True:
                frame = adapter.read_frame()
                if frame is not None:
                    feats = enrich_features(frame.metrics)
                    intents = policy.compute_intents(feats)
                    payload = json.dumps(intents).encode()
                    sock.sendto(payload, target)
                    if args.verbose:
                        logging.getLogger(__name__).info(f"sent {intents}")
                    
                    if is_polling_adapter:
                        time.sleep(period)
                        continue

                if not is_polling_adapter:
                    # Polling interval of 2ms gives <2ms delay for network adapters
                    time.sleep(0.002)
        except KeyboardInterrupt:
            pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
