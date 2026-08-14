#!/usr/bin/env python3
"""Lifehug — Question-Judgment interaction loader.

The single authoritative definition (recurring-defect doctrine,
``docs/BUILDING.md`` §8) for assembling the judgment context every
question-generation path sends to a model:
``interactions/question_judgment/prompt/behavior.md`` (the rubric — never
truncated) plus this vault's ``state/question_judgment/learned.md`` (vault
data, empty when absent).

``system/classify_story.py``'s ``build_prompt`` and
``system/research_expand.py``'s expansion prompt path both call
``load_judgment_rubric()`` instead of hand-reading ``system/research.md``
and slicing it — the ``research[:3000]`` / ``research_notes[:800]``
truncations that used to sit between those two generation paths and the
craft doctrine are gone (``docs/pr-specs/question-judgment-interaction.md``).

Public API:

    load_judgment_rubric(*, vault_root=None, framework_root=None) -> str
    read_judgment_definition(*parts, framework_root=None) -> str

Graceful degradation: when ``interactions/question_judgment/`` itself is
absent, or its ``prompt/behavior.md`` can't be read (a vault running
against a framework snapshot that predates this interaction — see the
contract's binding facts), the loader falls back to the PRE-MIGRATION
behavior: read ``system/research.md`` and truncate to 3000 characters,
exactly as the old ``classify_story.build_prompt`` did. This is an
intentional, temporary compatibility shim for a vault mid-upgrade, not a
re-introduction of the truncation bug — a vault on-version (the normal
case, since this interaction ships in ``system/version.json``'s
``framework_files``) never takes this path.

Every vault read goes through ``vault_paths`` (never a hand-built path);
every framework read goes through ``lifehug_core.INTERACTIONS_DIR`` /
an explicit ``framework_root`` override, the same convention
``system/conversation.py``'s ``_conversation_dir_path`` uses.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lifehug_core import INTERACTIONS_DIR, REPO_DIR, SYSTEM_DIR
from vault_paths import read_vault_text, vault_data_path

INTERACTION_NAME = "question_judgment"

# Pre-migration fallback constant, preserved verbatim from the old
# classify_story.build_prompt truncation so a mid-upgrade vault's behavior
# doesn't silently change out from under it. See module docstring.
LEGACY_RESEARCH_CHAR_LIMIT = 3000


def _definition_dir(*, framework_root: str | Path | None = None) -> Path:
    if framework_root is not None:
        return Path(framework_root) / "interactions" / INTERACTION_NAME
    return INTERACTIONS_DIR / INTERACTION_NAME


def read_judgment_definition(*parts: str, framework_root: str | Path | None = None) -> str:
    """Read one ``interactions/question_judgment/`` definition file verbatim.

    Raises OSError when the file is absent — the definition tree is a
    framework file, not optional vault state.
    """
    return _definition_dir(framework_root=framework_root).joinpath(*parts).read_text(encoding="utf-8")


def _legacy_research_path(*, framework_root: str | Path | None = None) -> Path:
    if framework_root is not None:
        return Path(framework_root) / "system" / "research.md"
    return SYSTEM_DIR / "research.md"


def _legacy_fallback(*, framework_root: str | Path | None = None) -> str:
    """Pre-migration behavior: system/research.md truncated to 3000 chars.

    Only reachable when interactions/question_judgment/'s behavior.md
    can't be read (a vault mid-upgrade). See module docstring.
    """
    path = _legacy_research_path(framework_root=framework_root)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:LEGACY_RESEARCH_CHAR_LIMIT]


def _load_learned(*, vault_root: str | Path | None = None, framework_root: str | Path | None = None) -> str:
    root = REPO_DIR if vault_root is None else Path(vault_root)
    framework_system_dir = Path(framework_root) / "system" if framework_root is not None else SYSTEM_DIR
    try:
        path = vault_data_path(
            "question_judgment_learned",
            vault_root=root,
            framework_system_dir=framework_system_dir,
        )
    except KeyError:
        # The data path isn't registered (e.g. an old vault_contract.json
        # snapshot mid-upgrade) — treat exactly like a missing file.
        return ""
    try:
        return read_vault_text(path, vault_root=root)
    except FileNotFoundError:
        return ""


def load_judgment_rubric(*, vault_root: str | Path | None = None, framework_root: str | Path | None = None) -> str:
    """Assemble the judgment context every generation path sends a model.

    ``prompt/behavior.md`` (never truncated) plus
    ``state/question_judgment/learned.md`` (empty when absent, appended
    under its own heading when present). Falls back to the pre-migration
    truncated ``research.md`` injection only when the interaction
    definition itself can't be read — see the module docstring.
    """
    try:
        behavior = read_judgment_definition("prompt", "behavior.md", framework_root=framework_root)
    except OSError:
        return _legacy_fallback(framework_root=framework_root)

    parts = [behavior.strip()]
    learned = _load_learned(vault_root=vault_root, framework_root=framework_root).strip()
    if learned:
        parts.append("## Learned amendments\n\n" + learned)
    return "\n\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the assembled question-judgment context.")
    parser.parse_args()
    print(load_judgment_rubric())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
