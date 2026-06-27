#!/usr/bin/env python3
"""Lifehug Artifact Workflow.

Creates occasion-driven outputs (letters, posts, chapters) and can promote the
working context pack plus the final authored output back into immutable sources.

The script does not call AI. It emits context and prompts; a desktop agent or
Telegram/OpenClaw agent writes the artifact, then this script saves and
registers it.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import compose
from lifehug_core import (
    ARTIFACT_SOURCES_DIR,
    OUTPUTS_DIR,
    REPO_DIR,
    TEMPLATES_DIR,
    WIKI_DIR,
    now_utc,
    read_json,
    slugify,
    split_frontmatter,
    write_json,
    write_text,
)
from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256, register_source

ARTIFACT_FILE = "artifact.json"
CONTEXT_FILE = "context.md"
SUPPORTED_FORMATS = compose.VALID_FORMATS


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def display_path(path: Path) -> str:
    return rel(path)


def parse_categories_arg(raw: str | None) -> list[str]:
    if not raw:
        return []
    out = []
    for item in raw.split(","):
        item = item.strip().upper()
        if item:
            if not re.match(r"^[A-Z]$", item):
                raise ValueError(f"invalid category '{item}'")
            out.append(item)
    return out


def default_title(subject: str | None, occasion: str | None, format_name: str, date: str | None) -> str:
    parts = []
    if date:
        parts.append(date)
    if subject:
        parts.append(subject)
    if occasion:
        parts.append(occasion)
    parts.append(format_name)
    return slugify(" ".join(parts))


def output_dir_for(ref: str) -> Path:
    path = Path(ref)
    if not path.is_absolute():
        if len(path.parts) == 1:
            path = OUTPUTS_DIR / path
        else:
            path = REPO_DIR / path
    return path


def artifact_path(out_dir: Path) -> Path:
    return out_dir / ARTIFACT_FILE


def load_artifact(out_dir: Path) -> dict:
    data = read_json(artifact_path(out_dir), default=None)
    if not isinstance(data, dict):
        raise SystemExit(f"Error: no {ARTIFACT_FILE} found in {display_path(out_dir)}")
    data.setdefault("versions", [])
    data.setdefault("promoted_sources", [])
    data.setdefault("context_sources", [])
    return data


def save_artifact(out_dir: Path, data: dict) -> None:
    data["updated_at"] = now_utc()
    write_json(artifact_path(out_dir), data)


def latest_version_file(out_dir: Path) -> Path | None:
    versions = []
    for path in out_dir.glob("v*.md"):
        match = re.match(r"^v(\d+)\.md$", path.name)
        if match:
            versions.append((int(match.group(1)), path))
    if not versions:
        return None
    return sorted(versions)[-1][1]


def next_version_number(out_dir: Path) -> int:
    latest = latest_version_file(out_dir)
    if latest is None:
        return 1
    return int(latest.stem[1:]) + 1


def read_body_without_frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    _metadata, body = split_frontmatter(text)
    return body.strip()


def snippet(text: str, limit: int = 1800) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0] + "..."


def source_answers_for(categories: list[str]) -> tuple[list[dict], list[str]]:
    answers = compose.read_answers_for_categories(categories)
    lookup = compose.build_question_lookup()
    source_paths = []
    blocks = []
    for item in answers:
        qid = item["id"]
        path = Path("answers") / item["file"]
        source_paths.append(path.as_posix())
        blocks.append({
            "id": qid,
            "question": lookup.get(qid, "(question text not found)"),
            "source": path.as_posix(),
            "body": compose.extract_answer_body(item["content"]),
        })
    return blocks, source_paths


def wiki_matches(subject: str | None, limit: int = 6) -> tuple[list[dict], list[str]]:
    if not subject or not WIKI_DIR.exists():
        return [], []
    subject_l = subject.lower()
    matches: list[dict] = []
    paths: list[str] = []
    for path in sorted(WIKI_DIR.rglob("*.md")):
        if path.name in {"index.md", "log.md", "SCHEMA.md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        haystack = f"{path.stem} {text}".lower()
        if subject_l not in haystack:
            continue
        body = read_body_without_frontmatter(path)
        paths.append(rel(path))
        matches.append({"source": rel(path), "body": body})
        if len(matches) >= limit:
            break
    return matches, paths


def prior_artifacts(subject: str | None, current_dir: Path, limit: int = 4) -> tuple[list[dict], list[str]]:
    if not subject or not OUTPUTS_DIR.exists():
        return [], []
    subject_l = subject.lower()
    matches: list[dict] = []
    paths: list[str] = []
    for out_dir in sorted(OUTPUTS_DIR.iterdir()):
        if not out_dir.is_dir() or out_dir.resolve() == current_dir.resolve():
            continue
        data = read_json(out_dir / ARTIFACT_FILE, default={})
        meta_subject = str(data.get("subject", ""))
        meta_title = str(data.get("title", out_dir.name))
        if subject_l not in f"{meta_subject} {meta_title}".lower():
            continue
        latest = latest_version_file(out_dir)
        if not latest:
            continue
        body = latest.read_text(encoding="utf-8", errors="replace")
        paths.append(rel(latest))
        matches.append({"source": rel(latest), "body": body})
        if len(matches) >= limit:
            break
    return matches, paths


def build_context(meta: dict, out_dir: Path) -> tuple[str, list[str]]:
    answers, answer_paths = source_answers_for(meta.get("categories", []))
    wiki, wiki_paths = wiki_matches(meta.get("subject"))
    artifacts, artifact_paths = prior_artifacts(meta.get("subject"), out_dir)
    sources = answer_paths + wiki_paths + artifact_paths

    lines = [
        f"# Artifact Context: {meta['title']}",
        "",
        "## Task",
        f"- Format: {meta['format']}",
        f"- Subject: {meta.get('subject') or '(none)'}",
        f"- Occasion: {meta.get('occasion') or '(none)'}",
        f"- Occasion date: {meta.get('occasion_date') or '(none)'}",
        f"- Audience: {meta.get('audience') or '(not specified)'}",
        f"- Privacy: {meta.get('privacy') or 'owner_only'}",
        "",
        "## Source Answers",
    ]
    if answers:
        for item in answers:
            lines.extend([
                "",
                f"### [{item['id']}] {item['question']}",
                f"Source: {item['source']}",
                "",
                snippet(item["body"], 2200),
            ])
    else:
        lines.append("(no matching answers found)")

    lines.extend(["", "## Wiki Context"])
    if wiki:
        for item in wiki:
            lines.extend(["", f"### {item['source']}", "", snippet(item["body"], 1600)])
    else:
        lines.append("(no matching wiki pages found)")

    lines.extend(["", "## Prior Artifacts"])
    if artifacts:
        for item in artifacts:
            lines.extend(["", f"### {item['source']}", "", snippet(item["body"], 1200)])
    else:
        lines.append("(no prior artifacts found for this subject)")

    lines.extend(["", "## Source Index"])
    if sources:
        lines.extend(f"- {source}" for source in sources)
    else:
        lines.append("- (none)")

    return "\n".join(lines).rstrip() + "\n", sources


def build_prompt(meta: dict, context: str) -> str:
    template_path = TEMPLATES_DIR / f"{meta['format']}.md"
    if not template_path.exists():
        raise SystemExit(f"Error: missing template {display_path(template_path)}")
    template = template_path.read_text(encoding="utf-8").strip()
    return f"""LIFEHUG ARTIFACT

You are creating a meaningful life artifact for the author. Use the context as
grounding, but write the final piece as a human artifact the author could send,
post, publish, or keep.

FORMAT INSTRUCTIONS
{template}

ARTIFACT DETAILS
- Title: {meta['title']}
- Format: {meta['format']}
- Subject: {meta.get('subject') or '(none)'}
- Occasion: {meta.get('occasion') or '(none)'}
- Occasion date: {meta.get('occasion_date') or '(none)'}
- Audience: {meta.get('audience') or '(not specified)'}

CONTEXT PACK
{context}

Output ONLY the artifact text. No explanation, no markdown fences.
"""


def write_compose_meta(out_dir: Path, meta: dict) -> None:
    compose_meta = {
        "title": meta["title"],
        "format": meta["format"],
        "subject": meta.get("subject", ""),
        "categories": meta.get("categories", []),
        "created": meta.get("created_at", now_utc())[:10],
        "versions": [
            {
                "version": str(v["version"]),
                "created": v["created_at"],
                "model": v.get("model", "unknown"),
                **({"feedback": v["feedback"]} if v.get("feedback") else {}),
            }
            for v in meta.get("versions", [])
        ],
    }
    compose.write_meta(out_dir / "meta.yaml", compose_meta)


def cmd_new(args: argparse.Namespace) -> int:
    if args.format not in SUPPORTED_FORMATS:
        raise SystemExit(f"Error: --format must be one of {', '.join(SUPPORTED_FORMATS)}")
    try:
        categories = parse_categories_arg(args.categories)
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from exc
    resolved_subject = args.subject
    if not categories and args.subject:
        categories, resolved_subject = compose.resolve_categories(args.subject, None)

    title = args.title or default_title(resolved_subject or args.subject, args.occasion, args.format, args.date)
    out_dir = OUTPUTS_DIR / slugify(title)
    out_dir.mkdir(parents=True, exist_ok=True)
    if artifact_path(out_dir).exists() and not args.force:
        raise SystemExit(f"Error: artifact already exists at {display_path(out_dir)} (use --force to rebuild context)")

    meta = {
        "version": 1,
        "artifact_id": out_dir.name,
        "title": title,
        "format": args.format,
        "subject": resolved_subject or args.subject or "",
        "occasion": args.occasion or "",
        "occasion_date": args.date or "",
        "audience": args.audience or "",
        "privacy": args.privacy,
        "categories": categories,
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "context_path": rel(out_dir / CONTEXT_FILE),
        "context_sources": [],
        "versions": [],
        "promoted_sources": [],
    }
    context, sources = build_context(meta, out_dir)
    meta["context_sources"] = sources
    write_text(out_dir / CONTEXT_FILE, context)
    save_artifact(out_dir, meta)
    write_compose_meta(out_dir, meta)

    print(f"Created artifact task: {display_path(out_dir)}")
    print(f"Context pack: {display_path(out_dir / CONTEXT_FILE)} ({len(sources)} source refs)")
    print()
    print(f"Next: python3 system/lifehug.py artifact prompt {display_path(out_dir)}")
    if args.print_prompt:
        print()
        print(build_prompt(meta, context))
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    out_dir = output_dir_for(args.output)
    meta = load_artifact(out_dir)
    context_path = REPO_DIR / meta["context_path"]
    if not context_path.exists():
        context, sources = build_context(meta, out_dir)
        meta["context_sources"] = sources
        write_text(context_path, context)
        save_artifact(out_dir, meta)
    else:
        context = context_path.read_text(encoding="utf-8", errors="replace")
    print(build_prompt(meta, context))
    return 0


def cmd_save(args: argparse.Namespace) -> int:
    out_dir = output_dir_for(args.output)
    meta = load_artifact(out_dir)
    content = sys.stdin.read().strip()
    if not content:
        raise SystemExit("Error: artifact content must be provided on stdin")
    version = next_version_number(out_dir)
    out_file = out_dir / f"v{version}.md"
    write_text(out_file, content + "\n")
    entry = {
        "version": version,
        "path": rel(out_file),
        "created_at": now_utc(),
        "model": args.model or "unknown",
    }
    if args.feedback:
        entry["feedback"] = args.feedback
    meta.setdefault("versions", []).append(entry)
    if args.final:
        meta["final_version"] = version
    save_artifact(out_dir, meta)
    write_compose_meta(out_dir, meta)
    print(f"Saved {display_path(out_file)}")
    if args.final:
        print(f"Marked v{version} final")
    return 0


def cmd_final(args: argparse.Namespace) -> int:
    out_dir = output_dir_for(args.output)
    meta = load_artifact(out_dir)
    version = args.version
    if version == "latest":
        latest = latest_version_file(out_dir)
        if latest is None:
            raise SystemExit("Error: no artifact versions exist")
        version = latest.stem[1:]
    version_number = int(str(version).lstrip("v"))
    if not (out_dir / f"v{version_number}.md").exists():
        raise SystemExit(f"Error: v{version_number}.md does not exist")
    meta["final_version"] = version_number
    save_artifact(out_dir, meta)
    print(f"Marked {display_path(out_dir / f'v{version_number}.md')} final")
    return 0


def artifact_version_path(out_dir: Path, meta: dict, version: str) -> Path:
    wanted = version
    if wanted == "final":
        final_version = meta.get("final_version")
        if final_version:
            wanted = str(final_version)
        else:
            wanted = "latest"
    if wanted == "latest":
        latest = latest_version_file(out_dir)
        if latest is None:
            raise SystemExit("Error: no artifact versions exist")
        return latest
    number = int(str(wanted).lstrip("v"))
    path = out_dir / f"v{number}.md"
    if not path.exists():
        raise SystemExit(f"Error: {display_path(path)} does not exist")
    return path


def unique_source_path(meta: dict, kind: str, version_path: Path | None = None) -> Path:
    day = now_utc()[:10]
    suffix = kind
    if version_path is not None:
        suffix = f"{kind}-{version_path.stem}"
    base = f"{day}-{slugify(meta['artifact_id'])}-{suffix}"
    path = ARTIFACT_SOURCES_DIR / f"{base}.md"
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = ARTIFACT_SOURCES_DIR / f"{base}-{index}.md"
        if not candidate.exists():
            return candidate
        index += 1


def source_metadata(meta: dict, source_path: Path, body: str, *, kind: str,
                    source_medium: str, version_path: Path | None = None) -> dict:
    source_type = "authored_artifact" if kind == "final" else "artifact_context"
    trust = "authored_expression" if kind == "final" else "derived_context"
    authority = "first_person_expression" if kind == "final" else "derived_working_context"
    source_id_suffix = version_path.stem if version_path is not None else kind
    values = {
        "title": f"{meta['title']} ({kind})" if kind != "final" else meta["title"],
        "type": source_type,
        "source_id": f"artifact:{meta['artifact_id']}:{source_id_suffix}",
        "source_medium": source_medium,
        "source_type": source_type,
        "source_trust": trust,
        "authority": authority,
        "artifact_id": meta["artifact_id"],
        "artifact_title": meta["title"],
        "artifact_format": meta["format"],
        "subject": meta.get("subject", ""),
        "occasion": meta.get("occasion", ""),
        "occasion_date": meta.get("occasion_date", ""),
        "audience": meta.get("audience", ""),
        "privacy": meta.get("privacy", "owner_only"),
        "generated_from": meta.get("context_sources", []),
        "output_path": rel(version_path) if version_path is not None else meta.get("context_path"),
        "captured_at": now_utc(),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": rel(source_path),
        "content_sha256": payload_sha256(body),
    }
    if version_path is not None:
        values["output_version"] = version_path.stem
    return values


def write_source(meta: dict, *, kind: str, source_medium: str,
                 version_path: Path | None = None) -> Path:
    if kind == "context":
        payload_path = REPO_DIR / meta["context_path"]
        payload = payload_path.read_text(encoding="utf-8", errors="replace").strip()
        heading = f"# Artifact Context: {meta['title']}"
        body = payload if payload.startswith("# ") else f"{heading}\n\n{payload}"
    elif kind == "final":
        if version_path is None:
            raise ValueError("final source requires a version path")
        payload = version_path.read_text(encoding="utf-8", errors="replace").strip()
        body = f"# {meta['title']}\n\n{payload}\n"
    else:
        raise ValueError(f"unknown source kind: {kind}")

    source_path = unique_source_path(meta, kind, version_path)
    metadata = source_metadata(meta, source_path, body, kind=kind,
                               source_medium=source_medium, version_path=version_path)
    content = f"{format_frontmatter(metadata)}\n\n{body.rstrip()}\n"
    write_text(source_path, content)
    register_source(source_path)
    return source_path


def record_promotion(out_dir: Path, meta: dict, kind: str, path: Path, version_path: Path | None) -> None:
    entry = {
        "kind": kind,
        "path": rel(path),
        "promoted_at": now_utc(),
    }
    if version_path is not None:
        entry["output_version"] = version_path.stem
        entry["output_path"] = rel(version_path)
    existing = {
        (item.get("kind"), item.get("output_path"), item.get("path"))
        for item in meta.setdefault("promoted_sources", [])
    }
    key = (entry.get("kind"), entry.get("output_path"), entry.get("path"))
    if key not in existing:
        meta["promoted_sources"].append(entry)
    save_artifact(out_dir, meta)


def existing_promotion(meta: dict, kind: str, version_path: Path | None) -> Path | None:
    output_path = rel(version_path) if version_path is not None else meta.get("context_path")
    for item in meta.get("promoted_sources", []):
        if item.get("kind") != kind:
            continue
        if item.get("output_path") != output_path and kind == "final":
            continue
        if kind == "context" and item.get("path"):
            path = REPO_DIR / str(item["path"])
            if path.exists():
                return path
        if kind == "final" and item.get("path"):
            path = REPO_DIR / str(item["path"])
            if path.exists():
                return path
    return None


def cmd_promote_source(args: argparse.Namespace) -> int:
    out_dir = output_dir_for(args.output)
    meta = load_artifact(out_dir)
    kinds = ["context", "final"] if args.kind == "all" else [args.kind]
    version_path = None
    if "final" in kinds:
        version_path = artifact_version_path(out_dir, meta, args.version)

    for kind in kinds:
        maybe_existing = existing_promotion(meta, kind, version_path if kind == "final" else None)
        if maybe_existing is not None:
            print(f"{kind} source already promoted: {display_path(maybe_existing)}")
            continue
        path = write_source(
            meta,
            kind=kind,
            source_medium=args.source,
            version_path=version_path if kind == "final" else None,
        )
        record_promotion(out_dir, meta, kind, path, version_path if kind == "final" else None)
        print(f"Promoted {kind} source: {display_path(path)}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    rows = []
    if OUTPUTS_DIR.exists():
        for out_dir in sorted(OUTPUTS_DIR.iterdir()):
            if not out_dir.is_dir() or not artifact_path(out_dir).exists():
                continue
            data = read_json(artifact_path(out_dir), default={})
            rows.append(
                f"{out_dir.name:<34} {data.get('format', '?'):<10} "
                f"{data.get('subject', ''):<20} versions={len(data.get('versions', []))}"
            )
    if not rows:
        print("(no artifact tasks yet)")
        return 0
    print("Artifacts:")
    for row in rows:
        print(f"  {row}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    out_dir = output_dir_for(args.output)
    data = load_artifact(out_dir)
    print(f"Title:     {data.get('title')}")
    print(f"Format:    {data.get('format')}")
    print(f"Subject:   {data.get('subject') or '(none)'}")
    print(f"Occasion:  {data.get('occasion') or '(none)'}")
    print(f"Date:      {data.get('occasion_date') or '(none)'}")
    print(f"Privacy:   {data.get('privacy') or 'owner_only'}")
    print(f"Path:      {display_path(out_dir)}")
    print(f"Context:   {data.get('context_path')}")
    if data.get("final_version"):
        print(f"Final:     v{data['final_version']}")
    print()
    print("Versions:")
    for item in data.get("versions", []):
        marker = " final" if data.get("final_version") == item.get("version") else ""
        print(f"  v{item['version']}  {item.get('created_at', '?')}  {item.get('model', 'unknown')}{marker}")
    print()
    print("Promoted sources:")
    for item in data.get("promoted_sources", []):
        print(f"  {item.get('kind')}: {item.get('path')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create Lifehug artifacts and promote them as sources")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="Create an artifact task and context pack")
    p.add_argument("--subject", help="Focus subject, e.g. Mom or Katie")
    p.add_argument("--occasion", help="Occasion, e.g. Mother's Day")
    p.add_argument("--format", required=True, choices=SUPPORTED_FORMATS)
    p.add_argument("--date", help="Occasion date YYYY-MM-DD")
    p.add_argument("--title", help="Output slug/title; defaults from subject/occasion/format")
    p.add_argument("--audience", default="")
    p.add_argument("--privacy", default="owner_only")
    p.add_argument("--categories", help="Explicit category letters, e.g. K,L")
    p.add_argument("--force", action="store_true", help="Rebuild context if task already exists")
    p.add_argument("--print-prompt", action="store_true")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("prompt", help="Print the generation prompt for an artifact")
    p.add_argument("output", help="Output dir, e.g. outputs/mothers-day or mothers-day")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("save", help="Save generated artifact text from stdin as vN.md")
    p.add_argument("output")
    p.add_argument("--model", default="unknown")
    p.add_argument("--feedback", default="")
    p.add_argument("--final", action="store_true", help="Mark this saved version final")
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("final", help="Mark an artifact version final")
    p.add_argument("output")
    p.add_argument("--version", default="latest")
    p.set_defaults(func=cmd_final)

    p = sub.add_parser("promote-source", help="Promote artifact context/final output into sources/artifacts")
    p.add_argument("output")
    p.add_argument("--kind", default="final", choices=["context", "final", "all"])
    p.add_argument("--version", default="final", help="final, latest, or vN")
    p.add_argument("--source", default="lifehug artifact")
    p.set_defaults(func=cmd_promote_source)

    p = sub.add_parser("list", help="List artifact tasks")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("info", help="Show artifact task details")
    p.add_argument("output")
    p.set_defaults(func=cmd_info)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
