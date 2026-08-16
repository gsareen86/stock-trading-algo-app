"""Strategy discovery.

Same convention as tools: `app/strategies/<id>/strategy.py` exporting `STRATEGY`. Load
failures are recorded rather than swallowed, because a strategy that vanished from a typo
should not look like one that was never written — and here, a missing strategy silently
narrows what the platform considers.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from app.strategies.protocols import StrategyDefinition, StrategyLoadFailure

log = logging.getLogger(__name__)

STRATEGIES_PACKAGE = "app.strategies"
#: Modules that are framework, not strategies.
_NOT_STRATEGIES = {"protocols", "registry", "indicators"}


class StrategyRegistry:
    def __init__(self, definitions: dict[str, StrategyDefinition] | None = None) -> None:
        self._strategies: dict[str, StrategyDefinition] = dict(definitions or {})
        self._failures: list[StrategyLoadFailure] = []

    def register(self, definition: StrategyDefinition) -> None:
        if definition.id in self._strategies:
            raise ValueError(f"duplicate strategy id {definition.id!r}")
        self._strategies[definition.id] = definition

    @classmethod
    def discover(cls, package: str = STRATEGIES_PACKAGE) -> StrategyRegistry:
        registry = cls()
        root = importlib.import_module(package)

        for module_info in pkgutil.iter_modules(root.__path__):
            if not module_info.ispkg or module_info.name in _NOT_STRATEGIES:
                continue
            dotted = f"{package}.{module_info.name}.strategy"
            try:
                module = importlib.import_module(dotted)
                definition = getattr(module, "STRATEGY", None)
                if definition is None:
                    raise AttributeError("module defines no module-level STRATEGY")
                registry.register(definition)
            except Exception as exc:
                log.warning("strategy %s failed to load: %s", dotted, exc)
                registry._failures.append(
                    StrategyLoadFailure(module=dotted, error=f"{type(exc).__name__}: {exc}")
                )
        return registry

    def ids(self) -> list[str]:
        return sorted(self._strategies)

    def definitions(self) -> list[StrategyDefinition]:
        return [self._strategies[i] for i in self.ids()]

    def get(self, strategy_id: str) -> StrategyDefinition | None:
        return self._strategies.get(strategy_id)

    @property
    def load_failures(self) -> list[StrategyLoadFailure]:
        return list(self._failures)
