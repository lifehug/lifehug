"""v368 — the owner's question queue (ruling "Question queue", 2026-09-27).

* Never re-send: "A send must never repeat a question that's already been
  sent or answered … That should never happen." Refined: "a question sent but
  not answered CAN be re-sent if the queue was empty … But I feel like I
  already answered them and then it was sent again. That's the problem."
* Distribution: "no single focus over 30%; people focuses as a group up to
  50%; the rest of the week to my-life and projects."
* Interleave: "never two questions from the same group on consecutive days
  (that's sorting)."

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

import delivery_guard as guard  # noqa: E402
import question_planner as qp  # noqa: E402

spec = importlib.util.spec_from_file_location("ask_v368", SYSTEM / "ask.py")
ask = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ask)


def q(qid, *, answered=False, text="Tell me about that."):
    return {"id": qid, "category": qid[0], "text": text, "answered": answered}


EMPTY_DIR = Path(tempfile.mkdtemp(prefix="v368-no-answers-"))  # never written to


def records(questions, **kwargs):
    kwargs.setdefault("rotation", {})
    kwargs.setdefault("queue_data", {})
    kwargs.setdefault("answers_dir", EMPTY_DIR)
    return guard.delivery_records(questions, **kwargs)


class NeverResendRuleTests(unittest.TestCase):
    def test_an_answered_question_is_never_allowed(self):
        bank = [q("E27", answered=True), q("A34")]
        verdict = guard.send_verdict("E27", bank, records(bank))
        self.assertFalse(verdict["allowed"])
        self.assertEqual(verdict["rule"], guard.AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN)

    def test_an_answer_file_counts_as_answered_even_before_the_bank_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "E27.md").write_text("answer", encoding="utf-8")
            bank = [q("E27"), q("A34")]
            verdict = guard.send_verdict("E27", bank, records(bank, answers_dir=Path(tmp)))
        self.assertFalse(verdict["allowed"])
        self.assertTrue(verdict["answered"])

    def test_a_sent_question_waits_while_anything_unasked_remains(self):
        bank = [q("A17a"), q("A18")]
        rec = records(bank, rotation={"delivery_counts": {"A17a": 1}})
        verdict = guard.send_verdict("A17a", bank, rec)
        self.assertFalse(verdict["allowed"])
        self.assertEqual(verdict["rule"], guard.A_SENT_QUESTION_WAITS_UNTIL_NOTHING_UNASKED_REMAINS)
        self.assertTrue(guard.send_verdict("A18", bank, rec)["allowed"])

    def test_a_sent_question_may_come_back_only_when_nothing_unasked_remains(self):
        bank = [q("A17a"), q("A18", answered=True)]
        rec = records(bank, rotation={"delivery_counts": {"A17a": 3}})
        self.assertTrue(guard.send_verdict("A17a", bank, rec)["allowed"])

    def test_a_queue_item_marked_sent_is_a_send(self):
        bank = [q("G6"), q("A1")]
        rec = records(bank, queue_data={"queue": [{"question_id": "G6", "status": "sent"}]})
        self.assertIn("G6", rec["sent"])
        self.assertFalse(guard.send_verdict("G6", bank, rec)["allowed"])

    def test_a_host_can_only_add_records(self):
        bank = [q("G6"), q("A1")]
        rec = records(bank, also_sent=["G6"], also_answered=["A1,  "])
        self.assertIn("G6", rec["sent"])
        self.assertIn("A1", rec["answered"])
        self.assertFalse(guard.send_verdict("A1", bank, rec)["allowed"])

    def test_an_unknown_question_is_refused(self):
        bank = [q("A1")]
        self.assertFalse(guard.send_verdict("Z9", bank, records(bank))["allowed"])


class AskNeverResendsTests(unittest.TestCase):
    """The selection seat: `ask.pick_next_question` under the same rule."""

    def setUp(self):
        self.enterContext(mock.patch.object(ask, "load_config", return_value={}))
        self.read_json = self.enterContext(mock.patch.object(ask, "read_json", return_value={}))
        self.enterContext(mock.patch.object(guard, "ANSWERS_DIR", EMPTY_DIR))
        self.categories = {c: {"group": "main"} for c in "ABCDE"} | {"G": {"group": "project"}}

    def queue(self, *ids, sent=()):
        self.read_json.return_value = {
            "expires_at": "2099-01-01T00:00:00Z",
            "queue": [{"question_id": i, "status": "sent" if i in sent else "queued"} for i in ids],
        }

    def test_the_e27_morning_an_answered_head_is_skipped(self):
        # 24 Sep: E27 answered, but a stale view still showed it queued.
        self.queue("E27", "A34", "H11", "G6")
        bank = [q("E27", answered=True), q("A34"), q("G6"), q("H11")]
        pick = ask.pick_next_question(bank, self.categories, {"delivery_counts": {"E27": 1}})
        self.assertEqual(pick["id"], "A34")

    def test_a_queued_head_already_delivered_is_skipped(self):
        self.queue("E27", "A34")
        bank = [q("E27"), q("A34")]
        pick = ask.pick_next_question(bank, self.categories, {"delivery_counts": {"E27": 4}})
        self.assertEqual(pick["id"], "A34")

    def test_host_records_are_honoured(self):
        self.queue("A34", "H11", "G6")
        bank = [q("A34"), q("G6"), q("H11")]
        pick = ask.pick_next_question(bank, self.categories, {},
                                      also_sent=["A34"], also_answered=["H11"])
        self.assertEqual(pick["id"], "G6")

    def test_a_used_up_queue_falls_back_to_the_bank_never_a_repeat(self):
        # The A17a week: the queue expired and one question was sent 8 days.
        self.read_json.return_value = {"expires_at": "2000-01-01T00:00:00Z", "queue": []}
        bank = [q("A17a"), q("A18"), q("B2")]
        rotation = {"delivery_counts": {"A17a": 8}, "last_question_id": "A17a"}
        seen = set()
        for _ in range(3):
            pick = ask.pick_next_question(bank, self.categories, rotation)
            self.assertNotEqual(pick["id"], "A17a")
            seen.add(pick["id"])
            rotation["delivery_counts"][pick["id"]] = 1
            rotation["last_question_id"] = pick["id"]
            if seen == {"A18", "B2"}:
                break
        self.assertEqual(seen, {"A18", "B2"})

    def test_only_an_exhausted_bank_re_offers_least_offered_not_yesterdays(self):
        self.read_json.return_value = {}
        bank = [q("A1"), q("A2"), q("A3", answered=True)]
        rotation = {"delivery_counts": {"A1": 1, "A2": 1}, "last_question_id": "A1"}
        self.assertEqual(ask.pick_next_question(bank, self.categories, rotation)["id"], "A2")
        rotation = {"delivery_counts": {"A1": 1, "A2": 3}, "last_question_id": "A2"}
        self.assertEqual(ask.pick_next_question(bank, self.categories, rotation)["id"], "A1")

    def test_an_answered_question_never_comes_back_even_when_nothing_else_remains(self):
        self.read_json.return_value = {}
        bank = [q("A1", answered=True)]
        self.assertIsNone(ask.pick_next_question(bank, self.categories, {}, also_answered=[]))


# ---------------------------------------------------------------------------
# Distribution + interleave, on a synthetic vault shaped like a real one: the
# primary life story (five categories, roadmap cap 0.40), one project, and six
# people.
# ---------------------------------------------------------------------------

PEOPLE = ["mom", "dad", "spouse", "son", "daughter", "brother"]
PEOPLE_CATS = "KLMNOP"


TEXTS = ("Walk me through that day.", "What was the hardest part?", "When did it change?",
         "What did it teach you?", "Tell me about the house.", "Who was there with you?")


def bank_rows(cat, count, start=1):
    return [q(f"{cat}{n}", text=TEXTS[n % len(TEXTS)]) for n in range(start, start + count)]


def synthetic_state():
    questions = []
    categories = {}
    for cat in "ABCDE":
        categories[cat] = {"group": "main", "name": cat}
        questions += bank_rows(cat, 12)
    categories["F"] = {"group": "project", "name": "Company"}
    questions += bank_rows("F", 24)
    for cat, count in zip(PEOPLE_CATS, (30, 4, 12, 8, 8, 6)):
        categories[cat] = {"group": "focus", "name": cat}
        questions += bank_rows(cat, count)
    # The spouse is well covered (saturated) — she must still come round.
    questions += [q(f"M{n}", answered=True) for n in range(20, 45)]
    coverage = {"categories": {}}
    return questions, categories, coverage


def synthetic_roadmap():
    focuses = [{"id": "my-life", "type": "life_story", "primary": True, "tier": "extreme",
                "cap": 0.4, "categories": list("ABCDE")},
               {"id": "company", "type": "project", "tier": "extreme", "cap": 0.3,
                "categories": ["F"]}]
    for person, cat in zip(PEOPLE, PEOPLE_CATS):
        focuses.append({"id": person, "type": "person", "tier": "standard", "cap": 0.3,
                        "categories": [cat], "target_depth": 20})
    return {"focuses": focuses}


class SyntheticVault:
    def __enter__(self):
        self.patches = [
            mock.patch.object(qp, "load_question_state", side_effect=synthetic_state),
            mock.patch.object(qp, "resolve_roadmap", return_value=synthetic_roadmap()),
            mock.patch.object(qp, "load_candidates", return_value=[]),
            mock.patch.object(qp, "read_answer_dates", return_value={}),
            mock.patch.object(qp, "global_fullness", return_value=0.5),
        ]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


def week(seed, state=None, previous=None):
    return qp.build_queue(8, 2, 8, state or qp.default_planner_state(), seed=seed,
                          previous_queue=previous or {"queue": []})["queue"]


def weeks(start, count):
    """Consecutive weeks, each built from the one it replaces."""
    out, previous = [], {"queue": []}
    for seed in range(start, start + count):
        built = week(seed, previous=previous)
        out.append(built)
        previous = {"queue": built}
    return out


class DistributionTests(unittest.TestCase):
    SEEDS = range(60)

    def test_no_single_focus_over_thirty_percent_including_the_life_story(self):
        cap = math.ceil(8 * qp.SINGLE_FOCUS_CAP)
        self.assertEqual(cap, 3)  # "Etherfuse was at its cap, not over it": 3 of 8
        with SyntheticVault():
            for seed in self.SEEDS:
                per = Counter(item["focus"] for item in week(seed))
                self.assertLessEqual(max(per.values()), cap, (seed, per))

    def test_people_as_a_group_up_to_half(self):
        with SyntheticVault():
            people = [sum(1 for i in week(seed) if i["group"] == "focus") for seed in self.SEEDS]
        self.assertLessEqual(max(people), 4)
        self.assertGreaterEqual(sum(people) / len(people), 3.0)  # was held to 2 by the 0.25 cap

    def test_one_slot_per_person_before_anyone_gets_two(self):
        with SyntheticVault():
            for seed in self.SEEDS:
                per = Counter(i["focus"] for i in week(seed) if i["group"] == "focus")
                if per:
                    self.assertEqual(max(per.values()), 1, (seed, per))

    def test_every_person_comes_up_within_a_few_weeks(self):
        with SyntheticVault():
            for start in range(0, 200, 3):
                seen = {i["focus"] for built in weeks(start, 2) for i in built}
                self.assertTrue(set(PEOPLE) <= seen, (start, set(PEOPLE) - seen))

    def test_the_rest_goes_to_my_life_and_projects(self):
        with SyntheticVault():
            for seed in self.SEEDS:
                groups = Counter(i["group"] for i in week(seed))
                self.assertEqual(sum(groups.values()), 8)
                self.assertGreaterEqual(groups["main"] + groups["project"], 4)

    def test_a_copied_pre_ruling_cap_is_migrated_on_read(self):
        stored = qp.default_planner_state()
        stored["caps"]["group"] = {"main": 0.5, "project": 0.35, "focus": 0.25, "timeline": 0.01}
        with mock.patch.object(qp, "read_json", return_value=json.loads(json.dumps(stored))):
            self.assertEqual(qp.load_planner_state()["caps"]["group"]["focus"], 0.5)
        stored["caps"]["group"]["focus"] = 0.4  # an author's own choice is kept
        with mock.patch.object(qp, "read_json", return_value=json.loads(json.dumps(stored))):
            self.assertEqual(qp.load_planner_state()["caps"]["group"]["focus"], 0.4)

    def test_the_week_is_reproducible_for_a_seed(self):
        with SyntheticVault():
            self.assertEqual(week(7), week(7))


def item(qid, group, focus):
    return {"question_id": qid, "group": group, "focus": focus}


class InterleaveTests(unittest.TestCase):
    def test_built_weeks_never_put_one_group_on_consecutive_days(self):
        with SyntheticVault():
            for seed in range(60):
                days = week(seed)
                for a, b in zip(days, days[1:]):
                    self.assertNotEqual(a["group"], b["group"], (seed, [d["group"] for d in days]))

    def test_sorted_input_comes_out_alternating_and_stable(self):
        sorted_week = ([item(f"A{n}", "main", "my-life") for n in range(3)]
                       + [item(f"F{n}", "project", "co") for n in range(2)]
                       + [item(f"K{n}", "focus", p) for n, p in enumerate(["mom", "dad", "son"])])
        out = qp.interleave_week(sorted_week)
        self.assertEqual(sorted(i["question_id"] for i in out),
                         sorted(i["question_id"] for i in sorted_week))
        for a, b in zip(out, out[1:]):
            self.assertNotEqual(a["group"], b["group"])
        self.assertEqual(out, qp.interleave_week(sorted_week))

    def test_a_forced_repeat_is_as_rare_as_the_mix_allows_and_never_the_same_focus(self):
        lopsided = ([item(f"K{n}", "focus", p) for n, p in enumerate(["mom", "dad", "son", "mom2", "daughter"])]
                    + [item("A1", "main", "my-life")])
        out = qp.interleave_week(lopsided)
        repeats = sum(a["group"] == b["group"] for a, b in zip(out, out[1:]))
        self.assertEqual(repeats, 5 - 1 - 1)  # five of one group, one other: three forced
        for a, b in zip(out, out[1:]):
            self.assertNotEqual(a["focus"], b["focus"])

    def test_priority_order_is_kept_where_the_rule_allows(self):
        days = [item("A1", "main", "my-life"), item("K1", "focus", "mom"),
                item("A2", "main", "my-life"), item("F1", "project", "co")]
        self.assertEqual([i["question_id"] for i in qp.interleave_week(days)],
                         ["A1", "K1", "A2", "F1"])


if __name__ == "__main__":
    unittest.main()


class DeliveryCheckCliTests(unittest.TestCase):
    """The pre-send check a host calls, against a real vault on disk."""

    def setUp(self):
        import shutil
        import subprocess
        import os
        from tempdirs import root_parent_tmp
        self.subprocess = subprocess
        self.vault = root_parent_tmp(self, ROOT, prefix="v368-check-")
        system = self.vault / "system"
        system.mkdir()
        (self.vault / "state").mkdir()
        for name in ("ask.py", "delivery_guard.py", "lifehug_core.py", "vault_paths.py",
                     "vault_contract.json", "update.py"):
            shutil.copyfile(SYSTEM / name, system / name)
        (system / "question-bank.md").write_text(
            "## A: Origins\n- [ ] A1: Where did it start?\n- [x] A2: Who was there?\n"
            "- [ ] A3: What changed?\n", encoding="utf-8")
        (system / "rotation.json").write_text(json.dumps(
            {"version": 1, "current_pass": 1, "delivery_counts": {"A1": 2}}), encoding="utf-8")
        self.env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.vault),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        subprocess.run([sys.executable, str(system / "update.py"), "--migrate-vault",
                        "--vault-root", str(self.vault)], cwd=self.vault, env=self.env,
                       check=True, capture_output=True, text=True, timeout=20)

    def check(self, *args):
        result = self.subprocess.run(
            [sys.executable, str(self.vault / "system" / "delivery_guard.py"), *args, "--json"],
            cwd=self.vault, env=self.env, capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    def test_answered_is_refused_with_exit_three(self):
        code, verdict = self.check("A2")
        self.assertEqual(code, guard.REFUSED_EXIT)
        self.assertEqual(verdict["rule"], guard.AN_ANSWERED_QUESTION_IS_NEVER_SENT_AGAIN)

    def test_sent_waits_and_unsent_is_allowed(self):
        self.assertEqual(self.check("A1")[0], guard.REFUSED_EXIT)
        self.assertEqual(self.check("A3")[0], 0)

    def test_host_records_make_it_stricter(self):
        code, verdict = self.check("A3", "--also-answered", "A3")
        self.assertEqual(code, guard.REFUSED_EXIT)
        self.assertTrue(verdict["answered"])
        # Every unanswered question has now gone out: a re-offer is allowed.
        self.assertEqual(self.check("A1", "--also-sent", "A3")[0], 0)

    def test_dry_run_pick_honours_the_rule(self):
        result = self.subprocess.run(
            [sys.executable, str(self.vault / "system" / "ask.py"), "--dry-run"],
            cwd=self.vault, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertIn("[A3]", result.stdout)
        result = self.subprocess.run(
            [sys.executable, str(self.vault / "system" / "ask.py"), "--dry-run",
             "--also-answered", "A3"],
            cwd=self.vault, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertIn("[A1]", result.stdout)  # nothing unasked left: the sent one may return
