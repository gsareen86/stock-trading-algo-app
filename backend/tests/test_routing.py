"""Chain resolution and pruning.

Pruning is not vetoing: a task whose primary is unavailable should be served by its fallback,
not fail. These assert that distinction, which is the whole reason a chain exists.
"""

from __future__ import annotations

from app.core.settings import Settings
from app.llm.routing import SkipReason, resolve_chain

NEVER_OPEN = lambda provider: False  # noqa: E731


def _settings(**overrides) -> Settings:
    return Settings(app_env="test", _env_file=None, **overrides)


class TestChainConstruction:
    def test_primary_only_when_no_fallback(self) -> None:
        settings = _settings(llm_route={"narrative": "ollama/llama3.1"})

        assert settings.chain_for_task("narrative") == ["ollama/llama3.1"]

    def test_fallbacks_follow_primary_in_order(self) -> None:
        settings = _settings(
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "openai/gpt-4o, anthropic/claude-sonnet-5"},
        )

        assert settings.chain_for_task("narrative") == [
            "ollama/llama3.1",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-5",
        ]

    def test_duplicate_targets_collapse(self) -> None:
        """Repeating a rung would just retry an already-failed target."""
        settings = _settings(
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "ollama/llama3.1,openai/gpt-4o"},
        )

        assert settings.chain_for_task("narrative") == ["ollama/llama3.1", "openai/gpt-4o"]

    def test_blank_entries_ignored(self) -> None:
        settings = _settings(
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": " , openai/gpt-4o ,"},
        )

        assert settings.chain_for_task("narrative") == ["ollama/llama3.1", "openai/gpt-4o"]

    def test_unrouted_task_uses_default_then_its_fallbacks(self) -> None:
        settings = _settings(
            llm_default_task_model="anthropic/claude-sonnet-5",
            llm_fallback={"research": "ollama/llama3.1"},
        )

        assert settings.chain_for_task("research") == [
            "anthropic/claude-sonnet-5",
            "ollama/llama3.1",
        ]


class TestRungMetadata:
    def test_local_providers_flagged(self) -> None:
        settings = _settings(
            llm_route={"narrative": "lemonade/qwen3-8b"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
        )

        chain = resolve_chain(
            settings, "narrative", is_breaker_open=NEVER_OPEN, budget_exhausted=False
        )

        assert [r.is_local for r in chain.rungs] == [True, False]
        assert [r.is_fallback for r in chain.rungs] == [False, True]

    def test_base_url_resolved_for_local_rung(self) -> None:
        settings = _settings(
            llm_route={"narrative": "lemonade/qwen3-8b"},
            llm_provider_base_url={"lemonade": "http://localhost:9001/v1"},
        )

        chain = resolve_chain(
            settings, "narrative", is_breaker_open=NEVER_OPEN, budget_exhausted=False
        )

        assert chain.rungs[0].api_base == "http://localhost:9001/v1"


class TestBreakerPruning:
    def test_open_primary_is_skipped_and_fallback_survives(self) -> None:
        settings = _settings(
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
        )

        chain = resolve_chain(
            settings,
            "narrative",
            is_breaker_open=lambda provider: provider == "ollama",
            budget_exhausted=False,
        )

        assert [r.target for r in chain.rungs] == ["anthropic/claude-sonnet-5"]
        assert chain.skipped[0][1] is SkipReason.BREAKER_OPEN

    def test_all_open_yields_empty_chain(self) -> None:
        settings = _settings(
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
        )

        chain = resolve_chain(
            settings, "narrative", is_breaker_open=lambda p: True, budget_exhausted=False
        )

        assert chain.is_empty
        assert chain.dominant_skip_reason is SkipReason.BREAKER_OPEN


class TestBudgetPruning:
    def test_paid_rungs_pruned_local_kept(self) -> None:
        """A spend cap must not disable the free provider that could still answer."""
        settings = _settings(
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_fallback={"narrative": "lemonade/qwen3-8b"},
        )

        chain = resolve_chain(
            settings, "narrative", is_breaker_open=NEVER_OPEN, budget_exhausted=True
        )

        assert [r.target for r in chain.rungs] == ["lemonade/qwen3-8b"]
        assert chain.skipped[0][1] is SkipReason.BUDGET_EXCEEDED

    def test_all_paid_chain_empties_when_over_budget(self) -> None:
        settings = _settings(
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_fallback={"narrative": "openai/gpt-4o"},
        )

        chain = resolve_chain(
            settings, "narrative", is_breaker_open=NEVER_OPEN, budget_exhausted=True
        )

        assert chain.is_empty
        assert chain.dominant_skip_reason is SkipReason.BUDGET_EXCEEDED

    def test_budget_reason_wins_over_breaker(self) -> None:
        """Budget is the actionable message; a breaker is a side effect."""
        settings = _settings(
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_fallback={"narrative": "ollama/llama3.1"},
        )

        chain = resolve_chain(
            settings,
            "narrative",
            is_breaker_open=lambda provider: provider == "ollama",
            budget_exhausted=True,
        )

        assert chain.is_empty
        assert chain.dominant_skip_reason is SkipReason.BUDGET_EXCEEDED
