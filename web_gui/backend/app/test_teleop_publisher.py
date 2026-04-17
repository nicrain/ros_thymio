from app.models import AppConfig
from app.teleop_publisher import (
    TELEOP_DIRECTIONS,
    _build_twist_cmd,
    _cmd_topic,
)


def test_cmd_topic_sim():
    assert _cmd_topic(use_sim=True) == "/model/thymio/cmd_vel"


def test_cmd_topic_real():
    assert _cmd_topic(use_sim=False) == "/cmd_vel"


def test_teleop_directions():
    assert TELEOP_DIRECTIONS == {"forward", "backward", "left", "right", "stop"}


def test_build_twist_cmd_stop():
    cfg = AppConfig()
    cmd = _build_twist_cmd("stop", use_sim=True, cfg=cfg)
    assert cmd[0:4] == ["ros2", "topic", "pub", "--once"]
    assert cmd[4] == "/model/thymio/cmd_vel"
    assert "linear: {x: 0.0" in cmd[-1]


def test_build_twist_cmd_forward():
    cfg = AppConfig()
    cfg.motion.max_forward_speed = 0.5
    cmd = _build_twist_cmd("forward", use_sim=False, cfg=cfg)
    assert cmd[4] == "/cmd_vel"
    assert "x: 0.5" in cmd[-1]


def test_build_twist_cmd_backward():
    cfg = AppConfig()
    cfg.motion.reverse_speed = -0.3
    cmd = _build_twist_cmd("backward", use_sim=False, cfg=cfg)
    assert "x: -0.3" in cmd[-1]


def test_build_twist_cmd_left():
    cfg = AppConfig()
    cfg.motion.turn_forward_speed = 0.1
    cfg.motion.turn_angular_speed = 1.5
    cmd = _build_twist_cmd("left", use_sim=True, cfg=cfg)
    assert "x: 0.1" in cmd[-1]
    assert "z: 1.5" in cmd[-1]


def test_build_twist_cmd_right():
    cfg = AppConfig()
    cfg.motion.turn_forward_speed = 0.2
    cfg.motion.turn_angular_speed = 2.0
    cmd = _build_twist_cmd("right", use_sim=True, cfg=cfg)
    assert "x: 0.2" in cmd[-1]
    assert "z: -2.0" in cmd[-1]


def test_build_twist_cmd_unknown_raises():
    cfg = AppConfig()
    try:
        _build_twist_cmd("spin", use_sim=False, cfg=cfg)
    except ValueError as e:
        assert "Unknown direction" in str(e)
    else:
        raise AssertionError("Expected ValueError for unknown direction")
