"""One-Click Context Summary: the pure extractive summarizer, tested
against a fake embedding provider with hand-picked vectors (same approach
tests/test_ranking.py and tests/test_collections_clustering.py already use
for their own algorithms) -- no real ML model needed."""

import numpy as np

from memoryos.summarization.summarizer import split_sentences, summarize


class DictEmbeddingProvider:
    """Maps exact sentence strings to pre-chosen vectors, so tests can
    control precisely which sentences are "similar" vs "outliers"."""

    def __init__(self, vectors: dict[str, np.ndarray]):
        self._vectors = vectors

    @property
    def dimension(self) -> int:
        return 2

    @property
    def model_name(self) -> str:
        return "fake"

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._vectors[t] for t in texts])


def test_split_sentences_splits_on_terminal_punctuation():
    text = "This is the first sentence. This is the second one! Is this the third?"
    sentences = split_sentences(text)
    assert sentences == [
        "This is the first sentence.",
        "This is the second one!",
        "Is this the third?",
    ]


def test_split_sentences_filters_short_fragments():
    text = "Hi. This is a real sentence with enough words. Ok."
    sentences = split_sentences(text)
    assert sentences == ["This is a real sentence with enough words."]


def test_split_sentences_empty_text_returns_empty_list():
    assert split_sentences("   ") == []


def test_summarize_returns_all_sentences_when_fewer_than_requested():
    provider = DictEmbeddingProvider({})
    text = "First sentence goes here now. Second sentence follows after that."
    result = summarize(text, provider, num_sentences=3)
    assert result == [
        "First sentence goes here now.",
        "Second sentence follows after that.",
    ]


def test_summarize_returns_empty_list_for_empty_text():
    provider = DictEmbeddingProvider({})
    assert summarize("", provider) == []


def test_summarize_picks_sentences_closest_to_centroid():
    # Three sentences cluster tightly around [1, 0]; two are outliers near
    # [0, 1] -- the centroid of all five leans toward the majority group,
    # so the three majority sentences should be the ones picked.
    sentences = {
        "Alpha sentence about the main topic here.": np.array([1.0, 0.0]),
        "Beta sentence about the main topic too.": np.array([0.95, 0.05]),
        "Gamma sentence also on the main topic.": np.array([0.9, 0.1]),
        "Delta sentence about something unrelated.": np.array([0.0, 1.0]),
        "Epsilon sentence also unrelated to the rest.": np.array([0.05, 0.95]),
    }
    text = " ".join(sentences.keys())
    provider = DictEmbeddingProvider(sentences)

    result = summarize(text, provider, num_sentences=3)

    assert set(result) == {
        "Alpha sentence about the main topic here.",
        "Beta sentence about the main topic too.",
        "Gamma sentence also on the main topic.",
    }


def test_summarize_preserves_original_reading_order_not_similarity_order():
    # Verified by direct computation (not eyeballed): with these four
    # vectors, sentence D (position 3, last) has the *highest* raw
    # similarity to the centroid and sentence A (position 0, first) the
    # second-highest -- both ahead of B/C. A naive "return in
    # similarity-rank order" implementation would emit [D, A]; the correct
    # output, sorted back to original reading order, is [A, D].
    sentence_a = "First sentence about the shared main topic here."
    sentence_b = "Second sentence also about that same main topic."
    sentence_c = "Third sentence about something else entirely now."
    sentence_d = "Fourth sentence also about the shared main topic."
    vectors = {
        sentence_a: np.array([0.85, 0.15]),
        sentence_b: np.array([0.8, 0.2]),
        sentence_c: np.array([0.0, 1.0]),
        sentence_d: np.array([1.0, 0.0]),
    }
    text = f"{sentence_a} {sentence_b} {sentence_c} {sentence_d}"
    provider = DictEmbeddingProvider(vectors)

    result = summarize(text, provider, num_sentences=2)

    assert result == [sentence_a, sentence_d]


def test_summarize_respects_num_sentences_argument():
    sentences = {
        f"This is generated sentence number {i} here.": np.array([1.0, float(i) * 0.01])
        for i in range(6)
    }
    text = " ".join(sentences.keys())
    provider = DictEmbeddingProvider(sentences)

    result = summarize(text, provider, num_sentences=2)

    assert len(result) == 2
