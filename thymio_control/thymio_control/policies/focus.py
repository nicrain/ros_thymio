"""FocusPolicy — maps focus level and alpha asymmetry to control intents.

Algorithm
---------
- **speed_intent**: derived from ``beta_alpha_theta`` (the "engagement" ratio).
  Higher engagement → higher speed intent.  EMA smoothing (α=0.35) applied
  to the raw ratio before normalisation to reduce frame-to-frame jitter.
- **steer_intent**: derived from ``alpha_asym`` (right minus left alpha power,
  normalised).  Values > 0.5 indicate rightward bias; < 0.5 leftward.

Note
----
The normalisation constants are calibrated against
``20260408111446_Patient01.edf`` (3-min stats: p5=0.323, p95=2.359).
Re-calibrate for different recordings.
"""
from __future__ import annotations

from typing import Dict

from thymio_control.policies.base import Policy
from thymio_control.processors.enrich import clip01


class FocusPolicy(Policy):
    """Map focus level and alpha lateralisation to speed / steer intents.

    Attributes are intentionally exposed as class-level defaults so they can
    be overridden in subclasses or via config injection without subclassing.
    """

    focus_offset: float = 0.3230
    focus_scale:  float = 2.0355
    steer_gain:   float = 1.1
    ema_alpha:    float = 0.35

    def __init__(self) -> None:
        super().__init__()
        self._bat_smooth: float = 0.0
        self._primed: bool = False

    def compute_intents(self, features: Dict[str, float]) -> Dict[str, float]:
        focus = features.get("beta_alpha_theta", 0.0)

        # EMA smoothing on raw beta_alpha_theta (before normalisation)
        if not self._primed:
            self._bat_smooth = focus
            self._primed = True
        else:
            self._bat_smooth = (
                self.ema_alpha * focus + (1.0 - self.ema_alpha) * self._bat_smooth
            )

        focus_norm = clip01((self._bat_smooth - self.focus_offset) / self.focus_scale)

        asym = features.get("alpha_asym", 0.0)
        steer_intent = clip01(0.5 + self.steer_gain * asym)
        speed_intent = clip01(focus_norm)

        return {"speed_intent": speed_intent, "steer_intent": steer_intent}
