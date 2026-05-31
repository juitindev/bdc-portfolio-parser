"""Tests for qa.retrieve — chunking + source attribution.

Offline by default: these exercise the PURE-PYTHON chunking and provenance
paths. No embedding model is loaded and no Qdrant index is built — those need
the `qa` extra and are slow; the attribution contract does not depend on them.
"""
import pytest

from bdc_parser.qa.retrieve import (
    SourceRef,
    Chunk,
    Section,
    extract_sections,
    chunk_section,
    build_chunks,
    _paragraphs,
    _is_xbrl_noise,
)


# A tiny synthetic 10-K: front matter, a body Item 1 and Item 1A, plus a
# Schedule-of-Investments-looking table that must be excluded.
SAMPLE_HTML = """
<html><body>
<p>FORWARD-LOOKING STATEMENTS. This annual report contains forward-looking
statements within the meaning of the federal securities laws.</p>

<p>Item 1. Business.</p>
<p>We are a business development company. {para1}</p>
<p>{para2}</p>

<p>Item 1A. Risk Factors.</p>
<p>Investing in our securities involves risk. {para3}</p>

<table>
    <tr><td>Portfolio Company (a)</td><td>Industry</td>
        <td>Investment Type</td><td>Rate</td></tr>
    <tr><td>Investment Type</td><td></td><td></td><td></td></tr>
    <tr><td>Acme Corp</td><td>Manufacturing</td></tr>
    <tr><td>First Lien Debt</td><td>(S+7.75%)</td><td>11.71%</td>
        <td>1/15/2024</td><td>1/15/2029</td><td>$</td><td>1,000</td>
        <td>$</td><td>990</td><td>$</td><td>1,050</td></tr>
    <tr><td>First Lien Debt</td><td>(S+7.50%)</td><td>11.50%</td>
        <td>2/15/2024</td><td>1/15/2029</td><td>$</td><td>500</td>
        <td>$</td><td>495</td><td>$</td><td>520</td></tr>
    <tr><td>First Lien Debt</td><td>(S+8.00%)</td><td>12.00%</td>
        <td>3/15/2024</td><td>1/15/2029</td><td>$</td><td>200</td>
        <td>$</td><td>198</td><td>$</td><td>205</td></tr>
</table>
</body></html>
""".format(
    para1=" ".join(["alpha"] * 300),
    para2=" ".join(["beta"] * 300),
    para3=" ".join(["gamma"] * 50),
)


class TestSourceRef:
    def test_cite_string_contains_doc_item_and_offsets(self):
        ref = SourceRef("FDUS 10-K", "FDUS", "1A", "Risk Factors", 100, 250)
        s = ref.cite()
        assert "FDUS 10-K" in s
        assert "Item 1A" in s
        assert "Risk Factors" in s
        assert "100" in s and "250" in s

    def test_chunk_requires_a_ref(self):
        with pytest.raises((ValueError, TypeError)):
            Chunk(text="orphan text", ref=None)


class TestSectioning:
    def test_splits_by_item_header(self):
        sections = extract_sections(SAMPLE_HTML)
        items = {s.item for s in sections}
        assert "1" in items
        assert "1A" in items

    def test_front_matter_captured(self):
        sections = extract_sections(SAMPLE_HTML)
        front = [s for s in sections if s.item == "FRONT"]
        assert front, "front matter before Item 1 should be its own section"
        assert "forward-looking" in front[0].text.lower()

    def test_schedule_table_excluded_from_corpus(self):
        # The portfolio-company schedule table must NOT leak into any section.
        sections = extract_sections(SAMPLE_HTML, strip_schedule=True)
        joined = " ".join(s.text for s in sections)
        assert "Acme Corp" not in joined
        assert "First Lien Debt" not in joined

    def test_schedule_present_when_not_stripped(self):
        # Sanity: the table really is in the document; stripping is what removes it.
        sections = extract_sections(SAMPLE_HTML, strip_schedule=False)
        joined = " ".join(s.text for s in sections)
        assert "Acme Corp" in joined


class TestChunking:
    def test_chunks_carry_source_refs(self):
        chunks = build_chunks("FDUS", html=SAMPLE_HTML)
        assert chunks, "expected at least one chunk"
        for c in chunks:
            assert isinstance(c.ref, SourceRef)
            assert c.ref.doc_id == "FDUS 10-K"
            assert c.ref.ticker == "FDUS"
            assert c.ref.item  # non-empty
            assert c.ref.char_end >= c.ref.char_start

    def test_ref_item_matches_source_section(self):
        # A chunk whose text is the risk-factors content must be tagged Item 1A.
        chunks = build_chunks("FDUS", html=SAMPLE_HTML)
        risk = [c for c in chunks if "gamma" in c.text]
        assert risk, "risk-factors chunk not found"
        assert all(c.ref.item == "1A" for c in risk)

    def test_large_section_produces_multiple_chunks_with_overlap(self):
        # Item 1 has two ~300-word paragraphs => exceeds the 512-token target,
        # so it must split into >1 chunk.
        sec = [s for s in extract_sections(SAMPLE_HTML) if s.item == "1"][0]
        chunks = chunk_section(sec, "FDUS 10-K", "FDUS")
        assert len(chunks) >= 2
        # overlap: some text from an earlier chunk reappears in the next
        joined_first = chunks[0].text
        assert any(tok in joined_first for tok in ("alpha", "beta"))

    def test_offsets_are_absolute_into_section(self):
        sec = Section("1", "Business", "para one.\n\npara two.", char_start=1000)
        chunks = chunk_section(sec, "FDUS 10-K", "FDUS")
        assert chunks
        # char_start must be offset by the section's own char_start (>=1000)
        assert chunks[0].ref.char_start >= 1000


class TestParagraphs:
    def test_blank_line_split(self):
        paras = _paragraphs("one\n\ntwo\n\nthree")
        assert [p for _, p in paras] == ["one", "two", "three"]

    def test_offsets_increase(self):
        paras = _paragraphs("aaa\n\nbbb")
        offs = [o for o, _ in paras]
        assert offs == sorted(offs)


class TestXbrlNoiseFilter:
    def test_xbrl_soup_flagged_as_noise(self):
        noise = ("2025-12-31 0001513363 fdus:CihIntermediateLlcMember "
                 "us-gaap:InvestmentUnaffiliatedIssuerMember srt:MinimumMember "
                 "dei:EntityCentralIndexKey country:US")
        assert _is_xbrl_noise(noise) is True

    def test_date_and_cik_soup_flagged_as_noise(self):
        # The real front-matter noise is mostly dates + CIK numbers with only a
        # few colon-tags, which a tag-ratio heuristic misses but the prose
        # fraction catches.
        noise = ("2/21/2023 2024-01-01 2024-12-31 0001513363 6/26/2023 "
                 "2025-01-01 2025-12-31 0001513363 900,000 11/25/2019 "
                 "fdus:BusinessServicesMember")
        assert _is_xbrl_noise(noise) is True

    def test_real_prose_not_flagged(self):
        prose = ("Fidus Investment Corporation provides customized debt and "
                 "equity financing solutions to lower middle-market companies "
                 "with revenues between $10 million and $150 million.")
        assert _is_xbrl_noise(prose) is False

    def test_empty_is_noise(self):
        assert _is_xbrl_noise("") is True

    def test_build_chunks_drops_noise(self):
        # A document whose front matter is XBRL soup should yield fewer chunks
        # with drop_noise=True than without.
        html = """
        <html><body>
        <p>Item 1. Business.</p>
        <p>{prose}</p>
        <p>{soup}</p>
        </body></html>
        """.format(
            prose=" ".join(["Fidus", "invests", "in", "lower", "middle", "market"] * 20),
            soup=" ".join(["fdus:CihIntermediateLlcMember", "us-gaap:Member"] * 60),
        )
        kept = build_chunks("FDUS", html=html, drop_noise=True)
        allc = build_chunks("FDUS", html=html, drop_noise=False)
        assert len(kept) < len(allc)
        assert all(not _is_xbrl_noise(c.text) for c in kept)
