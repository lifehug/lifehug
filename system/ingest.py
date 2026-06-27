#!/usr/bin/env python3
"""Lifehug — Unified source ingest with pluggable connectors.

Provides a standard interface for importing external sources (X/Twitter,
email, Instagram, etc.) into the Lifehug source store. Each connector
adapts its source format into standardized records.

Usage:
    python3 system/ingest.py --source x --limit 50
    python3 system/ingest.py --source email --query "personal" --since 2020-01-01
    python3 system/ingest.py --source instagram --export-path /path/to/export
    python3 system/ingest.py --source file --path /path/to/stories.txt
    python3 system/ingest.py --list-sources
    python3 system/ingest.py --source x --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from lifehug_core import (
    CONNECTORS_DIR,
    QUESTION_CANDIDATES_FILE,
    REPO_DIR,
    SOURCES_DIR,
    now_utc,
    read_json,
    slugify,
    write_json,
    write_text,
)
from source_integrity import SCHEMA_VERSION, format_frontmatter, payload_sha256, register_source


# ---------------------------------------------------------------------------
# Standard source record
# ---------------------------------------------------------------------------

class SourceRecord:
    """Normalized record that every connector must produce."""

    def __init__(
        self,
        text: str,
        source_type: str,
        source_id: str,
        *,
        date: str | None = None,
        title: str | None = None,
        raw_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.text = text.strip()
        self.source_type = source_type
        self.source_id = source_id
        self.date = date or now_utc()
        self.title = title or self._title_from_text()
        self.raw_url = raw_url
        self.metadata = metadata or {}

    def _title_from_text(self) -> str:
        words = re.findall(r"[A-Za-z0-9']+", self.text)
        if not words:
            return "Untitled"
        return " ".join(words[:8]).strip().title()

    def dedup_key(self) -> str:
        return f"{self.source_type}:{self.source_id}"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "date": self.date,
            "title": self.title,
            "raw_url": self.raw_url,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Base connector
# ---------------------------------------------------------------------------

class BaseConnector(ABC):
    """Interface that every source connector must implement."""

    name: str = "base"
    description: str = "Base connector (do not use directly)"

    @abstractmethod
    def fetch(self, args: argparse.Namespace) -> list[SourceRecord]:
        """Fetch raw data from the source and return normalized records."""
        ...

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Add connector-specific CLI arguments."""
        pass


# ---------------------------------------------------------------------------
# Built-in connectors
# ---------------------------------------------------------------------------

class FileConnector(BaseConnector):
    """Ingest from a local text/markdown file."""

    name = "file"
    description = "Import stories from a local text or markdown file"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--path", help="Path to the file to ingest")

    def fetch(self, args: argparse.Namespace) -> list[SourceRecord]:
        path = Path(args.path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        # Split on double newlines if file is large (>2000 chars) to get
        # individual stories; otherwise treat as one record
        if len(text) > 2000:
            chunks = re.split(r"\n{3,}", text)
            chunks = [c.strip() for c in chunks if c.strip() and len(c.strip()) > 50]
        else:
            chunks = [text.strip()]
        records = []
        for i, chunk in enumerate(chunks):
            source_id = hashlib.sha256(f"{path.name}:{i}".encode()).hexdigest()[:12]
            records.append(SourceRecord(
                text=chunk,
                source_type="file",
                source_id=source_id,
                title=None,
                metadata={"original_file": str(path)},
            ))
        return records


class XConnector(BaseConnector):
    """Ingest from X/Twitter using bird CLI or export file."""

    name = "x"
    description = "Import tweets from X/Twitter (bird CLI or export)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--export-path", help="Path to X data export JSON")
        parser.add_argument("--username", help="Twitter username to fetch")

    def fetch(self, args: argparse.Namespace) -> list[SourceRecord]:
        if args.export_path:
            return self._from_export(args)
        return self._from_bird(args)

    def _from_export(self, args: argparse.Namespace) -> list[SourceRecord]:
        path = Path(args.export_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Export file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        tweets = data if isinstance(data, list) else data.get("tweets", data.get("data", []))
        records = []
        for tweet in tweets[: args.limit or 500]:
            t = tweet.get("tweet", tweet)
            text = t.get("full_text", t.get("text", "")).strip()
            if not text or len(text) < 20:
                continue
            tweet_id = str(t.get("id", t.get("id_str", "")))
            created = t.get("created_at", "")
            records.append(SourceRecord(
                text=text,
                source_type="x",
                source_id=tweet_id or hashlib.sha256(text.encode()).hexdigest()[:12],
                date=created or None,
                raw_url=f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
                metadata={"retweet_count": t.get("retweet_count", 0), "favorite_count": t.get("favorite_count", 0)},
            ))
        return records

    def _from_bird(self, args: argparse.Namespace) -> list[SourceRecord]:
        import subprocess
        limit = args.limit or 50
        env = os.environ.copy()
        bird_env = Path.home() / ".config" / "bird" / "env"
        if bird_env.exists():
            for line in bird_env.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    key, _, val = line.partition("=")
                    env[key.strip()] = val.strip().strip('"').strip("'")
        cmd = ["bird", "me", "-n", str(limit), "--json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        except FileNotFoundError:
            raise RuntimeError("bird CLI not found. Install it or use --export-path")
        except subprocess.TimeoutExpired:
            raise RuntimeError("bird CLI timed out")
        if result.returncode != 0:
            raise RuntimeError(f"bird CLI failed: {result.stderr.strip()}")
        tweets = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(tweets, list):
            tweets = tweets.get("tweets", tweets.get("data", []))
        records = []
        for tweet in tweets:
            text = tweet.get("full_text", tweet.get("text", "")).strip()
            if not text or len(text) < 20:
                continue
            tweet_id = str(tweet.get("id", tweet.get("id_str", "")))
            records.append(SourceRecord(
                text=text,
                source_type="x",
                source_id=tweet_id or hashlib.sha256(text.encode()).hexdigest()[:12],
                date=tweet.get("created_at"),
                raw_url=f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
                metadata={k: tweet.get(k, 0) for k in ("retweet_count", "favorite_count")},
            ))
        return records


class EmailConnector(BaseConnector):
    """Ingest from Gmail using gog CLI."""

    name = "email"
    description = "Import personal emails from Gmail (gog CLI)"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--query", help="Gmail search query", default="is:sent label:personal")
        parser.add_argument("--since", help="Only emails after this date (YYYY-MM-DD)")

    def fetch(self, args: argparse.Namespace) -> list[SourceRecord]:
        import subprocess
        query = args.query or "is:sent label:personal"
        if args.since:
            query += f" after:{args.since}"
        limit = args.limit or 50
        cmd = ["gog", "gmail", "list", "--query", query, "--max", str(limit), "--json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            raise RuntimeError("gog CLI not found. Install it for Gmail access.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("gog CLI timed out")
        if result.returncode != 0:
            raise RuntimeError(f"gog failed: {result.stderr.strip()}")
        messages = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(messages, list):
            messages = messages.get("messages", [])
        records = []
        for msg in messages:
            body = msg.get("snippet", msg.get("body", "")).strip()
            subject = msg.get("subject", "")
            if not body or len(body) < 30:
                continue
            text = f"Subject: {subject}\n\n{body}" if subject else body
            msg_id = str(msg.get("id", ""))
            records.append(SourceRecord(
                text=text,
                source_type="email",
                source_id=msg_id or hashlib.sha256(text.encode()).hexdigest()[:12],
                date=msg.get("date", msg.get("internalDate")),
                title=subject or None,
                metadata={"from": msg.get("from", ""), "to": msg.get("to", "")},
            ))
        return records


class InstagramConnector(BaseConnector):
    """Ingest from Instagram data export."""

    name = "instagram"
    description = "Import posts from Instagram data export"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--export-path", help="Path to Instagram data export directory or JSON")

    def fetch(self, args: argparse.Namespace) -> list[SourceRecord]:
        path = Path(args.export_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Export path not found: {path}")

        # Instagram exports can be a directory or a JSON file
        posts_files = []
        if path.is_dir():
            for candidate in [
                path / "content" / "posts_1.json",
                path / "your_instagram_activity" / "content" / "posts_1.json",
                path / "posts_1.json",
            ]:
                if candidate.exists():
                    posts_files.append(candidate)
            if not posts_files:
                # Try any JSON file
                posts_files = list(path.rglob("posts*.json"))
        elif path.suffix == ".json":
            posts_files = [path]

        if not posts_files:
            raise FileNotFoundError("No Instagram posts JSON found in export")

        records = []
        for posts_file in posts_files:
            data = json.loads(posts_file.read_text(encoding="utf-8"))
            posts = data if isinstance(data, list) else data.get("posts", data.get("ig_posts", []))
            for post in posts[: args.limit or 500]:
                # Instagram export format varies
                media = post.get("media", [post]) if isinstance(post.get("media"), list) else [post]
                for item in media:
                    caption = item.get("title", item.get("caption", "")).strip()
                    if not caption or len(caption) < 20:
                        continue
                    ts = item.get("creation_timestamp", item.get("taken_at", ""))
                    date = None
                    if isinstance(ts, (int, float)):
                        date = datetime.fromtimestamp(ts).isoformat()
                    elif isinstance(ts, str) and ts:
                        date = ts
                    uri = item.get("uri", "")
                    records.append(SourceRecord(
                        text=caption,
                        source_type="instagram",
                        source_id=hashlib.sha256(f"ig:{caption[:100]}:{ts}".encode()).hexdigest()[:12],
                        date=date,
                        raw_url=uri if uri.startswith("http") else None,
                        metadata={"media_type": item.get("media_type", "unknown")},
                    ))
        return records


# ---------------------------------------------------------------------------
# Connector registry
# ---------------------------------------------------------------------------

BUILTIN_CONNECTORS: dict[str, type[BaseConnector]] = {
    "file": FileConnector,
    "x": XConnector,
    "email": EmailConnector,
    "instagram": InstagramConnector,
}


def discover_connectors() -> dict[str, type[BaseConnector]]:
    """Load built-in connectors and any custom ones from system/connectors/."""
    connectors = dict(BUILTIN_CONNECTORS)
    if CONNECTORS_DIR.exists():
        for path in sorted(CONNECTORS_DIR.glob("*_connector.py")):
            name = path.stem.replace("_connector", "")
            if name in connectors:
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"connectors.{name}", path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for attr in dir(mod):
                        obj = getattr(mod, attr)
                        if (
                            isinstance(obj, type)
                            and issubclass(obj, BaseConnector)
                            and obj is not BaseConnector
                            and hasattr(obj, "name")
                        ):
                            connectors[obj.name] = obj
            except Exception as exc:
                print(f"warning: failed to load connector {path.name}: {exc}", file=sys.stderr)
    return connectors


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def source_dir(source_type: str) -> Path:
    return SOURCES_DIR / source_type


def load_existing_ids(source_type: str) -> set[str]:
    """Load source_id values already ingested for dedup."""
    directory = source_dir(source_type)
    ids: set[str] = set()
    if not directory.exists():
        return ids
    for path in directory.glob("*.md"):
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'^source_id:\s*"?(.+?)"?\s*$', text, re.MULTILINE)
        if match:
            ids.add(match.group(1).strip())
    return ids


def store_record(record: SourceRecord) -> Path:
    """Write a source record to the appropriate directory."""
    directory = source_dir(record.source_type)
    directory.mkdir(parents=True, exist_ok=True)
    day = record.date[:10] if record.date and len(record.date) >= 10 else datetime.now().date().isoformat()
    base = f"{day}-{slugify(record.title or 'untitled')}"
    path = directory / f"{base}.md"
    if path.exists():
        idx = 2
        while True:
            candidate = directory / f"{base}-{idx}.md"
            if not candidate.exists():
                path = candidate
                break
            idx += 1

    relative = path.relative_to(REPO_DIR).as_posix()
    payload = f"# {record.title}\n\n{record.text}\n"
    metadata: dict[str, Any] = {
        "title": record.title,
        "type": "ingested_source",
        "source_type": record.source_type,
        "source_id": f"{record.source_type}:{record.source_id}",
        "source_medium": record.source_type,
        "source": record.source_type,
        "captured_at": record.date,
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": payload_sha256(payload),
    }
    if record.raw_url:
        metadata["raw_url"] = record.raw_url
    if record.metadata:
        metadata["metadata"] = record.metadata

    content = f"{format_frontmatter(metadata)}\n\n{payload}"
    write_text(path, content)
    register_source(path)
    return path


def generate_candidates(record: SourceRecord, source_path: str) -> list[dict]:
    """Generate deterministic candidate questions for an ingested record."""
    subject = record.title or "this story"
    created = now_utc()
    templates = [
        ("scene", f"Can you walk through {subject} as a scene — what did you see, hear, feel?", 0.60),
        ("meaning", f"What does {subject} help explain about who you became?", 0.50),
        ("relationship", f"Who else mattered in {subject}, and how?", 0.48),
    ]
    candidates = []
    for i, (kind, text, priority) in enumerate(templates, 1):
        cid = f"cand-{slugify(Path(source_path).stem)}-{i}"
        candidates.append({
            "id": cid,
            "text": text,
            "source_path": source_path,
            "target_page": None,
            "kind": kind,
            "priority": priority,
            "reason": f"Auto-generated from ingested {record.source_type} source",
            "status": "candidate",
            "story_function": kind,
            "created_at": created,
        })
    return candidates


def append_candidates(candidates: list[dict]) -> None:
    data = read_json(QUESTION_CANDIDATES_FILE, default=None)
    if not isinstance(data, dict):
        data = {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    existing = {c.get("id") for c in data["candidates"]}
    for c in candidates:
        if c["id"] not in existing:
            data["candidates"].append(c)
    data["last_updated"] = now_utc()
    write_json(QUESTION_CANDIDATES_FILE, data)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> int:
    connectors = discover_connectors()
    if args.list_sources:
        print("Available ingest sources:")
        for name, cls in sorted(connectors.items()):
            print(f"  {name}: {cls.description}")
        return 0

    if not args.source:
        print("Error: --source is required (or use --list-sources)", file=sys.stderr)
        return 1

    if args.source not in connectors:
        print(f"Error: unknown source '{args.source}'. Available: {', '.join(sorted(connectors))}", file=sys.stderr)
        return 1

    connector = connectors[args.source]()
    print(f"Fetching from {args.source}...", flush=True)
    try:
        records = connector.fetch(args)
    except Exception as exc:
        print(f"Error fetching: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No records found.")
        return 0

    # Dedup
    existing = load_existing_ids(args.source)
    new_records = [r for r in records if r.dedup_key() not in existing and r.source_id not in existing]
    skipped = len(records) - len(new_records)

    if args.limit:
        new_records = new_records[: args.limit]

    print(f"Found {len(records)} records, {skipped} already ingested, {len(new_records)} new")

    if args.dry_run:
        for r in new_records[:10]:
            print(f"  would ingest: {r.title} ({r.source_type}:{r.source_id})")
        if len(new_records) > 10:
            print(f"  ... and {len(new_records) - 10} more")
        return 0

    all_candidates = []
    for record in new_records:
        path = store_record(record)
        relative = path.relative_to(REPO_DIR).as_posix()
        if not args.no_candidates:
            candidates = generate_candidates(record, relative)
            all_candidates.extend(candidates)
        print(f"  ✓ {relative}")

    if all_candidates:
        append_candidates(all_candidates)
        print(f"✓ Added {len(all_candidates)} candidate questions")

    print(f"✓ Ingested {len(new_records)} records from {args.source}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lifehug unified source ingest")
    parser.add_argument("--source", help="Source connector name (x, email, instagram, file)")
    parser.add_argument("--list-sources", action="store_true", help="List available connectors")
    parser.add_argument("--limit", type=int, help="Max records to ingest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-candidates", action="store_true", help="Skip candidate question generation")

    # Connector-specific args (added by connectors but defined here for compatibility)
    parser.add_argument("--path", help="File path (file connector)")
    parser.add_argument("--export-path", help="Export file/directory path")
    parser.add_argument("--query", help="Search query (email connector)")
    parser.add_argument("--since", help="Date filter (YYYY-MM-DD)")
    parser.add_argument("--username", help="Username (X connector)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return cmd_ingest(args)


if __name__ == "__main__":
    raise SystemExit(main())
