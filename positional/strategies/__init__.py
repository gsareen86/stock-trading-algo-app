from positional.strategies.base import BasePositionalStrategy, PositionalSignal
from positional.strategies.trend_following import TrendFollowingStrategy
from positional.strategies.breakout_retest import BreakoutRetestStrategy
from positional.strategies.quality_momentum import QualityMomentumStrategy
from positional.strategies.vcp_breakout import VCPBreakoutStrategy
from positional.strategies.sector_rotation import SectorRotationStrategy
from positional.strategies.mean_reversion import MeanReversionStrategy
from positional.strategies.earnings_momentum import EarningsMomentumStrategy
from positional.strategies.brahma_vishnu_mahesh import BrahmaVishnuMaheshStrategy
from positional.strategies.fun_tech_momentum import FunTechMomentumStrategy
from positional.strategies.young_momentum import YoungMomentumStrategy


def all_positional_strategies() -> list[BasePositionalStrategy]:
    return [
        TrendFollowingStrategy(),
        BreakoutRetestStrategy(),
        QualityMomentumStrategy(),
        VCPBreakoutStrategy(),
        SectorRotationStrategy(),
        MeanReversionStrategy(),
        EarningsMomentumStrategy(),
        BrahmaVishnuMaheshStrategy(),
        FunTechMomentumStrategy(),
        YoungMomentumStrategy(),
    ]


__all__ = [
    "BasePositionalStrategy", "PositionalSignal",
    "TrendFollowingStrategy", "BreakoutRetestStrategy",
    "QualityMomentumStrategy", "VCPBreakoutStrategy",
    "SectorRotationStrategy", "MeanReversionStrategy",
    "EarningsMomentumStrategy",
    "BrahmaVishnuMaheshStrategy", "FunTechMomentumStrategy",
    "YoungMomentumStrategy",
    "all_positional_strategies",
]
