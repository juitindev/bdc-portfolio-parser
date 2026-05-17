"""Provider-agnostic LLM factory.

The import of `langchain` is lazy so the package functions completely
without the AI extras installed. Call `llm_available()` before assuming
a model can be constructed.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = os.environ.get("BDC_PARSER_MODEL", "anthropic:claude-sonnet-4-6")

_API_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
)


def llm_available() -> bool:
    """True if langchain is importable AND at least one provider API key is set."""
    try:
        import langchain  # noqa: F401
    except ImportError:
        return False
    return any(os.environ.get(k) for k in _API_KEYS)


def get_model(model: str | None = None):
    """Return a configured chat model. Raises ImportError if langchain is missing."""
    from langchain.chat_models import init_chat_model
    return init_chat_model(model or DEFAULT_MODEL, temperature=0)
