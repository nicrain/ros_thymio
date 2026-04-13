from app.command_runner import _build_launch_command
from app.models import AppConfig


def test_launch_command_does_not_include_unsupported_tcp_args():
    cfg = AppConfig()
    cfg.launch.run_eeg = True
    cfg.eeg.tcp_host = "172.27.96.1"
    cfg.eeg.tcp_port = 1234

    command = _build_launch_command(cfg)

    assert "ros2 launch thymio_control experiment_core.launch.py" in command
    assert "run_eeg:=true" in command
    assert "tcp_host:=" not in command
    assert "tcp_port:=" not in command
