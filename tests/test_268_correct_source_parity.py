"""lifehug#268 — `lifehug.py correct-source` must bind the same flags as
`source_integrity.py correct`, mechanically, forever.

v236 (lifehug#255, O-E0d) added `--supersedes` to `source_integrity.py
cmd_correct`; v237 (O-C2) added `--role`. Neither flag reached `lifehug.py
correct-source` — the other reference on the same product-parity catalog
row — because the two parsers were two independent hand-written argument
lists. Per ADR 0021 ("one definition, many hosts") the fix is
`source_integrity.add_correct_source_arguments`: ONE function both entry
points call to build their argparse arguments, so they cannot drift again.

Every test below was run against unmodified `main` first and seen failing:
`correct-source`'s parser had no `--supersedes` and no `--role` at all, so
`--supersedes` raised `error: unrecognized arguments` before either command
ever ran.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tempdirs import root_parent_tmp  # noqa: E402

import lifehug  # noqa: E402
import source_integrity as si  # noqa: E402

ANSWER_TEXT = (
    '---\ntitle: "Question A1"\nsource_id: "answer:A1"\ntype: "prompted_answer"\n'
    "---\n\n# Question A1\n\nCharlee wrote me a letter when I was a boy.\n"
)


def _subparser(parser, command):
    """The argparse subparser bound to `command`, never a hand-copied action
    list — derived from the parser's own subparsers action."""
    sub_action = next(
        a for a in parser._subparsers._group_actions if a.dest == "command"
    )
    return sub_action.choices[command]


def _option_strings(parser, command) -> set[str]:
    sub = _subparser(parser, command)
    flags: set[str] = set()
    for action in sub._actions:
        flags.update(action.option_strings)
    return flags


class CorrectSourceFlagParityTests(unittest.TestCase):
    """The structural half: both entry points accept the identical flag set,
    derived from `source_integrity`'s own parser rather than a hand list."""

    def test_correct_source_accepts_the_same_flags_as_correct(self):
        expected = _option_strings(si.build_parser(), "correct")
        actual = _option_strings(lifehug.build_parser(), "correct-source")
        self.assertEqual(expected, actual)
        # Guard the guard: if these ever stop being in the expected set, the
        # comparison above would pass trivially without proving anything.
        self.assertIn("--supersedes", expected)
        self.assertIn("--role", expected)

    def test_correct_source_parser_parses_supersedes_and_role(self):
        parser = lifehug.build_parser()
        args = parser.parse_args(
            [
                "correct-source",
                "answers/A1.md",
                "--supersedes",
                "correction:xyz",
                "--role",
                "placement",
            ]
        )
        self.assertEqual(args.supersedes, "correction:xyz")
        self.assertEqual(args.role, "placement")


class CorrectSourceForwardsSupersedesAndRoleTests(unittest.TestCase):
    """The behavioral half: what `correct-source` forwards to
    `source_integrity.py`, run back through the real parser+handler, files
    the identical record `source_integrity.py correct` would file directly."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="correct-source-268-")
        self.answers = self.root / "answers"
        self.corrections = self.root / "sources" / "corrections"
        self.answers.mkdir(parents=True)
        self.corrections.mkdir(parents=True)
        (self.answers / "A1.md").write_text(ANSWER_TEXT, encoding="utf-8")
        self._patches = [
            mock.patch.object(si, "REPO_DIR", self.root),
            mock.patch.object(si, "ANSWERS_DIR", self.answers),
            mock.patch.object(si, "SOURCES_DIR", self.root / "sources"),
            mock.patch.object(si, "CORRECTION_SOURCES_DIR", self.corrections),
            mock.patch.object(si, "SOURCE_MANIFEST_FILE", self.root / "state" / "source_manifest.json"),
            mock.patch.object(si, "WIKI_DIR", self.root / "wiki"),
        ]
        for patch in self._patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _run_correct(self, target, body, *, kind="factual", role=None, supersedes=None):
        """Directly invoke `source_integrity.py correct` — the reference
        implementation both entry points must agree with. Returns
        (exit_code, stdout, stderr, metadata-or-None) — `create_linked_source`
        is idempotent by content identity, so a duplicate call can print the
        SAME pre-existing path rather than creating a new file; either way
        the printed path names the record to read back."""
        args = SimpleNamespace(
            target=target, kind=kind, source="manual", title=None,
            role=role, supersedes=supersedes,
        )
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(body)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = si.cmd_correct(args)
        stdout, stderr = out.getvalue(), err.getvalue()
        metadata = None
        if code == 0:
            metadata = self._metadata_from_stdout(stdout)
        return code, stdout, stderr, metadata

    def _metadata_from_stdout(self, stdout: str) -> dict[str, object]:
        match = re.search(r"correction source: (\S+)", stdout)
        assert match, f"no correction path printed in: {stdout!r}"
        path = self.root / match.group(1)
        metadata, _ = si.split_frontmatter(path.read_text(encoding="utf-8"))
        return metadata

    def test_correct_source_forwards_produce_the_same_record_as_correct(self):
        # Predecessor correction, filed the reference way.
        code, _, err, predecessor = self._run_correct(
            "answers/A1.md", "It happened in my Childhood.", role="content",
        )
        self.assertEqual(code, 0, err)
        first_id = predecessor["source_id"]

        # A reference correction filed directly via `source_integrity.py
        # correct --supersedes <id> --role placement`.
        code, _, err, reference = self._run_correct(
            "answers/A1.md", "It happened around May 2022, in Sedona.",
            role="placement", supersedes=first_id,
        )
        self.assertEqual(code, 0, err)

        # What `lifehug.py correct-source --supersedes <id> --role
        # placement` actually forwards — captured via lifehug's own
        # run_python choke point, then fed through source_integrity's real
        # parser+handler exactly as the real subprocess call would.
        parser = lifehug.build_parser()
        cli_args = parser.parse_args(
            [
                "correct-source", "answers/A1.md",
                "--kind", "factual", "--role", "placement",
                "--supersedes", first_id,
            ]
        )
        captured: list[tuple[str, list[str]]] = []

        def fake_run_python(script_name, flags):
            captured.append((script_name, flags))
            return 0

        with mock.patch.object(lifehug, "run_python", fake_run_python):
            rc = lifehug.cmd_correct_source(cli_args)
        self.assertEqual(rc, 0)
        self.assertEqual(len(captured), 1)
        script_name, flags = captured[0]
        self.assertEqual(script_name, "source_integrity.py")
        self.assertIn("--supersedes", flags)
        self.assertIn("--role", flags)

        # Same target, same body, same flags: `create_linked_source` is
        # content-identity idempotent, so feeding the FORWARDED flags back
        # through the real parser+handler either creates the byte-identical
        # record the reference call already made, or reuses it outright —
        # both outcomes prove the two entry points agree.
        forwarded_args = si.build_parser().parse_args(flags)
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("It happened around May 2022, in Sedona.")), \
                contextlib.redirect_stdout(out):
            code = si.cmd_correct(forwarded_args)
        self.assertEqual(code, 0)
        via_correct_source = self._metadata_from_stdout(out.getvalue())

        for key in ("source_id", "correction_role", "supersedes", "supersedes_path", "correction_kind"):
            self.assertEqual(
                via_correct_source[key], reference[key],
                f"{key} diverged between correct-source and correct",
            )


if __name__ == "__main__":
    unittest.main()
