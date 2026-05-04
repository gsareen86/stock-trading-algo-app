from positional.strategies.base import BasePositionalStrategy, PositionalSignal
from positional.strategies.trend_following import TrendFollowingStrategy
from positional.strategies.breakout_retest import BreakoutRetestStrategy
from positional.strategies.quality_momentum import QualityMomentumStrategy
from positional.strategies.vcp_breakout import VCPBreakoutStrategy
from positional.strategies.sector_rotation import SectorRotationStrategy
from positional.strategies.mean_reversion import MeanReversionStrategy
from positional.strategies.earnings_momentum import EarningsMomentumStrategy


def all_positional_strategies() -> list[BasePositionalStrategy]:
    return [
        TrendFollowingStrategy(),
        BreakoutRetestStrategy(),
        QualityMomentumStrategy(),
        VCPBreakoutStrategy(),
        SectorRotationStrategy(),
        MeanReversionStrategy(),
        EarningsMomentumStrategy(),
    ]


__all__ = [
    "BasePositionalStrategy", "PositionalSignal",
    "TrendFollowingStrategy", "BreakoutRetestStrategy",
    "QualityMomentumStrategy", "VCPBreakoutStrategy",
    "SectorRotationStrategy", "MeanReversionStrategy",
    "EarningsMomentumStrategy",
    "all_positional_strategies",
]
