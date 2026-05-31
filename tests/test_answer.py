"""Tests for qa.answer — refuse-if-empty guard + citations-required contract.

Offline by default. No live LLM is invoked: we inject retrieval results via
`_chunks` and force the no-API-key path, mirroring the existing rate-parser
test pattern.
"""
import pytest

from bdc_parser.qa.answer import answer, build_prompt, Answer, REFUSAL
from bdc_parser.qa.retrieve import RetrievedChunk, SourceRef


def _chunk(text, item="1A", start=10, end=99, score=0.9):
    ref = SourceRef("FDUS 10-K", "FDUS", item, "Risk Factors", start, end)
    return RetrievedChunk(text=text, ref=ref, score=score)


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    # Guarantee the LLM is considered unavailable for every test in this module,
    # so nothing reaches a real provider.
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)


class TestRefuseIfEmpty:
    def test_empty_retrieval_refuses(self):
        a = answer("What are the risks?", ticker="FDUS", _chunks=[])
        assert a.refused is True
        assert a.llm_used is False
        assert not a.has_citations()
        assert "can't answer" in a.text.lower() or "cannot" in a.text.lower()

    def test_refusal_mentions_no_source(self):
        a = answer("anything", ticker="FDUS", _chunks=[])
        assert a.text == REFUSAL.format(ticker="FDUS")

    def test_refusal_never_calls_llm(self, monkeypatch):
        # Even if a key were set, empty retrieval must short-circuit before
        # any model construction.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
        import bdc_parser.qa.answer as ans

        def _boom(*a, **k):
            raise AssertionError("get_model must not be called on empty retrieval")

        monkeypatch.setattr(ans, "get_model", _boom)
        a = answer("anything", ticker="FDUS", _chunks=[])
        assert a.refused is True


class TestCitationsRequired:
    def test_answer_with_chunks_has_citations(self):
        chunks = [_chunk("We face credit risk and interest-rate risk.")]
        a = answer("What risks?", ticker="FDUS", _chunks=chunks, use_llm=False)
        assert a.refused is False
        assert a.has_citations()
        assert len(a.citations) == 1
        assert "FDUS 10-K" in a.citations[0]
        assert "Item 1A" in a.citations[0]

    def test_citations_appear_in_rendered_text(self):
        chunks = [_chunk("alpha risk."), _chunk("beta risk.", start=200, end=260)]
        a = answer("risks?", ticker="FDUS", _chunks=chunks, use_llm=False)
        assert "[1]" in a.text and "[2]" in a.text
        assert "Sources:" in a.text

    def test_no_llm_answer_is_still_grounded(self):
        chunks = [_chunk("The company invests in lower middle market firms.")]
        a = answer("strategy?", ticker="FDUS", _chunks=chunks, use_llm=False)
        assert a.llm_used is False
        assert a.chunks  # grounded: carries its sources
        assert "lower middle market" in a.text

    def test_every_answer_object_carries_its_sources(self):
        # The Answer dataclass cannot represent a non-refused answer without
        # the chunks it was built from.
        chunks = [_chunk("x")]
        a = answer("q", ticker="FDUS", _chunks=chunks, use_llm=False)
        assert a.chunks is chunks or a.chunks == chunks


class TestPromptContract:
    def test_prompt_numbers_each_source(self):
        chunks = [_chunk("first passage"), _chunk("second passage", start=300, end=360)]
        prompt = build_prompt("the question?", chunks)
        assert "[1]" in prompt and "[2]" in prompt
        assert "first passage" in prompt
        assert "second passage" in prompt
        assert "the question?" in prompt

    def test_prompt_instructs_grounding(self):
        prompt = build_prompt("q", [_chunk("p")])
        low = prompt.lower()
        assert "only" in low and "cite" in low


class TestLLMPath:
    def test_llm_used_when_model_available(self, monkeypatch):
        # Mock both llm_available and get_model so no network call happens but
        # the llm branch is exercised and citations are still appended.
        import bdc_parser.qa.answer as ans

        class _Resp:
            content = "Credit risk is the primary concern [1]."

        class _Model:
            def invoke(self, prompt):
                return _Resp()

        monkeypatch.setattr(ans, "llm_available", lambda: True)
        monkeypatch.setattr(ans, "get_model", lambda *a, **k: _Model())

        chunks = [_chunk("We face credit risk.")]
        a = answer("risks?", ticker="FDUS", _chunks=chunks, use_llm=True)
        assert a.llm_used is True
        assert "Credit risk" in a.text
        assert "Sources:" in a.text          # citations appended
        assert a.has_citations()
