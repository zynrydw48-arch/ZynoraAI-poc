"""Interactive entrypoint: scan + index the corpus, then a search/feedback loop.

Run with:  python -m memoryos.cli.main [--root PATH ...]
"""

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

from memoryos.embeddings.sentence_transformer_provider import SentenceTransformerProvider
from memoryos.index.store import IndexStore
from memoryos.indexing import Indexer
from memoryos.ocr.tesseract_engine import TesseractOcrEngine
from memoryos.scanner.discover import discover_files
from memoryos.search.engine import SearchEngine
from memoryos.vision.caption import Captioner
from memoryos.vision.pipeline import VisionPipeline
from memoryos.vision.tags import ObjectTagger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_DIR = PROJECT_ROOT / ".index"


@dataclass
class SessionStats:
    searches: int = 0
    marked_found: int = 0
    marked_not_found: int = 0
    latencies: list = field(default_factory=list)


def print_scan_and_index_stats(report, stats, elapsed_models_load: float) -> None:
    by_type: dict[str, int] = {}
    for f in report.files:
        by_type[f.file_type] = by_type.get(f.file_type, 0) + 1

    print("\n=== Indexing stats ===")
    print(f"Model load time: {elapsed_models_load:.1f}s")
    print(f"Files discovered: {len(report.files)} {by_type}")
    if report.skipped_known_unsupported:
        print(f"Skipped (known unsupported, e.g. legacy .ppt): {report.skipped_known_unsupported}")
    if report.skipped_unsupported:
        print(f"Skipped (other unsupported extensions): {report.skipped_unsupported}")
    print(
        f"Indexed: {stats.indexed}  |  Unchanged (cached): {stats.unchanged_skipped}  |  "
        f"Pruned (deleted files): {stats.pruned}  |  Errors: {len(stats.errors)}"
    )
    if stats.errors:
        print("Errors:")
        for path, err in stats.errors:
            print(f"  {path}: {err}")
    print(f"Indexing time: {stats.elapsed_seconds:.1f}s")


def print_hits(hits, latency: float) -> None:
    print(f"\nTop {len(hits)} results (search latency: {latency:.2f}s)")
    print("-" * 60)
    for hit in hits:
        print(f"#{hit.rank}  {hit.filename}")
        print(f"   Path: {hit.path}")
        print(f"   Similarity: {hit.similarity:.3f}")
        print("   Reasons:")
        for reason in hit.reasons:
            print(f"     - {reason}")
        print("-" * 60)


def interactive_search_loop(engine: SearchEngine, session_stats: SessionStats) -> None:
    print("\nDescribe a file from memory (or type 'quit' to exit).")
    while True:
        query = input("\n> ").strip()
        if not query:
            continue
        if query.lower() in {"quit", "exit", "q"}:
            break

        while True:
            t0 = time.time()
            hits = engine.search(query)
            latency = time.time() - t0
            session_stats.searches += 1
            session_stats.latencies.append(latency)

            if not hits:
                print("No indexed files to search yet.")
                break

            print_hits(hits, latency)

            answer = input("Was the correct file found? 1) Yes  2) No: ").strip()
            if answer == "2":
                session_stats.marked_not_found += 1
                refinement = input("Describe the file a little more: ").strip()
                if refinement:
                    query = f"{query} {refinement}"
                    continue
            else:
                session_stats.marked_found += 1
            break


def print_session_summary(session_stats: SessionStats) -> None:
    print("\n=== Session summary ===")
    print(f"Searches performed: {session_stats.searches}")
    print(f"Marked found: {session_stats.marked_found}  |  Marked not found: {session_stats.marked_not_found}")
    if session_stats.latencies:
        avg_latency = sum(session_stats.latencies) / len(session_stats.latencies)
        print(f"Average search latency: {avg_latency:.2f}s  |  Max: {max(session_stats.latencies):.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zynora AI PoC: semantic file search")
    parser.add_argument(
        "--root",
        action="append",
        dest="roots",
        help="Root directory to scan recursively (repeatable). Defaults to the project directory.",
    )
    args = parser.parse_args()
    roots = [Path(r) for r in args.roots] if args.roots else [PROJECT_ROOT]

    print("Loading models (embedding, OCR, vision)...")
    t0 = time.time()
    embedding_provider = SentenceTransformerProvider()
    ocr_engine = TesseractOcrEngine()
    vision_pipeline = VisionPipeline(ocr_engine, ObjectTagger(), Captioner())
    elapsed_models_load = time.time() - t0

    report = discover_files(roots)

    index_store = IndexStore(INDEX_DIR)
    index_store.load(embedding_model_name=embedding_provider.model_name)
    indexer = Indexer(embedding_provider, ocr_engine, vision_pipeline, index_store)
    stats = indexer.index_files(report.files)

    print_scan_and_index_stats(report, stats, elapsed_models_load)

    search_engine = SearchEngine(embedding_provider, index_store)
    session_stats = SessionStats()
    try:
        interactive_search_loop(search_engine, session_stats)
    except (EOFError, KeyboardInterrupt):
        print()

    print_session_summary(session_stats)


if __name__ == "__main__":
    main()
