#!/usr/bin/env python3
"""Connector framework primitives: permanent metadata ledger + re-excavation.

The design invariant: THE LEDGER IS PERMANENT; RELEVANCE IS RECOMPUTED.

- fetch() appends NEW message metadata to the ledger (cheap, cursor-based;
  never re-pulls what the ledger already has). Implemented per connector.
- excavate() re-scores the ENTIRE ledger against the CURRENT wiki, rosters,
  and sources; refreshes date evidence and discovery mining; and
  delta-promotes threads that newly cross the threshold. Entries are never
  dropped from the ledger — only their score fields are refreshed — so old
  mail can gain value over time without re-fetching.

Tier 0 is the ledger (state/connectors/<name>_ledger.jsonl): one compact
JSON line per scanned message, no bodies. Tier 1 is auto-promoted immutable
sources under sources/<name>/, written only for threads at or above the
calibrated threshold, idempotent by message id, bounded by a per-run cap.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import source_integrity
from lifehug_core import (
    CONNECTORS_STATE_DIR,
    REPO_DIR,
    STATE_DIR,
    append_text,
    now_utc,
    read_json,
    slugify,
    write_json,
    write_text,
)
from connectors.scoring import (
    AXES,
    BANDS,
    address_tokens,
    build_context,
    dossier_vip_verdicts,
    group_threads,
    load_scoring_config,
    score_thread,
    tokens_known,
)

# Safety valves on auto-promotion: at most this many threads per run, and
# --dry-run reports without writing. The threshold itself is the owner's
# explicit, versioned decision (state/connectors/weights.json).
DEFAULT_PROMOTION_CAP = 25
MAX_DISCOVERY_PER_RUN = 25


# ---------------------------------------------------------------------------
# Ledger + cursor I/O
# ---------------------------------------------------------------------------

def load_ledger(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("message_id"):
            entries.append(row)
    return entries


def append_ledger(path: Path, new_entries: list[dict]) -> tuple[int, int]:
    """Append entries whose message_id is not yet ledgered. Returns
    (added, total). Dedupe is by message id, so re-pulling an overlapping
    window can never duplicate."""
    existing = load_ledger(path)
    seen = {entry["message_id"] for entry in existing}
    added = [
        entry for entry in new_entries
        if entry.get("message_id") and entry["message_id"] not in seen
    ]
    if added:
        append_text(
            path,
            "".join(
                json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
                for entry in added
            ),
        )
    return len(added), len(existing) + len(added)


def rewrite_ledger(path: Path, entries: list[dict]) -> None:
    """Excavation refresh: same permanent entries, freshly recomputed score
    fields. Entries are never dropped here — the ledger only ever grows,
    via append_ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(entry, ensure_ascii=False, sort_keys=True) for entry in entries]
    write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def load_cursor(path: Path) -> dict:
    return read_json(path, default=None) or {}


def save_cursor(path: Path, data: dict) -> None:
    write_json(path, data)


def append_discovery_candidates(candidates_path: Path, candidates: list[dict]) -> int:
    """Append connector-mined proposals into state/question_candidates.json
    using the existing candidate schema, deduped by id so re-excavation
    never doubles them."""
    data = read_json(candidates_path, default=None)
    if not isinstance(data, dict):
        data = {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    existing_ids = {item.get("id") for item in data["candidates"]}
    added = 0
    for candidate in candidates:
        if candidate["id"] not in existing_ids:
            data["candidates"].append(candidate)
            existing_ids.add(candidate["id"])
            added += 1
    if added:
        write_json(candidates_path, data)
    return added


def _rel(repo_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(repo_dir).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Base connector
# ---------------------------------------------------------------------------

class BaseConnector:
    """Shared ledger/excavation machinery. Subclasses implement the
    source-specific pieces: build_client, fetch, fetch_thread (bodies for
    promotion), extract_date_evidence, mine_discovery."""

    name = "base"

    def __init__(self, *, repo_dir: Path | None = None, state_dir: Path | None = None):
        self.repo_dir = Path(repo_dir) if repo_dir else REPO_DIR
        self.state_dir = Path(state_dir) if state_dir else CONNECTORS_STATE_DIR

    @property
    def ledger_path(self) -> Path:
        return self.state_dir / f"{self.name}_ledger.jsonl"

    @property
    def cursor_path(self) -> Path:
        return self.state_dir / f"{self.name}.json"

    @property
    def date_evidence_path(self) -> Path:
        return self.state_dir / f"{self.name}_date_evidence.json"

    @property
    def weights_path(self) -> Path:
        return self.state_dir / "weights.json"

    @property
    def dossiers_path(self) -> Path:
        return self.state_dir / f"{self.name}_dossiers.json"

    @property
    def body_cache_dir(self) -> Path:
        return self.state_dir / f"{self.name}_body_cache"

    @property
    def reports_dir(self) -> Path:
        return self.repo_dir / "state" / "reports"

    @property
    def candidates_path(self) -> Path:
        return self.repo_dir / "state" / "question_candidates.json"

    @property
    def manifest_path(self) -> Path:
        return self.repo_dir / "state" / "source_manifest.json"

    @property
    def sources_dir(self) -> Path:
        return self.repo_dir / "sources" / self.name

    # --- subclass hooks -----------------------------------------------------

    def build_client(self):
        raise NotImplementedError(f"connector '{self.name}' has no client")

    def fetch(self, **_kwargs) -> dict:
        raise NotImplementedError(f"connector '{self.name}' has no fetch")

    def fetch_thread(self, client, thread_id: str, entries: list[dict]) -> list[dict]:
        """Bodies for ONE thread being promoted (or calibration-sampled).
        Never called during ledger build — metadata only there."""
        raise NotImplementedError

    def fetch_thread_cached(self, client, thread_id: str, entries: list[dict]) -> list[dict]:
        """Cache-first body fetch (v108). Fetched bodies persist COMMITTED
        under state/connectors/<name>_body_cache/ keyed by message id, so
        promotions, dossier sampling, and future passes read the cache first
        and fetch only misses."""
        wanted = [str(e.get("message_id") or "") for e in entries if e.get("message_id")]
        cached: dict[str, dict] = {}
        for message_id in wanted:
            row = read_json(self.body_cache_dir / f"{_cache_key(message_id)}.json", default=None)
            if isinstance(row, dict) and row.get("message_id"):
                cached[message_id] = row
        if wanted and all(message_id in cached for message_id in wanted):
            return [cached[message_id] for message_id in wanted]
        messages = self.fetch_thread(client, thread_id, entries)
        self.body_cache_dir.mkdir(parents=True, exist_ok=True)
        for message in messages:
            message_id = str(message.get("message_id") or "")
            if message_id:
                write_json(self.body_cache_dir / f"{_cache_key(message_id)}.json", message)
        return messages

    def extract_date_evidence(self, entries: list[dict], thresholds: dict) -> list[dict]:
        return []

    def mine_discovery(
        self,
        entries: list[dict],
        threads: dict[str, list[dict]],
        scored: dict[str, dict],
        context,
    ) -> list[dict]:
        return []

    def owner_email(self, client=None) -> str:
        if client is not None:
            try:
                return str(client.profile_email() or "")
            except Exception:  # noqa: BLE001
                pass
        return str(load_cursor(self.cursor_path).get("owner") or "")

    def timeline_contradiction_candidates(self, evidence: list[dict] | None = None) -> list[dict]:
        """Timeline date contradictions as question candidates (v110, issue
        #44). The timeline module itself stays read-only — it SURFACES
        evidence/memory conflicts as date_contradiction gap entries; the
        excavation (already a write path) converts them into the existing
        candidate schema, deduped by id on append. `evidence` is this run's
        freshly extracted assertions, so candidates never lag a run. No-op
        without date evidence or a working timeline module."""
        try:
            import timeline as tl_mod  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return []
        # The excavation reads THIS connector's repo, not the process vault —
        # every timeline root at once, through the timeline's own authority so
        # a newly added root can never be missed here (v120 moved
        # entity_rosters/ and connectors/ off STATE_DIR and this site kept
        # reading the process vault for both).
        state = self.repo_dir / "state"
        with tl_mod.vault_roots(
            CLASSIFICATIONS_DIR=state / "classifications",
            CONNECTORS_STATE_DIR=state / "connectors",
            ENTITY_ROSTERS_DIR=state / "entity_rosters",
            MANUAL_SOURCES_DIR=self.repo_dir / "sources" / "manual",
            PLACEMENTS_FILE=state / "timeline_placements.json",
            STATE_DIR=state,
            WIKI_DIR=self.repo_dir / "wiki",
        ):
            data = tl_mod.timeline_data(evidence=evidence)
        corroboration = data.get("corroboration") or {}
        if not corroboration.get("available"):
            return []
        now = now_utc()
        evidence_ref = f"state/connectors/{self.name}_date_evidence.json"
        candidates: list[dict] = []
        for item in corroboration.get("contradictions") or []:
            if item.get("connector") not in (None, "", self.name):
                continue  # raised by another connector's evidence
            candidates.append({
                "id": f"cand-{self.name}-date-contradiction-{item['key']}",
                "text": item["candidate_text"],
                "source_path": evidence_ref,
                "target_page": None,
                "kind": "date_contradiction",
                "priority": 0.7,
                "reason": (f"Connector-mined: {item['evidence_count']} {item['entity']} "
                           f"record(s) cluster in {item['evidence_says']}; the story says "
                           f"{item['memory_says']}. Surfaced on the timeline as a "
                           "date_contradiction gap — never auto-applied."),
                "status": "candidate",
                "provenance": "connector-mined",
                "connector": self.name,
                "created_at": now,
            })
        return candidates

    # --- excavation ---------------------------------------------------------

    def _promoted_source_ids(self) -> set[str]:
        manifest = read_json(self.manifest_path, default=None) or {}
        prefix = f"{self.name}:"
        return {
            str(entry.get("source_id"))
            for entry in (manifest.get("sources") or {}).values()
            if str(entry.get("source_id") or "").startswith(prefix)
        }

    def score_ledger(self, entries: list[dict], client=None):
        config = load_scoring_config(self.weights_path)
        context = build_context(self.repo_dir, entries, config, owner_email=self.owner_email(client))
        threads = group_threads(entries)
        scored = {thread_id: score_thread(thread_entries, context)
                  for thread_id, thread_entries in threads.items()}
        return context, threads, scored

    def excavate(
        self,
        *,
        dry_run: bool = False,
        cap: int = DEFAULT_PROMOTION_CAP,
        client=None,
        dossier_limit: int | None = None,
        ai_caller=None,
        model: str | None = None,
    ) -> dict:
        """The quarterly/yearly operation: re-score the whole ledger against
        the current repo, refresh date evidence + discovery, delta-promote.
        Runs the AI dossier pass FIRST (v108), so fresh verdicts calibrate
        this run's scoring."""
        entries = load_ledger(self.ledger_path)
        summary: dict[str, object] = {
            "connector": self.name,
            "dry_run": dry_run,
            "entries": len(entries),
            "threads": 0,
            "bands": {},
            "promoted": [],
            "would_promote": [],
            "skipped_cap": 0,
            "promotion_errors": [],
            "date_evidence": 0,
            "candidates_added": 0,
            "dossiers": None,
            "report_path": None,
        }
        if not entries:
            print(f"connector-{self.name}: ledger is empty — run connector-fetch {self.name} first")
            return summary

        from connectors.dossier import run_dossier_pass  # local import avoids the import cycle
        dossier_summary = run_dossier_pass(
            self, entries=entries, client=client, limit=dossier_limit,
            model=model, dry_run=dry_run, ai_caller=ai_caller)
        summary["dossiers"] = {
            "classified": len(dossier_summary["classified"]),
            "candidates": len(dossier_summary["candidates"]),
            "skipped_fresh": len(dossier_summary["skipped_fresh"]),
            "errors": dossier_summary["errors"],
        }

        now = now_utc()
        context, threads, scored = self.score_ledger(entries, client=client)
        summary["threads"] = len(threads)

        # Refresh score fields on the permanent entries. Prior scores are
        # overwritten, never trusted — relevance lives at run time.
        bands: dict[str, int] = {band: 0 for band in BANDS}
        for thread_id, thread_entries in threads.items():
            result = scored[thread_id]
            bands[result["band"]] += 1
            for entry in thread_entries:
                entry["scores"] = result["scores"]
                entry["total"] = result["total"]
                entry["band"] = result["band"]
                entry["last_scored_at"] = now
        summary["bands"] = bands

        # Date evidence: refreshed from scratch every excavation.
        evidence = self.extract_date_evidence(entries, context.thresholds)
        summary["date_evidence"] = len(evidence)

        # Discovery mining: unknown people / untold threads / unknown
        # institutions → existing question-candidates schema.
        candidates = self.mine_discovery(entries, threads, scored, context)[:MAX_DISCOVERY_PER_RUN]
        # Timeline date contradictions (v110) join the same candidate flow —
        # the excavation's fresh evidence, so they never lag a run.
        candidates += self.timeline_contradiction_candidates(evidence)

        # Delta-promotion: band == promote, not already in the manifest,
        # highest scores first, bounded by the per-run cap.
        already_promoted = self._promoted_source_ids()
        promotable = [
            thread_id for thread_id, result in scored.items()
            if result["band"] == "promote" and f"{self.name}:{thread_id}" not in already_promoted
        ]
        promotable.sort(key=lambda tid: (-scored[tid]["total"], tid))
        skipped_cap = max(0, len(promotable) - cap)
        summary["skipped_cap"] = skipped_cap
        for thread_id in promotable[:cap]:
            result = scored[thread_id]
            if dry_run:
                summary["would_promote"].append({
                    "thread_id": thread_id,
                    "total": result["total"],
                    "subject": _thread_subject(threads[thread_id]),
                })
                continue
            try:
                path = self._promote_thread(
                    client, thread_id, threads[thread_id], result, now,
                    threshold=context.thresholds["promote"],
                )
            except Exception as exc:  # noqa: BLE001 — one bad thread must not kill the run
                summary["promotion_errors"].append(f"{thread_id}: {exc}")
                continue
            summary["promoted"].append(_rel(self.repo_dir, path))

        if not dry_run:
            rewrite_ledger(self.ledger_path, entries)
            write_json(self.date_evidence_path, {
                "version": 1,
                "updated_at": now,
                "evidence": evidence,
            })
            summary["candidates_added"] = append_discovery_candidates(self.candidates_path, candidates)
            report_path = self._write_excavation_report(summary, scored, threads, now)
            summary["report_path"] = _rel(self.repo_dir, report_path)
            cursor = load_cursor(self.cursor_path)
            cursor["last_excavation"] = {
                "at": now,
                "entries": len(entries),
                "threads": len(threads),
                "bands": bands,
                "promoted": len(summary["promoted"]),
                "candidates_added": summary["candidates_added"],
            }
            save_cursor(self.cursor_path, cursor)
        else:
            summary["candidates_added"] = len(candidates)
            summary["date_evidence"] = len(evidence)

        print(f"connector-{self.name} excavation{' (dry run)' if dry_run else ''}: "
              f"{len(threads)} threads — " +
              ", ".join(f"{band}={bands[band]}" for band in BANDS))
        if summary["promoted"]:
            print(f"  promoted {len(summary['promoted'])} thread(s) to sources/{self.name}/")
        if summary["would_promote"]:
            print(f"  would promote {len(summary['would_promote'])} thread(s) (dry run)")
        if skipped_cap:
            print(f"  {skipped_cap} promotable thread(s) deferred by the per-run cap ({cap})")
        if summary["promotion_errors"]:
            print(f"  {len(summary['promotion_errors'])} promotion error(s) — see report")
        print(f"  date evidence: {summary['date_evidence']} assertion(s); "
              f"discovery candidates added: {summary['candidates_added']}")
        return summary

    def _unique_source_path(self, date: str, title: str) -> Path:
        base = f"{date}-{slugify(title)}"
        path = self.sources_dir / f"{base}.md"
        index = 2
        while path.exists():
            path = self.sources_dir / f"{base}-{index}.md"
            index += 1
        return path

    def _promote_thread(
        self,
        client,
        thread_id: str,
        entries: list[dict],
        result: dict,
        now: str,
        *,
        threshold: float,
    ) -> Path:
        """Write the immutable Tier-1 source: an external_record registered
        via source_integrity, provenance-pinned, owner-only."""
        messages = self.fetch_thread_cached(client, thread_id, entries)
        title = _thread_subject(entries)
        date = min((str(e.get("date") or "") for e in entries if e.get("date")), default="") or now[:10]
        lines = [f"# {title}", ""]
        lines.append(f"> Auto-promoted from {self.name} by connector-excavate on {now[:10]} "
                     f"(score {result['total']}, threshold {threshold}).")
        lines.append(f"> Thread {thread_id} · {len(entries)} message(s). "
                     "This is a third-party record — corroborating evidence, not first-person memory.")
        for message in messages:
            lines.append("")
            lines.append("---")
            lines.append("")
            header = f"**{message.get('date', '')}** — **{message.get('from_name') or message.get('from_email', '?')}**"
            if message.get("subject"):
                header += f" · {message['subject']}"
            lines.append(header)
            lines.append("")
            lines.append(str(message.get("body") or "").strip() or "(no plain-text body)")
        payload = "\n".join(lines).rstrip() + "\n"

        path = self._unique_source_path(date, title)
        metadata = {
            "title": title,
            "type": "external_record",
            "source_id": f"{self.name}:{thread_id}",
            "source_medium": self.name,
            "source_trust": "external_record",
            "authority": "third_party_record",
            "captured_at": f"{date}T00:00:00Z",
            "visibility": "owner_only",
            "sensitivity": "private",
            "status": "raw",
            "immutable": True,
            "schema_version": source_integrity.SCHEMA_VERSION,
            "raw_url": self.thread_url(thread_id),
            "source_path": _rel(self.repo_dir, path),
            "content_sha256": source_integrity.payload_sha256(payload),
            "metadata": {
                "connector": self.name,
                "thread_id": thread_id,
                "message_ids": sorted(str(e.get("message_id")) for e in entries if e.get("message_id")),
                "scores": result["scores"],
                "total": result["total"],
                "promoted_at": now,
            },
        }
        write_text(path, f"{source_integrity.format_frontmatter(metadata)}\n\n{payload}")
        source_integrity.register_source(path)
        relative = _rel(self.repo_dir, path)
        for entry in entries:
            entry["promoted"] = True
            entry["promoted_path"] = relative
            entry["promoted_at"] = now
        return path

    def thread_url(self, thread_id: str) -> str:
        return f"{self.name}://{thread_id}"

    # --- reports ------------------------------------------------------------

    def _dossier_vip_rows(self) -> list[tuple[str, dict]]:
        """Persisted dossier verdicts currently acting as auto-VIPs (v108) —
        listed in the excavation report so the owner can veto via weights.json."""
        from connectors.dossier import load_dossiers  # local import avoids the cycle
        config = load_scoring_config(self.weights_path)
        data = load_dossiers(self.dossiers_path)
        vips = dossier_vip_verdicts(data.get("dossiers") or {}, config)
        return sorted(vips.items())

    def _write_excavation_report(
        self,
        summary: dict,
        scored: dict[str, dict],
        threads: dict[str, list[dict]],
        now: str,
    ) -> Path:
        previous = load_cursor(self.cursor_path).get("last_excavation") or {}
        lines = [
            f"# {self.name} excavation — {now}",
            "",
            f"- ledger: {summary['entries']} messages in {summary['threads']} threads",
            "- bands: " + ", ".join(f"{band}={summary['bands'].get(band, 0)}" for band in BANDS),
            f"- promoted this run: {len(summary['promoted'])}"
            + (f" (cap deferred {summary['skipped_cap']})" if summary["skipped_cap"] else ""),
            f"- date evidence assertions: {summary['date_evidence']}",
            f"- discovery candidates added: {summary['candidates_added']}",
        ]
        if previous:
            lines.append(f"- previous run: {previous.get('at', '?')} "
                         f"(promoted {previous.get('promoted', 0)}, bands {previous.get('bands', {})})")
        if summary["promoted"]:
            lines += ["", "## Newly promoted"]
            for path in summary["promoted"]:
                lines.append(f"- {path}")
        if summary["promotion_errors"]:
            lines += ["", "## Promotion errors"]
            lines += [f"- {error}" for error in summary["promotion_errors"]]
        dossier_vips = self._dossier_vip_rows()
        if dossier_vips:
            lines += ["", "## Dossier VIPs (auto-applied — veto via vip_blocklist in weights.json)"]
            for email, verdict in dossier_vips:
                confidence = verdict.get("confidence", 0)
                try:
                    confidence = f"{float(confidence):.2f}"
                except (TypeError, ValueError):
                    confidence = "?"
                lines.append(
                    f"- {verdict.get('suggested_label') or email} <{email}> — "
                    f"{verdict.get('classification', '?')} ({confidence}): "
                    f"{verdict.get('significance') or '(no significance recorded)'}")
        near = sorted(
            ((tid, r) for tid, r in scored.items() if r["band"] == "near_band"),
            key=lambda item: -item[1]["total"],
        )[:10]
        if near:
            lines += ["", "## Near-band (just below threshold)"]
            for tid, r in near:
                lines.append(f"- [{r['total']}] {_thread_subject(threads[tid])} ({tid})")
        path = self.reports_dir / f"{self.name}_excavation.md"
        write_text(path, "\n".join(lines) + "\n")
        return path

    def report(self) -> int:
        """Ledger summary: volume, span, current bands, top correspondents."""
        entries = load_ledger(self.ledger_path)
        cursor = load_cursor(self.cursor_path)
        print(f"connector: {self.name}")
        print(f"ledger: {self.ledger_path}")
        if not entries:
            print("ledger is empty — run connector-fetch first")
            return 0
        threads = group_threads(entries)
        dates = sorted(str(e.get("date")) for e in entries if e.get("date"))
        print(f"messages: {len(entries)} in {len(threads)} threads")
        if dates:
            print(f"span: {dates[0]} → {dates[-1]}")
        bands = {band: 0 for band in BANDS}
        unscored = 0
        for thread_entries in threads.values():
            band = str(thread_entries[0].get("band") or "")
            if band in bands:
                bands[band] += 1
            else:
                unscored += 1
        if unscored:
            print(f"bands: {unscored} thread(s) unscored — run connector-excavate {self.name}")
        else:
            print("bands: " + ", ".join(f"{band}={bands[band]}" for band in BANDS))
        promoted = sorted({str(e.get("promoted_path")) for e in entries if e.get("promoted_path")})
        print(f"promoted: {len(promoted)} source(s) under sources/{self.name}/")
        evidence = read_json(self.date_evidence_path, default=None) or {}
        if evidence.get("evidence") is not None:
            print(f"date evidence: {len(evidence['evidence'])} assertion(s) (updated {evidence.get('updated_at', '?')})")
        if cursor.get("last_fetch_at"):
            print(f"last fetch: {cursor['last_fetch_at']} (total {cursor.get('total_messages', '?')})")
        if cursor.get("last_excavation"):
            last = cursor["last_excavation"]
            print(f"last excavation: {last.get('at', '?')} — promoted {last.get('promoted', 0)}")
        config = load_scoring_config(self.weights_path)
        print(f"promote threshold: {config['thresholds']['promote']} (weights: {self.weights_path})")
        return 0

    def audit(self) -> int:
        """Everything auto-promoted, newest first, with scores — the
        occasional-eyeball listing. Retractions go through the existing
        retract-source flow."""
        entries = load_ledger(self.ledger_path)
        promoted_threads: dict[str, list[dict]] = {}
        for entry in entries:
            if entry.get("promoted"):
                promoted_threads.setdefault(str(entry.get("thread_id")), []).append(entry)
        if not promoted_threads:
            print(f"no {self.name} sources auto-promoted yet")
            return 0
        rows = []
        for thread_id, thread_entries in promoted_threads.items():
            first = thread_entries[0]
            rows.append({
                "thread_id": thread_id,
                "promoted_at": str(first.get("promoted_at") or ""),
                "date": min(str(e.get("date") or "") for e in thread_entries),
                "subject": _thread_subject(thread_entries),
                "total": first.get("total", "?"),
                "path": str(first.get("promoted_path") or ""),
            })
        rows.sort(key=lambda row: (row["promoted_at"], row["thread_id"]), reverse=True)
        print(f"auto-promoted {self.name} sources: {len(rows)} (newest first)")
        for row in rows:
            print(f"- [{row['total']}] {row['date']} {row['subject']}")
            print(f"  {row['path']} (promoted {row['promoted_at'][:10] or '?'})")
        print("to suppress one: python3 system/lifehug.py retract-source <path> --reason \"...\"")
        return 0

    def calibrate(self, *, seed: int = 106, examples_per_band: int = 10, client=None) -> Path:
        """Phase 2 shadow run: score the full ledger and report the
        distribution, per-band counts at candidate thresholds, random
        examples per band with reasons, and a discovery preview — so the
        owner signs off ONCE on weights + threshold."""
        entries = load_ledger(self.ledger_path)
        if not entries:
            raise SystemExit(f"ledger is empty — run connector-fetch {self.name} first")
        now = now_utc()
        context, threads, scored = self.score_ledger(entries, client=client)
        config = load_scoring_config(self.weights_path)
        totals = [result["total"] for result in scored.values()]

        lines = [
            f"# {self.name} calibration — {now}",
            "",
            f"Ledger: {len(entries)} messages in {len(threads)} threads. "
            "Scores below use the CURRENT weights/thresholds "
            f"(promote = {config['thresholds']['promote']}).",
            "",
            "## Score distribution",
            "",
            "```",
        ]
        bins = [0] * 20
        for total in totals:
            bins[min(19, int(total / 0.05))] += 1
        peak = max(bins) or 1
        for index, count in enumerate(bins):
            bar = "#" * round(40 * count / peak)
            lines.append(f"{index * 0.05:.2f}-{index * 0.05 + 0.05:.2f} | {count:5d} {bar}")
        lines += ["```", "", "## Promotion counts at candidate thresholds", ""]
        for candidate_threshold in (0.5, 0.6, 0.7, 0.8):
            count = sum(1 for total in totals if total >= candidate_threshold)
            lines.append(f"- threshold {candidate_threshold:.1f}: {count} thread(s) would promote")
        lines += ["", f"Current bands (threshold {config['thresholds']['promote']}):"]
        band_counts = {band: 0 for band in BANDS}
        for result in scored.values():
            band_counts[result["band"]] += 1
        lines += [f"- {band}: {band_counts[band]}" for band in BANDS]

        rng = random.Random(seed)
        lines += ["", "## Examples per band (random, with reasons)"]
        for band in BANDS:
            members = [(tid, r) for tid, r in scored.items() if r["band"] == band]
            rng.shuffle(members)
            lines += ["", f"### {band} ({len(members)} threads)"]
            for tid, result in members[:examples_per_band]:
                thread_entries = threads[tid]
                subject = _thread_subject(thread_entries)
                parties = sorted({str(e.get("from_email")) for e in thread_entries if e.get("from_email")})
                lines.append("")
                lines.append(f"- **[{result['total']}]** {subject} — {', '.join(parties[:3])} ({tid})")
                for axis in AXES:
                    lines.append(f"  - {axis} {result['scores'][axis]:.2f}: {result['reasons'][axis]}")

        lines += ["", "## Discovery preview", ""]
        unknown = [
            (email, stats) for email, stats in context.correspondent_stats.items()
            if stats.get("messages", 0) >= 3
            and not _known_email(email, stats, context)
        ]
        unknown.sort(key=lambda item: (-item[1]["messages"], item[0]))
        lines.append(f"### Top unknown correspondents ({len(unknown)} total, showing 30)")
        for email, stats in unknown[:30]:
            lines.append(
                f"- {stats.get('name') or email} <{email}> — {stats['messages']} messages, "
                f"{stats.get('span_days', 0)}d span, owner replies: {stats.get('owner_replies', 0)}")
        untold = sorted(
            ((tid, r) for tid, r in scored.items()
             if r["scores"]["narrative_density"] >= 0.6 and r["scores"]["novelty"] >= 0.7),
            key=lambda item: -item[1]["total"],
        )[:20]
        lines += ["", f"### Untold narrative threads ({len(untold)} shown)"]
        for tid, result in untold:
            lines.append(f"- [{result['total']}] {_thread_subject(threads[tid])} ({tid})")
        lines += [
            "",
            "## Next step",
            "",
            "Pick the promote threshold, then record it:",
            "",
            "```bash",
            f"python3 system/lifehug.py connector-calibrate {self.name} --set-threshold 0.6",
            "```",
        ]
        path = self.reports_dir / f"{self.name}_calibration.md"
        write_text(path, "\n".join(lines) + "\n")
        print(f"✓ calibration report: {_rel(self.repo_dir, path)}")
        return path

    def set_threshold(self, value: float) -> None:
        """Record the owner's calibrated promote threshold (versioned config)."""
        config = load_scoring_config(self.weights_path)
        config["thresholds"]["promote"] = float(value)
        write_json(self.weights_path, {
            "version": 1,
            "updated_at": now_utc(),
            "weights": config["weights"],
            "thresholds": config["thresholds"],
        })
        print(f"✓ promote threshold set to {value} in {self.weights_path} "
              "(takes effect on the next excavation)")


def _cache_key(message_id: str) -> str:
    """Filesystem-safe body-cache key for a message id."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(message_id)) or "unknown"


def _thread_subject(entries: list[dict]) -> str:
    subject = ""
    for entry in entries:
        subject = str(entry.get("subject") or "").strip()
        if subject:
            break
    subject = re.sub(r"^(re|fwd?)\s*:\s*", "", subject, flags=re.IGNORECASE).strip()
    return subject or "(no subject)"


def _known_email(email: str, stats: dict, context) -> bool:
    if email.lower() in (getattr(context, "known_emails", None) or set()):
        return True
    tokens = address_tokens(str(stats.get("name") or ""), email)
    return tokens_known(tokens, context.known_any_token_sets)
