"""The LLM gateway.

The invariant these protect is that a failing provider degrades the platform rather than
breaking it: ``complete`` returns ``None`` on every failure path and never raises.
"""

from __future__ import annotations

import re
from pathlib import Path

import litellm
import pytest
from sqlalchemy import select

from app.core.settings import Settings
from app.llm.breaker import CircuitBreaker
from app.llm.budget import DailyBudget
from app.llm.gateway import LiteLLMGateway
from app.llm.recorder import CallRecorder
from app.llm.types import Message
from app.persistence.models import LlmCall

MESSAGES = [Message(role="user", content="explain this evidence")]

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _recorded(session_factory) -> list[LlmCall]:
    """Rows the gateway wrote, oldest first."""
    with session_factory() as session:
        return list(session.execute(select(LlmCall).order_by(LlmCall.id)).scalars())


# ── fakes ─────────────────────────────────────────────────────────────────────
class _Usage:
    prompt_tokens = 10
    completion_tokens = 5
    total_tokens = 15


class FakeResponse:
    def __init__(self, content: str = "a plain-English explanation") -> None:
        message = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": message})()]
        self.usage = _Usage()
        self._hidden_params = {"response_cost": 0.00012}


class RateLimitError(Exception):
    """Named to match what the gateway classifies without importing LiteLLM's hierarchy."""

    status_code = 429


def _settings(tmp_path: Path, **overrides) -> Settings:
    base = {
        "app_env": "test",
        "llm_cache_dir": str(tmp_path / "cache"),
        "llm_max_retries": 0,
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})


def _record_calls(monkeypatch: pytest.MonkeyPatch, result=None, error=None) -> list[dict]:
    """Patch ``litellm.acompletion`` and capture the kwargs it was called with."""
    calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return result if result is not None else FakeResponse()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return calls


def _dispatch_by_model(monkeypatch: pytest.MonkeyPatch, behaviours: dict) -> list[str]:
    """Patch ``acompletion`` to behave differently per model, recording dispatch order.

    A value that is an exception instance is raised; anything else is returned.
    """
    dispatched: list[str] = []

    async def fake_acompletion(**kwargs):
        model = kwargs["model"]
        dispatched.append(model)
        outcome = behaviours.get(model, RuntimeError(f"no behaviour for {model}"))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    return dispatched


# ── tests ─────────────────────────────────────────────────────────────────────
class TestTaskRouting:
    async def test_task_dispatches_to_its_configured_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_route={"narrative": "ollama/llama3.1"})
        calls = _record_calls(monkeypatch)

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is not None
        assert calls[0]["model"] == "ollama/llama3.1"
        assert result.provider == "ollama"

    async def test_unrouted_task_uses_the_default_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_default_task_model="anthropic/claude-sonnet-5")
        calls = _record_calls(monkeypatch)

        await LiteLLMGateway(settings).complete(task="research", messages=MESSAGES)

        assert calls[0]["model"] == "anthropic/claude-sonnet-5"

    @pytest.mark.parametrize("provider", ["lemonade", "llama_cpp"])
    async def test_openai_compatible_provider_routed_by_base_url(
        self, provider: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The local servers need no adapter code — only a translation to openai/ + base URL."""
        settings = _settings(
            tmp_path,
            llm_route={"narrative": f"{provider}/qwen3-8b"},
            llm_provider_base_url={provider: "http://localhost:9001/v1"},
        )
        calls = _record_calls(monkeypatch)

        await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert calls[0]["model"] == "openai/qwen3-8b"
        assert calls[0]["api_base"] == "http://localhost:9001/v1"

    async def test_openai_provider_honours_a_custom_base_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "openai/qwen3-8b"},
            llm_provider_base_url={"openai": "http://localhost:8000/v1"},
        )
        calls = _record_calls(monkeypatch)

        await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert calls[0]["api_base"] == "http://localhost:8000/v1"

    async def test_hosted_provider_gets_no_api_base(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_route={"narrative": "anthropic/claude-sonnet-5"})
        calls = _record_calls(monkeypatch)

        await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert "api_base" not in calls[0]


class TestFailuresNeverRaise:
    async def test_provider_error_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch, error=RuntimeError("upstream exploded"))

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is None

    async def test_rate_limit_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch, error=RateLimitError("slow down"))

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is None

    async def test_unexpected_response_shape_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch, result=object())

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is None

    async def test_prose_when_schema_requested_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returning unparseable text would break downstream parsing at a worse moment."""
        _record_calls(monkeypatch, result=FakeResponse("not json at all"))

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative",
            messages=MESSAGES,
            schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )

        assert result is None

    async def test_valid_json_is_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch, result=FakeResponse('{"summary": "ok"}'))

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative",
            messages=MESSAGES,
            schema={"type": "object"},
        )

        assert result is not None
        assert result.parsed == {"summary": "ok"}


class TestCircuitBreaker:
    async def test_opens_after_threshold_and_stops_calling_the_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_breaker_threshold=3, llm_cache_enabled=False)
        calls = _record_calls(monkeypatch, error=RateLimitError("429"))
        gateway = LiteLLMGateway(settings)

        for _ in range(3):
            assert await gateway.complete(task="narrative", messages=MESSAGES) is None
        assert len(calls) == 3

        # Fourth call short-circuits: no network request is issued.
        assert await gateway.complete(task="narrative", messages=MESSAGES) is None
        assert len(calls) == 3

    async def test_closes_after_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_breaker_threshold=1, llm_cache_enabled=False)
        breaker = CircuitBreaker(threshold=1, cooldown_seconds=0.01)
        calls = _record_calls(monkeypatch, error=RateLimitError("429"))
        gateway = LiteLLMGateway(settings, breaker=breaker)

        await gateway.complete(task="narrative", messages=MESSAGES)
        assert breaker.is_open("anthropic")

        import time

        time.sleep(0.02)

        await gateway.complete(task="narrative", messages=MESSAGES)
        assert len(calls) == 2  # the probe went out

    async def test_non_rate_limit_errors_do_not_trip_the_breaker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A malformed prompt is a bug to fix, not a provider to back off from."""
        settings = _settings(tmp_path, llm_breaker_threshold=2, llm_cache_enabled=False)
        calls = _record_calls(monkeypatch, error=ValueError("bad prompt"))
        gateway = LiteLLMGateway(settings)

        for _ in range(4):
            await gateway.complete(task="narrative", messages=MESSAGES)

        assert len(calls) == 4  # every one still attempted


class TestCache:
    async def test_identical_request_served_from_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_calls(monkeypatch)
        gateway = LiteLLMGateway(_settings(tmp_path))

        first = await gateway.complete(task="narrative", messages=MESSAGES)
        second = await gateway.complete(task="narrative", messages=MESSAGES)

        assert len(calls) == 1
        assert first is not None and second is not None
        assert second.cached is True
        assert second.text == first.text

    async def test_different_messages_miss_the_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_calls(monkeypatch)
        gateway = LiteLLMGateway(_settings(tmp_path))

        await gateway.complete(task="narrative", messages=MESSAGES)
        await gateway.complete(task="narrative", messages=[Message(role="user", content="other")])

        assert len(calls) == 2

    async def test_failures_are_not_cached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A None means the provider was unavailable, not that the answer is 'nothing'."""
        settings = _settings(tmp_path)
        _record_calls(monkeypatch, error=RuntimeError("down"))
        gateway = LiteLLMGateway(settings)
        assert await gateway.complete(task="narrative", messages=MESSAGES) is None

        calls = _record_calls(monkeypatch)  # provider recovers
        result = await gateway.complete(task="narrative", messages=MESSAGES)

        assert len(calls) == 1
        assert result is not None

    async def test_cache_can_be_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _record_calls(monkeypatch)
        gateway = LiteLLMGateway(_settings(tmp_path, llm_cache_enabled=False))

        await gateway.complete(task="narrative", messages=MESSAGES)
        await gateway.complete(task="narrative", messages=MESSAGES)

        assert len(calls) == 2


class TestObservability:
    async def test_trace_id_absent_when_unconfigured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch)

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is not None
        assert result.trace_id is None

    async def test_trace_id_attached_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.llm import observability

        observability.reset()
        settings = _settings(tmp_path, langfuse_public_key="pk", langfuse_secret_key="sk")
        calls = _record_calls(monkeypatch)

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is not None
        assert result.trace_id is not None
        assert calls[0]["metadata"]["trace_id"] == result.trace_id
        assert calls[0]["metadata"]["generation_name"] == "narrative"
        observability.reset()

    async def test_usage_and_cost_are_captured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _record_calls(monkeypatch)

        result = await LiteLLMGateway(_settings(tmp_path)).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is not None
        assert result.total_tokens == 15
        assert result.cost_usd == pytest.approx(0.00012)
        assert result.latency_ms is not None

    async def test_local_model_is_unpriced_not_zero_priced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Found live against Ollama, not in these fakes.

        LiteLLM populates ``response_cost`` for *every* call, computing exactly ``0.0`` for a
        provider it has no pricing for, rather than omitting the field. The gateway read that
        number faithfully and recorded a local call as costing zero dollars — priced, at a
        price of nothing — when the ledger's whole distinction is priced vs. unpriced. Every
        fake here reported a hosted-shaped cost, so nothing exercised the real value.
        """
        settings = _settings(tmp_path, llm_route={"narrative": "ollama/gemma4:12b"})
        free = FakeResponse()
        free._hidden_params = {"response_cost": 0.0}
        _record_calls(monkeypatch, result=free)

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is not None
        assert result.cost_usd is None
        # Tokens are still real; it is only the *price* that does not exist.
        assert result.total_tokens == 15


class TestIsolation:
    def test_no_module_outside_app_llm_imports_litellm(self) -> None:
        """The indirection is what keeps the router swappable — assert it, don't hope."""
        pattern = re.compile(r"^\s*(import|from)\s+litellm\b", re.MULTILINE)
        offenders = [
            path.relative_to(BACKEND_ROOT)
            for path in (BACKEND_ROOT / "app").rglob("*.py")
            if "llm" not in path.parts and pattern.search(path.read_text("utf-8"))
        ]

        assert offenders == []


class TestFallbackChain:
    async def test_fallback_answers_when_primary_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        dispatched = _dispatch_by_model(
            monkeypatch,
            {
                "ollama/llama3.1": RuntimeError("ollama down"),
                "anthropic/claude-sonnet-5": FakeResponse("explained"),
            },
        )

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert dispatched == ["ollama/llama3.1", "anthropic/claude-sonnet-5"]
        assert result is not None
        assert result.text == "explained"

    async def test_result_names_the_model_that_answered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A narrative claiming an origin it did not have is worse than one with none."""
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        _dispatch_by_model(
            monkeypatch,
            {
                "ollama/llama3.1": RuntimeError("down"),
                "anthropic/claude-sonnet-5": FakeResponse(),
            },
        )

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is not None
        assert result.model == "anthropic/claude-sonnet-5"
        assert result.requested_model == "ollama/llama3.1"
        assert result.used_fallback is True
        assert result.provider == "anthropic"

    async def test_no_fallback_means_result_matches_request(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path, llm_route={"narrative": "ollama/llama3.1"}, llm_cache_enabled=False
        )
        _dispatch_by_model(monkeypatch, {"ollama/llama3.1": FakeResponse()})

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is not None
        assert result.model == result.requested_model == "ollama/llama3.1"
        assert result.used_fallback is False

    async def test_chain_order_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "openai/gpt-4o,anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        dispatched = _dispatch_by_model(
            monkeypatch,
            {
                "ollama/llama3.1": RuntimeError("down"),
                "openai/gpt-4o": RuntimeError("down too"),
                "anthropic/claude-sonnet-5": FakeResponse(),
            },
        )

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert dispatched == [
            "ollama/llama3.1",
            "openai/gpt-4o",
            "anthropic/claude-sonnet-5",
        ]
        assert result is not None

    async def test_whole_chain_failing_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        _dispatch_by_model(
            monkeypatch,
            {
                "ollama/llama3.1": RuntimeError("down"),
                "anthropic/claude-sonnet-5": RuntimeError("also down"),
            },
        )

        result = await LiteLLMGateway(settings).complete(task="narrative", messages=MESSAGES)

        assert result is None


class TestBreakerPrunesRatherThanVetoes:
    async def test_open_primary_still_reaches_the_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression this guards: an open breaker used to fail the whole call."""
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        breaker = CircuitBreaker(threshold=1, cooldown_seconds=600)
        breaker.record_rate_limit("ollama")
        dispatched = _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})

        result = await LiteLLMGateway(settings, breaker=breaker).complete(
            task="narrative", messages=MESSAGES
        )

        assert dispatched == ["anthropic/claude-sonnet-5"]  # primary never attempted
        assert result is not None

    async def test_all_providers_open_returns_none_without_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        breaker = CircuitBreaker(threshold=1, cooldown_seconds=600)
        breaker.record_rate_limit("ollama")
        breaker.record_rate_limit("anthropic")
        dispatched = _dispatch_by_model(monkeypatch, {})

        result = await LiteLLMGateway(settings, breaker=breaker).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is None
        assert dispatched == []


class TestBudgetGuardrail:
    async def test_paid_provider_refused_when_exhausted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_daily_budget_inr=88.0,
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, 1.0)
        budget.add(1.5)
        dispatched = _dispatch_by_model(monkeypatch, {})

        result = await LiteLLMGateway(settings, budget=budget).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is None
        assert dispatched == []

    async def test_local_provider_still_runs_when_exhausted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A spend cap must not disable the provider that costs nothing."""
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_daily_budget_inr=88.0,
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, 1.0)
        budget.add(5.0)
        _dispatch_by_model(monkeypatch, {"ollama/llama3.1": FakeResponse()})

        result = await LiteLLMGateway(settings, budget=budget).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is not None

    async def test_paid_rung_skipped_but_local_fallback_serves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_fallback={"narrative": "ollama/llama3.1"},
            llm_daily_budget_inr=88.0,
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, 1.0)
        budget.add(2.0)
        dispatched = _dispatch_by_model(monkeypatch, {"ollama/llama3.1": FakeResponse()})

        result = await LiteLLMGateway(settings, budget=budget).complete(
            task="narrative", messages=MESSAGES
        )

        assert dispatched == ["ollama/llama3.1"]
        assert result is not None
        assert result.used_fallback is True

    async def test_unset_cap_never_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, None)
        budget.add(10_000.0)
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})

        result = await LiteLLMGateway(settings, budget=budget).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is not None

    async def test_successful_cost_accrues_to_the_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, 1.0)
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})

        await LiteLLMGateway(settings, budget=budget).complete(task="narrative", messages=MESSAGES)

        assert budget.spent_today() == pytest.approx(0.00012)


class TestGatewayRecording:
    async def test_success_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        settings = _settings(tmp_path, llm_route={"narrative": "anthropic/claude-sonnet-5"})
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})

        await LiteLLMGateway(settings, recorder=CallRecorder(session_factory)).complete(
            task="narrative", messages=MESSAGES
        )

        (row,) = _recorded(session_factory)
        assert row.status == "ok"
        assert row.total_tokens == 15

    async def test_each_attempt_in_a_fallback_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        """The reason Router was not used: per-attempt rows must exist."""
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "ollama/llama3.1"},
            llm_fallback={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        _dispatch_by_model(
            monkeypatch,
            {
                "ollama/llama3.1": RuntimeError("down"),
                "anthropic/claude-sonnet-5": FakeResponse(),
            },
        )

        await LiteLLMGateway(settings, recorder=CallRecorder(session_factory)).complete(
            task="narrative", messages=MESSAGES
        )

        rows = _recorded(session_factory)
        assert [r.status for r in rows] == ["failed", "ok"]
        assert [r.model for r in rows] == ["ollama/llama3.1", "anthropic/claude-sonnet-5"]
        assert [r.used_fallback for r in rows] == [False, True]

    async def test_rate_limit_recorded_distinctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": RateLimitError("429")})

        await LiteLLMGateway(settings, recorder=CallRecorder(session_factory)).complete(
            task="narrative", messages=MESSAGES
        )

        (row,) = _recorded(session_factory)
        assert row.status == "rate_limited"

    async def test_breaker_short_circuit_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        breaker = CircuitBreaker(threshold=1, cooldown_seconds=600)
        breaker.record_rate_limit("anthropic")
        _dispatch_by_model(monkeypatch, {})

        await LiteLLMGateway(
            settings, breaker=breaker, recorder=CallRecorder(session_factory)
        ).complete(task="narrative", messages=MESSAGES)

        (row,) = _recorded(session_factory)
        assert row.status == "breaker_open"

    async def test_budget_refusal_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        settings = _settings(
            tmp_path,
            llm_route={"narrative": "anthropic/claude-sonnet-5"},
            llm_cache_enabled=False,
        )
        budget = DailyBudget(None, 1.0)
        budget.add(2.0)
        _dispatch_by_model(monkeypatch, {})

        await LiteLLMGateway(
            settings, budget=budget, recorder=CallRecorder(session_factory)
        ).complete(task="narrative", messages=MESSAGES)

        (row,) = _recorded(session_factory)
        assert row.status == "budget_exceeded"

    async def test_cache_hit_recorded_without_cost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_factory
    ) -> None:
        """Re-charging the original price to a cache hit would double-count the day."""
        settings = _settings(tmp_path, llm_route={"narrative": "anthropic/claude-sonnet-5"})
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})
        gateway = LiteLLMGateway(settings, recorder=CallRecorder(session_factory))

        await gateway.complete(task="narrative", messages=MESSAGES)
        await gateway.complete(task="narrative", messages=MESSAGES)

        rows = _recorded(session_factory)
        assert [r.status for r in rows] == ["ok", "cached"]
        assert rows[0].cost_usd == pytest.approx(0.00012)
        assert rows[1].cost_usd is None

    async def test_recording_failure_does_not_break_the_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path, llm_route={"narrative": "anthropic/claude-sonnet-5"})
        _dispatch_by_model(monkeypatch, {"anthropic/claude-sonnet-5": FakeResponse()})

        class ExplodingFactory:
            def __call__(self):
                raise RuntimeError("ledger unavailable")

        result = await LiteLLMGateway(settings, recorder=CallRecorder(ExplodingFactory())).complete(
            task="narrative", messages=MESSAGES
        )

        assert result is not None
