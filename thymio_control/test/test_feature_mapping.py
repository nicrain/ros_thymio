import pytest

from thymio_control.eeg_control_pipeline import Twist, feature_to_twist


def _make_twist(linear_x: float = 0.0, angular_z: float = 0.0) -> Twist:
    twist = Twist()
    twist.linear.x = linear_x
    twist.angular.z = angular_z
    return twist


def test_feature_to_twist_forward_band_matches_movement_style():
    twist = feature_to_twist(0.25, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(0.2)
    assert twist.angular.z == pytest.approx(0.0)
    assert abs(twist.linear.x) <= 0.2
    assert abs(twist.angular.z) <= 1.2


def test_feature_to_twist_reverse_band_matches_movement_style():
    twist = feature_to_twist(0.75, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(-0.15000000000000002)
    assert twist.angular.z == pytest.approx(0.0)
    assert abs(twist.linear.x) <= 0.2
    assert abs(twist.angular.z) <= 1.2


def test_feature_to_twist_turn_value_matches_movement_style():
    twist = feature_to_twist(1.0, max_forward_speed=0.2, turn_angular_speed=1.2, steer_deadzone=0.05)

    assert twist.linear.x == pytest.approx(0.0)
    assert twist.angular.z == pytest.approx(1.2)


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