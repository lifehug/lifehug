#!/usr/bin/env python3
"""The Mirror — synthesized introspection surface (v100).

The weekly classifier extracts contradictions and self-understanding insights
(including ``position:`` stated positions) from every source, but until now
they had no surface. The Mirror distills them into ``wiki/self/mirror.md`` —
a dated weekly *edition* the author reads, never a live profile:

  ## Tensions I keep circling        (MI-style discrepancy, "and" never "but")
  ## What I seem to know about myself
  ## Stated positions
  ## Sit with                        (exactly 3 short open questions)

Voice contract: every claim quotes or cites the author's own words
("you've said", never "you are"); a sentence that can't cite a source
shouldn't render. The raw entries stay browsable in the viewer's Mirror view
beneath the synthesis.

Keyless path mirrors classify_story: ``--emit-task DIR`` writes the prompt +
manifest for agent completion via ``--from-response PATH``.

Mirror has a second half as of v224. The page above is what the classifier
*noticed*; ``mirror_work`` is what the temporal substrate cannot settle on its
own — contradictions and unplaced identities, each an actionable row with
**Play now** (the audited timeline plan §2.5, §8.2). The two halves are
deliberately separate: the synthesis is a weekly reading with a model in it,
the rows are derived from claims with no model anywhere, and neither one may
quietly become the other. The bound entry points are at the bottom of this
file; the read model, the Play target and the resolution write live in
``system/mirror_work.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mirror_work
from lifehug_core import (
    CLASSIFICATIONS_DIR,
    MIRROR_RESPONSES_FILE,
    REPO_DIR,
    WIKI_DIR,
    load_config,
    now_utc,
    read_json,
    write_json,
    write_text,
)
from mirror_work import MIRROR_ROW_CAP, MirrorResolution, MirrorWorkRow

MIRROR_PAGE_REL = Path("self") / "mirror.md"

REQUIRED_SECTIONS = [
    "## Tensions I keep circling",
    "## What I seem to know about myself",
    "## Stated positions",
    "## Sit with",
]

# Defensive input cap per kind — the prompt stays bounded as the archive grows.
MAX_ENTRIES_PER_KIND = 300


def mirror_page_path() -> Path:
    return WIKI_DIR / MIRROR_PAGE_REL


def load_mirror_entries() -> list[dict]:
    """Every classifier-extracted contradiction / insight / position, PLUS the
    author's own conversation responses to a tension (issue #119 — the
    Mirror's first inbound path), newest first:
    {kind, text, source, source_short, classified_at}. ``position`` = an
    insight the classifier prefixed ``position:`` (the author's stated
    stance, v96 opinion lane). ``response`` = a "Sit with" reply the author
    gave in conversation (``state/mirror_responses.json``, the ONE writer is
    ``append_mirror_responses`` below)."""
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, text: str, *, source: str, source_short: str, classified_at: str) -> None:
        text = text.strip()
        if not text or (kind, text.lower()) in seen:
            return
        seen.add((kind, text.lower()))
        entries.append({
            "kind": kind,
            "text": text,
            "source": source,
            "source_short": source_short,
            "classified_at": classified_at,
        })

    # v237: stale classifications are withheld from the Mirror the moment a
    # correction is filed — `classify_story.current_classification_files` is
    # the one gate.
    import classify_story  # noqa: PLC0415

    for path, data in classify_story.current_classification_files(CLASSIFICATIONS_DIR):
        source = str(data.get("source_path", path.stem))
        classified_at = str(data.get("classified_at", ""))
        source_short = Path(source).stem

        for c in data.get("contradictions") or []:
            if isinstance(c, str):
                add("contradiction", c, source=source, source_short=source_short,
                    classified_at=classified_at)
        for i in data.get("self_understanding_insights") or []:
            if isinstance(i, str):
                kind = "position" if i.strip().lower().startswith("position:") else "insight"
                add(kind, i, source=source, source_short=source_short,
                    classified_at=classified_at)

    responses = read_json(MIRROR_RESPONSES_FILE, default={}) or {}
    for item in responses.get("responses") or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        session_id = str(item.get("session_id", ""))
        add(
            "response",
            text,
            source=f"conversation:{session_id}",
            source_short=session_id,
            classified_at=str(item.get("responded_at", "")),
        )

    entries.sort(key=lambda e: e["classified_at"], reverse=True)
    return entries


def append_mirror_responses(responses: list[dict]) -> int:
    """Append author responses to ``state/mirror_responses.json``.

    THE ONE writer of this file (issue #119, restated by the contract's
    consistency-audit amendment — a duplicate write path named elsewhere was
    dropped). Idempotent on ``(session_id, text)``: a re-run of the same
    conversation-close never duplicates. Author's words stored verbatim —
    never rewritten (voice contract).
    """
    if not responses:
        return 0
    data = read_json(MIRROR_RESPONSES_FILE, default=None)
    if not isinstance(data, dict) or not isinstance(data.get("responses"), list):
        data = {"version": 1, "responses": []}
    existing = {
        (str(r.get("session_id", "")), str(r.get("text", "")).strip())
        for r in data["responses"] if isinstance(r, dict)
    }
    added = 0
    for item in responses:
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not session_id or not text:
            continue
        key = (session_id, text)
        if key in existing:
            continue
        existing.add(key)
        data["responses"].append({
            "session_id": session_id,
            "responded_at": str(item.get("responded_at") or now_utc()),
            "tension_ref": str(item.get("tension_ref") or "").strip(),
            "text": text,
            "source": "conversation",
        })
        added += 1
    if added:
        data["version"] = 1
        write_json(MIRROR_RESPONSES_FILE, data)
    return added


def _capped(entries: list[dict], kind: str) -> list[dict]:
    return [e for e in entries if e["kind"] == kind][:MAX_ENTRIES_PER_KIND]


def build_mirror_prompt(entries: list[dict] | None = None) -> str:
    """The synthesis prompt. The AI writes the page BODY (markdown, no
    frontmatter) under a fixed section contract."""
    if entries is None:
        entries = load_mirror_entries()
    cfg = load_config()
    name = cfg.get("name") or "the author"

    def block(kind: str, label: str) -> str:
        rows = _capped(entries, kind)
        if not rows:
            return f"### {label}\n(none yet)\n"
        lines = [f"### {label} ({len(rows)})"]
        lines.extend(f"- {e['text']}  [source: {e['source_short']}]" for e in rows)
        return "\n".join(lines) + "\n"

    return f"""You are the Mirror inside Lifehug, a private life-story system. Below are
introspective signals a classifier extracted from {name}'s own answers and
stories: contradictions in how they narrate themselves, self-understanding
insights, and stated positions. Distill them into this week's Mirror page —
a synthesis {name} will read about themselves.

VOICE CONTRACT (hard rules):
- Second person, warm, curious — a thoughtful friend, not an oracle.
- "You've said…" / "you've written…", NEVER "you are…". No trait verdicts.
- Every claim cites its evidence inline as (source: A10) or (sources: A10,
  L3) using the source ids shown in brackets below. A sentence you cannot
  source, you do not write.
- Present tensions as two things that COEXIST, joined by "and" — never
  "but/however", never "inconsistent", no judgment. The author resolves them,
  not you. Rejecting the framing is a legitimate outcome.
- Never invent, embellish, or infer beyond the material. Quote the author's
  own phrasings where they're vivid.
- Calm over complete: pick what matters most, don't inventory everything.
- Author responses show them ENGAGING a tension in conversation — reflect
  the development in this week's edition. Never declare the tension
  resolved: the author resolves tensions, not you.

OUTPUT: markdown BODY only (no frontmatter, no top-level # title), with
EXACTLY these four sections in this order:

## Tensions I keep circling
3-6 tensions, each 2-3 sentences: the two coexisting truths with citations,
then one open question. At most one per theme.

## What I seem to know about myself
4-8 short paragraphs or bullets distilling the strongest recurring
self-knowledge, grouped by theme, each cited.

## Stated positions
The author's explicitly stated stances (the "position:" entries), each as one
bullet in the author's own spirit, cited. If there are none, write one line
saying no positions have been stated yet.

## Sit with
EXACTLY 3 items. Each is one short line: a single tension, insight, or
position worth carrying this week, ending in an open question. These feed the
home page's "worth sitting with" card.

THE SIGNALS:

{block("contradiction", "Contradictions")}
{block("insight", "Self-understanding insights")}
{block("position", "Stated positions")}
{block("response", "Author responses to tensions")}
"""


def validate_mirror_body(body: str) -> list[str]:
    """Section-contract check for a synthesized body. Returns error strings."""
    errors = []
    for section in REQUIRED_SECTIONS:
        if section not in body:
            errors.append(f"missing section: {section}")
    if body.lstrip().startswith("---"):
        errors.append("body must not carry frontmatter (the compiler adds it)")
    if "## Sit with" in body:
        tail = body.split("## Sit with", 1)[1]
        tail = tail.split("\n## ", 1)[0]
        bullets = [ln for ln in tail.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]
        if not bullets:
            errors.append("Sit with section has no items")
        elif len(bullets) > 3:
            errors.append(f"Sit with has {len(bullets)} items (max 3)")
    return errors


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def compose_page(body: str, entries: list[dict]) -> str:
    counts = {k: sum(1 for e in entries if e["kind"] == k)
              for k in ("contradiction", "insight", "position")}
    fm = "\n".join([
        "---",
        'title: "Mirror"',
        "type: self",
        "visibility: owner_only",
        "sensitivity: private",
        "synthesized: true",
        f'generated_at: "{now_utc()}"',
        f"contradictions: {counts['contradiction']}",
        f"insights: {counts['insight']}",
        f"positions: {counts['position']}",
        "---",
        "",
        "# Mirror",
        "",
    ])
    return fm + body.strip() + "\n"


def write_mirror_page(body: str, dry_run: bool = False) -> Path:
    entries = load_mirror_entries()
    page = compose_page(body, entries)
    path = mirror_page_path()
    if dry_run:
        print(f"would write {path}")
        return path
    write_text(path, page)
    print(f"✓ Mirror written: {path}")
    return path


def _page_generated_at() -> str:
    page = mirror_page_path()
    if not page.exists():
        return ""
    head = page.read_text(encoding="utf-8", errors="replace")[:600]
    import re  # noqa: PLC0415
    m = re.search(r'^generated_at:\s*"?([0-9T:Z.+-]+)"?', head, re.MULTILINE)
    return m.group(1) if m else ""


FRESH_DAYS = 6  # an edition younger than this is "this week's" — don't re-emit


def emit_task(out_dir: Path) -> int:
    """Keyless path: write the synthesis prompt + a manifest for the agent.
    No-ops when this week's edition already exists (the maintenance skill
    pre-completes the synthesis BEFORE the weekly script runs)."""
    generated = _page_generated_at()
    if generated:
        import datetime as _dt  # noqa: PLC0415
        try:
            when = _dt.datetime.fromisoformat(generated.replace("Z", "+00:00"))
            age = _dt.datetime.now(_dt.timezone.utc) - when
            if age.days < FRESH_DAYS:
                print(f"Mirror already fresh (generated {generated}) — nothing to emit.")
                return 0
        except ValueError:
            pass
    entries = load_mirror_entries()
    if not entries:
        print("No mirror material yet — nothing to emit.")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = out_dir / "mirror.prompt.md"
    write_text(prompt_file, build_mirror_prompt(entries))
    manifest = out_dir / "manifest.json"
    write_json(manifest, {
        "task": "mirror",
        "emitted_at": now_utc(),
        "ingest_command": "python3 system/mirror.py --from-response <response>",
        "items": [{
            "prompt": prompt_file.name,
            "response": "mirror.response.md",
        }],
    })
    print(f"✓ Emitted mirror synthesis task to {out_dir}")
    print(f"  Manifest: {manifest}")
    print("  Write the markdown body to mirror.response.md, then run the ingest_command.")
    return 0


def from_response(path: Path, dry_run: bool = False) -> int:
    body = _strip_fences(path.read_text(encoding="utf-8"))
    errors = validate_mirror_body(body)
    if errors:
        for e in errors:
            print(f"✗ {e}", file=sys.stderr)
        return 1
    write_mirror_page(body, dry_run=dry_run)
    return 0


def compile_mirror(model: str | None = None, dry_run: bool = False) -> int:
    """Keyed path: synthesize via call_ai and write the page."""
    entries = load_mirror_entries()
    if not entries:
        print("No mirror material yet — the classifier hasn't extracted "
              "contradictions or insights. Nothing to synthesize.")
        return 0
    from ai_provider import call_ai  # noqa: PLC0415
    from research_expand import DEFAULT_MODEL  # noqa: PLC0415
    cfg = load_config()
    model = model or cfg.get("mirror_model") or cfg.get("research_model") or DEFAULT_MODEL
    print(f"Synthesizing the Mirror from {len(entries)} signal(s) with {model}…")
    raw = call_ai(build_mirror_prompt(entries), model)
    body = _strip_fences(raw)
    errors = validate_mirror_body(body)
    if errors:
        for e in errors:
            print(f"✗ {e}", file=sys.stderr)
        print("✗ Synthesis violated the section contract; page not written.",
              file=sys.stderr)
        return 1
    write_mirror_page(body, dry_run=dry_run)
    return 0


# --------------------------------------------------------------------------
# The actionable half — contradictions and identities, bound to this vault
# --------------------------------------------------------------------------
#
# `mirror_work` is told which vault on every call, because the temporal store
# is (the platform runs many vaults in one process and the OSS package runs
# one). The three functions below are the local binding for the single vault
# this process resolved at import, and they are the whole of Mirror's
# actionable surface as far as the CLI, the viewer and the skills are
# concerned.
#
# Nothing here touches the synthesis above. The page's frontmatter counts the
# classifier's signals and only those: an actionable row is a thing to answer,
# not a number to display somewhere else, and §2.5's "quiet" is a promise that
# Mirror never nags from another surface.


def load_actionable_rows(
    *, cap: int = MIRROR_ROW_CAP, include_resolved: bool = False
) -> list[MirrorWorkRow]:
    """The contradiction and identity rows for THIS vault, hardest first.

    Each row carries its own Play target. Open/resolved is derived from the
    current active claims on every read — see ``mirror_work.derive_row_state``
    — so there is no row state to keep, migrate or repair.
    """
    return mirror_work.load_mirror_rows(
        REPO_DIR, cap=cap, include_resolved=include_resolved
    )


def resolve_actionable_item(item: object, resolution_text: str, **kwargs: object
                            ) -> MirrorResolution:
    """File a Play conversation's resolution against THIS vault.

    A thin binding over ``mirror_work.resolve_mirror_item``: the person's words
    become a durable source, replacements arrive as new claims through a new
    receipt, and the losing claims are retired by a correction. An empty answer
    writes nothing — see :func:`abandon_actionable_item`, whose underlying
    function cannot write at all.
    """
    return mirror_work.resolve_mirror_item(
        REPO_DIR, item=item, resolution_text=resolution_text, **kwargs  # type: ignore[arg-type]
    )


def abandon_actionable_item(item: object, reason: str = "") -> MirrorResolution:
    """The Play conversation ended without settling anything — write nothing.

    Bound here for symmetry only: ``mirror_work.abandon_mirror_item`` takes no
    vault root at all, which is what makes "no correction is invented" a
    property of the code rather than a promise in a docstring.
    """
    return mirror_work.abandon_mirror_item(item, reason=reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile the Mirror page")
    parser.add_argument("--model", help="AI model override")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--emit-task", metavar="DIR",
                        help="Keyless: write the prompt + manifest for agent completion")
    parser.add_argument("--from-response", metavar="PATH",
                        help="Ingest an agent-written markdown body and write the page")
    parser.add_argument("--print-prompt", action="store_true",
                        help="Print the synthesis prompt and exit")
    args = parser.parse_args(argv)

    if args.print_prompt:
        print(build_mirror_prompt())
        return 0
    if args.emit_task:
        return emit_task(Path(args.emit_task))
    if args.from_response:
        return from_response(Path(args.from_response), dry_run=args.dry_run)
    return compile_mirror(model=args.model, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
