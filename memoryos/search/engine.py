import time
from dataclasses import dataclass, field

from memoryos.database.db import Database
from memoryos.embeddings.provider import EmbeddingProvider
from memoryos.index.store import IndexStore
from memoryos.ranking.attribute_boost import compute_attribute_boost
from memoryos.ranking.reasons import build_reasons, tokenize
from memoryos.ranking.similarity import rank_by_similarity

DEFAULT_TOP_K = 10

# Bug fix: pure cosine similarity over a flattened caption/tags/colors text
# embedding can misrank on attribute-specific queries (e.g. "white dog"),
# since the embedding doesn't reliably bind an adjective to the right noun.
# Widening the candidate pool before applying memoryos.ranking.attribute_boost
# lets an exact color/object keyword match pull a record back up even if raw
# similarity alone put it just outside the naive top_k.
_CANDIDATE_MULTIPLIER = 4
_MIN_CANDIDATES = 40


def _rerank_with_attribute_boost(
    query: str,
    records: list,
    embeddings,
    query_embedding,
    top_k: int,
) -> list[tuple[int, float]]:
    query_tokens = tokenize(query)
    candidate_k = min(len(records), max(top_k * _CANDIDATE_MULTIPLIER, _MIN_CANDIDATES))
    candidates = rank_by_similarity(embeddings, query_embedding, candidate_k)

    if not query_tokens:
        return candidates[:top_k]

    boosted = [
        (idx, similarity, similarity + compute_attribute_boost(query_tokens, records[idx].metadata))
        for idx, similarity in candidates
    ]
    boosted.sort(key=lambda entry: entry[2], reverse=True)
    return [(idx, similarity) for idx, similarity, _ in boosted[:top_k]]


@dataclass
class SearchHit:
    rank: int
    filename: str
    path: str
    similarity: float
    reasons: list[str]
    # Email Search Integration Phase 2: carries the record's file_type/metadata
    # straight through so the UI (ResultCard, an email preview panel) can
    # render Subject/Sender/Date/Attachments without a second DB round-trip
    # per result -- same file_type/metadata shape build_reasons() already
    # reads (see memoryos/ranking/reasons.py's RankedRecord Protocol).
    file_type: str = ""
    metadata: dict = field(default_factory=dict)


class SearchEngine:
    """Legacy JSON/NumPy-index-backed search, kept working unchanged as a
    verified fallback (used by memoryos/cli/main.py) until the SQLite-backed
    DatabaseSearchEngine below has been fully validated."""

    def __init__(self, embedding_provider: EmbeddingProvider, index_store: IndexStore):
        self._embedding_provider = embedding_provider
        self._index_store = index_store

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
        if not self._index_store.records or self._index_store.embeddings is None:
            return []

        query_embedding = self._embedding_provider.encode([query])[0]
        ranked = _rerank_with_attribute_boost(
            query, self._index_store.records, self._index_store.embeddings, query_embedding, top_k
        )

        hits = []
        for rank, (idx, similarity) in enumerate(ranked, start=1):
            record = self._index_store.records[idx]
            hits.append(
                SearchHit(
                    rank=rank,
                    filename=record.filename,
                    path=record.path,
                    similarity=similarity,
                    reasons=build_reasons(query, record),
                    file_type=record.file_type,
                    metadata=record.metadata,
                )
            )
        return hits


class DatabaseSearchEngine:
    """SQLite-backed search for the desktop UI. Same ranking/reason logic as
    SearchEngine (shared via memoryos.ranking), just a different storage
    backend -- this is what the embedding-storage swappability promise looks
    like in practice."""

    def __init__(self, embedding_provider: EmbeddingProvider, database: Database):
        self._embedding_provider = embedding_provider
        self._database = database

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchHit]:
        start = time.time()
        records, embeddings = self._database.embedding_matrix()
        if not records or embeddings is None:
            self._database.record_search(duration_seconds=time.time() - start, result_count=0)
            return []

        query_embedding = self._embedding_provider.encode([query])[0]
        ranked = _rerank_with_attribute_boost(query, records, embeddings, query_embedding, top_k)

        hits = []
        for rank, (idx, similarity) in enumerate(ranked, start=1):
            record = records[idx]
            hits.append(
                SearchHit(
                    rank=rank,
                    filename=record.filename,
                    path=record.path,
                    similarity=similarity,
                    reasons=build_reasons(query, record),
                    file_type=record.file_type,
                    metadata=record.metadata,
                )
            )

        self._database.record_search(duration_seconds=time.time() - start, result_count=len(hits))
        return hits
