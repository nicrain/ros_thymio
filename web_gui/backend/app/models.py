from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LaunchConfig(BaseModel):
    use_sim: bool = True
    use_gui: bool = True
    run_eeg: bool = False
    run_gaze: bool = False
    run_rviz: bool = False
    use_teleop: bool = True
    use_tobii_bridge: bool = False
    use_enobio_bridge: bool = False


class EegConfig(BaseModel):
    input: Literal["mock", "tcp_client", "tcp_file", "lsl", "file"] = "mock"
    policy: Literal["focus", "theta_beta"] = "focus"
    tcp_control_mode: Literal["feature", "movement"] = "feature"
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 6001
    file_path: str = ""
    lsl_stream_type: str = "EEG"
    lsl_timeout: float = 8.0
    lsl_channel_map: str = "alpha=0,theta=1,beta=2,left_alpha=3,right_alpha=4"


class FilterConfig(BaseModel):
    enabled: bool = True
    type: Literal["none", "lowpass", "bandpass", "notch"] = "bandpass"
    low_hz: float = 1.0
    high_hz: float = 40.0
    notch_hz: float = 50.0
    order: int = 4


class MotionConfig(BaseModel):
    max_forward_speed: float = 0.2
    reverse_speed: float = -0.15
    turn_forward_speed: float = 0.1
    turn_angular_speed: float = 1.2
    reverse_threshold: float = 0.2
    steer_deadzone: float = 0.1
    line_mode: Literal["", "blackline", "whiteline"] = ""


class PipelineConfig(BaseModel):
    source_type: Literal["mock", "tcp_client", "tcp_file", "lsl", "file"] = "mock"
    selected_channels: list[int] = Field(default_factory=lambda: [0, 1, 2])
    algorithm: Literal["theta_beta_ratio", "alpha_beta_ratio", "custom"] = "theta_beta_ratio"


class AppConfig(BaseModel):
    launch: LaunchConfig = Field(default_factory=LaunchConfig)
    eeg: EegConfig = Field(default_factory=EegConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    motion: MotionConfig = Field(default_factory=MotionConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


class ConfigEnvelope(BaseModel):
    config: AppConfig
    source_files: dict[str, str]


class SystemStatus(BaseModel):
    mode: Literal["mock", "real"] = "mock"
    ros_available: bool = False
    thymio_connected: bool = False
    thymio_probe_detail: str = "Unknown"
    eeg_stream_alive: bool = False
    running: bool = False
    last_error: str | None = None


class CommandRequest(BaseModel):
    dry_run: bool = True


class CommandResult(BaseModel):
    accepted: bool
    dry_run: bool
    command: str
    detail: str


class WsFrame(BaseModel):
    status: SystemStatus
    channels: dict[str, float]
    features: dict[str, float]
    control: dict[str, float]
    timestamp: float


class ConfigPatch(BaseModel):
    patch: dict[str, Any]
