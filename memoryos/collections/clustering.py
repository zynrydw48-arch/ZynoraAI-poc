"""AI Project Collections (Week 2): local, offline clustering of indexed
files into candidate "project collections" -- e.g. grouping a budget sheet,
a pitch deck, and a client's emails that all belong to the same project.

Pure function over the same (records, embeddings) shape
memoryos.database.db.Database.embedding_matrix() already returns -- no DB
dependency here, no new embedding computation, and independently testable
with synthetic vectors (matching memoryos.ranking.similarity's approach).

Algorithm: DBSCAN over cosine distance -- chosen over a partition-everything
algorithm (k-means, agglomerative-to-completion) specifically because DBSCAN
labels sparse/unrelated files as noise instead of forcing every file into
some cluster, which is what "suggest project collections" out of an
arbitrary personal file corpus actually needs (most files won't belong to
any detected project). One concrete "context trigger" from the spec is
layered on top of pure vector distance: files sharing the same email sender
get a distance discount, so a client's emails cluster together even when
their wording varies a lot.

Cluster naming is a local heuristic (most frequent shared non-stopword
token across member semantic_text, reusing memoryos.ranking.reasons'
tokenizer) -- no LLM call, keeps this fully offline.
"""

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN

from memoryos.database.db import FileRecord
from memoryos.ranking.reasons import tokenize

DEFAULT_EPS = 0.35
DEFAULT_MIN_SAMPLES = 2

# Distance (cosine distance ranges 0..2) subtracted for a shared context
# signal, clamped to >= 0 -- deliberately small relative to DEFAULT_EPS so
# it nudges borderline pairs together rather than forcing unrelated content
# into one cluster purely because two emails share a sender.
_SHARED_SENDER_DISTANCE_DISCOUNT = 0.15

_MIN_NAME_TOKEN_COVERAGE = 0.5  # a token must appear in >=50% of members' text
_MAX_NAME_TOKENS = 2


@dataclass
class ProposedCollection:
    member_indices: list[int]
    file_paths: list[str]
    suggested_name: str


def _email_senders(records: list[FileRecord]) -> np.ndarray:
    return np.array(
        [
            (r.metadata.get("structural", {}).get("email_sender") or "")
            if r.file_type == "email"
            else ""
            for r in records
        ],
        dtype=object,
    )


def _build_distance_matrix(records: list[FileRecord], embeddings: np.ndarray) -> np.ndarray:
    """Cosine distance (embeddings are already L2-normalized -- see
    memoryos.ranking.similarity's docstring), discounted for the shared-
    sender context trigger. Fully vectorized: a Python-level double loop
    here would be O(n^2) in pure Python on top of the already-O(n^2)
    memory cost, and this needs to stay fast for a corpus of thousands of
    files."""
    similarity = embeddings @ embeddings.T
    distance = 1.0 - similarity

    senders = _email_senders(records)
    has_sender = senders != ""
    same_sender = (
        (senders[:, None] == senders[None, :]) & has_sender[:, None] & has_sender[None, :]
    )
    distance = np.where(same_sender, distance - _SHARED_SENDER_DISTANCE_DISCOUNT, distance)

    np.fill_diagonal(distance, 0.0)
    # Floating-point noise (and the discount subtraction) can push a few
    # entries slightly negative -- DBSCAN's precomputed-metric path requires
    # a non-negative matrix.
    np.clip(distance, 0.0, None, out=distance)
    return distance


def _suggest_name(records: list[FileRecord], member_indices: list[int]) -> str:
    token_counts: dict[str, int] = {}
    for idx in member_indices:
        for token in set(tokenize(records[idx].semantic_text)):
            token_counts[token] = token_counts.get(token, 0) + 1

    min_count = max(2, int(len(member_indices) * _MIN_NAME_TOKEN_COVERAGE))
    candidates = [t for t, count in token_counts.items() if count >= min_count]
    candidates.sort(key=lambda t: (-token_counts[t], t))

    if candidates:
        return " ".join(t.title() for t in candidates[:_MAX_NAME_TOKENS])

    file_type = records[member_indices[0]].file_type
    return f"{len(member_indices)} related {file_type} files"


def discover_collections(
    records: list[FileRecord],
    embeddings: np.ndarray | None,
    eps: float = DEFAULT_EPS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list[ProposedCollection]:
    """Groups records into candidate project collections. A record with no
    close relatives is simply absent from the result (DBSCAN noise), not
    forced into a singleton collection of its own."""
    if embeddings is None or len(records) < min_samples:
        return []

    distance_matrix = _build_distance_matrix(records, embeddings)
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(
        distance_matrix
    )

    clusters: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        if label == -1:
            continue
        clusters.setdefault(label, []).append(idx)

    return [
        ProposedCollection(
            member_indices=member_indices,
            file_paths=[records[i].path for i in member_indices],
            suggested_name=_suggest_name(records, member_indices),
        )
        for member_indices in clusters.values()
    ]
