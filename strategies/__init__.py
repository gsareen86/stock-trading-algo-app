from strategies.base import BaseStrategy, Signal
from strategies.bollinger_breakout import BollingerBreakoutStrategy
from strategies.gap_play import GapPlayStrategy
from strategies.momentum import MomentumStrategy
from strategies.moving_average import EMACrossoverStrategy
from strategies.opening_range_breakout import OpeningRangeBreakoutStrategy
from strategies.pair_trading import PairTradingStrategy
from strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from strategies.supertrend import SupertrendStrategy
from strategies.vwap_reversion import VWAPReversionStrategy


def all_strategies() -> list[BaseStrategy]:
    """Order matters only for log readability — composite scoring is weighted."""
    return [
        # Legacy long-biased trend / mean-rev / breakout
        EMACrossoverStrategy(),
        RSIMeanReversionStrategy(),
        BollingerBreakoutStrategy(),
        MomentumStrategy(),
        # Direction-balanced additions (Tier 1)
        OpeningRangeBreakoutStrategy(),
        VWAPReversionStrategy(),
        PairTradingStrategy(),
        # High-conviction direction picks (Tier 2)
        SupertrendStrategy(),
        GapPlayStrategy(),
    ]


__all__ = [
    "BaseStrategy", "Signal",
    "EMACrossoverStrategy", "RSIMeanReversionStrategy",
    "BollingerBreakoutStrategy", "MomentumStrategy",
    "OpeningRangeBreakoutStrategy", "VWAPReversionStrategy",
    "PairTradingStrategy", "SupertrendStrategy", "GapPlayStrategy",
    "all_strategies",
]
