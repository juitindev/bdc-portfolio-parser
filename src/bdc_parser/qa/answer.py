"""Grounded answer generation over retrieved 10-K chunks (v0 — RAG path).

Two hard guarantees, both tested offline:

  1. REFUSE-IF-EMPTY. If retrieval returns no chunks, the layer refuses and
     says it cannot answer from the source. It does NOT call the LLM and does
     NOT hallucinate. (CLAUDE.md "Claude Code Usage": refuse rather than
     hallucinate when retrieval is empty.)

  2. CITATIONS REQUIRED. When chunks are present, the prompt forces the model
     to ground every claim in the supplied, numbered sources, and the returned
     Answer always carries the SourceRefs of the chunks it was built from. An
     answer object cannot be produced without its sources attached.

The LLM is reached through the existing provider-agnostic factory in
ai/llm.py — no hardcoded Anthropic client.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bdc_parser.ai.llm import get_model, llm_available
from bdc_parser.qa.retrieve import RetrievedChunk, retrieve

REFUSAL = (
    "I can't answer that from the {ticker} 10-K — retrieval returned no "
    "relevant passages. (No grounded source, so I won't guess.)"
)

_SYSTEM = (
    "You are a financial-filings analyst. Answer ONLY from the numbered "
    "sources provided. Every factual claim must cite the source(s) it came "
    "from using bracketed numbers like [1] or [2]. If the sources do not "
    "contain the answer, say so plainly and do not speculate. Do not use "
    "outside knowledge."
)


@dataclass
class Answer:
    """A grounded answer. `refused=True` means no source was available."""
    text: str
    question: str
    ticker: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    refused: bool = False
    llm_used: bool = False

    @property
    def citations(self) -> list[str]:
        """Citation strings for every source backing this answer."""
        return [c.ref.cite() for c in self.chunks]

    def has_citations(self) -> bool:
        return bool(self.chunks)


def _format_sources(chunks: list[RetrievedChunk]) -> str:
    blocks = []
    for i, c in enumerate(chunks, start=1):
        blocks.append(f"[{i}] {c.ref.cite()}\n{c.text}")
    return "\n\n".join(blocks)


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """Assemble the grounded prompt. Exposed for testing the citation contract."""
    sources = _format_sources(chunks)
    return (
        f"{_SYSTEM}\n\n"
        f"=== SOURCES ===\n{sources}\n\n"
        f"=== QUESTION ===\n{question}\n\n"
        f"Answer, citing sources with [n]:"
    )


def answer(
    question: str,
    ticker: str = "FDUS",
    *,
    k: int = 10,
    use_llm: bool = True,
    _chunks: list[RetrievedChunk] | None = None,
) -> Answer:
    """Answer a question from a ticker's 10-K via the RAG path.

    `_chunks` lets tests inject retrieval results without a live index.
    `use_llm=False` (or no API key / no langchain) returns a grounded,
    citation-bearing extractive stub instead of calling a model — the package
    must work with no API key.
    """
    chunks = _chunks if _chunks is not None else retrieve(question, ticker, k=k)

    # GUARD 1: refuse-if-empty. No source -> no answer, no LLM call.
    if not chunks:
        return Answer(
            text=REFUSAL.format(ticker=ticker.upper()),
            question=question,
            ticker=ticker.upper(),
            chunks=[],
            refused=True,
            llm_used=False,
        )

    # No-LLM / no-key path: still grounded, still cited (extractive fallback).
    if not use_llm or not llm_available():
        preview = chunks[0].text.strip().replace("\n", " ")
        if len(preview) > 400:
            preview = preview[:400] + "…"
        text = (
            f"[no-LLM mode] Top grounded passage for {ticker.upper()}:\n"
            f"{preview} [1]\n\n"
            f"Sources:\n"
            + "\n".join(f"[{i}] {c.ref.cite()}" for i, c in enumerate(chunks, 1))
        )
        return Answer(text=text, question=question, ticker=ticker.upper(),
                      chunks=chunks, refused=False, llm_used=False)

    prompt = build_prompt(question, chunks)
    model = get_model()
    resp = model.invoke(prompt)
    body = getattr(resp, "content", resp)
    if isinstance(body, list):  # some providers return content blocks
        body = "".join(getattr(b, "text", str(b)) for b in body)

    text = (
        f"{body}\n\n"
        f"Sources:\n"
        + "\n".join(f"[{i}] {c.ref.cite()}" for i, c in enumerate(chunks, 1))
    )
    return Answer(text=text, question=question, ticker=ticker.upper(),
                  chunks=chunks, refused=False, llm_used=True)
