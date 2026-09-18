"""Regenerate the wholly synthetic receipt golden from actual historical code.

Not run by the suite. Requires the two named commits in local Git history.
Run with TMPDIR=/private/tmp on macOS; no network, model, or real vault is used.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests/goldens/classifier_receipt_identity.json"
PRODUCERS = {
    "grouped_v306": "809cd3f1686756db0d7cb2a6eb8edbfa3c995cf9",
    "split_v309": "b00947dbed57e7106524463ea3902f62d3ce4437",
}
NOW = "2026-09-17T00:00:00Z"
STEM = "synthetic-envelope"
SOURCE_PATH = "sources/manual/synthetic-envelope.md"
STORY = "I found an envelope after the winter move, while I worked at Acorn."
EVENT = {
    "title": "Finding an envelope", "description": STORY, "places": [],
    "date": {"anchor_ref": "the winter move", "relation": "after"},
    "timeline_relation": {
        "relation": "within", "candidate_id": "node:synthetic-acorn-job",
        "entity_refs": ["organization/acorn"],
        "evidence": {"quote": "while I worked at Acorn",
                     "start": STORY.index("while"), "end": len(STORY) - 1},
    },
}

# Each subprocess imports the WHOLE archived system at its own revision and
# calls its real migration/writer, including telling and document declarations.
GENERATE = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "system"))
import classifier_claims as cc
import temporal_store as store
args = json.load(sys.stdin)
root = Path("vault").resolve()
path = root / args["source_path"]
path.parent.mkdir(parents=True)
source_text = ("---\ntitle: Synthetic envelope\ntype: story\n"
    "source_id: story:synthetic-envelope\ncontent_sha256: "
    + store.payload_sha256(args["story"]) + "\n---\n\n" + args["story"] + "\n")
path.write_text(source_text, encoding="utf-8")
directory = root / "state/classifications"
directory.mkdir(parents=True)
classification = {"source_path": args["source_path"], "people": [], "places": [],
    "time_periods": [], "themes": [], "events": [args["event"]]}
(directory / (args["stem"] + ".json")).write_text(json.dumps(classification))
cc.migrate_classifier_moments(root, classifications_dir=directory,
    dry_run=False, publish=False, now=args["now"])
receipts = [json.loads((root / p).read_text()) for p in store.receipt_relative_paths(root)]
print(json.dumps({"classification": classification, "source_text": source_text,
    "receipts": receipts}, sort_keys=True))
'''


def main() -> None:
    result = {"provenance": {
        "synthetic_only": True,
        "generator": "tests/generate_classifier_receipt_identity.py",
        "method": "git archive system at each producer commit; actual migrate_classifier_moments publish=False",
        "producers": PRODUCERS,
        "now": NOW,
    }, "stem": STEM, "source_path": SOURCE_PATH}
    for label, revision in PRODUCERS.items():
        archive = subprocess.check_output(["git", "archive", revision, "system"], cwd=ROOT)
        with tempfile.TemporaryDirectory(prefix="synthetic-receipt-generator-") as temporary:
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(temporary, filter="data")
            output = subprocess.check_output(
                [sys.executable, "-B", "-c", GENERATE], cwd=temporary,
                input=json.dumps({"source_path": SOURCE_PATH, "story": STORY,
                    "event": EVENT, "stem": STEM, "now": NOW}).encode(),
            )
            generated = json.loads(output)
            for key in ("classification", "source_text"):
                if key in result:
                    assert result[key] == generated[key]
                result[key] = generated[key]
            result[label] = generated["receipts"]
    DESTINATION.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
