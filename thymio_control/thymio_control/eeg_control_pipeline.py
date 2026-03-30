#!/usr/bin/env python3
"""EEG 控制管线（短期可落地骨架）。

目标：
- 从 TCP / LSL / mock 输入读取 EEG 指标。
- 统一到标准帧结构，便于后续算法复用。
- 通过可插拔策略输出 speed_intent / steer_intent（范围 [0, 1]）。
- 以 UDP 发送到现有 thymio_ros.py 的 gaze 输入链路。

该文件保持单文件自包含，便于快速迭代实验。
"""

import argparse
import json
import math
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:
    yaml = None


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


def _parse_sod_packet(packet: str) -> Dict[str, float]:
    """解析 SOD...EOD 包，提取序号、特征数、运动值和特征值。"""

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

    expected_len = 5 + feature_count
    if len(parts) < expected_len:
        return {}

    metrics: Dict[str, float] = {
        "packet_no": float(packet_no),
        "feature_count": float(feature_count),
        "movement": movement,
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


class TcpJsonAdapter(BaseAdapter):
    """从单个 TCP 客户端读取按行分隔的 JSON 帧。

    字段可扩展，但至少需要一个数值型 EEG 指标。
    典型载荷示例：
      {"alpha": 10.2, "theta": 6.3, "beta": 8.7, "left_alpha": 4.8, "right_alpha": 5.4}
    """

    def __init__(self, host: str, port: int) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(1)
        self._srv.settimeout(0.3)

        self._conn = None
        self._addr = None
        self._buf = ""

    def _accept_if_needed(self) -> None:
        if self._conn is not None:
            return
        try:
            conn, addr = self._srv.accept()
            conn.settimeout(0.1)
            self._conn = conn
            self._addr = addr
            print(f"[tcp] client connected: {addr}")
        except socket.timeout:
            pass

    def read_frame(self) -> Optional[EegFrame]:
        self._accept_if_needed()
        if self._conn is None:
            return None

        try:
            data = self._conn.recv(4096)
            if not data:
                print("[tcp] client disconnected")
                self._conn.close()
                self._conn = None
                self._addr = None
                self._buf = ""
                return None
            self._buf += data.decode("utf-8", errors="ignore")
        except socket.timeout:
            return None
        except OSError:
            self._conn = None
            self._addr = None
            self._buf = ""
            return None

        if "\n" not in self._buf:
            return None

        line, self._buf = self._buf.split("\n", 1)
        line = line.strip()
        if not line:
            return None

        try:
            obj = json.loads(line)
            metrics = {k: float(v) for k, v in obj.items() if isinstance(v, (int, float))}
        except Exception:
            return None

        if not metrics:
            return None

        return EegFrame(ts=time.time(), source="tcp", metrics=metrics)


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

        self._last_connect_attempt = now
        try:
            sock = socket.create_connection((self._host, self._port), timeout=2.0)
            sock.settimeout(0.2)
            self._sock = sock
            print(f"[tcp-client] connected to {self._host}:{self._port}")
        except Exception:
            self._sock = None

    def _extract_packet(self) -> Optional[str]:
        start = self._buf.find("SOD")
        if start < 0:
            if len(self._buf) > 4096:
                self._buf = self._buf[-128:]
            return None

        end = self._buf.find("EOD", start)
        if end < 0:
            if start > 0:
                self._buf = self._buf[start:]
            return None

        packet = self._buf[start : end + 3]
        self._buf = self._buf[end + 3 :]
        return packet

    def read_frame(self) -> Optional[EegFrame]:
        self._connect_if_needed()
        if self._sock is None:
            return None

        try:
            data = self._sock.recv(4096)
            if not data:
                print(f"[tcp-client] disconnected from {self._host}:{self._port}")
                self._close_socket()
                return None
            self._buf += data.decode("utf-8", errors="ignore")
        except socket.timeout:
            return None
        except OSError:
            self._close_socket()
            return None

        packet = self._extract_packet()
        if packet is None:
            return None

        metrics = _parse_sod_packet(packet)
        if not metrics:
            return None

        return EegFrame(ts=time.time(), source="tcp_client", metrics=metrics)


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
        print(
            f"[lsl] connected stream name={info.name()} type={info.type()} channels={info.channel_count()}"
        )

    def read_frame(self) -> Optional[EegFrame]:
        sample, _ = self._inlet.pull_sample(timeout=0.05)
        if sample is None:
            return None

        arr = [float(v) for v in sample]
        metrics: Dict[str, float] = {}
        for name, idx in self._channel_map.items():
            if 0 <= idx < len(arr):
                metrics[name] = arr[idx]

        if not metrics:
            return None

        return EegFrame(ts=time.time(), source="lsl", metrics=metrics)


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


class Policy:
    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        raise NotImplementedError


class FocusPolicy(Policy):
    """将专注相关分数映射为速度，将 alpha 非对称映射为转向。

    输出语义与现有 thymio_ros.py 的 gaze 逻辑保持一致：
    - y 越低：越偏向前进
    - y 越高：越偏向减速/停止/后退区间
    - x < 0.3 左转，x > 0.7 右转
    """

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        focus = features.get("beta_alpha_theta", 0.0)
        # 比值范围因设备与采集设置而异，这里用可调的粗归一化。
        focus_norm = clip01((focus - 0.15) / 0.85)

        asym = features.get("alpha_asym", 0.0)
        steer_intent = clip01(0.5 + 1.1 * asym)
        speed_intent = clip01(1.0 - focus_norm)
        return {"speed_intent": speed_intent, "steer_intent": steer_intent}


class ThetaBetaPolicy(Policy):
    """使用 theta/beta 比值控制速度，使用 alpha 非对称控制转向。"""

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        ratio = features.get("theta_beta", 1.0)
        # 比值越高通常代表注意力越弱，对应更慢（speed_intent 更低）。
        speed_intent = clip01(1.0 - (ratio - 0.5) / 2.0)
        steer_intent = clip01(0.5 + 1.1 * features.get("alpha_asym", 0.0))
        return {"speed_intent": speed_intent, "steer_intent": steer_intent}


def with_legacy_xy(intents: Dict[str, float]) -> Dict[str, float]:
    """附加旧字段 x/y，保证旧链路可继续使用。"""

    speed_intent = clip01(float(intents.get("speed_intent", 0.5)))
    steer_intent = clip01(float(intents.get("steer_intent", 0.5)))
    out = dict(intents)
    out["speed_intent"] = speed_intent
    out["steer_intent"] = steer_intent
    out["x"] = steer_intent
    # 旧链路中 y 越小速度越快，因此与 speed_intent 方向相反。
    out["y"] = clip01(1.0 - speed_intent)
    return out


POLICIES = {
    "focus": FocusPolicy,
    "theta_beta": ThetaBetaPolicy,
}


def parse_channel_map(text: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if isinstance(text, dict):
        for k, v in text.items():
            out[str(k)] = int(v)
        return out
    if not text:
        return out
    for item in text.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        out[k.strip()] = int(v.strip())
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


def flatten_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """把分层配置展开成 argparse 同名键。"""

    flat = dict(cfg)
    sections = {
        "adapter": ["input", "tcp_host", "tcp_port", "lsl_stream_type", "lsl_timeout", "lsl_channel_map"],
        "policy_cfg": ["policy"],
        "output": ["udp_host", "udp_port", "hz", "disable_legacy_xy", "verbose"],
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
        print("[keyboard] Initialized. Use W/S/A/D to simulate EEG intent, Space to reset.")

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
    if args.input == "tcp":
        return TcpJsonAdapter(args.tcp_host, args.tcp_port)
    if args.input == "tcp_client":
        return TcpClientJsonAdapter(args.tcp_host, args.tcp_port)
    if args.input == "lsl":
        channel_map = parse_channel_map(args.lsl_channel_map)
        if not channel_map:
            raise RuntimeError("LSL mode requires --lsl-channel-map")
        return LslAdapter(args.lsl_stream_type, args.lsl_timeout, channel_map)
    raise RuntimeError(f"Unsupported input mode: {args.input}")


def main() -> int:
    parser = argparse.ArgumentParser(description="EEG -> UDP intent pipeline for Thymio")
    parser.add_argument("--config", default="", help="Path to YAML config file")
    parser.add_argument("--input", choices=["mock", "tcp", "tcp_client", "lsl"], default="mock")
    parser.add_argument("--policy", choices=sorted(POLICIES.keys()), default="focus")

    parser.add_argument("--tcp-host", default="0.0.0.0", help="TCP server bind host")
    parser.add_argument("--tcp-port", type=int, default=6001, help="TCP server bind port")

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
    parser.add_argument(
        "--disable-legacy-xy",
        action="store_true",
        help="Disable legacy x/y fields in outgoing payload",
    )
    parser.add_argument("--verbose", action="store_true", help="Print feature and output details")
    args = parser.parse_args()

    if args.config:
        if yaml is None:
            print("ERROR: PyYAML is required to load config")
            return 1
        try:
            cfg = load_yaml_config(args.config)
            args = apply_config_to_args(args, parser, cfg)
        except Exception as e:
            print(f"ERROR: cannot load config: {e}")
            return 1

    adapter = build_adapter(args)
    policy = POLICIES[args.policy]()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target = (args.udp_host, int(args.udp_port))

    last_ts = time.time()
    hz = float(args.hz)
    period = 1.0 / max(1.0, hz)

    try:
        while True:
            frame = adapter.read_frame()
            if frame is not None:
                feats = enrich_features(frame.metrics)
                intents = policy.compute_intents(feats)
                if not args.disable_legacy_xy:
                    intents = with_legacy_xy(intents)
                payload = json.dumps(intents).encode()
                sock.sendto(payload, target)
                last_ts = time.time()
                if args.verbose:
                    print(f"[eeg-pipeline] sent {intents}")
            else:
                time.sleep(period)
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
