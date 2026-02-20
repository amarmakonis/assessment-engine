"""
OpenAI gateway singleton.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def get_llm_gateway():
    from app.infrastructure.llm.gateway import OpenAIGateway
    return OpenAIGateway()
