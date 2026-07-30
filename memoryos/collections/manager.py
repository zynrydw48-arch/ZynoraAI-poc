"""AI Project Collections (Week 2): CollectionManager wires
memoryos.collections.clustering's pure algorithm to the app's actual
indexed files (Database.embedding_matrix()) and owns Collection CRUD --
mirrors how memoryos.search.engine is the thing that wires memoryos.ranking
(pure) to Database, rather than the pure module reaching into SQLite itself.
"""

from memoryos.collections.clustering import DEFAULT_EPS, DEFAULT_MIN_SAMPLES, discover_collections
from memoryos.database.db import Collection, Database

# A proposed cluster whose file set overlaps an existing auto-generated
# collection by at least this much (Jaccard similarity) is treated as
# "already discovered" and skipped -- otherwise re-running discovery after
# every reindex would recreate near-duplicate collections indefinitely.
DEFAULT_OVERLAP_THRESHOLD = 0.6


def _jaccard(a: set, b: set) -> float:
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


class CollectionManager:
    def __init__(self, database: Database):
        self._database = database

    def create_collection(
        self, name: str, description: str = "", file_paths: list[str] | None = None
    ) -> Collection:
        return self._database.create_collection(
            name=name, description=description, auto_generated=False, file_paths=file_paths
        )

    def rename_collection(self, collection_id: str, new_name: str) -> None:
        self._database.rename_collection(collection_id, new_name)

    def update_description(self, collection_id: str, description: str) -> None:
        self._database.update_collection_description(collection_id, description)

    def delete_collection(self, collection_id: str) -> None:
        self._database.delete_collection(collection_id)

    def add_files(self, collection_id: str, file_paths: list[str]) -> None:
        self._database.add_files_to_collection(collection_id, file_paths)

    def remove_files(self, collection_id: str, file_paths: list[str]) -> None:
        self._database.remove_files_from_collection(collection_id, file_paths)

    def get_collection(self, collection_id: str) -> Collection | None:
        return self._database.get_collection(collection_id)

    def list_collections(self) -> list[Collection]:
        return self._database.list_collections()

    def collections_for_file(self, file_path: str) -> list[Collection]:
        return self._database.get_collections_for_file(file_path)

    def run_auto_discovery(
        self,
        eps: float = DEFAULT_EPS,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    ) -> list[Collection]:
        """Scans every currently-indexed file and creates a new
        auto_generated collection for each newly-detected project-like
        cluster. Safe to call repeatedly (e.g. after every indexing run) --
        proposals that substantially overlap an existing auto-generated
        collection are skipped rather than duplicated, both against
        collections from earlier runs and against ones just created within
        this same call."""
        records, embeddings = self._database.embedding_matrix()
        proposals = discover_collections(records, embeddings, eps=eps, min_samples=min_samples)
        if not proposals:
            return []

        existing_file_sets = [
            set(c.file_paths) for c in self._database.list_collections() if c.auto_generated
        ]

        created = []
        for proposal in proposals:
            proposed_set = set(proposal.file_paths)
            if any(
                _jaccard(proposed_set, existing_set) >= overlap_threshold
                for existing_set in existing_file_sets
            ):
                continue
            created.append(
                self._database.create_collection(
                    name=proposal.suggested_name,
                    auto_generated=True,
                    file_paths=proposal.file_paths,
                )
            )
            existing_file_sets.append(proposed_set)
        return created
