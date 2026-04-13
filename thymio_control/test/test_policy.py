import pytest

from thymio_control.eeg_control_pipeline import FocusPolicy, ThetaBetaPolicy


def test_focus_policy_clips_speed_and_steer_bounds():
    policy = FocusPolicy()

    low = policy.compute_intents({"beta_alpha_theta": -10.0, "alpha_asym": -10.0})
    high = policy.compute_intents({"beta_alpha_theta": 10.0, "alpha_asym": 10.0})

    assert low["speed_intent"] == pytest.approx(0.0)
    assert low["steer_intent"] == pytest.approx(0.0)
    assert high["speed_intent"] == pytest.approx(1.0)
    assert high["steer_intent"] == pytest.approx(1.0)


def test_focus_policy_steer_direction_matches_alpha_asym_sign():
    policy = FocusPolicy()

    left_bias = policy.compute_intents({"beta_alpha_theta": 0.5, "alpha_asym": -0.1})
    right_bias = policy.compute_intents({"beta_alpha_theta": 0.5, "alpha_asym": 0.1})

    assert left_bias["steer_intent"] < 0.5
    assert right_bias["steer_intent"] > 0.5


def test_theta_beta_policy_ratio_controls_speed_inversely():
    policy = ThetaBetaPolicy()

    low_ratio = policy.compute_intents({"theta_beta": 0.5, "alpha_asym": 0.0})
    high_ratio = policy.compute_intents({"theta_beta": 2.5, "alpha_asym": 0.0})

    assert low_ratio["speed_intent"] > high_ratio["speed_intent"]
    assert 0.0 <= low_ratio["speed_intent"] <= 1.0
    assert 0.0 <= high_ratio["speed_intent"] <= 1.0


def test_theta_beta_policy_steer_is_clipped():
    policy = ThetaBetaPolicy()

    left = policy.compute_intents({"theta_beta": 1.0, "alpha_asym": -100.0})
    right = policy.compute_intents({"theta_beta": 1.0, "alpha_asym": 100.0})

    assert left["steer_intent"] == pytest.approx(0.0)
    assert right["steer_intent"] == pytest.approx(1.0)
