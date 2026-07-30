"""One-Click Context Summary (Week 2): a fast, fully local extractive
summarizer -- deliberately NOT an abstractive/generative summary. Every
model in this codebase either embeds (no text generation) or captions
images (BLIP, too narrow for arbitrary documents); adding a real
summarization model would mean a new multi-hundred-MB download, more
packaging complexity, and multi-second CPU generation per file, all in
tension with "fast" and this project's local-first, no-new-heavy-
dependency posture. Instead this reuses the embedding model already loaded
for search: split the document into sentences, compute their centroid
(mean-pooled embedding), and return the sentences closest to that centroid
in their original reading order -- classic centroid/TextRank-adjacent
extractive summarization. The trade-off, stated plainly: bullets are exact
sentences pulled from the text, not rewritten prose.
"""

import re

import numpy as np

from memoryos.embeddings.provider import EmbeddingProvider

# Splits after sentence-ending punctuation followed by whitespace and a
# capital letter or digit -- a lightweight heuristic, not full NLP sentence
# boundary detection (no spacy/nltk dependency for this). Good enough for
# "pick 3 salient sentences," not aiming for perfect handling of every
# abbreviation edge case.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_MIN_SENTENCE_WORDS = 4
DEFAULT_NUM_SENTENCES = 3


def split_sentences(text: str) -> list[str]:
    candidates = _SENTENCE_SPLIT_RE.split(text.strip())
    return [s.strip() for s in candidates if len(s.split()) >= _MIN_SENTENCE_WORDS]


def summarize(
    text: str,
    embedding_provider: EmbeddingProvider,
    num_sentences: int = DEFAULT_NUM_SENTENCES,
) -> list[str]:
    """Up to num_sentences sentences from `text`, in original reading
    order, chosen by cosine similarity to the mean-pooled embedding of all
    of the text's own candidate sentences (a self-contained centroid --
    no dependency on the file's separately-stored document embedding)."""
    sentences = split_sentences(text)
    if not sentences:
        return []
    if len(sentences) <= num_sentences:
        return sentences

    embeddings = embedding_provider.encode(sentences)
    centroid = embeddings.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    similarities = embeddings @ centroid
    top_indices = np.argsort(-similarities)[:num_sentences]
    ordered_indices = sorted(top_indices.tolist())
    return [sentences[i] for i in ordered_indices]
