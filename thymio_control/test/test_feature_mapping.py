import pytest

from thymio_control.eeg_control_pipeline import Twist, feature_to_twist


def _make_twist(linear_x: float = 0.0, angular_z: float = 0.0) -> Twist:
    twist = Twist()
    twist.linear.x = linear_x
    twist.angular.z = angular_z
    return twist


def test_feature_to_twist_negative_value_maps_to_reverse_left_turn():
    twist = feature_to_twist(-0.8, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(-0.16)
    assert twist.angular.z == pytest.approx(-0.96)
    assert abs(twist.linear.x) <= 0.2
    assert abs(twist.angular.z) <= 1.2


def test_feature_to_twist_positive_value_maps_to_forward_right_turn():
    twist = feature_to_twist(0.8, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(0.16)
    assert twist.angular.z == pytest.approx(0.96)
    assert abs(twist.linear.x) <= 0.2
    assert abs(twist.angular.z) <= 1.2


def test_feature_to_twist_zero_value_returns_stop():
    twist = feature_to_twist(0.0, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(0.0)
    assert twist.angular.z == pytest.approx(0.0)


def test_feature_to_twist_falls_back_to_last_twist_on_empty_input():
    last_twist = _make_twist(linear_x=0.12, angular_z=-0.33)

    twist = feature_to_twist(None, last_twist=last_twist)

    assert twist.linear.x == pytest.approx(0.12)
    assert twist.angular.z == pytest.approx(-0.33)


def test_feature_to_twist_falls_back_to_last_twist_on_bad_input():
    last_twist = _make_twist(linear_x=0.08, angular_z=0.44)

    twist = feature_to_twist("bad-input", last_twist=last_twist)

    assert twist.linear.x == pytest.approx(0.08)
    assert twist.angular.z == pytest.approx(0.44)