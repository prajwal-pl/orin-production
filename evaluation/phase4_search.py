"""Run the versioned imaginary meeting-preparation retrieval check."""

import json
import tempfile
from pathlib import Path

from orchestration.search import SearchIndex
from orchestration.sync import SyncStore


FIXTURE = Path(__file__).parent / "fixtures" / "phase4_search_v1.json"


def main() -> None:
    scenario = json.loads(FIXTURE.read_text())
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        index = SearchIndex(SyncStore(root / "sync.db"))
        index.ingest_evidence(scenario["owner"], scenario["evidence"])
        approved = root / "approved"
        approved.mkdir()
        (approved / "meeting.md").write_text(scenario["local_note"])
        index.index_local_files(scenario["owner"], approved, ["meeting.md"])
        metadata = index.search(scenario["owner"], scenario["query"])
        all_hits = index.search(scenario["owner"], scenario["query"], include_content=True)
        expected = set(scenario["expected_metadata_ids"])
        retrieved = {hit.source_id for hit in metadata}
        recall = len(retrieved & expected) / len(expected)
        assert recall == 1.0
        assert {hit.source for hit in all_hits} == set(scenario["expected_with_content_sources"])
        assert index.search("another-owner", scenario["query"], include_content=True) == []
        print(f"{scenario['version']}: metadata recall={recall:.2f}; "
              f"metadata sources={len(metadata)}; with approved local content={len(all_hits)}")


if __name__ == "__main__":
    main()
