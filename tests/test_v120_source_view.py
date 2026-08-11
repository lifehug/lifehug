"""v120: owner-only, read-only raw source-body viewer security contract."""

from __future__ import annotations

import ast
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "system"))

import serve_wiki  # noqa: E402


class SourceViewTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name)
        self.answers = self.repo / "answers"
        self.sources = self.repo / "sources"
        self.answers.mkdir()
        for name in ("manual", "artifacts", "corrections", "gmail", "imports"):
            (self.sources / name).mkdir(parents=True)
        self.manifest = self.repo / "state" / "source_manifest.json"
        self.manifest.parent.mkdir()
        self._originals = {
            "ANSWERS_DIR": serve_wiki.ANSWERS_DIR,
            "SOURCES_DIR": serve_wiki.SOURCES_DIR,
            "SOURCE_MANIFEST_FILE": serve_wiki.SOURCE_MANIFEST_FILE,
        }
        serve_wiki.ANSWERS_DIR = self.answers
        serve_wiki.SOURCES_DIR = self.sources
        serve_wiki.SOURCE_MANIFEST_FILE = self.manifest

        self.answer = self.answers / "A1.md"
        self.answer.write_text(
            "---\n"
            'title: "The Blue Bicycle"\n'
            'type: "prompted_answer"\n'
            'source_id: "answer:A1"\n'
            'visibility: "owner_only"\n'
            "immutable: true\n"
            'raw_url: "https://secret.example/private"\n'
            "---\n"
            "# The Blue Bicycle\n\n"
            "I learned to ride beside the old oak tree.\n",
            encoding="utf-8",
        )
        self.manual = self.sources / "manual" / "summer.md"
        self.manual.write_text("# Summer Story\n\nA synthetic summer memory.\n", encoding="utf-8")
        self.manifest.write_text(json.dumps({"sources": {
            "answers/A1.md": {
                "title": "The Blue Bicycle",
                "type": "prompted_answer",
                "source_path": "answers/A1.md",
                "source_medium": "voice",
                "metadata": "do-not-render-private-envelope",
                "raw_url": "https://secret.example/private",
            },
            "sources/manual/summer.md": {
                "title": "Summer Story",
                "type": "manual_source",
                "source_path": "sources/manual/summer.md",
            },
        }}), encoding="utf-8")

    def _track(self, ref: str, **metadata) -> None:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["sources"][ref] = {"source_path": ref, **metadata}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

    def tearDown(self):
        for name, value in self._originals.items():
            setattr(serve_wiki, name, value)
        self.tempdir.cleanup()

    def test_approved_roots_resolve_exact_regular_markdown_files(self):
        refs = ["answers/A1.md", "sources/manual/summer.md"]
        for family in ("artifacts", "corrections", "gmail"):
            path = self.sources / family / "record.md"
            path.write_text(f"# Synthetic {family}\n", encoding="utf-8")
            ref = f"sources/{family}/record.md"
            self._track(ref, title=f"Synthetic {family}")
            refs.append(ref)
        nested = self.sources / "manual" / "nested"
        nested.mkdir()
        (nested / "story.md").write_text("nested", encoding="utf-8")
        self._track("sources/manual/nested/story.md", title="Nested story")
        refs.append("sources/manual/nested/story.md")

        for ref in refs:
            with self.subTest(ref=ref):
                self.assertIsNotNone(serve_wiki.read_source_ref(ref))
                self.assertEqual(serve_wiki.source_href(ref), f"/source/{ref}")

    def test_path_tricks_non_files_and_unapproved_roots_fail_closed(self):
        (self.sources / "imports" / "archive.md").write_text("private", encoding="utf-8")
        cases = [
            "", " answers/A1.md", "answers/A1.md ", "/etc/passwd",
            "../answers/A1.md", "answers/../A1.md",
            "answers/./A1.md", "answers//A1.md", "answers\\A1.md",
            "answers/%2e%2e/A1.md", "answers/%252e%252e/A1.md",
            "answers/A1.md\x00.txt", "answers", "answers/A1.txt",
            "sources/imports/archive.md", "sources/unknown/archive.md",
        ]
        for ref in cases:
            with self.subTest(ref=repr(ref)):
                self.assertIsNone(serve_wiki.read_source_ref(ref))
                self.assertIsNone(serve_wiki.source_href(ref))

    def test_every_symlink_target_and_symlinked_directory_is_rejected(self):
        outside = self.repo / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        (self.answers / "outside-link.md").symlink_to(outside)
        (self.answers / "inside-link.md").symlink_to(self.answer)
        self._track("answers/outside-link.md")
        self._track("answers/inside-link.md")

        real_dir = self.repo / "real-dir"
        real_dir.mkdir()
        (real_dir / "secret.md").write_text("secret", encoding="utf-8")
        (self.sources / "manual" / "dir-link").symlink_to(real_dir, target_is_directory=True)
        in_root_dir = self.sources / "manual" / "real"
        in_root_dir.mkdir()
        (in_root_dir / "story.md").write_text("story", encoding="utf-8")
        (self.sources / "manual" / "in-root-dir-link").symlink_to(
            in_root_dir, target_is_directory=True)
        self._track("sources/manual/dir-link/secret.md")
        self._track("sources/manual/in-root-dir-link/story.md")

        for ref in (
            "answers/outside-link.md",
            "answers/inside-link.md",
            "sources/manual/dir-link/secret.md",
            "sources/manual/in-root-dir-link/story.md",
        ):
            with self.subTest(ref=ref):
                self.assertIsNone(serve_wiki.read_source_ref(ref))

    def test_untracked_regular_file_is_not_an_approved_source(self):
        untracked = self.sources / "custom-connector" / "record.md"
        untracked.parent.mkdir()
        untracked.write_text("# Untracked\n", encoding="utf-8")
        self.assertIsNone(serve_wiki.read_source_ref("sources/custom-connector/record.md"))
        self._track("sources/custom-connector/record.md", type="external_record")
        self.assertIsNotNone(serve_wiki.read_source_ref("sources/custom-connector/record.md"))

    def test_final_file_swap_cannot_redirect_the_open_descriptor(self):
        outside = self.repo / "outside.md"
        outside.write_text("outside secret", encoding="utf-8")
        held = self.answers / "A1-held.md"
        original_open = serve_wiki.os.open
        swapped = False

        def swap_after_open(path, flags, *args, **kwargs):
            nonlocal swapped
            fd = original_open(path, flags, *args, **kwargs)
            if path == "A1.md" and kwargs.get("dir_fd") is not None and not swapped:
                swapped = True
                self.answer.rename(held)
                self.answer.symlink_to(outside)
            return fd

        with mock.patch.object(serve_wiki.os, "open", side_effect=swap_after_open):
            source = serve_wiki.read_source_ref("answers/A1.md", include_body=True)
        self.assertIsNotNone(source)
        self.assertIn("old oak tree", source.text)
        self.assertNotIn("outside secret", source.text)

    def test_integrity_and_action_links_never_read_source_bodies(self):
        large = self.sources / "custom-connector" / "large.md"
        large.parent.mkdir()
        large.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
        self._track("sources/custom-connector/large.md", title="Large synthetic record")
        with mock.patch.object(serve_wiki.os, "read",
                               side_effect=AssertionError("link building must not read bodies")):
            self.assertEqual(
                serve_wiki.source_href("sources/custom-connector/large.md"),
                "/source/sources/custom-connector/large.md",
            )
            _, integrity, _ = serve_wiki.view_sources()
            _, actions = serve_wiki.source_actions_html("sources/custom-connector/large.md")
        self.assertIn("Large synthetic record", integrity)
        self.assertIn("Read source", actions)

    def test_rendered_body_uses_safe_metadata_and_links_both_directions(self):
        result = serve_wiki.source_document_html("answers/A1.md")
        self.assertIsNotNone(result)
        title, body = result
        self.assertEqual(title, "The Blue Bicycle")
        self.assertIn("I learned to ride beside the old oak tree.", body)
        self.assertIn("owner_only", body)
        self.assertIn("/views/sources", body)
        self.assertIn("/source-actions?ref=answers/A1.md", body)
        self.assertNotIn("secret.example", body)
        self.assertNotIn("do-not-render-private-envelope", body)

        _, action_body = serve_wiki.source_actions_html("answers/A1.md")
        self.assertIn('href="/source/answers/A1.md"', action_body)
        self.assertIn('href="/views/sources"', action_body)
        self.assertIn("/actions/reflect", action_body)
        self.assertIn("/actions/fix", action_body)

        _, integrity_body, _ = serve_wiki.view_sources()
        self.assertIn('href="/source/answers/A1.md"', integrity_body)
        self.assertIn('href="/source/sources/manual/summer.md"', integrity_body)

    def test_allowlist_has_one_authoritative_resolver(self):
        source = Path(serve_wiki.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        manifest_callers = set()
        # The behavior this guards is a single authoritative opener for raw
        # source bodies. The no-follow fd walk itself now lives in
        # vault_paths.py (lifehug#recurring-defect-doctrine: one importable
        # no-follow I/O module, not a second hand-rolled implementation
        # here) — so the guard tracks calls to its open_vault_fd /
        # read_vault_bytes entry points instead of a raw os.open call.
        vault_io_callers = set()
        body_read_callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                        and child.func.id == "_manifest_source_record"):
                    manifest_callers.add(node.name)
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                        and child.func.id in {"open_vault_fd", "read_vault_bytes"}):
                    vault_io_callers.add(node.name)
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                        and child.func.id == "read_source_ref"
                        and any(keyword.arg == "include_body"
                                and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True
                                for keyword in child.keywords)):
                    body_read_callers.add(node.name)
        self.assertEqual(manifest_callers, {"read_source_ref"})
        self.assertEqual(vault_io_callers, {"read_source_ref"})
        self.assertEqual(body_read_callers, {"source_document_html"})
        self.assertNotIn("def resolve_source_ref", source,
                         "do not reintroduce validate-then-reopen source resolvers")


class SourceViewHttpTests(SourceViewTests):
    def setUp(self):
        super().setUp()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve_wiki.Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def _get(self, path: str, *, host: str | None = None) -> tuple[int, dict[str, str], str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host} if host else {}
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read().decode("utf-8", "replace")
        result = response.status, dict(response.getheaders()), body
        conn.close()
        return result

    def test_get_renders_without_mutating_any_source_or_state_file(self):
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in (self.answer, self.manual, self.manifest)}
        status, headers, body = self._get("/source/answers/A1.md")
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in (self.answer, self.manual, self.manifest)}
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("The Blue Bicycle", body)
        self.assertEqual(after, before)

    def test_http_rejects_encoded_traversal_absolute_nul_and_directory(self):
        for path in (
            "/source/answers/%2e%2e/outside.md",
            "/source/answers/%252e%252e/outside.md",
            "/source/%2Fetc%2Fpasswd",
            "/source/answers/A1.md%00.txt",
            "/source/sources/manual",
        ):
            with self.subTest(path=path):
                status, headers, body = self._get(path)
                self.assertEqual(status, 404)
                self.assertEqual(headers.get("Cache-Control"), "no-store")
                self.assertIn("Source unavailable", body)

    def test_raw_source_get_requires_loopback_host(self):
        # A spoofed Host authority is now rejected by do_GET's own
        # peer/Host boundary check (lifehug#109) before the request ever
        # reaches the /source/ route's narrower _source_get_allowed()
        # check, so the response is the general owner-boundary rejection
        # rather than the route-specific "only on this device" message —
        # the 403 + no-store guarantee this test cares about still holds.
        status, headers, body = self._get(
            "/source/answers/A1.md", host="127.0.0.1.evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertIn("Forbidden", body)


if __name__ == "__main__":
    unittest.main()
