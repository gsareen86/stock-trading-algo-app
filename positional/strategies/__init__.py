"""Active positional strategies.

The bot trades four positional setups that feed a single confluence scorecard
(see positional/scorer.py):

  - Minervini Trend Template + VCP   (positional/scanner.py)
  - Brahma-Vishnu-Mahesh             (multi-year base breakout, top-down)
  - Fundamental-Technical Momentum   (CANSLIM-style earnings-driven breakout)
  - Young Momentum                   (1-2-3-4 continuation)

Minervini lives in positional/scanner.py because it predates the BasePositionalStrategy
interface; the other three implement BasePositionalStrategy here.
"""
from positional.strategies.base import BasePositionalStrategy, PositionalSignal
from positional.strategies.brahma_vishnu_mahesh import BrahmaVishnuMaheshStrategy
from positional.strategies.fun_tech_momentum import FunTechMomentumStrategy
from positional.strategies.young_momentum import YoungMomentumStrategy


def all_positional_strategies() -> list[BasePositionalStrategy]:
    """The three BasePositionalStrategy implementations (Minervini is run separately)."""
    return [
        BrahmaVishnuMaheshStrategy(),
        FunTechMomentumStrategy(),
        YoungMomentumStrategy(),
    ]


__all__ = [
    "BasePositionalStrategy", "PositionalSignal",
    "BrahmaVishnuMaheshStrategy", "FunTechMomentumStrategy",
    "YoungMomentumStrategy",
    "all_positional_strategies",
]
