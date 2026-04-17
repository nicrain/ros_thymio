from app.models import AppConfig
from app.teleop_publisher import (
    TELEOP_DIRECTIONS,
    _build_twist,
    _cmd_topic,
)


def test_cmd_topic_sim():
    assert _cmd_topic(use_sim=True) == "/model/thymio/cmd_vel"


def test_cmd_topic_real():
    assert _cmd_topic(use_sim=False) == "/cmd_vel"


def test_teleop_directions():
    assert TELEOP_DIRECTIONS == {"forward", "backward", "left", "right", "stop"}


def test_build_twist_stop():
    cfg = AppConfig()
    lin, ang = _build_twist("stop", cfg)
    assert lin == 0.0
    assert ang == 0.0


def test_build_twist_forward():
    cfg = AppConfig()
    cfg.motion.max_forward_speed = 0.5
    lin, ang = _build_twist("forward", cfg)
    assert lin == 0.5
    assert ang == 0.0


def test_build_twist_backward():
    cfg = AppConfig()
    cfg.motion.reverse_speed = -0.3
    lin, ang = _build_twist("backward", cfg)
    assert lin == -0.3
    assert ang == 0.0


def test_build_twist_left():
    cfg = AppConfig()
    cfg.motion.turn_forward_speed = 0.1
    cfg.motion.turn_angular_speed = 1.5
    lin, ang = _build_twist("left", cfg)
    assert lin == 0.1
    assert ang == 1.5


def test_build_twist_right():
    cfg = AppConfig()
    cfg.motion.turn_forward_speed = 0.2
    cfg.motion.turn_angular_speed = 2.0
    lin, ang = _build_twist("right", cfg)
    assert lin == 0.2
    assert ang == -2.0


def test_build_twist_unknown_raises():
    cfg = AppConfig()
    try:
        _build_twist("spin", cfg)
    except ValueError as e:
        assert "Unknown direction" in str(e)
    else:
        raise AssertionError("Expected ValueError for unknown direction")
