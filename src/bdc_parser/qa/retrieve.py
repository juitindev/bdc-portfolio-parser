"""RAG retrieval over a BDC 10-K filing (v0 — FDUS only).

Pipeline:
    raw/<ticker>_10k_latest.html
        -> strip Schedule of Investments tables   (already structured in CSV)
        -> section-aware split by 10-K Item header
        -> ~512-token windows, ~64-token overlap, on paragraph boundaries
        -> BGE-base embeddings (768-dim) into an embedded Qdrant collection
        -> retrieve(query, ticker, k) -> ranked chunks WITH source refs

Design split (deliberate):
  * Chunking + source refs are PURE PYTHON (no torch / qdrant import). This is
    the attribution path and it is unit-tested offline.
  * Embedding + vector storage are isolated behind lazy imports so the base
    package keeps working without the `qa` extra installed. Heavy deps load
    only when you actually embed or query.

PROVENANCE IS THE POINT OF THIS SLICE: every chunk carries a SourceRef
(document id + 10-K Item/section + a stable character offset into the
filing's extracted text). retrieve() exposes that ref so it flows to
qa.answer and gets cited. A chunk cannot exist without a ref — the
dataclass requires one.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from bdc_parser.locate import find_schedule_groups
from bdc_parser.paths import cache_path

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Chunking knobs — tokens approximated by whitespace words (heuristic-first;
# keeps chunking offline-testable without loading the BGE tokenizer).
TARGET_TOKENS = 512
OVERLAP_TOKENS = 64

EMBED_MODEL = "BAAI/bge-base-en-v1.5"
EMBED_DIM = 768

# 10-K Item header, e.g. "Item 1A. Risk Factors." / "Item 7. Management's ..."
_ITEM_RE = re.compile(r"^\s*Item\s+(\d+[A-Z]?)\b[.․．]?\s*(.*)$", re.I)


# --------------------------------------------------------------------------- #
# Source attribution
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SourceRef:
    """Stable pointer back to where a chunk came from in the filing.

    This is the whole reason the slice exists: an answer built from a chunk
    can cite exactly this ref.
    """
    doc_id: str                 # e.g. "FDUS 10-K"
    ticker: str                 # e.g. "FDUS"
    item: str                   # 10-K item id, e.g. "1A", or "FRONT" (pre-Item 1)
    section: str                # human-readable section title
    char_start: int             # offset into the filing's extracted text
    char_end: int

    def cite(self) -> str:
        """Compact citation string for display / prompts."""
        return f"[{self.doc_id} | Item {self.item} ({self.section}) | chars {self.char_start}-{self.char_end}]"


@dataclass
class Chunk:
    """A unit of retrievable text plus its required source ref."""
    text: str
    ref: SourceRef

    def __post_init__(self):
        if self.ref is None:                       # belt-and-suspenders
            raise ValueError("Chunk created without a SourceRef — provenance is mandatory.")


@dataclass
class RetrievedChunk:
    """A chunk returned from retrieve(), with its similarity score."""
    text: str
    ref: SourceRef
    score: float = 0.0

    def to_dict(self) -> dict:
        d = {"text": self.text, "score": self.score, "ref": asdict(self.ref)}
        return d


# --------------------------------------------------------------------------- #
# Section-aware text extraction (pure python)
# --------------------------------------------------------------------------- #
@dataclass
class Section:
    item: str
    title: str
    text: str
    char_start: int             # offset of this section in the full extracted text


def _strip_schedule_tables(soup: BeautifulSoup) -> None:
    """Remove Schedule of Investments tables from the soup in place.

    They are already structured in data/<ticker>_schedule_full.csv, so the
    RAG corpus excludes them per the Architecture note. We reuse the same
    detector parse.py / locate.py use, so "what counts as the Schedule" stays
    consistent across the codebase.
    """
    tables = soup.find_all("table")
    groups = find_schedule_groups(str(soup))
    drop = {idx for g in groups for idx in g.tables}
    for idx in sorted(drop, reverse=True):
        if idx < len(tables):
            tables[idx].decompose()


def extract_sections(html: str, *, strip_schedule: bool = True) -> list[Section]:
    """Split a 10-K into sections keyed by Item header.

    Text before the first real "Item 1." (cover page, TOC, forward-looking
    boilerplate) is captured as a single "FRONT" section so nothing is lost.
    """
    soup = BeautifulSoup(html, "lxml")
    if strip_schedule:
        _strip_schedule_tables(soup)

    full_text = soup.get_text("\n")
    full_text = full_text.replace(" ", " ")
    lines = full_text.split("\n")

    # Locate Item-header lines. A 10-K's table of contents repeats every Item
    # title; the *body* occurrences are what we want. We take, for each item,
    # the LAST matching line (TOC entries come first, body last) so a section's
    # body is what gets chunked.
    header_idx: dict[str, int] = {}   # item -> line index (last wins)
    header_title: dict[str, str] = {}
    order: list[str] = []
    char_at_line: list[int] = []
    running = 0
    for ln in lines:
        char_at_line.append(running)
        running += len(ln) + 1        # +1 for the join "\n"

    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped or len(stripped) > 130:
            continue
        m = _ITEM_RE.match(stripped)
        if not m:
            continue
        item = m.group(1).upper()
        title = (m.group(2) or "").strip().rstrip(".") or f"Item {item}"
        if item not in header_idx:
            order.append(item)
        header_idx[item] = i
        header_title[item] = title

    # Order item bodies by their chosen line index.
    chosen = sorted(((header_idx[it], it) for it in header_idx), key=lambda x: x[0])

    sections: list[Section] = []

    # FRONT matter: everything before the first body Item header.
    first_line = chosen[0][0] if chosen else len(lines)
    front_text = "\n".join(lines[:first_line]).strip()
    if front_text:
        sections.append(Section("FRONT", "Front Matter", front_text, 0))

    for k, (line_i, item) in enumerate(chosen):
        next_line = chosen[k + 1][0] if k + 1 < len(chosen) else len(lines)
        body = "\n".join(lines[line_i:next_line]).strip()
        if not body:
            continue
        sections.append(Section(
            item=item,
            title=header_title.get(item, f"Item {item}"),
            text=body,
            char_start=char_at_line[line_i],
        ))
    return sections


# --------------------------------------------------------------------------- #
# Chunking (pure python) — carries refs
# --------------------------------------------------------------------------- #
def _paragraphs(text: str) -> list[tuple[int, str]]:
    """Split into paragraphs on blank lines; return (offset_within_section, para)."""
    out: list[tuple[int, str]] = []
    pos = 0
    for part in re.split(r"\n\s*\n", text):
        # advance pos to the real start of this part within `text`
        idx = text.find(part, pos)
        if idx < 0:
            idx = pos
        para = part.strip()
        if para:
            out.append((idx, para))
        pos = idx + len(part)
    return out


def _word_count(s: str) -> int:
    return len(s.split())


def _explode_paragraph(off: int, para: str, limit: int = TARGET_TOKENS) -> list[tuple[int, str]]:
    """Split a paragraph that exceeds `limit` words into word-windows.

    Critical for provenance: BGE truncates input at ~512 tokens, so a chunk
    larger than that would be embedded only partially while its SourceRef
    char_end claimed the whole span. Splitting here keeps every chunk's offsets
    honest about what was actually embedded. Offsets are computed by locating
    each window's text inside the original paragraph.
    """
    words = para.split()
    if len(words) <= limit:
        return [(off, para)]
    out: list[tuple[int, str]] = []
    search_from = 0
    for i in range(0, len(words), limit):
        window = " ".join(words[i:i + limit])
        # locate this window within the paragraph to get an accurate offset
        idx = para.find(words[i], search_from)
        if idx < 0:
            idx = search_from
        out.append((off + idx, window))
        search_from = idx + len(window)
    return out


def chunk_section(section: Section, doc_id: str, ticker: str) -> list[Chunk]:
    """Chunk one section into ~TARGET_TOKENS windows on paragraph boundaries.

    Overlap (~OVERLAP_TOKENS) is carried by replaying trailing paragraphs of
    the previous window into the next. Every emitted chunk gets a SourceRef
    whose char offsets are absolute into the filing's extracted text.
    """
    raw_paras = _paragraphs(section.text)
    if not raw_paras:
        return []

    # Pre-split any paragraph larger than the target so no single unit can
    # exceed the embedding window. This is what keeps char offsets honest.
    paras: list[tuple[int, str]] = []
    for off, para in raw_paras:
        paras.extend(_explode_paragraph(off, para))

    chunks: list[Chunk] = []
    cur: list[tuple[int, str]] = []
    cur_tokens = 0

    def emit(group: list[tuple[int, str]]):
        if not group:
            return
        start_off = group[0][0]
        last_off, last_para = group[-1]
        end_off = last_off + len(last_para)
        text = "\n\n".join(p for _, p in group).strip()
        if not text:
            return
        ref = SourceRef(
            doc_id=doc_id,
            ticker=ticker,
            item=section.item,
            section=section.title,
            char_start=section.char_start + start_off,
            char_end=section.char_start + end_off,
        )
        chunks.append(Chunk(text=text, ref=ref))

    for off, para in paras:
        ptok = _word_count(para)
        # A single paragraph larger than the target becomes its own chunk.
        if ptok >= TARGET_TOKENS and cur:
            emit(cur)
            cur, cur_tokens = [], 0
        cur.append((off, para))
        cur_tokens += ptok
        if cur_tokens >= TARGET_TOKENS:
            emit(cur)
            # build overlap tail for the next window
            tail: list[tuple[int, str]] = []
            tok = 0
            for item in reversed(cur):
                tok += _word_count(item[1])
                tail.insert(0, item)
                if tok >= OVERLAP_TOKENS:
                    break
            # avoid an overlap that is the entire window (would loop)
            cur = tail if len(tail) < len(cur) else []
            cur_tokens = sum(_word_count(p) for _, p in cur)

    emit(cur)
    return chunks


# The filing's front matter carries a large machine-readable layer: XBRL inline
# tags ("fdus:CihIntermediateLlcMember", "us-gaap:..."), bare CIK numbers, and
# date soup ("2025-12-31 0001513363 ..."). These embed poorly and pollute
# retrieval. The cleanest separator on real FDUS data is the PROSE FRACTION —
# the share of whitespace tokens that are ordinary words (alphabetic, <=20
# chars). Real narrative scores 0.85-0.94; XBRL/CIK/date soup scores 0.0-0.46.
# A 0.55 cut collapses front-matter noise (53 -> 8 chunks) while keeping every
# Item-1/1A/7/8 narrative chunk. Measured, not guessed — see ROADMAP for the
# corpus-cleaning follow-up.
_PROSE_THRESHOLD = 0.55


def _prose_fraction(text: str) -> float:
    toks = text.split()
    if not toks:
        return 0.0
    words = sum(1 for w in toks if w.isalpha() and len(w) <= 20)
    return words / len(toks)


def _is_xbrl_noise(text: str) -> bool:
    """True if a chunk is dominated by machine-readable (non-prose) tokens."""
    return _prose_fraction(text) < _PROSE_THRESHOLD


def build_chunks(ticker: str, *, html: str | None = None,
                 drop_noise: bool = True) -> list[Chunk]:
    """Full chunking pass for a ticker. Pure python — no embedding.

    `drop_noise=True` filters chunks dominated by non-prose tokens (XBRL tags,
    CIK numbers, date soup) so the retrieval corpus is real narrative text. The
    dropped count is observable via the difference in returned length when
    toggled.
    """
    doc_id = f"{ticker.upper()} 10-K"
    if html is None:
        path = cache_path(ticker)
        if not path.exists():
            raise FileNotFoundError(
                f"No cached filing at {path}. Run `bdc-parse fetch {ticker}` first."
            )
        html = path.read_text(encoding="utf-8")
    sections = extract_sections(html)
    chunks: list[Chunk] = []
    for sec in sections:
        chunks.extend(chunk_section(sec, doc_id, ticker.upper()))
    if drop_noise:
        chunks = [c for c in chunks if not _is_xbrl_noise(c.text)]
    return chunks


# --------------------------------------------------------------------------- #
# Embedding + vector store (lazy heavy imports)
# --------------------------------------------------------------------------- #
_MODEL_CACHE: dict[str, object] = {}


def embeddings_available() -> bool:
    """True if the qa extra (sentence-transformers + qdrant-client) is importable."""
    import importlib.util as u
    return bool(u.find_spec("sentence_transformers")) and bool(u.find_spec("qdrant_client"))


def _get_embedder():
    if EMBED_MODEL not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer
        _MODEL_CACHE[EMBED_MODEL] = SentenceTransformer(EMBED_MODEL)
    return _MODEL_CACHE[EMBED_MODEL]


def _embed(texts: list[str]):
    model = _get_embedder()
    # BGE retrieval convention: queries get a short instruction prefix; passages
    # are embedded as-is. normalize so we can use cosine/dot interchangeably.
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def _query_prefix(query: str) -> str:
    return f"Represent this sentence for searching relevant passages: {query}"


class FilingIndex:
    """An embedded-Qdrant index over one filing's chunks.

    Built in-memory by default (Qdrant ':memory:' / location=None). Optionally
    persisted to a local path for reuse, but v0 just rebuilds per process —
    FDUS is ~a few hundred chunks, seconds to embed.
    """

    def __init__(self, ticker: str, *, location: str | None = None):
        self.ticker = ticker.upper()
        self.collection = f"{self.ticker.lower()}_10k"
        self._chunks: list[Chunk] = []
        self._client = None
        self._location = location

    def _client_lazy(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            # location=":memory:" -> embedded, no server, no disk.
            self._client = QdrantClient(location=self._location or ":memory:")
        return self._client

    def build(self, chunks: list[Chunk] | None = None) -> "FilingIndex":
        from qdrant_client.models import Distance, VectorParams, PointStruct

        self._chunks = chunks if chunks is not None else build_chunks(self.ticker)
        if not self._chunks:
            raise ValueError(f"No chunks produced for {self.ticker} — nothing to index.")

        client = self._client_lazy()
        if client.collection_exists(self.collection):
            client.delete_collection(self.collection)
        client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        vectors = _embed([c.text for c in self._chunks])
        points = [
            PointStruct(
                id=i,
                vector=vectors[i].tolist(),
                payload={"text": c.text, "ref": asdict(c.ref)},
            )
            for i, c in enumerate(self._chunks)
        ]
        client.upsert(collection_name=self.collection, points=points)
        return self

    def search(self, query: str, k: int = 10) -> list[RetrievedChunk]:
        client = self._client_lazy()
        qvec = _embed([_query_prefix(query)])[0]
        result = client.query_points(
            collection_name=self.collection,
            query=qvec.tolist(),
            limit=k,
        )
        out: list[RetrievedChunk] = []
        for h in result.points:
            payload = h.payload or {}
            ref_d = payload.get("ref", {})
            ref = SourceRef(**ref_d)
            out.append(RetrievedChunk(text=payload.get("text", ""), ref=ref, score=float(h.score)))
        return out


# process-level cache so repeated `ask` calls in one run don't re-embed
_INDEX_CACHE: dict[str, FilingIndex] = {}


def get_index(ticker: str) -> FilingIndex:
    key = ticker.upper()
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = FilingIndex(key).build()
    return _INDEX_CACHE[key]


def retrieve(query: str, ticker: str, k: int = 10) -> list[RetrievedChunk]:
    """Retrieve the top-k chunks for a query over a ticker's 10-K.

    Returns a list of RetrievedChunk, each carrying a SourceRef so the answer
    layer can cite it. Returns [] only if the index is empty; an empty return
    is the signal qa.answer uses to REFUSE rather than hallucinate.

    Raises RuntimeError if the qa extra is not installed (so the caller can
    surface a clear "pip install .[qa]" message rather than a deep ImportError).
    """
    if not embeddings_available():
        raise RuntimeError(
            "RAG retrieval needs the qa extra. Install with: pip install -e .[qa]"
        )
    index = get_index(ticker)
    return index.search(query, k=k)
