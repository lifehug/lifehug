"""Offline synthetic apply benchmark; no private vault or model is accepted.

Run with --framework pointing at a second OSS checkout for a same-fixture
comparison. Outputs counts/timings only and removes the disposable vault.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest import mock


def run(framework: Path, moments: int) -> dict:
    sys.path[:0] = [str(framework / "system"), str(framework / "tests")]
    import go_dig_writer as writer
    import landmark_offer as offer
    import landmark_projection as lp
    import temporal_claims as tc
    import temporal_publication as pub
    import temporal_store as store
    import timeline
    from test_landmark_offer import NOW, ScriptedCall, read_dates, read_unit, reading, synthetic_vault
    from test_place_containment import moment_claim, year

    def fingerprints(root):
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}

    with tempfile.TemporaryDirectory(prefix="synthetic-receipt-fold-",
                                     dir=Path(tempfile.gettempdir()).resolve()) as temporary:
        root = Path(temporary)
        with synthetic_vault(root):
            lp.file_landmark_record(root, "birth", {
                "domain": "birth", "label": "birth", "date": year("1960")}, ordinal=1, now=NOW)
            with store.receipt_read_batch(root), timeline.landmark_publication_batch(root):
                for i in range(36):
                    house, stay = i % 12, i // 12
                    writer.record_unit({"landmark": {
                        "domain": "residences", "label": f"Synthetic house {house}",
                        "city": "Synthetic Harbor", "address": f"{house + 1} Synthetic Lane",
                        "nickname": f"Lantern {house}",
                        "link": f"https://maps.example.test/house/{house}",
                        "span": {"start": year(str(1970 + stay * 10)),
                                 "end": year(str(1972 + stay * 10))}}}, now=NOW)
            for i in range(moments):
                text = (f"I remember synthetic occasion {i:04d} at Lantern {i % 12}. "
                        + "This invented passage describes an ordinary afternoon in detail. " * 8)
                source = store.promote_conversational_source(root, text, {
                    "session_ref": f"synthetic-{i}", "turn_ref": "1", "occurred_at": NOW})
                claim = moment_claim({"source": source.source_id, "quote": text,
                                      "mention": f"Synthetic occasion {i:04d}"},
                                     temporal_value="1980" if i % 17 == 0 else None)
                claim.update(source_ref=source.to_dict(),
                             place_mentions=[f"Lantern {i % 12}", "Synthetic Harbor"])
                claim["evidence"].append({"quote": "ordinary afternoon in detail"})
                claim = tc.validate_temporal_claim(claim)
                receipt = {"source_ref": source.to_dict(), "extractor_version": "classifier:1",
                           "claims": [claim], "created_at": NOW,
                           "extractor": {"name": "synthetic-classifier", "rule_version": "1",
                                         "context": {"labels": ["synthetic", "offline"],
                                                     "notes": text}}}
                store.write_receipt(root, receipt, now=NOW)
                if i % 20 == 0:
                    old_id = claim["claim_id"]
                    stamp = "2026-09-16T00:00:00Z"
                    receipt.update(extractor_version="classifier:2", created_at=stamp,
                                   claims=[{**claim, "extractor_version": "classifier:2", "created_at": stamp}])
                    store.write_receipt(root, receipt, now=stamp)
                    store.retract_claims(root, [old_id], reason="Synthetic earlier interpretation",
                                         occurred_at=stamp)
            timeline.redraw_landmarks()
            before = store.read_active_index(root)
            initial = pub.read_projection(root)
            assert sum(n["event_kind"] == "moment" for n in initial["nodes"]) >= moments

            units, events, sentences = [], [], []
            for i in range(76):
                house = i % 12
                start = 2000 + (i // 12) * 3
                label = f"Synthetic house {house} stay {i}"
                address, nickname = f"{house + 1} Synthetic Lane", f"Lantern {house}"
                link = f"https://maps.example.test/house/{house}"
                quote = (f"I lived at {address} in Synthetic Harbor, nicknamed {nickname}, "
                         f"from {start} to {start + 2}. Its map link is {link}.")
                sentences.append(quote)
                units.append(read_unit(f"u{i}", "residences", label, quote,
                                       record={"label": label, "city": "Synthetic Harbor"},
                                       names={"address": address, "nickname": nickname, "link": link},
                                       dates=read_dates(str(start), str(start + 2))))
            for i in range(10):
                quote = f"Synthetic person {i} was born in 2001."
                sentences.append(quote)
                events.append({"ref": f"e{i}", "kind": "child_born", "text": quote,
                               "subject_mention": f"Synthetic person {i}", "date": "2001",
                               "quote": quote, "within": f"u{i}"})
            proposal = offer.propose("\n".join(sentences), root,
                                     call=ScriptedCall(reading=reading(units=units, events=events)), now=NOW)
            assert len(proposal["units"]) == 76 and len(proposal["events"]) == 10
            ids = [unit["unit_id"] for unit in proposal["units"]]
            counts, timings = {}, {}

            def wrap(module, name, timed=True):
                original = getattr(module, name)
                key = f"{module.__name__}.{name}"

                def measured(*args, **kwargs):
                    counts[key] = counts.get(key, 0) + 1
                    started = time.perf_counter() if timed else 0
                    try:
                        return original(*args, **kwargs)
                    finally:
                        if timed:
                            timings[key] = timings.get(key, 0) + time.perf_counter() - started
                return mock.patch.object(module, name, measured)

            print(json.dumps({"stage": "seeded", "counts": before["counts"],
                              "landmark_sources": len(lp.load_landmark_sources(root)),
                              "projection_bytes": pub.projection_path(root).stat().st_size}), flush=True)
            with contextlib.ExitStack() as stack:
                for module, names in (
                    (store, ("load_receipts", "read_receipt", "fold_active_index", "write_active_index")),
                    (timeline, ("redraw_landmarks",)), (pub, ("publish",)),
                ):
                    for name in names:
                        stack.enter_context(wrap(module, name))
                for name in ("stat", "fstat", "scandir", "open"):
                    stack.enter_context(wrap(os, name, False))
                started, cpu = time.perf_counter(), time.process_time()
                receipt = offer.apply(proposal["proposal_id"], ids, root, now=NOW)
                wall, cpu = time.perf_counter() - started, time.process_time() - cpu
            assert receipt["counts"]["units"] == 76 and receipt["counts"]["claims"] == 10
            assert len(receipt["filed_names"]) == 76
            assert all(row["names"].get("nickname") and row["names"].get("address")
                       and row["names"].get("link") for row in receipt["filed_names"])
            assert all((row.get("alias") or {}).get("applied") for row in receipt["filed_names"])
            assert counts["temporal_publication.publish"] == 1
            assert counts["timeline.redraw_landmarks"] == 77
            assert store.read_active_index(root) == store.fold_active_index(root)
            after = fingerprints(root)
            assert offer.apply(proposal["proposal_id"], ids, root, now=NOW) == receipt
            assert fingerprints(root) == after
            return {"apply_wall_seconds": wall, "apply_cpu_seconds": cpu,
                    "threading": "one synchronous Python thread; no affinity imposed on macOS",
                    "cpu_affinity_count": (len(os.sched_getaffinity(0))
                                           if hasattr(os, "sched_getaffinity") else None),
                    "before": before["counts"], "receipt_counts": receipt["counts"],
                    "calls": counts, "phase_seconds": timings, "immutable_replay": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--moments", type=int, default=1000)
    args = parser.parse_args()
    if hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    print(json.dumps(run(args.framework, args.moments), indent=2, sort_keys=True), flush=True)
