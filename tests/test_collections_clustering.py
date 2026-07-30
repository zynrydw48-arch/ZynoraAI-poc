"""AI Project Collections (Week 2): the pure clustering algorithm, tested
against synthetic embeddings only -- no Database, no real ML model, same
approach tests/test_ranking.py already uses for rank_by_similarity."""

import numpy as np
import pytest

from memoryos.collections.clustering import discover_collections
from memoryos.database.db import FileRecord


def _normalize(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def _record(path: str, semantic_text: str, file_type: str = "pdf", metadata: dict | None = None) -> FileRecord:
    return FileRecord(
        id=f"id-{path}",
        path=path,
        filename=path,
        extension=f".{file_type}",
        file_type=file_type,
        semantic_text=semantic_text,
        metadata=metadata or {},
    )


def test_two_similar_and_one_dissimilar_file_cluster_correctly():
    # Two near-identical vectors (budget + pitch deck for the same project)
    # and one orthogonal one (an unrelated file).
    budget = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
    pitch_deck = np.array([0.88, 0.12, 0.0, 0.0], dtype=np.float32)
    unrelated = np.array([0.0, 0.0, 0.9, 0.1], dtype=np.float32)
    embeddings = _normalize(np.vstack([budget, pitch_deck, unrelated]))

    records = [
        _record("budget.xlsx", "Project Delta quarterly budget spreadsheet"),
        _record("pitch.pptx", "Project Delta pitch deck presentation"),
        _record("vacation.jpg", "a photo of a beach", file_type="image"),
    ]

    proposals = discover_collections(records, embeddings, eps=0.2, min_samples=2)

    assert len(proposals) == 1
    assert set(proposals[0].file_paths) == {"budget.xlsx", "pitch.pptx"}
    assert "vacation.jpg" not in proposals[0].file_paths


def test_all_dissimilar_files_produce_no_proposals():
    embeddings = _normalize(
        np.array(
            [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
    )
    records = [_record(f"f{i}.pdf", f"unrelated content {i}") for i in range(3)]

    proposals = discover_collections(records, embeddings, eps=0.2, min_samples=2)

    assert proposals == []


def test_singleton_never_appears_in_any_proposal():
    close_a = np.array([0.9, 0.1], dtype=np.float32)
    close_b = np.array([0.88, 0.12], dtype=np.float32)
    lone = np.array([0.0, 1.0], dtype=np.float32)
    embeddings = _normalize(np.vstack([close_a, close_b, lone]))
    records = [
        _record("a.pdf", "quarterly report alpha"),
        _record("b.pdf", "quarterly report alpha two"),
        _record("c.pdf", "completely different"),
    ]

    proposals = discover_collections(records, embeddings, eps=0.2, min_samples=2)

    assert len(proposals) == 1
    all_clustered_paths = {p for prop in proposals for p in prop.file_paths}
    assert "c.pdf" not in all_clustered_paths


def _borderline_email_embeddings() -> np.ndarray:
    # Angularly separated enough that raw cosine distance (~0.22) safely
    # exceeds the shared-sender discount (0.15) with margin to spare, so
    # eps = raw_distance - 0.10 stays comfortably positive while still being
    # smaller than the discount -- i.e. only reachable *with* the discount.
    email_a = np.array([0.9, 0.1], dtype=np.float32)
    email_b = np.array([0.5, 0.5], dtype=np.float32)
    return _normalize(np.vstack([email_a, email_b]))


def test_shared_email_sender_pulls_a_borderline_pair_together():
    # Two emails from the same sender, placed just outside a tight eps by
    # raw cosine distance alone -- the shared-sender discount (see
    # clustering._SHARED_SENDER_DISTANCE_DISCOUNT) should be enough to pull
    # them into one cluster; without it they'd land as noise (see the next
    # test, which uses the identical vectors/eps but different senders).
    embeddings = _borderline_email_embeddings()
    records = [
        _record(
            "a.eml",
            "invoice for services rendered",
            file_type="email",
            metadata={"structural": {"email_sender": "client@example.com"}},
        ),
        _record(
            "b.eml",
            "follow up on invoice payment",
            file_type="email",
            metadata={"structural": {"email_sender": "client@example.com"}},
        ),
    ]
    raw_cosine_distance = 1.0 - float(embeddings[0] @ embeddings[1])
    eps = raw_cosine_distance - 0.10
    assert eps > 0  # sanity: the test vectors must keep this comfortably positive

    proposals = discover_collections(records, embeddings, eps=eps, min_samples=2)

    assert len(proposals) == 1
    assert set(proposals[0].file_paths) == {"a.eml", "b.eml"}


def test_different_email_senders_do_not_get_the_discount():
    embeddings = _borderline_email_embeddings()
    records = [
        _record(
            "a.eml",
            "invoice for services rendered",
            file_type="email",
            metadata={"structural": {"email_sender": "client-one@example.com"}},
        ),
        _record(
            "b.eml",
            "follow up on invoice payment",
            file_type="email",
            metadata={"structural": {"email_sender": "client-two@example.com"}},
        ),
    ]
    raw_cosine_distance = 1.0 - float(embeddings[0] @ embeddings[1])
    eps = raw_cosine_distance - 0.10
    assert eps > 0

    proposals = discover_collections(records, embeddings, eps=eps, min_samples=2)

    assert proposals == []


def test_suggested_name_uses_shared_keyword_across_members():
    embeddings = _normalize(
        np.array([[0.9, 0.1], [0.88, 0.12], [0.86, 0.14]], dtype=np.float32)
    )
    records = [
        _record("a.xlsx", "Zephyr project budget spreadsheet"),
        _record("b.pptx", "Zephyr project pitch deck"),
        _record("c.docx", "Zephyr project meeting notes"),
    ]

    proposals = discover_collections(records, embeddings, eps=0.2, min_samples=2)

    assert len(proposals) == 1
    assert "Zephyr" in proposals[0].suggested_name


def test_suggested_name_falls_back_when_no_shared_keyword():
    embeddings = _normalize(
        np.array([[0.9, 0.1], [0.88, 0.12]], dtype=np.float32)
    )
    records = [
        _record("a.pdf", "aaa bbb ccc"),
        _record("b.pdf", "xxx yyy zzz"),
    ]

    proposals = discover_collections(records, embeddings, eps=0.2, min_samples=2)

    assert len(proposals) == 1
    assert "related pdf files" in proposals[0].suggested_name


def test_empty_records_returns_empty_list():
    assert discover_collections([], None) == []


def test_none_embeddings_returns_empty_list():
    records = [_record("a.pdf", "x")]
    assert discover_collections(records, None) == []


def test_fewer_records_than_min_samples_returns_empty_list():
    embeddings = _normalize(np.array([[1.0, 0.0]], dtype=np.float32))
    records = [_record("a.pdf", "x")]
    assert discover_collections(records, embeddings, min_samples=2) == []
