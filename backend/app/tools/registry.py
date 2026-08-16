"""Discovery, validation and invocation.

Tools live in `app/tools/<name>/tool.py` exporting a module-level `TOOL`. Discovery is by
convention rather than an explicit list because a list is one more place to forget — at the
cost that a tool with an import error would disappear silently, which is why load failures
are recorded and surfaced rather than swallowed.

`invoke` never raises. A tool is called from an agent loop, and one RSS feed being down must
not end a cycle — the same rule the LLM gateway follows, for the same reason.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from jsonschema import Draft202012Validator

from app.tools.types import (
    FailureReason,
    ToolContext,
    ToolLoadFailure,
    ToolManifest,
    ToolResult,
)

log = logging.getLogger(__name__)

TOOLS_PACKAGE = "app.tools"
#: Subpackages that are registry machinery, not tools.
_NOT_TOOLS = {"types", "registry", "bindings", "evidence"}


class ToolRegistry:
    """Holds the discovered tools and runs them under their declared contracts."""

    def __init__(self, manifests: dict[str, ToolManifest] | None = None) -> None:
        self._tools: dict[str, ToolManifest] = dict(manifests or {})
        self._failures: list[ToolLoadFailure] = []
        self._validators: dict[str, tuple[Draft202012Validator, Draft202012Validator]] = {}
        for manifest in self._tools.values():
            self._compile(manifest)

    # ── registration ──────────────────────────────────────────────────────────
    def _compile(self, manifest: ToolManifest) -> None:
        self._validators[manifest.name] = (
            Draft202012Validator(manifest.input_schema),
            Draft202012Validator(manifest.output_schema),
        )

    def register(self, manifest: ToolManifest) -> None:
        if manifest.name in self._tools:
            raise ValueError(
                f"duplicate tool name {manifest.name!r} — a silent overwrite would make one "
                "of the two capabilities unreachable with no error"
            )
        self._tools[manifest.name] = manifest
        self._compile(manifest)

    @classmethod
    def discover(cls, package: str = TOOLS_PACKAGE) -> ToolRegistry:
        """Import every tool subpackage and collect its manifest."""
        registry = cls()
        root = importlib.import_module(package)

        for module_info in pkgutil.iter_modules(root.__path__):
            if not module_info.ispkg or module_info.name in _NOT_TOOLS:
                continue
            dotted = f"{package}.{module_info.name}.tool"
            try:
                module = importlib.import_module(dotted)
                manifest = getattr(module, "TOOL", None)
                if manifest is None:
                    raise AttributeError("module defines no module-level TOOL")
                registry.register(manifest)
            except Exception as exc:
                log.warning("tool %s failed to load: %s", dotted, exc)
                registry._failures.append(
                    ToolLoadFailure(module=dotted, error=f"{type(exc).__name__}: {exc}")
                )
        return registry

    # ── inspection ────────────────────────────────────────────────────────────
    def names(self) -> list[str]:
        return sorted(self._tools)

    def manifests(self) -> list[ToolManifest]:
        return [self._tools[name] for name in self.names()]

    def get(self, name: str) -> ToolManifest | None:
        return self._tools.get(name)

    @property
    def load_failures(self) -> list[ToolLoadFailure]:
        return list(self._failures)

    # ── invocation ────────────────────────────────────────────────────────────
    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        context: ToolContext | None = None,
    ) -> ToolResult:
        manifest = self._tools.get(name)
        if manifest is None:
            return ToolResult.failure(
                name, FailureReason.UNKNOWN_TOOL, f"no tool named {name!r}"
            )

        input_validator, output_validator = self._validators[name]
        payload = arguments or {}

        problems = _describe(input_validator, payload)
        if problems:
            # The handler is deliberately not called: running on arguments known to be wrong
            # produces a failure further from its cause.
            return ToolResult.failure(name, FailureReason.INVALID_INPUT, problems)

        try:
            output = manifest.handler(payload, context or ToolContext())
        except Exception as exc:
            log.warning("tool %s raised: %s", name, exc)
            return ToolResult.failure(
                name, FailureReason.HANDLER_ERROR, f"{type(exc).__name__}: {exc}"
            )

        problems = _describe(output_validator, output)
        if problems:
            # A source that changed shape fails here, loudly, rather than becoming a strangely
            # worded narrative nobody can trace.
            log.warning("tool %s returned non-conforming output: %s", name, problems)
            return ToolResult.failure(name, FailureReason.INVALID_OUTPUT, problems)

        return ToolResult.success(name, output)


def _describe(validator: Draft202012Validator, instance: Any) -> str | None:
    """Human-readable summary of the first few schema violations, or None if valid."""
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if not errors:
        return None
    parts = []
    for error in errors[:3]:
        location = ".".join(str(p) for p in error.path) or "<root>"
        parts.append(f"{location}: {error.message}")
    if len(errors) > 3:
        parts.append(f"(+{len(errors) - 3} more)")
    return "; ".join(parts)
