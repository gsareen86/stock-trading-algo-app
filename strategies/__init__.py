from strategies.base import BaseStrategy, Signal
from strategies.moving_average import EMACrossoverStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.momentum import MomentumStrategy


def all_strategies() -> list[BaseStrategy]:
    return [
        EMACrossoverStrategy(),
        RSIMeanReversionStrategy(),
        BollingerBreakoutStrategy(),
        MomentumStrategy(),
    ]


__all__ = [
    "BaseStrategy", "Signal",
    "EMACrossoverStrategy", "RSIMeanReversionStrategy",
    "BollingerBreakoutStrategy", "MomentumStrategy",
    "all_strategies",
]
