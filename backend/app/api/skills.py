"""Skill discovery endpoint.

Publishes the registered manifests so the platform's capabilities are inspectable without
reading the source — and so a skill that vanished because of a typo is distinguishable from
one that was never written.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.skills.bindings import to_public_dict
from app.skills.registry import SkillRegistry

router = APIRouter(prefix="/skills", tags=["skills"])


def get_registry(request: Request) -> SkillRegistry:
    return request.app.state.skills


@router.get("")
async def list_skills(
    registry: Annotated[SkillRegistry, Depends(get_registry)],
) -> dict[str, Any]:
    return {
        # to_public_dict deliberately omits the handler — an import path is an implementation
        # detail, and publishing one tells a reader how to reach code this API never meant
        # to expose.
        "skills": [to_public_dict(manifest) for manifest in registry.manifests()],
        "count": len(registry.names()),
        "load_failures": [
            {"module": failure.module, "error": failure.error} for failure in registry.load_failures
        ],
    }
