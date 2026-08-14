"""issue/PR question-judgment-interaction — interactions/question_judgment/.

The AI's judgment calls on question quality/priority become one reviewable,
versioned Interaction (interactions/README.md pattern) instead of scattered,
truncated prompt fragments. Covers: the single authoritative loader
(system/question_judgment.py's load_judgment_rubric — behavior + learned
assembly, graceful legacy fallback), the two truncation-bug regressions
(system/classify_story.py's old research[:3000] and
system/research_expand.py's old research_notes[:800]), the shipped
definition's YAML/structural shape, and the vault-contract/framework-manifest
registrations.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import question_judgment  # noqa: E402
import vault_paths  # noqa: E402
from lifehug_core import _parse_simple_yaml  # noqa: E402

INTERACTION_DIR = ROOT / "interactions" / "question_judgment"


def load(name: str):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — mirrors tests/test_v70_v71_craft.py's helper so
    classify_story/research_expand stay isolated from other test files'
    module state."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


# A handful of strings that only appear this far into the shipped rubric —
# used across several tests to prove nothing got truncated.
LAST_HARD_RULE_NEEDLE = "One question at a time. Never leading. How/What openers"
PENALTY_TABLE_LAST_ROW_NEEDLE = "duplicate_of_<id>"
CRITICAL_GAP_BAND_NEEDLE = "0.85–0.95 — critical gap"
CONVERGENCE_NEEDLE = "Convergence Principle"


class LoaderAssemblyTests(unittest.TestCase):
    """load_judgment_rubric(): behavior + learned assembly, graceful misses."""

    def _behavior_text(self) -> str:
        return (INTERACTION_DIR / "prompt" / "behavior.md").read_text(encoding="utf-8").strip()

    def test_assembles_behavior_and_learned_when_both_present(self):
        tmp = root_parent_tmp(self, ROOT)
        vault = tmp / "vault"
        (vault / "state" / "question_judgment").mkdir(parents=True)
        (vault / "state" / "question_judgment" / "learned.md").write_text(
            "Era-anchor candidates are exempt from the broad-generality reading.",
            encoding="utf-8",
        )
        result = question_judgment.load_judgment_rubric(vault_root=vault)

        self.assertIn(LAST_HARD_RULE_NEEDLE, result)
        self.assertIn("## Learned amendments", result)
        self.assertIn("Era-anchor candidates are exempt", result)
        # behavior comes before learned (load order: behavior, then learned)
        self.assertLess(result.index(LAST_HARD_RULE_NEEDLE), result.index("## Learned amendments"))

    def test_missing_learned_file_yields_behavior_only(self):
        tmp = root_parent_tmp(self, ROOT)
        vault = tmp / "vault"
        vault.mkdir(parents=True)
        result = question_judgment.load_judgment_rubric(vault_root=vault)

        self.assertIn(LAST_HARD_RULE_NEEDLE, result)
        self.assertNotIn("## Learned amendments", result)
        self.assertEqual(result, self._behavior_text())

    def test_missing_interaction_dir_falls_back_to_legacy_truncated_research(self):
        tmp = root_parent_tmp(self, ROOT)
        framework_root = tmp / "framework"
        (framework_root / "system").mkdir(parents=True)
        long_research = "RESEARCH " * 1000  # far over the 3000-char legacy limit
        (framework_root / "system" / "research.md").write_text(long_research, encoding="utf-8")
        # interactions/question_judgment/ deliberately absent.
        vault = tmp / "vault"
        vault.mkdir(parents=True)

        result = question_judgment.load_judgment_rubric(vault_root=vault, framework_root=framework_root)

        self.assertEqual(result, long_research[:3000])
        self.assertEqual(len(result), 3000)

    def test_missing_interaction_dir_and_missing_research_yields_empty(self):
        tmp = root_parent_tmp(self, ROOT)
        framework_root = tmp / "framework"
        (framework_root / "system").mkdir(parents=True)
        vault = tmp / "vault"
        vault.mkdir(parents=True)

        result = question_judgment.load_judgment_rubric(vault_root=vault, framework_root=framework_root)

        self.assertEqual(result, "")

    def test_shipped_definition_loads_against_the_real_repo_root(self):
        # No overrides — exercises the actual shipped interactions/question_judgment/
        # tree and the real REPO_DIR-bound vault (learned.md legitimately absent
        # here; this repo's own vault has never had a weekly rubric-edit run).
        result = question_judgment.load_judgment_rubric()
        self.assertIn(LAST_HARD_RULE_NEEDLE, result)
        self.assertIn(PENALTY_TABLE_LAST_ROW_NEEDLE, result)
        self.assertIn(CONVERGENCE_NEEDLE, result)


class ClassifierTruncationRegressionTests(unittest.TestCase):
    """Regression: system/classify_story.py's old research[:3000] truncation
    used to cut system/research.md off mid-way through §1's craft essentials.
    The classifier prompt must now carry the full, untruncated rubric."""

    def setUp(self):
        self.cls = load("classify_story")

    def test_prompt_contains_the_full_rubric_untruncated(self):
        tmp = root_parent_tmp(self, ROOT)
        src = tmp / "story.md"
        src.write_text("body", encoding="utf-8")
        prompt = self.cls.build_prompt(src, {"title": "t", "type": "unprompted_story"}, "Story text.")

        self.assertIn("## Question-Judgment Rubric", prompt)
        # The rubric's LAST hard rule and the tail of its penalty vocabulary
        # table both appear — the old research[:3000] slice of research.md
        # could never have carried content this far into the document.
        self.assertIn(LAST_HARD_RULE_NEEDLE, prompt)
        self.assertIn(PENALTY_TABLE_LAST_ROW_NEEDLE, prompt)
        self.assertIn(CRITICAL_GAP_BAND_NEEDLE, prompt)
        self.assertNotIn("research[:3000]", prompt)

    def test_prompt_no_longer_reads_research_md_directly(self):
        self.assertFalse(hasattr(self.cls, "RESEARCH_FILE"))


class ResearchExpandTruncationRegressionTests(unittest.TestCase):
    """Regression: system/research_expand.py's old research_notes[:800]
    truncation held almost nothing but research.md's header and the
    AI-privacy paragraph. The expansion prompt must now carry the full
    rubric when the loader's output is passed through."""

    def setUp(self):
        self.re_mod = load("research_expand")

    def test_expansion_prompt_contains_the_full_rubric_untruncated(self):
        rubric = self.re_mod.load_judgment_rubric()
        prompt = self.re_mod.build_expansion_prompt(
            topic="Ohio years", topic_type="time_period", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="", research_notes=rubric,
        )

        self.assertIn("## QUESTION-JUDGMENT RUBRIC", prompt)
        self.assertIn(LAST_HARD_RULE_NEEDLE, prompt)
        self.assertIn(PENALTY_TABLE_LAST_ROW_NEEDLE, prompt)
        self.assertIn(CRITICAL_GAP_BAND_NEEDLE, prompt)

    def test_no_research_notes_yields_no_section(self):
        prompt = self.re_mod.build_expansion_prompt(
            topic="Ohio years", topic_type="time_period", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="",
        )
        self.assertNotIn("## QUESTION-JUDGMENT RUBRIC", prompt)

    def test_run_expansion_call_site_passes_the_full_rubric(self):
        # The _run_expansion function itself (not just build_expansion_prompt)
        # must call the loader with no slice applied — this is the exact seam
        # the old research_notes[:800] truncation lived in.
        source = SYSTEM.joinpath("research_expand.py").read_text(encoding="utf-8")
        self.assertNotIn("research_notes[:800]", source)
        self.assertNotIn("research_notes.strip()[:1000]", source)
        self.assertIn("research_notes = load_judgment_rubric()", source)


class ShippedDefinitionShapeTests(unittest.TestCase):
    """The interaction.yaml / lints.yaml YAML shape and behavior.md structure."""

    def test_interaction_yaml_parses_via_parse_simple_yaml(self):
        parsed = _parse_simple_yaml(INTERACTION_DIR / "interaction.yaml")
        self.assertEqual(parsed["interaction"], "question_judgment")
        self.assertEqual(parsed["modes"], "judge|rubric_edit")
        self.assertEqual(parsed["role.worker"], "medium")
        self.assertEqual(parsed["role.planner"], "high")
        self.assertEqual(parsed["knob.weekly_edit_max_chars"], "600")
        self.assertEqual(parsed["knob.recalibration_cadence"], "quarterly")
        self.assertEqual(parsed["knob.priority_floor"], "0.4")
        self.assertEqual(parsed["knob.priority_ceiling"], "0.95")
        self.assertIn("budget.behavior", parsed)

    def test_evals_lints_yaml_parses_via_parse_simple_yaml(self):
        parsed = _parse_simple_yaml(INTERACTION_DIR / "evals" / "lints.yaml")
        self.assertEqual(parsed["lint.behavior_has_numbered_rules"], "on")
        self.assertEqual(parsed["rule_count.min"], "11")
        self.assertEqual(parsed["band.floor"], "0.4")
        self.assertEqual(parsed["band.ceiling"], "0.95")
        # penalty_vocab.* mirrors question_candidates.check_quality's flags —
        # cross-checked against the live module below, not just re-typed here.
        penalty_vocab = {v for k, v in parsed.items() if k.startswith("penalty_vocab.")}
        self.assertIn("yes_no_wording", penalty_vocab)
        self.assertIn("self_directed_why", penalty_vocab)
        self.assertIn("too_broad", penalty_vocab)
        self.assertIn("no_scene_or_stakes_path", penalty_vocab)
        self.assertIn("no_source_citation", penalty_vocab)
        self.assertIn("too_short", penalty_vocab)
        self.assertIn("possibly_vague", penalty_vocab)
        self.assertIn("duplicate_of_", penalty_vocab)

    def test_lints_pass_against_the_shipped_behavior_file(self):
        """evals/lints.yaml's lint.behavior_has_numbered_rules /
        rule_count.min, exercised deterministically against the real
        shipped file (no engine reads this file yet — see evals/README
        conventions — this is the fixture-level check the contract's test
        plan asks for)."""
        lints = _parse_simple_yaml(INTERACTION_DIR / "evals" / "lints.yaml")
        behavior = (INTERACTION_DIR / "prompt" / "behavior.md").read_text(encoding="utf-8")
        rule_numbers = sorted(
            int(n) for n in re.findall(r"^\*\*(\d{1,2})\. ", behavior, flags=re.MULTILINE)
        )
        self.assertGreaterEqual(len(rule_numbers), int(lints["rule_count.min"]))
        self.assertEqual(rule_numbers[:11], list(range(1, 12)))

    def test_penalty_vocabulary_mirrors_check_quality_flags_exactly(self):
        qc = load("question_candidates")
        behavior = (INTERACTION_DIR / "prompt" / "behavior.md").read_text(encoding="utf-8")
        # Every flag check_quality can emit (except the dynamic
        # duplicate_of_<id> suffix) appears verbatim in the rubric's penalty
        # vocabulary table.
        sample = qc.check_quality("did you go to the store", source_path=None)
        self.assertIn("yes_no_wording", sample["flags"])
        for flag in ("yes_no_wording", "self_directed_why", "too_broad",
                     "no_scene_or_stakes_path", "no_source_citation",
                     "too_short", "possibly_vague"):
            self.assertIn(f"`{flag}`", behavior, f"penalty vocabulary missing {flag}")
        self.assertIn("duplicate_of_<id>", behavior)

    def test_priority_band_matches_knobs(self):
        interaction = _parse_simple_yaml(INTERACTION_DIR / "interaction.yaml")
        behavior = (INTERACTION_DIR / "prompt" / "behavior.md").read_text(encoding="utf-8")
        self.assertIn(interaction["knob.priority_floor"], behavior)
        self.assertIn(interaction["knob.priority_ceiling"], behavior)

    def test_no_router_or_plan_dir_shipped(self):
        self.assertFalse((INTERACTION_DIR / "router").exists())
        self.assertFalse((INTERACTION_DIR / "plan").exists())

    def test_overlay_set_matches_conversation_interaction(self):
        conversation_overlays = {p.name for p in (ROOT / "interactions" / "conversation" / "overlays").glob("*.md")}
        judgment_overlays = {p.name for p in (INTERACTION_DIR / "overlays").glob("*.md")}
        self.assertEqual(conversation_overlays, judgment_overlays)
        for overlay in (INTERACTION_DIR / "overlays").glob("*.md"):
            text = overlay.read_text(encoding="utf-8")
            self.assertIn("No deltas are verified yet", text)


class VaultContractRegistrationTests(unittest.TestCase):
    """state/question_judgment/learned.md is declared vault data, not a
    framework file — registered in vault_contract.json, never shipped."""

    def test_learned_data_path_registered(self):
        entry = vault_paths.VAULT_DATA_PATHS["question_judgment_learned"]
        self.assertEqual(entry["external_path"], "state/question_judgment/learned.md")
        self.assertEqual(entry["classification"], "durable_data")
        self.assertEqual(entry["kind"], "file")
        self.assertFalse(entry.get("required", False))
        self.assertTrue(entry.get("tracked", False))

    def test_learned_path_is_not_a_framework_file(self):
        version = json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertNotIn("state/question_judgment/learned.md", version["framework_files"])

    def test_digest_is_self_consistent(self):
        self.assertEqual(
            vault_paths.VAULT_CONTRACT["identity"]["content_digest"],
            vault_paths._contract_digest(vault_paths.VAULT_CONTRACT),
        )


class FrameworkManifestCompletenessTests(unittest.TestCase):
    """Every new file under interactions/question_judgment/ (plus the
    loader module) is registered in framework_files — recurring-defect
    doctrine: one place, checked, not reasoned about by hand per PR."""

    def test_every_shipped_interaction_file_is_a_framework_file(self):
        version = json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        framework_files = set(version["framework_files"])
        on_disk = {
            p.relative_to(ROOT).as_posix()
            for p in INTERACTION_DIR.rglob("*")
            if p.is_file()
        }
        self.assertTrue(on_disk, "expected shipped files under interactions/question_judgment/")
        missing = on_disk - framework_files
        self.assertEqual(missing, set(), f"files on disk but not in framework_files: {missing}")

    def test_loader_module_is_a_framework_file(self):
        version = json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertIn("system/question_judgment.py", version["framework_files"])

    def test_version_bumped_past_main(self):
        version = json.loads((ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(version["version"], 164)


class ADRTests(unittest.TestCase):
    def test_adr_0007_exists(self):
        adr = ROOT / "docs" / "adr" / "0007-question-judgment-interaction.md"
        self.assertTrue(adr.exists())
        text = adr.read_text(encoding="utf-8")
        self.assertIn("ADR 0007", text)
        self.assertIn("question_judgment_learned", text)


if __name__ == "__main__":
    unittest.main()
