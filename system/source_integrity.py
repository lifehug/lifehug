#!/usr/bin/env python3
"""Source integrity tools for Lifehug's raw story layer.

The source layer is the evidence base: prompted answers and ingested stories.
This module keeps that layer append-oriented without making daily answering
heavy. Safe metadata/manifest repairs are scriptable; story changes are routed
through additive correction or reflection sources.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    CORRECTION_SOURCES_DIR,
    REPO_DIR,
    SOURCE_LINT_FINDINGS_FILE,
    SOURCE_MANIFEST_FILE,
    SOURCES_DIR,
    answer_id_from_filename,
    now_utc,
    read_json,
    slugify,
    split_frontmatter,
    write_json,
    write_text,
)

SCHEMA_VERSION = 1
REQUIRED_SOURCE_KEYS = (
    "type",
    "source_id",
    "captured_at",
    "visibility",
    "status",
    "immutable",
    "schema_version",
    "source_path",
    "content_sha256",
)
FRONTMATTER_ORDER = (
    "title",
    "type",
    "source_id",
    "question_id",
    "question_text",
    "category",
    "category_name",
    "pass_number",
    "source_medium",
    "source_type",
    "source_trust",
    "authority",
    "artifact_id",
    "artifact_title",
    "artifact_format",
    "subject",
    "occasion",
    "occasion_date",
    "audience",
    "privacy",
    "generated_from",
    "output_path",
    "output_version",
    "captured_at",
    "asked_at",
    "answered_date",
    "visibility",
    "status",
    "immutable",
    "schema_version",
    "corrects",
    "reflects",
    "correction_kind",
    "raw_url",
    "source_path",
    "content_sha256",
    "metadata",
)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_payload(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return f"{text}\n" if text else ""


def payload_sha256(text: str) -> str:
    return hashlib.sha256(normalize_payload(text).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_payload(content: str) -> str:
    _metadata, body = split_frontmatter(content)
    return body


def has_frontmatter(content: str) -> bool:
    metadata, body = split_frontmatter(content)
    return bool(metadata) or body != content


def source_paths() -> list[Path]:
    paths: list[Path] = []
    if ANSWERS_DIR.exists():
        paths.extend(p for p in ANSWERS_DIR.glob("*.md") if p.name != ".gitkeep")
    if SOURCES_DIR.exists():
        paths.extend(p for p in SOURCES_DIR.rglob("*.md") if p.name != ".gitkeep")
    return sorted(paths, key=lambda p: rel(p))


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _answer_source_label(text: str) -> str:
    match = re.search(r"\*\*Source:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def _answer_date(text: str) -> str:
    match = re.search(r"\*\*Asked:\*\*\s*([^|]+?)\s*\|\s*\*\*Answered:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
    if match:
        return match.group(2).strip()
    match = re.search(r"\*\*Answered:\*\*\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _answer_category(text: str) -> tuple[str, str, int | None]:
    match = re.search(
        r"\*\*Category:\*\*\s*([A-Z])\s*\((.+?)\)\s*\|\s*\*\*Pass:\*\*\s*(\d+)",
        text,
        re.MULTILINE,
    )
    if not match:
        return "", "", None
    return match.group(1), match.group(2).strip(), int(match.group(3))


def _filename_date(path: Path) -> str:
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", path.stem)
    return match.group(1) if match else ""


def _path_source_type(path: Path, metadata: dict[str, object]) -> str:
    if metadata.get("type"):
        return str(metadata["type"])
    if path.parent == ANSWERS_DIR:
        return "prompted_answer"
    try:
        relative = path.resolve().relative_to(SOURCES_DIR.resolve())
        if relative.parts and relative.parts[0] == "corrections":
            return "source_correction"
        if relative.parts and relative.parts[0] == "artifacts":
            return "artifact_source"
        if relative.parts and relative.parts[0] == "manual":
            return "unprompted_story"
        return "ingested_source"
    except ValueError:
        return "source"


def _source_id(path: Path, metadata: dict[str, object]) -> str:
    if metadata.get("source_id"):
        return str(metadata["source_id"])
    qid = answer_id_from_filename(path)
    if path.parent == ANSWERS_DIR and qid:
        return f"answer:{qid}"
    try:
        relative = path.resolve().relative_to(SOURCES_DIR.resolve())
        stem = "/".join(relative.with_suffix("").parts)
        return f"source:{stem}"
    except ValueError:
        return f"source:{path.stem}"


def _source_title(path: Path, metadata: dict[str, object], payload: str) -> str:
    if metadata.get("title"):
        return str(metadata["title"])
    heading = _first_heading(payload)
    if heading:
        return heading
    qid = answer_id_from_filename(path)
    if path.parent == ANSWERS_DIR and qid:
        return f"Answer {qid}"
    return path.stem.replace("-", " ").title()


def _captured_at(path: Path, metadata: dict[str, object], original_text: str) -> str:
    if metadata.get("captured_at"):
        return str(metadata["captured_at"])
    if path.parent == ANSWERS_DIR:
        answered = _answer_date(original_text)
        if answered:
            return answered
    named = _filename_date(path)
    if named:
        return named
    return _mtime_utc(path)


def _source_medium(path: Path, metadata: dict[str, object], original_text: str) -> str:
    if metadata.get("source_medium"):
        return str(metadata["source_medium"])
    if metadata.get("source"):
        return str(metadata["source"])
    if path.parent == ANSWERS_DIR:
        return _answer_source_label(original_text)
    try:
        relative = path.resolve().relative_to(SOURCES_DIR.resolve())
        return relative.parts[0] if relative.parts else "source"
    except ValueError:
        return "source"


def build_source_metadata(path: Path, content: str) -> dict[str, object]:
    existing, payload = split_frontmatter(content)
    source_type = _path_source_type(path, existing)
    metadata = dict(existing)
    metadata.setdefault("title", _source_title(path, existing, payload))
    metadata.setdefault("type", source_type)
    metadata.setdefault("source_id", _source_id(path, existing))
    qid = answer_id_from_filename(path)
    if path.parent == ANSWERS_DIR and qid:
        metadata.setdefault("question_id", qid)
        heading = _first_heading(payload or content)
        if heading.startswith(f"Question {qid}:"):
            metadata.setdefault("question_text", heading.split(":", 1)[1].strip())
        category, category_name, pass_number = _answer_category(content)
        if category:
            metadata.setdefault("category", category)
        if category_name:
            metadata.setdefault("category_name", category_name)
        if pass_number is not None:
            metadata.setdefault("pass_number", pass_number)
    metadata.setdefault("source_medium", _source_medium(path, existing, content))
    metadata.setdefault("captured_at", _captured_at(path, existing, content))
    metadata.setdefault("visibility", "owner_only")
    metadata.setdefault("status", "raw")
    metadata.setdefault("immutable", True)
    metadata.setdefault("schema_version", SCHEMA_VERSION)
    metadata["source_path"] = rel(path)
    metadata["content_sha256"] = payload_sha256(payload)
    return metadata


def format_frontmatter(metadata: dict[str, object]) -> str:
    keys = [key for key in FRONTMATTER_ORDER if key in metadata]
    keys.extend(sorted(key for key in metadata if key not in keys))
    lines = ["---"]
    for key in keys:
        value = metadata[key]
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=True)}")
    lines.append("---")
    return "\n".join(lines)


def apply_metadata_fix(path: Path) -> None:
    content = path.read_text(encoding="utf-8", errors="replace")
    _metadata, payload = split_frontmatter(content)
    metadata = build_source_metadata(path, content)
    write_text(path, f"{format_frontmatter(metadata)}\n\n{payload.lstrip()}")


def source_record(path: Path) -> dict[str, object]:
    content = path.read_text(encoding="utf-8", errors="replace")
    metadata, payload = split_frontmatter(content)
    inferred = build_source_metadata(path, content)
    source_id = str(metadata.get("source_id") or inferred["source_id"])
    source_type = str(metadata.get("type") or inferred["type"])
    return {
        "path": rel(path),
        "abs_path": path,
        "source_id": source_id,
        "type": source_type,
        "title": str(metadata.get("title") or inferred["title"]),
        "captured_at": str(metadata.get("captured_at") or inferred["captured_at"]),
        "source_medium": str(metadata.get("source_medium") or inferred["source_medium"]),
        "has_frontmatter": has_frontmatter(content),
        "metadata": metadata,
        "required_missing": [key for key in REQUIRED_SOURCE_KEYS if key not in metadata],
        "content_sha256": payload_sha256(payload),
        "declared_content_sha256": str(metadata.get("content_sha256", "")),
        "file_sha256": file_sha256(path),
    }


def scan_sources() -> list[dict[str, object]]:
    return [source_record(path) for path in source_paths()]


def load_manifest() -> dict:
    data = read_json(SOURCE_MANIFEST_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": None, "sources": {}}
    data.setdefault("version", 1)
    data.setdefault("sources", {})
    return data


def sync_manifest(records: list[dict[str, object]], *, write: bool = True, prune_missing: bool = False) -> dict:
    manifest = load_manifest()
    now = now_utc()
    sources = manifest.setdefault("sources", {})
    for record in records:
        path = str(record["path"])
        existing = sources.get(path, {})
        entry = dict(existing)
        entry.setdefault("first_seen_at", now)
        entry.setdefault("original_content_sha256", record["content_sha256"])
        entry.setdefault("original_file_sha256", record["file_sha256"])
        entry.update({
            "source_id": record["source_id"],
            "type": record["type"],
            "title": record["title"],
            "captured_at": record["captured_at"],
            "source_medium": record["source_medium"],
            "current_content_sha256": record["content_sha256"],
            "current_file_sha256": record["file_sha256"],
            "last_verified_at": now,
            "changed_since_first_seen": (
                entry.get("original_content_sha256", record["content_sha256"])
                != record["content_sha256"]
            ),
        })
        sources[path] = entry
    if prune_missing:
        current_paths = {str(record["path"]) for record in records}
        for path in sorted(set(sources) - current_paths):
            sources.pop(path, None)
    manifest["updated_at"] = now
    if write:
        write_json(SOURCE_MANIFEST_FILE, manifest)
    return manifest


def register_source(path: Path) -> dict:
    return sync_manifest([source_record(path)], write=True)


def finding(
    issue_type: str,
    severity: str,
    path: str,
    message: str,
    *,
    fixability: str,
    recommended_action: str,
) -> dict[str, str]:
    digest = hashlib.sha256(f"{issue_type}:{path}:{message}".encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"src-{digest}",
        "type": issue_type,
        "severity": severity,
        "path": path,
        "message": message,
        "fixability": fixability,
        "recommended_action": recommended_action,
        "status": "open",
    }


def _parse_sources_block(lines: list[str]) -> set[str]:
    refs: set[str] = set()
    for idx, line in enumerate(lines):
        if line.strip() != "sources:":
            continue
        for raw in lines[idx + 1:]:
            if not raw.startswith("  - "):
                break
            value = raw.split("-", 1)[1].strip().strip('"').strip("'")
            if value:
                refs.add(value)
    return refs


def _wiki_source_refs() -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    wiki_dir = REPO_DIR / "wiki"
    if not wiki_dir.exists():
        return refs
    for page in sorted(wiki_dir.rglob("*.md")):
        if page.name in {"SCHEMA.md", "index.md", "log.md"}:
            continue
        text = page.read_text(encoding="utf-8", errors="replace")
        page_refs = _parse_sources_block(text.splitlines())
        if page_refs:
            refs[rel(page)] = page_refs
    return refs


# Wiki dirs holding roster-graduated entity pages, mapped to their entity type.
_ENTITY_PAGE_DIRS = {"people": "person", "places": "place", "periods": "period", "objects": "object"}
# Two same-type pages whose source sets overlap at/above this Jaccard ratio (or
# where one is a strict subset of the other) look like one entity split in two.
DUPLICATE_SOURCE_JACCARD = 0.8


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf'^{re.escape(key)}:\s*"?(.*?)"?\s*$', text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _wiki_entity_pages() -> list[dict]:
    """Scan wiki entity dirs → [{path, type, origin, slug, sources}] per page."""
    pages: list[dict] = []
    wiki_dir = REPO_DIR / "wiki"
    for dir_name, entity_type in _ENTITY_PAGE_DIRS.items():
        directory = wiki_dir / dir_name
        if not directory.exists():
            continue
        for page in sorted(directory.glob("*.md")):
            if page.name == ".gitkeep":
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
            pages.append({
                "path": rel(page),
                "type": entity_type,
                "origin": _frontmatter_value(text, "origin"),
                "slug": page.stem,
                "sources": _parse_sources_block(text.splitlines()),
            })
    return pages


def _roster_slug_index(entity_type: str) -> set[str] | None:
    """All slugs an entity roster accounts for (slug + name + aliases, slugified).
    None when the roster is missing/empty — callers must skip judgment then."""
    data = read_json(REPO_DIR / "state" / "entity_rosters" / f"{entity_type}.json", default=None)
    entities = (data or {}).get("entities") or []
    if not entities:
        return None
    slugs: set[str] = set()
    for ent in entities:
        for raw in [ent.get("slug", ""), ent.get("name", ""), *ent.get("aliases", [])]:
            slug = slugify(str(raw or ""))
            if slug:
                slugs.add(slug)
    return slugs


def lint_records(records: list[dict[str, object]], *, strict: bool = False) -> list[dict[str, str]]:
    manifest = load_manifest()
    manifest_sources = manifest.get("sources", {})
    findings: list[dict[str, str]] = []
    by_id: dict[str, list[dict[str, object]]] = {}
    source_paths_set = {str(record["path"]) for record in records}
    source_ids_set = {str(record["source_id"]) for record in records}

    for record in records:
        path = str(record["path"])
        by_id.setdefault(str(record["source_id"]), []).append(record)

        if not record["has_frontmatter"]:
            findings.append(finding(
                "missing_frontmatter",
                "warning",
                path,
                "source file has no Lifehug source metadata frontmatter",
                fixability="safe",
                recommended_action="run source-lint --fix to add metadata without changing the body",
            ))

        missing = list(record.get("required_missing", []))
        if missing:
            findings.append(finding(
                "missing_source_metadata",
                "warning",
                path,
                f"missing source metadata: {', '.join(missing)}",
                fixability="safe",
                recommended_action="run source-lint --fix to add required metadata",
            ))

        metadata = record.get("metadata", {})
        declared = str(record.get("declared_content_sha256") or "")
        if declared and declared != record["content_sha256"]:
            findings.append(finding(
                "content_hash_mismatch",
                "error",
                path,
                "declared content hash does not match the current source body",
                fixability="manual",
                recommended_action="review the change; restore from git, accept as repair, or add a correction/reflection source",
            ))

        source_path = str(metadata.get("source_path", "")) if isinstance(metadata, dict) else ""
        if source_path and source_path != path:
            findings.append(finding(
                "source_path_mismatch",
                "warning",
                path,
                f"metadata source_path is {source_path}, expected {path}",
                fixability="safe",
                recommended_action="run source-lint --fix to align metadata with the file path",
            ))

        entry = manifest_sources.get(path)
        if not entry:
            findings.append(finding(
                "manifest_missing",
                "warning",
                path,
                "source is not registered in state/source_manifest.json",
                fixability="safe",
                recommended_action="run source-manifest --rebuild or source-lint --fix",
            ))
        elif entry.get("original_content_sha256") != record["content_sha256"]:
            findings.append(finding(
                "source_content_changed",
                "error",
                path,
                "source body changed after first manifest capture",
                fixability="manual",
                recommended_action="restore the original, accept as repair with an audit note, or create a correction/reflection source",
            ))

        target = ""
        if isinstance(metadata, dict):
            target = str(metadata.get("corrects") or metadata.get("reflects") or metadata.get("retracts") or "")
        if record["type"] in {"source_correction", "source_reflection", "source_retraction"} and target:
            if target not in source_ids_set and target not in source_paths_set:
                findings.append(finding(
                    "missing_correction_target",
                    "error",
                    path,
                    f"linked target {target} does not exist",
                    fixability="manual",
                    recommended_action="edit correction metadata to point at an existing source id or path",
                ))

    for source_id, matching in by_id.items():
        if len(matching) > 1:
            paths = ", ".join(str(item["path"]) for item in matching)
            for record in matching:
                findings.append(finding(
                    "duplicate_source_id",
                    "error",
                    str(record["path"]),
                    f"source id {source_id} is shared by: {paths}",
                    fixability="manual",
                    recommended_action="assign a distinct source_id to one file, then rebuild the manifest",
                ))

    for path in sorted(set(manifest_sources) - source_paths_set):
        findings.append(finding(
            "manifest_path_missing",
            "warning",
            path,
            "manifest entry points to a missing source file",
            fixability="safe",
            recommended_action="run source-manifest --rebuild after confirming the source was intentionally removed",
        ))

    wiki_refs = _wiki_source_refs()
    all_refs = {source for refs in wiki_refs.values() for source in refs}
    for page, refs in wiki_refs.items():
        for ref in sorted(refs - source_paths_set):
            findings.append(finding(
                "wiki_missing_source",
                "warning",
                page,
                f"wiki page cites missing source {ref}",
                fixability="safe",
                recommended_action="re-run compile; if it remains, fix the compiler or restore the source",
            ))

    # Entity-page sanity: catch roster/wiki drift (an entity page whose entity
    # left the roster) and split entities (two pages that are really one).
    entity_pages = _wiki_entity_pages()
    roster_indexes: dict[str, set[str] | None] = {}
    for page in entity_pages:
        if page["origin"] != "mention":
            continue
        entity_type = page["type"]
        if entity_type not in roster_indexes:
            roster_indexes[entity_type] = _roster_slug_index(entity_type)
        slug_index = roster_indexes[entity_type]
        if slug_index is None:
            continue  # no roster → cannot judge
        if page["slug"] not in slug_index:
            findings.append(finding(
                "entity_page_not_in_roster",
                "warning",
                page["path"],
                f"mention-origin {entity_type} page has no matching entity in the {entity_type} roster",
                fixability="manual",
                recommended_action="re-run compile (orphan cleanup removes it), or re-add the entity to state/entity_rosters/",
            ))
    by_type: dict[str, list[dict]] = {}
    for page in entity_pages:
        if page["sources"]:
            by_type.setdefault(page["type"], []).append(page)
    for entity_type, pages in by_type.items():
        for a, b in itertools.combinations(pages, 2):
            if a["origin"] != "mention" and b["origin"] != "mention":
                continue  # two hand-curated pages overlapping is intentional
            small, big = sorted((a, b), key=lambda p: len(p["sources"]))
            if len(small["sources"]) < 2:
                continue
            inter = small["sources"] & big["sources"]
            union = small["sources"] | big["sources"]
            subset = small["sources"] <= big["sources"]
            if not subset and len(inter) / len(union) < DUPLICATE_SOURCE_JACCARD:
                continue
            overlap = "a subset of" if subset else "nearly identical to"
            findings.append(finding(
                "duplicate_entity_suspect",
                "warning",
                small["path"],
                f"sources are {overlap} {big['path']} — likely one {entity_type} split into two pages",
                fixability="manual",
                recommended_action="merge the roster entries into one entity with aliases, delete the duplicate page, then re-run compile",
            ))

    if strict:
        for record in records:
            path = str(record["path"])
            if path not in all_refs:
                findings.append(finding(
                    "source_not_cited",
                    "info",
                    path,
                    "source is not cited by any current wiki page",
                    fixability="planner",
                    recommended_action="let compile/planner incorporate it or create follow-up questions",
                ))

    return sorted(findings, key=lambda f: (f["severity"], f["type"], f["path"], f["id"]))


def open_findings_count(findings: list[dict[str, str]]) -> int:
    return len([f for f in findings if f.get("status") == "open"])


def findings_payload(findings: list[dict[str, str]], *, updated_at: str | None = None) -> dict[str, object]:
    return {
        "version": 1,
        "updated_at": updated_at or now_utc(),
        "open_count": open_findings_count(findings),
        "findings": findings,
    }


def findings_changed(existing: object, findings: list[dict[str, str]]) -> bool:
    if not isinstance(existing, dict):
        return True
    return (
        existing.get("version") != 1
        or existing.get("open_count") != open_findings_count(findings)
        or existing.get("findings") != findings
    )


def write_findings(findings: list[dict[str, str]]) -> None:
    existing = read_json(SOURCE_LINT_FINDINGS_FILE, default=None)
    if not findings_changed(existing, findings):
        return
    data = findings_payload(findings)
    write_json(SOURCE_LINT_FINDINGS_FILE, data)


def print_findings(findings: list[dict[str, str]], *, limit: int | None = None) -> None:
    counts = Counter(f["severity"] for f in findings)
    print(
        "source lint: "
        f"{counts.get('error', 0)} error(s), "
        f"{counts.get('warning', 0)} warning(s), "
        f"{counts.get('info', 0)} info"
    )
    rows = findings[:limit] if limit else findings
    for item in rows:
        print(f"- [{item['severity']}] {item['id']} {item['type']} {item['path']}")
        print(f"  {item['message']}")
        print(f"  fix: {item['recommended_action']}")
    if limit and len(findings) > limit:
        print(f"... {len(findings) - limit} more finding(s)")


def apply_safe_fixes(records: list[dict[str, object]]) -> list[dict[str, object]]:
    for record in records:
        if not record["has_frontmatter"] or record.get("required_missing"):
            apply_metadata_fix(Path(record["abs_path"]))
            continue
        metadata = record.get("metadata", {})
        if isinstance(metadata, dict) and metadata.get("source_path") != record["path"]:
            apply_metadata_fix(Path(record["abs_path"]))
    fixed_records = scan_sources()
    sync_manifest(fixed_records, write=True, prune_missing=True)
    return fixed_records


def summarize_records(records: list[dict[str, object]]) -> None:
    counts = Counter(str(record["type"]) for record in records)
    print(f"sources: {len(records)}")
    for source_type, count in sorted(counts.items()):
        print(f"  {source_type}: {count}")
    missing_metadata = sum(1 for record in records if record.get("required_missing"))
    if missing_metadata:
        print(f"metadata needed: {missing_metadata}")


def _unique_path(directory: Path, title: str, captured_at: str) -> Path:
    day = captured_at[:10] if captured_at else datetime.now(timezone.utc).date().isoformat()
    base = f"{day}-{slugify(title)}"
    path = directory / f"{base}.md"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = directory / f"{base}-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def resolve_source_target(value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_DIR / candidate
    if candidate.exists():
        return candidate
    manifest = load_manifest()
    for path, entry in manifest.get("sources", {}).items():
        if value in {path, entry.get("source_id")}:
            resolved = REPO_DIR / path
            if resolved.exists():
                return resolved
    raise FileNotFoundError(f"source target not found: {value}")


def create_linked_source(
    target: str,
    body: str,
    *,
    source_type: str,
    title: str | None,
    source_medium: str,
    correction_kind: str | None = None,
    suppress_on: list[str] | None = None,
) -> Path:
    target_path = resolve_source_target(target)
    target_record = source_record(target_path)
    captured_at = now_utc()
    target_title = str(target_record.get("title") or target_record["source_id"])
    label = {"source_reflection": "Reflection",
             "source_retraction": "Retraction"}.get(source_type, "Correction")
    title = title or f"{label} for {target_title}"
    CORRECTION_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    path = _unique_path(CORRECTION_SOURCES_DIR, title, captured_at)
    payload = f"# {title}\n\n{body.strip()}\n"
    source_id_prefix = {"source_reflection": "reflection",
                        "source_retraction": "retraction"}.get(source_type, "correction")
    metadata: dict[str, object] = {
        "title": title,
        "type": source_type,
        "source_id": f"{source_id_prefix}:{path.stem}",
        "source_medium": source_medium,
        "captured_at": captured_at,
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": rel(path),
        "content_sha256": payload_sha256(payload),
    }
    if source_type == "source_reflection":
        metadata["reflects"] = target_record["source_id"]
    elif source_type == "source_retraction":
        # A retraction never deletes the source — it tells the COMPILER to
        # stop asserting it. suppress_on scopes it to specific page slugs
        # (the mis-attribution case: a source that belongs on Katie's pages
        # but was wrongly pulled onto the author's childhood); empty means
        # suppress everywhere.
        metadata["retracts"] = target_record["source_id"]
        metadata["retracts_path"] = rel(target_path)
        # Pin the CONTENT being retracted (v88): if the target's payload is
        # later replaced (a mis-filed source swapped for a genuine one under
        # the same id), the retraction stops applying automatically.
        metadata["retracts_sha256"] = str(target_record.get("content_sha256", ""))
        metadata["suppress_on"] = suppress_on or []
    else:
        metadata["corrects"] = target_record["source_id"]
        metadata["corrects_path"] = rel(target_path)
        metadata["correction_kind"] = correction_kind or "other"
    write_text(path, f"{format_frontmatter(metadata)}\n\n{payload}")
    register_source(path)
    if source_type == "source_correction":
        # v103: a corrected fact invalidates the target's derived
        # classification — its events/people/themes were extracted from the
        # uncorrected text. Mark it stale so the next weekly batch
        # re-classifies (the prompt injects corrections as authoritative);
        # the old classification keeps feeding the timeline/wiki until the
        # fresh one replaces it.
        try:
            import classify_story  # noqa: PLC0415
            if classify_story.mark_stale(target_path, reason=f"correction filed: {rel(path)}"):
                print(f"→ marked {rel(target_path)} for re-classification")
        except Exception as exc:  # never block the correction itself
            print(f"warn: could not mark classification stale: {exc}", file=sys.stderr)
    return path


def cmd_scan(args: argparse.Namespace) -> int:
    records = scan_sources()
    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "abs_path"} for r in records], indent=2))
    else:
        summarize_records(records)
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    if args.rebuild:
        manifest = sync_manifest(scan_sources(), write=True, prune_missing=True)
    else:
        manifest = load_manifest()
    if args.json:
        print(json.dumps(manifest, indent=2))
    else:
        sources = manifest.get("sources", {})
        changed = sum(1 for item in sources.values() if item.get("changed_since_first_seen"))
        print(f"manifest sources: {len(sources)}")
        print(f"changed since first seen: {changed}")
        print(f"path: {SOURCE_MANIFEST_FILE.relative_to(REPO_DIR)}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    records = scan_sources()
    if args.fix:
        records = apply_safe_fixes(records)
    findings = lint_records(records, strict=args.strict)
    if not args.no_write_findings:
        write_findings(findings)
    if args.json:
        print(json.dumps({"findings": findings}, indent=2))
    else:
        print_findings(findings, limit=args.limit)
    return 1 if any(f["severity"] == "error" for f in findings) else 0


def cmd_findings(args: argparse.Namespace) -> int:
    data = read_json(SOURCE_LINT_FINDINGS_FILE, default={"findings": []}) or {"findings": []}
    findings = data.get("findings", [])
    if args.status:
        findings = [f for f in findings if f.get("status") == args.status]
    if args.json:
        print(json.dumps({"findings": findings}, indent=2))
    else:
        print_findings(findings, limit=args.limit)
    return 0


def cmd_correct(args: argparse.Namespace) -> int:
    body = sys.stdin.read().strip()
    if not body:
        print("Error: correction text must be provided on stdin", file=sys.stderr)
        return 1
    path = create_linked_source(
        args.target,
        body,
        source_type="source_correction",
        title=args.title,
        source_medium=args.source,
        correction_kind=args.kind,
    )
    print(f"✓ Created correction source: {rel(path)}")
    return 0


def cmd_retract(args: argparse.Namespace) -> int:
    body = (sys.stdin.read().strip() if not sys.stdin.isatty() else "") or args.reason or ""
    if not body:
        print("Error: provide a reason (--reason or stdin)", file=sys.stderr)
        return 1
    path = create_linked_source(
        args.target,
        body,
        source_type="source_retraction",
        title=args.title,
        source_medium=args.source,
        suppress_on=args.from_page or [],
    )
    scope = f"on page(s) {', '.join(args.from_page)}" if args.from_page else "everywhere"
    print(f"✓ Created retraction source: {rel(path)}")
    print(f"  The compiler will stop asserting the target {scope}. The raw source is untouched.")
    return 0


def unretract(retraction_path: Path, reason: str) -> None:
    """Void a retraction: the compiler ignores it from the next compile on.
    Additive in spirit — the record and its original reason are preserved for
    the audit trail; only directive metadata (voided/voided_at/voided_reason)
    is added. The retracted source resumes being asserted."""
    content = retraction_path.read_text(encoding="utf-8", errors="replace")
    metadata, payload = split_frontmatter(content)
    if str(metadata.get("type", "")) != "source_retraction":
        raise ValueError(f"not a retraction source: {rel(retraction_path)}")
    if metadata.get("voided"):
        raise ValueError(f"already voided: {rel(retraction_path)}")
    metadata["voided"] = True
    metadata["voided_at"] = now_utc()
    metadata["voided_reason"] = reason
    write_text(retraction_path, f"{format_frontmatter(metadata)}\n\n{payload.strip()}\n")
    register_source(retraction_path)


def cmd_unretract(args: argparse.Namespace) -> int:
    path = resolve_source_target(args.retraction)
    try:
        unretract(path, args.reason or "unretracted")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"✓ Voided retraction: {rel(path)}")
    print("  The retracted source resumes being asserted on the next compile.")
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    body = sys.stdin.read().strip()
    if not body:
        print("Error: reflection text must be provided on stdin", file=sys.stderr)
        return 1
    path = create_linked_source(
        args.target,
        body,
        source_type="source_reflection",
        title=args.title,
        source_medium=args.source,
    )
    print(f"✓ Created reflection source: {rel(path)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug source integrity tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("retract", help="Retract a source: the compiler stops asserting it (file stays immutable)")
    p.add_argument("target", help="source id or path, e.g. answers/L20.md")
    p.add_argument("--reason", default=None, help="Why this is retracted (or pipe via stdin)")
    p.add_argument("--from-page", action="append", default=[], metavar="SLUG",
                   help="Only suppress on these wiki page slugs (repeatable); omit = everywhere")
    p.add_argument("--title", default=None)
    p.add_argument("--source", default="manual")
    p.set_defaults(func=cmd_retract)

    p = sub.add_parser("unretract", help="Void a wrong retraction: the retracted source resumes being asserted")
    p.add_argument("retraction", help="retraction source id or path under sources/corrections/")
    p.add_argument("--reason", default=None, help="Why the retraction was wrong")
    p.set_defaults(func=cmd_unretract)

    p = sub.add_parser("scan", help="Summarize raw source files")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("manifest", help="Show or rebuild the source manifest")
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("lint", help="Lint source integrity and write repair findings")
    p.add_argument("--fix", action="store_true", help="Apply safe metadata/manifest fixes")
    p.add_argument("--strict", action="store_true", help="Also report uncited sources")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-write-findings", action="store_true")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("findings", help="List persisted source lint findings")
    p.add_argument("--status", default="open")
    p.add_argument("--json", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_findings)

    p = sub.add_parser("correct", help="Create an additive correction source from stdin")
    p.add_argument("target", help="Source path or source_id to correct")
    p.add_argument("--kind", default="other", choices=["factual", "date", "name", "emotional", "perspective", "omission", "relationship", "other"])
    p.add_argument("--source", default="manual")
    p.add_argument("--title")
    p.set_defaults(func=cmd_correct)

    p = sub.add_parser("reflect", help="Create an additive reflection source from stdin")
    p.add_argument("target", help="Source path or source_id to reflect on")
    p.add_argument("--source", default="manual")
    p.add_argument("--title")
    p.set_defaults(func=cmd_reflect)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
