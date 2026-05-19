"""AlphaOnlyPolicy — uses alpha band power alone for speed control.

Algorithm
---------
- **speed_intent**: inversely proportional to ``alpha`` power.
  Alpha suppression (lower alpha) indicates cortical activation and
  higher attention, so lower alpha → higher speed intent.
  EMA smoothing (α=0.35) applied before normalisation.
- **steer_intent**: disabled (fixed at 0.5).

Calibration
-----------
Parameters are **placeholder values** estimated from the alpha range
observed in ``20260408111446_Patient01.edf`` (~0.5–7.5 µV²).
NOT yet calibrated via p5/p95 statistics like FocusPolicy and
ThetaBetaPolicy.  TODO: run formal calibration against the
reference EDF before production use.
"""
from __future__ import annotations

from typing import Dict

from thymio_control.policies.base import Policy
from thymio_control.processors.enrich import clip01


class AlphaOnlyPolicy(Policy):
    """Use alpha power inversely for speed intent; steering disabled."""

    # Normalisation: clip01(1.0 - (alpha_smooth - offset) / scale)
    # Alpha range from calibration: ~0.5 to ~7.5 µV²
    alpha_offset: float = 0.5    # p5 of alpha power
    alpha_scale:  float = 7.0    # p95 - p5
    ema_alpha:    float = 0.35

    def __init__(self) -> None:
        super().__init__()
        self._alpha_smooth: float = 0.0
        self._primed: bool = False

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        alpha = features.get("alpha", 0.0)

        # EMA smoothing on raw alpha (before normalisation)
        if not self._primed:
            self._alpha_smooth = alpha
            self._primed = True
        else:
            self._alpha_smooth = (
                self.ema_alpha * alpha + (1.0 - self.ema_alpha) * self._alpha_smooth
            )

        # Lower alpha = more focused = faster
        alpha_norm = clip01((self._alpha_smooth - self.alpha_offset) / self.alpha_scale)
        speed_intent = clip01(1.0 - alpha_norm)

        steer_intent = 0.5  # steering disabled — forward/backward only
        return {"speed_intent": speed_intent, "steer_intent": steer_intent}
