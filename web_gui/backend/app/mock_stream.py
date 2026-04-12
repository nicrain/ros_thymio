from __future__ import annotations

import math
import random
import time


class MockSignalGenerator:
    def __init__(self) -> None:
        self._t = 0.0

    def next(self) -> dict:
        self._t += 0.08
        now = time.time()

        alpha = 0.55 + 0.35 * math.sin(self._t)
        theta = 0.45 + 0.25 * math.sin(self._t * 0.6 + 1.2)
        beta = 0.5 + 0.3 * math.cos(self._t * 1.1)

        ratio = (theta + 1e-6) / (beta + 1e-6)
        speed_intent = max(min((alpha - 0.45) * 2.2, 1.0), -1.0)
        steer_intent = max(min((beta - theta) * 1.8, 1.0), -1.0)

        return {
            "timestamp": now,
            "channels": {
                "alpha": alpha + random.uniform(-0.03, 0.03),
                "theta": theta + random.uniform(-0.03, 0.03),
                "beta": beta + random.uniform(-0.03, 0.03),
                "left_alpha": alpha + random.uniform(-0.05, 0.05),
                "right_alpha": alpha + random.uniform(-0.05, 0.05),
            },
            "features": {
                "theta_beta_ratio": ratio,
                "focus_index": alpha - theta * 0.4,
                "asymmetry": random.uniform(-0.2, 0.2),
            },
            "control": {
                "speed_intent": speed_intent,
                "steer_intent": steer_intent,
            },
        }
