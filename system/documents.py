#!/usr/bin/env python3
"""``documents file``: the bulk, pinned door for family letters (v412).

``intake letter <id>`` files one letter from the archive's working tree.
``documents file`` files many — ``--all`` or ``--ids`` — reading the archive
THROUGH GIT AT ONE COMMIT (``ls-tree`` and ``cat-file --batch``), never its
working tree, so what is filed is exactly what that commit holds and the
archive is never written to. Each transcript goes through
``family_letters.file_letter``, the one writer of a letter record, so both
doors produce the same record: ``sources/letters/<collection>--<letter>.md``,
``source_id letters:<collection>--<letter>``, v404's frontmatter plus refs,
origin and the verbatim-header trailer.

* Re-running on the same commit writes nothing (the current record's
  ``origin.transcript_blob`` is the transcript's blob).
* A transcript whose blob changed files a NEW record that ``supersedes`` the
  current one; the old record stays.
* ``--map ID=REF`` says which people.yaml id is which vault person (``self``
  for the owner); the map, ``--scan-url-template`` and ``--repo-name`` are
  remembered in ``state/documents/letters.json`` once a real filing used them.
* ``--dry-run`` reports what would be written and writes nothing.
* Every record written is registered in the manifest in ONE sync.

Loop status: Loop-adjacent. Nothing on the daily/weekly/monthly rhythm runs
it; a filed letter enters the Loop the way any source does (the next classify
run reads it; v404's letter moment, ``document`` basis).

CLI::

    python3 system/lifehug.py documents file <archive> (--all | --ids ID …) --commit <sha>
        [--map ID=REF …] [--scan-url-template T] [--repo-name OWNER/NAME] [--dry-run] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import family_letters as fl
import letter_people as lp

_TRANSCRIPT_PATH_RE = re.compile(
    r"^letters/([a-z0-9][a-z0-9._-]*)/([a-z0-9][a-z0-9._-]*)/transcript\.md$")


class DocumentsError(RuntimeError):
    """A filing that must not proceed (bad repo, commit, map or people.yaml)."""


# ── the archive, read through git at one commit ───────────────────────────


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], input=stdin,
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise DocumentsError(f"git {' '.join(args[:2])} failed in {repo}: "
                             + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def resolve_commit(repo: Path, commit: str) -> str:
    if not commit or commit.startswith("-"):
        raise DocumentsError("--commit must name a commit")
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}").decode().strip()


def _batch_objects(repo: Path, specs: list[str]) -> dict[str, tuple[str, bytes] | None]:
    """``git cat-file --batch`` over ``<commit>:<path>`` specs."""
    if not specs:
        return {}
    for spec in specs:
        if "\n" in spec:
            raise DocumentsError(f"path with a newline: {spec!r}")
    out = _git(repo, "cat-file", "--batch", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    found: dict[str, tuple[str, bytes] | None] = {}
    pos = 0
    for spec in specs:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            found[spec] = None
            continue
        oid, _kind, size = header.split(" ")
        found[spec] = (oid, out[pos:pos + int(size)])
        pos += int(size) + 1
    return found


def _batch_oids(repo: Path, specs: list[str]) -> dict[str, str | None]:
    if not specs:
        return {}
    out = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
               stdin=("\n".join(specs) + "\n").encode("utf-8")).decode("utf-8", "replace")
    result: dict[str, str | None] = {}
    for spec, line in zip(specs, out.splitlines()):
        parts = line.split(" ")
        result[spec] = parts[0] if len(parts) == 2 and parts[1] == "blob" else None
    return result


@dataclass
class Read:
    commit: str
    transcripts: int
    letters: list[dict]
    people_text: str | None
    selected: int = 0
    errors: list[str] = field(default_factory=list)


def read_at_commit(repo: Path, commit: str, ids: list[str] | None = None) -> Read:
    """Every selected transcript at ``commit`` as the letter dict
    ``family_letters.file_letter`` takes, plus people.yaml's text."""
    repo = Path(repo).expanduser()
    if not repo.is_dir():
        raise DocumentsError(f"{repo} is not a directory")
    full = resolve_commit(repo, commit)
    listing = _git(repo, "ls-tree", "-r", "-z", "--name-only", full, "--", "letters/")
    paths = sorted(p for p in listing.decode("utf-8").split("\0") if _TRANSCRIPT_PATH_RE.match(p))
    read = Read(commit=full, transcripts=len(paths), letters=[], people_text=None)
    if ids is not None:
        wanted = [fl.normalize_id(i) for i in ids]
        have = {p[len("letters/"):-len("/transcript.md")]: p for p in paths}
        paths = [have[i] for i in dict.fromkeys(wanted) if i in have]
        read.errors += [f"{i}: no transcript at {full[:12]}" for i in dict.fromkeys(wanted)
                        if i not in have]
    read.selected = len(paths)
    people_spec = f"{full}:{lp.PEOPLE_FILE}"
    objects = _batch_objects(repo, [people_spec, *(f"{full}:{p}" for p in paths)])
    if objects.get(people_spec) is not None:
        read.people_text = objects[people_spec][1].decode("utf-8", "replace")
    parsed: list[tuple[str, str, bytes, dict, str]] = []
    for path in paths:
        letter_id = path[len("letters/"):-len("/transcript.md")]
        oid, data = objects[f"{full}:{path}"]  # type: ignore[misc]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            read.errors.append(f"{letter_id}: not UTF-8 ({exc})")
            continue
        header, body = fl.parse_header(text)
        if header.get("id") not in (None, letter_id):
            read.errors.append(f"{letter_id}: header id {header.get('id')!r} does not match its path")
            continue
        parsed.append((letter_id, oid, data, header, body))
    scan_specs = [f"{full}:{spec}" for _id, _oid, _data, header, _body in parsed
                  for spec in fl.scan_candidates(str(header.get("source_file") or ""))]
    scan_oids = _batch_oids(repo, scan_specs)
    for letter_id, oid, data, header, body in parsed:
        scan_blob = next((scan_oids.get(f"{full}:{spec}") for spec in
                          fl.scan_candidates(str(header.get("source_file") or ""))
                          if scan_oids.get(f"{full}:{spec}")), None)
        read.letters.append({"id": letter_id, "header": header, "body": body, "path": None,
                             "raw": data.decode("utf-8"), "transcript_blob": oid,
                             "commit": full, "scan_blob": scan_blob})
    return read


# ── the filing ─────────────────────────────────────────────────────────────


@dataclass
class Report:
    commit: str
    repo: str
    transcripts: int = 0
    selected: int = 0
    new: list[str] = field(default_factory=list)
    superseding: list[str] = field(default_factory=list)
    unchanged: int = 0
    refs_drifted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    authority: dict[str, int] = field(default_factory=dict)
    unmapped_people: dict[str, int] = field(default_factory=dict)
    written: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "commit": self.commit, "repo": self.repo, "transcripts": self.transcripts,
            "selected": self.selected, "written": len(self.new) + len(self.superseding),
            "new": len(self.new), "superseding": len(self.superseding),
            "unchanged": self.unchanged, "refs_drifted": len(self.refs_drifted),
            "errors": self.errors, "authority": self.authority, "paths": self.written,
        }


def file_documents(repo: Path, commit: str, *, ids: list[str] | None = None,
                   people_map: dict[str, str] | None = None,
                   scan_url_template: str | None = None, repo_name: str | None = None,
                   dry_run: bool = False, now: str | None = None) -> Report:
    from source_integrity import source_record, sync_manifest  # noqa: PLC0415

    read = read_at_commit(repo, commit, ids)
    try:
        people = lp.People.from_text(read.people_text)
    except lp.PeopleError as exc:
        raise DocumentsError(str(exc)) from exc
    context = fl.filing_context(people=people, people_map=people_map,
                                scan_url_template=scan_url_template, repo=repo_name)
    report = Report(commit=read.commit, repo=context["repo"], transcripts=read.transcripts,
                    selected=read.selected,
                    errors=list(read.errors))
    index = fl.letter_index()
    for letter in read.letters:
        outcome = fl.file_letter(letter["id"], letter=letter, context=context, index=index,
                                 register=False, dry_run=dry_run, now=now)
        status = outcome["status"]
        if status == "already":
            report.unchanged += 1
            if outcome.get("refs_drifted"):
                report.refs_drifted.append(letter["id"])
            continue
        if status not in ("filed", "would_file"):
            report.errors.append(f"{letter['id']}: {outcome.get('detail')}")
            continue
        (report.superseding if outcome.get("supersedes") else report.new).append(letter["id"])
        report.authority[outcome["authority"]] = report.authority.get(outcome["authority"], 0) + 1
        for pid in outcome.get("unmapped") or []:
            report.unmapped_people[pid] = report.unmapped_people.get(pid, 0) + 1
        if status == "filed":
            report.written.append(outcome["path"])
    if report.written:
        from lifehug_core import REPO_DIR  # noqa: PLC0415

        sync_manifest([source_record(REPO_DIR / rel) for rel in report.written], write=True)
    return report


# ── CLI ────────────────────────────────────────────────────────────────────


def print_report(report: Report, *, dry_run: bool) -> None:
    verb = "would write" if dry_run else "wrote"
    print(f"letters: {report.repo} @ {report.commit[:12]}")
    print(f"  transcripts at commit: {report.transcripts}; selected: {report.selected}")
    print(f"  {verb}: {len(report.new) + len(report.superseding)} "
          f"({len(report.new)} new, {len(report.superseding)} superseding)")
    print(f"  unchanged: {report.unchanged}")
    if report.authority:
        print("  authority: " + ", ".join(f"{k} {v}" for k, v in sorted(report.authority.items())))
    if report.refs_drifted:
        print(f"  refs drifted (filed records keep their refs; immutable): {len(report.refs_drifted)}")
    if report.unmapped_people:
        top = sorted(report.unmapped_people.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        print("  writers/recipients filed as person/<people.yaml id> (no --map): "
              + ", ".join(f"{pid} ×{n}" for pid, n in top)
              + (" …" if len(report.unmapped_people) > 8 else ""))
    for error in report.errors:
        print(f"  ✗ {error}")
    if not dry_run and report.written:
        print("  commit: git add sources/letters state/documents state/source_manifest.json "
              f"&& git commit -m 'File letters @ {report.commit[:12]}'")


def cmd_file(args: argparse.Namespace) -> int:
    if not args.all and not args.ids:
        print("documents file: pass --all or --ids ID [ID ...]", file=sys.stderr)
        return 2
    try:
        people_map = lp.parse_map_args(args.map)
        report = file_documents(
            Path(args.repo), args.commit, ids=None if args.all else list(args.ids),
            people_map=people_map, scan_url_template=args.scan_url_template,
            repo_name=args.repo_name, dry_run=args.dry_run)
        if not args.dry_run and (report.written or people_map or args.scan_url_template
                                 or args.repo_name):
            lp.save_config(people_map=people_map, scan_url_template=args.scan_url_template,
                           repo=args.repo_name)
    except (DocumentsError, lp.PeopleError) as exc:
        print(f"documents file: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print_report(report, dry_run=args.dry_run)
    return 1 if report.errors else 0


def add_file_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("repo", help="The family-letters archive (read through git; never written)")
    pick = p.add_mutually_exclusive_group()
    pick.add_argument("--all", action="store_true", help="Every transcript at the commit")
    pick.add_argument("--ids", nargs="+", metavar="ID", help="Letter ids (<collection>/<letter>)")
    p.add_argument("--commit", required=True, help="Commit of the archive to file from")
    p.add_argument("--map", action="append", metavar="ID=REF",
                   help="Map a people.yaml id to a vault ref (self, person/<slug>); repeatable; remembered")
    p.add_argument("--scan-url-template", default=None,
                   help="Scan URL with {id}/{collection}/{slug}; remembered")
    p.add_argument("--repo-name", default=None,
                   help=f"origin.repo (default: remembered, else {fl.ORIGIN_REPO}); remembered")
    p.add_argument("--dry-run", action="store_true", help="Report what would be filed; write nothing")
    p.add_argument("--json", action="store_true", help="Machine-readable counts")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("file", help="File letters from an archive at a pinned commit")
    add_file_arguments(p)
    p.set_defaults(func=cmd_file)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
