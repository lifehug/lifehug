#!/usr/bin/env python3
"""Lifehug — Output Composer

Generates versioned outputs (letters, tweets, instagram posts, chapter drafts) from
accumulated answers. This script does NOT call AI. It assembles prompts the AI
processes, and saves AI-generated content with version tracking.

Flow:
  1. AI runs:  python3 system/compose.py --prompt --format letter --subject katie \\
                 --title mothers-day-2026
  2. AI feeds the prompt to a model and gets back the output
  3. AI saves it back:
       echo "$content" | python3 system/compose.py --save outputs/mothers-day-2026 \\
         --format letter --subject katie --model anthropic/claude-opus-4-6
  4. To revise:
       python3 system/compose.py --revise outputs/mothers-day-2026 \\
         --feedback 'make it more personal'
       (prints a revision prompt; AI processes; --save again)

Usage:
    python3 system/compose.py --list
    python3 system/compose.py --info outputs/mothers-day-2026
    python3 system/compose.py --prompt --format letter --subject katie --title mothers-day-2026
    python3 system/compose.py --prompt --format tweet --categories A,B --title launch-tweet
    python3 system/compose.py --save outputs/title --format letter --subject katie --model X
    python3 system/compose.py --revise outputs/title --feedback "make it warmer"
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

SYSTEM_DIR = Path(__file__).parent
REPO_DIR = SYSTEM_DIR.parent
QUESTIONS_FILE = SYSTEM_DIR / "question-bank.md"
ANSWERS_DIR = REPO_DIR / "answers"
TEMPLATES_DIR = REPO_DIR / "templates"
OUTPUTS_DIR = REPO_DIR / "outputs"
CONFIG_FILE = REPO_DIR / "config.yaml"

VALID_FORMATS = ("letter", "tweet", "instagram", "chapter")


def _display_path(p):
    """Show path relative to the repo root when possible."""
    try:
        return str(Path(p).resolve().relative_to(REPO_DIR.resolve()))
    except ValueError:
        return str(p)


def load_config():
    """Load config.yaml as a simple key:value dict (no yaml library needed)."""
    config = {}
    if not CONFIG_FILE.exists():
        return config
    for line in CONFIG_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        config[key.strip()] = val.strip().strip('"').strip("'")
    return config


def parse_spotlight_subjects(md_text):
    """Discover subject → category-letter mapping from ## Spotlight sections.

    Walks question-bank.md. Inside a `## Spotlights` section header, each
    `## L: Spotlight on Katie` (or `Spotlight — Katie`) is recorded with its
    cleaned name. Also records categories K+ as spotlight categories regardless
    of section, since the convention is K+ = spotlight.
    """
    subjects = {}  # cleaned_name (lowercase) → category letter
    cat_names = {}  # letter → cleaned name

    header_pattern = re.compile(r'^## ([A-Z]): (.+?)\s*$')
    in_spotlight_section = False

    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## spotlight"):
            in_spotlight_section = True
            continue
        if stripped.startswith("## ") and not stripped.lower().startswith("## spotlight"):
            # Hit some other section header
            m = header_pattern.match(stripped)
            if m:
                cat_id = m.group(1)
                if cat_id < "K":
                    in_spotlight_section = False

        m = header_pattern.match(stripped)
        if not m:
            continue
        cat_id = m.group(1)
        raw_name = m.group(2).strip()

        # Only treat K+ as spotlight categories (matches ask.py convention)
        if cat_id < "K":
            continue

        # Clean: drop leading "Spotlight on", "Spotlight —", "Spotlight:", "Spotlight"
        clean = raw_name
        for prefix in ("Spotlight on ", "Spotlight — ", "Spotlight - ",
                       "Spotlight: ", "Spotlight "):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        # Drop trailing parentheticals: "Mom (Desi)" → "Mom"
        clean = re.sub(r'\s*\(.*?\)\s*$', '', clean).strip()

        cat_names[cat_id] = clean
        subjects[clean.lower()] = cat_id

    return subjects, cat_names


def resolve_categories(subject, categories_arg):
    """Figure out which category letters to use.

    Returns (categories_list, resolved_subject_name).

    If --categories is given, use those directly.
    Else if --subject is given, look it up in spotlight subjects.
    """
    if categories_arg:
        cats = [c.strip().upper() for c in categories_arg.split(",") if c.strip()]
        for c in cats:
            if not re.match(r'^[A-Z]$', c):
                print(f"Error: invalid category '{c}'", file=sys.stderr)
                sys.exit(1)
        return cats, None

    if subject:
        if not QUESTIONS_FILE.exists():
            print(f"Error: {QUESTIONS_FILE} not found", file=sys.stderr)
            sys.exit(1)
        md_text = QUESTIONS_FILE.read_text()
        subjects, cat_names = parse_spotlight_subjects(md_text)

        # Try exact (case-insensitive) match first
        key = subject.lower()
        if key in subjects:
            return [subjects[key]], cat_names[subjects[key]]

        # Substring match
        matches = [(name, letter) for name, letter in subjects.items() if key in name]
        if len(matches) == 1:
            name, letter = matches[0]
            return [letter], cat_names[letter]
        if len(matches) > 1:
            options = ", ".join(f"{cat_names[l]} ({l})" for _, l in matches)
            print(f"Error: subject '{subject}' is ambiguous. Matches: {options}",
                  file=sys.stderr)
            sys.exit(1)

        print(f"Error: subject '{subject}' not found in question-bank.md spotlights.",
              file=sys.stderr)
        if subjects:
            available = ", ".join(f"{cat_names[l]} ({l})" for _, l in subjects.items())
            print(f"Available subjects: {available}", file=sys.stderr)
        else:
            print("No spotlight subjects defined yet.", file=sys.stderr)
        sys.exit(1)

    return [], None


def read_answers_for_categories(categories):
    """Read all answer files whose question ID starts with one of the given letters."""
    if not ANSWERS_DIR.exists():
        return []
    cat_set = set(categories) if categories else None

    answers = []
    for f in sorted(ANSWERS_DIR.glob("*.md")):
        if f.name == ".gitkeep":
            continue
        stem = f.stem
        m = re.match(r'^([A-Z])(\d+)', stem)
        if not m:
            continue
        cat = m.group(1)
        if cat_set is not None and cat not in cat_set:
            continue
        try:
            content = f.read_text().strip()
        except Exception:
            continue
        answers.append({"id": m.group(0), "category": cat, "file": f.name, "content": content})
    return answers


def load_template(format_name):
    """Read templates/{format}.md."""
    path = TEMPLATES_DIR / f"{format_name}.md"
    if not path.exists():
        print(f"Error: template not found: {path}", file=sys.stderr)
        print(f"Expected one of: {', '.join(VALID_FORMATS)}", file=sys.stderr)
        sys.exit(1)
    return path.read_text().strip()


def build_question_lookup():
    """Build {qid: question_text} from question-bank.md."""
    if not QUESTIONS_FILE.exists():
        return {}
    pattern = re.compile(
        r'^- \[[ x]\] ([A-Z]\d+): (.+?)(?:\s*\*\(.+\)\*)?$',
        re.MULTILINE,
    )
    lookup = {}
    for m in pattern.finditer(QUESTIONS_FILE.read_text()):
        lookup[m.group(1)] = m.group(2).strip()
    return lookup


def extract_answer_body(content):
    """Pull the answer body out of an answer file (between --- markers)."""
    body_match = re.search(r'---\n+(.*?)(?:\n+---|\Z)', content, re.DOTALL)
    if body_match:
        return body_match.group(1).strip()
    return content.strip()


def build_prompt(format_name, subject_name, categories, title, feedback=None,
                 prior_version=None):
    """Assemble the full AI prompt: template + context + answers."""
    template = load_template(format_name)
    answers = read_answers_for_categories(categories)
    q_lookup = build_question_lookup()

    config = load_config()
    author_name = config.get("name", "the author")

    lines = []
    lines.append("=" * 70)
    lines.append(f"LIFEHUG — COMPOSE: {format_name.upper()}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Author: {author_name}")
    if subject_name:
        lines.append(f"Subject: {subject_name}")
    if title:
        lines.append(f"Title: {title}")
    if categories:
        lines.append(f"Source categories: {', '.join(categories)}")
    lines.append(f"Source answers: {len(answers)}")
    lines.append("")
    lines.append("-" * 70)
    lines.append(f"FORMAT: {format_name.upper()}")
    lines.append("-" * 70)
    lines.append("")
    lines.append(template)
    lines.append("")

    if prior_version is not None:
        lines.append("-" * 70)
        lines.append("CURRENT VERSION (to revise)")
        lines.append("-" * 70)
        lines.append("")
        lines.append(prior_version.strip())
        lines.append("")
        lines.append("-" * 70)
        lines.append("FEEDBACK")
        lines.append("-" * 70)
        lines.append("")
        lines.append(feedback or "(no specific feedback — improve overall quality)")
        lines.append("")
        lines.append("Write a new version that addresses the feedback while keeping")
        lines.append("what works. Use the source material below for grounding.")
        lines.append("")

    lines.append("-" * 70)
    lines.append("SOURCE MATERIAL — answers from the author")
    lines.append("-" * 70)
    lines.append("")

    if not answers:
        lines.append("(no answers found for the requested categories)")
    else:
        for ans in answers:
            qid = ans["id"]
            q_text = q_lookup.get(qid, "(question text not found)")
            lines.append(f"### [{qid}] {q_text}")
            lines.append("")
            lines.append(extract_answer_body(ans["content"]))
            lines.append("")

    lines.append("=" * 70)
    lines.append("END OF CONTEXT")
    lines.append("=" * 70)
    lines.append("")
    if prior_version is None:
        lines.append("Output ONLY the requested piece. No explanation, no preamble,")
        lines.append("no markdown fences. Just the content.")
    else:
        lines.append("Output ONLY the revised piece. No explanation, no preamble,")
        lines.append("no markdown fences. Just the new version.")

    return "\n".join(lines)


# ---------- meta.yaml read/write ----------

def write_meta(path, meta):
    """Write meta.yaml. Simple format — no PyYAML needed."""
    lines = []
    lines.append(f"title: {meta['title']}")
    lines.append(f"format: {meta['format']}")
    if meta.get("subject"):
        lines.append(f"subject: {meta['subject']}")
    cats = meta.get("categories") or []
    lines.append(f"categories: [{', '.join(cats)}]")
    lines.append(f"created: {meta['created']}")
    lines.append("versions:")
    for v in meta.get("versions", []):
        lines.append(f"  - version: {v['version']}")
        lines.append(f"    created: {v['created']}")
        lines.append(f"    model: {v.get('model', 'unknown')}")
        if v.get("feedback"):
            fb = v["feedback"].replace("'", "''")
            lines.append(f"    feedback: '{fb}'")
    path.write_text("\n".join(lines) + "\n")


def read_meta(path):
    """Read meta.yaml back into a dict. Tolerant of the format we write."""
    if not path.exists():
        return None

    meta = {"versions": []}
    versions = []
    current = None
    in_versions = False

    for raw in path.read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw.startswith(" ") and not raw.startswith("\t"):
            key, _, val = raw.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "versions":
                in_versions = True
                continue
            in_versions = False
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                meta[key] = [x.strip() for x in inner.split(",") if x.strip()] if inner else []
            else:
                meta[key] = val.strip('"').strip("'")
            continue

        # Indented line — part of a version entry
        if not in_versions:
            continue
        stripped = raw.strip()
        if stripped.startswith("- "):
            if current is not None:
                versions.append(current)
            current = {}
            stripped = stripped[2:]
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes (handle escaped '' inside)
        if val.startswith("'") and val.endswith("'") and len(val) >= 2:
            val = val[1:-1].replace("''", "'")
        elif val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        if current is None:
            current = {}
        current[key] = val

    if current is not None:
        versions.append(current)
    meta["versions"] = versions
    return meta


# ---------- commands ----------

def cmd_prompt(args):
    """Print the full AI prompt for generating a new piece."""
    if not args.format:
        print("Error: --prompt requires --format", file=sys.stderr)
        sys.exit(1)
    if args.format not in VALID_FORMATS:
        print(f"Error: --format must be one of {', '.join(VALID_FORMATS)}", file=sys.stderr)
        sys.exit(1)

    cats, subject_name = resolve_categories(args.subject, args.categories)
    if not cats and not args.categories:
        # No subject and no explicit categories → use all categories
        # Read all answer files to figure out which cats exist
        cats = sorted({m.group(1) for f in ANSWERS_DIR.glob("*.md")
                       if (m := re.match(r'^([A-Z])', f.stem))})

    if not cats:
        print("Warning: no categories resolved. Using all answers.", file=sys.stderr)

    name = subject_name or args.subject
    prompt = build_prompt(args.format, name, cats, args.title)
    print(prompt)


def _next_version(out_dir):
    """Find the next vN.md filename."""
    if not out_dir.exists():
        return 1
    versions = []
    for f in out_dir.glob("v*.md"):
        m = re.match(r'^v(\d+)\.md$', f.name)
        if m:
            versions.append(int(m.group(1)))
    return (max(versions) + 1) if versions else 1


def cmd_save(args):
    """Read content from stdin, save as next version, update meta.yaml."""
    if not args.save:
        print("Error: --save requires a target path", file=sys.stderr)
        sys.exit(1)

    target = Path(args.save)
    # Allow either a directory (auto-version) or an explicit vN.md path.
    if target.suffix == ".md":
        out_dir = target.parent
        match = re.match(r'^v(\d+)\.md$', target.name)
        if not match:
            print(f"Error: file must be named vN.md (got {target.name})", file=sys.stderr)
            sys.exit(1)
        version = int(match.group(1))
        out_file = target
    else:
        out_dir = target
        version = _next_version(out_dir)
        out_file = out_dir / f"v{version}.md"

    out_dir.mkdir(parents=True, exist_ok=True)

    content = sys.stdin.read()
    if not content.strip():
        print("Error: no content on stdin", file=sys.stderr)
        sys.exit(1)
    out_file.write_text(content if content.endswith("\n") else content + "\n")

    # Build/update meta.yaml
    meta_path = out_dir / "meta.yaml"
    today = datetime.now().date().isoformat()
    now_iso = datetime.now().isoformat(timespec="seconds")

    cats_for_meta = []
    if args.categories:
        cats_for_meta = [c.strip().upper() for c in args.categories.split(",") if c.strip()]
    elif args.subject:
        cats, _ = resolve_categories(args.subject, None)
        cats_for_meta = cats

    if meta_path.exists():
        meta = read_meta(meta_path)
        # Append a new version entry
        version_entry = {
            "version": str(version),
            "created": now_iso,
            "model": args.model or "unknown",
        }
        if args.feedback:
            version_entry["feedback"] = args.feedback
        meta["versions"].append(version_entry)
    else:
        meta = {
            "title": out_dir.name,
            "format": args.format or "unknown",
            "subject": args.subject or "",
            "categories": cats_for_meta,
            "created": today,
            "versions": [{
                "version": str(version),
                "created": now_iso,
                "model": args.model or "unknown",
            }],
        }
        if args.feedback:
            meta["versions"][0]["feedback"] = args.feedback

    write_meta(meta_path, meta)

    print(f"✓ Saved {_display_path(out_file)} (v{version})")
    print(f"  meta: {_display_path(meta_path)}")


def cmd_revise(args):
    """Generate a revision prompt: latest version + feedback + source answers."""
    if not args.revise:
        print("Error: --revise requires an output directory", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.revise)
    if not out_dir.exists() or not out_dir.is_dir():
        print(f"Error: {out_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    meta_path = out_dir / "meta.yaml"
    meta = read_meta(meta_path)
    if not meta:
        print(f"Error: no meta.yaml found in {out_dir}", file=sys.stderr)
        sys.exit(1)

    # Latest version: find highest vN.md
    latest_version = _next_version(out_dir) - 1
    if latest_version < 1:
        print(f"Error: no versions found in {out_dir}", file=sys.stderr)
        sys.exit(1)
    latest_file = out_dir / f"v{latest_version}.md"
    if not latest_file.exists():
        print(f"Error: {latest_file} missing", file=sys.stderr)
        sys.exit(1)

    prior = latest_file.read_text()
    fmt = meta.get("format") or "letter"
    subject = meta.get("subject") or ""
    cats = meta.get("categories") or []

    prompt = build_prompt(
        format_name=fmt,
        subject_name=subject,
        categories=cats,
        title=meta.get("title", out_dir.name),
        feedback=args.feedback,
        prior_version=prior,
    )
    print(prompt)


def cmd_list(args):
    """List all outputs with their versions and metadata."""
    if not OUTPUTS_DIR.exists():
        print("(no outputs yet)")
        return

    rows = []
    for d in sorted(OUTPUTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta = read_meta(d / "meta.yaml")
        if meta:
            n_versions = len(meta.get("versions", []))
            fmt = meta.get("format", "?")
            subj = meta.get("subject", "")
            created = meta.get("created", "?")
            subj_str = f" · {subj}" if subj else ""
            rows.append(f"  {d.name:<40}  [{fmt}] v{n_versions}{subj_str}  ({created})")
        else:
            md_files = sorted(d.glob("v*.md"))
            rows.append(f"  {d.name:<40}  ({len(md_files)} files, no meta)")

    if not rows:
        print("(no outputs yet)")
        return
    print("Outputs:")
    for r in rows:
        print(r)


def cmd_info(args):
    """Show details about a specific output."""
    if not args.info:
        print("Error: --info requires an output directory", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.info)
    if not out_dir.exists():
        print(f"Error: {out_dir} not found", file=sys.stderr)
        sys.exit(1)

    meta = read_meta(out_dir / "meta.yaml")
    if not meta:
        print(f"No meta.yaml in {out_dir}.")
        for f in sorted(out_dir.glob("v*.md")):
            print(f"  {f.name}")
        return

    print(f"Title:    {meta.get('title')}")
    print(f"Format:   {meta.get('format')}")
    if meta.get("subject"):
        print(f"Subject:  {meta['subject']}")
    cats = meta.get("categories") or []
    if cats:
        print(f"Sources:  {', '.join(cats)}")
    print(f"Created:  {meta.get('created')}")
    print(f"Path:     {out_dir}")
    print()
    print("Versions:")
    for v in meta.get("versions", []):
        line = f"  v{v.get('version')}  {v.get('created', '?')}  {v.get('model', '?')}"
        if v.get("feedback"):
            line += f"  — {v['feedback']}"
        print(line)


def main():
    parser = argparse.ArgumentParser(
        description="Lifehug output composer — letters, tweets, IG, chapters",
    )
    parser.add_argument("--prompt", action="store_true",
                        help="Generate AI prompt for a new piece")
    parser.add_argument("--save", metavar="PATH",
                        help="Save stdin to outputs/title (auto-versions to vN.md)")
    parser.add_argument("--revise", metavar="DIR",
                        help="Generate revision prompt for an output directory")
    parser.add_argument("--list", action="store_true",
                        help="List all outputs")
    parser.add_argument("--info", metavar="DIR",
                        help="Show details about an output")

    parser.add_argument("--format", choices=VALID_FORMATS,
                        help="Format type")
    parser.add_argument("--subject", metavar="NAME",
                        help="Spotlight subject (matched against question-bank.md)")
    parser.add_argument("--title", metavar="SLUG",
                        help="Title slug for the output (used by --prompt)")
    parser.add_argument("--categories", metavar="A,B,C",
                        help="Explicit category letters (overrides --subject)")
    parser.add_argument("--model", metavar="MODEL",
                        help="Model used to generate (recorded in meta.yaml)")
    parser.add_argument("--feedback", metavar="TEXT",
                        help="Revision feedback (used by --revise / --save)")

    args = parser.parse_args()

    if args.prompt:
        cmd_prompt(args)
    elif args.save:
        cmd_save(args)
    elif args.revise:
        cmd_revise(args)
    elif args.list:
        cmd_list(args)
    elif args.info:
        cmd_info(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
