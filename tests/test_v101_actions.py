"""Tests for the viewer write actions (v101): POST auth, jobs, second-voice
acknowledge, and the action UI surfaces."""

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import jobs  # noqa: E402
import question_planner as qp  # noqa: E402
import serve_wiki  # noqa: E402
import vault_paths  # noqa: E402


class PostAuthTests(unittest.TestCase):
    """The POST surface: token + localhost checks, dispatch, redirect."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), serve_wiki.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self._orig_action = serve_wiki.ACTIONS["/actions/candidate"]
        serve_wiki.ACTIONS["/actions/candidate"] = \
            lambda form: ("/views/candidates", "stub ok", None)

    def tearDown(self):
        serve_wiki.ACTIONS["/actions/candidate"] = self._orig_action

    def _post(self, path, data, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = urlencode(data)
        base = {"Content-Type": "application/x-www-form-urlencoded"}
        base.update(headers or {})
        conn.request("POST", path, body=body, headers=base)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        return resp, payload

    def test_post_without_token_403(self):
        resp, _ = self._post("/actions/candidate", {"id": "c1"})
        self.assertEqual(resp.status, 403)

    def test_post_with_wrong_token_403(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": "nope"})
        self.assertEqual(resp.status, 403)

    def test_post_with_bad_host_403(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": serve_wiki.SESSION_TOKEN},
                             headers={"Host": "evil.example.com"})
        self.assertEqual(resp.status, 403)

    def test_host_prefix_and_wrong_port_do_not_count_as_loopback(self):
        for host in (f"localhost.evil:{self.port}", f"127.0.0.1.evil:{self.port}",
                     "localhost:9"):
            with self.subTest(host=host):
                resp, _ = self._post(
                    "/actions/candidate",
                    {"id": "c1", "_token": serve_wiki.SESSION_TOKEN},
                    headers={"Host": host},
                )
                self.assertEqual(resp.status, 403)

    def test_post_with_foreign_origin_403(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": serve_wiki.SESSION_TOKEN},
                             headers={"Origin": "https://evil.example.com"})
        self.assertEqual(resp.status, 403)

    def test_origin_requires_exact_loopback_authority_and_port(self):
        for origin in (
            f"http://localhost.evil:{self.port}",
            f"http://localhost:{self.port + 1}",
            f"https://localhost:{self.port}",
        ):
            with self.subTest(origin=origin):
                resp, _ = self._post(
                    "/actions/candidate",
                    {"id": "c1", "_token": serve_wiki.SESSION_TOKEN},
                    headers={"Origin": origin},
                )
                self.assertEqual(resp.status, 403)

    def test_valid_post_redirects_with_flash(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": serve_wiki.SESSION_TOKEN})
        self.assertEqual(resp.status, 303)
        self.assertIn("flash=stub+ok", resp.getheader("Location"))

    def test_action_exception_has_fixed_private_failure_surface(self):
        secret = "private-answer-DO-NOT-LEAK"
        submitted = "submitted-private-body"
        logs = []

        def fail(_form):
            raise ValueError(f"bad path /private/vault/{secret}")

        original = serve_wiki.ACTIONS["/actions/candidate"]
        original_log_error = serve_wiki.Handler.log_error
        serve_wiki.ACTIONS["/actions/candidate"] = fail
        serve_wiki.Handler.log_error = lambda _self, fmt, *args: logs.append(fmt % args)
        try:
            resp, payload = self._post(
                "/actions/candidate",
                {
                    "id": submitted,
                    "_token": serve_wiki.SESSION_TOKEN,
                },
            )
        finally:
            serve_wiki.ACTIONS["/actions/candidate"] = original
            serve_wiki.Handler.log_error = original_log_error

        location = resp.getheader("Location")
        surface = "\n".join([location, payload.decode(), *logs])
        self.assertEqual(resp.status, 303)
        self.assertIn("action+failed+safely", location)
        self.assertIn("exception_class=ValueError", logs[0])
        self.assertNotIn(secret, surface)
        self.assertNotIn(submitted, surface)

    def test_invalid_typed_payload_is_fixed_303_not_500(self):
        original = serve_wiki.ACTIONS["/actions/candidate"]
        original_log_error = serve_wiki.Handler.log_error
        serve_wiki.ACTIONS["/actions/candidate"] = serve_wiki.act_candidate
        serve_wiki.Handler.log_error = lambda *_args: None
        try:
            resp, _ = self._post(
                "/actions/candidate",
                {
                    "id": "../../not-a-candidate",
                    "op": "dismiss",
                    "_token": serve_wiki.SESSION_TOKEN,
                },
            )
        finally:
            serve_wiki.ACTIONS["/actions/candidate"] = original
            serve_wiki.Handler.log_error = original_log_error
        self.assertEqual(resp.status, 303)
        self.assertIn("action+failed+safely", resp.getheader("Location"))

    def test_unknown_action_404(self):
        resp, _ = self._post("/actions/nope",
                             {"_token": serve_wiki.SESSION_TOKEN})
        self.assertEqual(resp.status, 404)

    def test_jobs_route_unknown_404(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/jobs/ffffffffffff.json")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    def test_flash_banner_renders_on_get(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/views/status?flash=hello+there")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('class="flash"', body)
        self.assertIn("hello there", body)

    def test_get_exception_has_fixed_private_failure_surface(self):
        secret = "GET-SECRET-private-path"
        logs = []
        original_builder = serve_wiki.VIEW_MAP.get("private-failure-test")
        original_log_error = serve_wiki.Handler.log_error

        def fail():
            raise RuntimeError(f"failed under /private/{secret}")

        serve_wiki.VIEW_MAP["private-failure-test"] = fail
        serve_wiki.Handler.log_error = lambda _self, fmt, *args: logs.append(fmt % args)
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request("GET", "/views/private-failure-test")
            resp = conn.getresponse()
            body = resp.read().decode()
            conn.close()
        finally:
            if original_builder is None:
                serve_wiki.VIEW_MAP.pop("private-failure-test", None)
            else:
                serve_wiki.VIEW_MAP["private-failure-test"] = original_builder
            serve_wiki.Handler.log_error = original_log_error
        surface = "\n".join([body, *logs])
        self.assertEqual(resp.status, 200)
        self.assertIn("temporarily unavailable", body)
        self.assertIn("exception_class=RuntimeError", logs[0])
        self.assertNotIn(secret, surface)

    def test_job_endpoint_converges_from_queued_to_succeeded(self):
        original = jobs.VAULT_ROOT
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            try:
                vault_paths._reset_process_binding_for_tests()
                vault = Path(tmp)
                (vault / "question-bank.md").write_text(
                    "# Questions\n\n## A: Origins\n- [ ] A1: Test?\n",
                    encoding="utf-8",
                )
                (vault / "state").mkdir()
                (vault / "state" / "rotation.json").write_text(
                    json.dumps({
                        "version": 1,
                        "current_pass": 1,
                        "pass_names": ["skeleton", "depth", "connections", "polish"],
                        "last_question_id": None,
                        "last_asked_at": None,
                        "questions_asked": 0,
                        "questions_answered": 0,
                        "next_question_id": None,
                        "focus_frequency": 4,
                    }) + "\n",
                    encoding="utf-8",
                )
                (vault / "state" / "coverage.json").write_text(
                    json.dumps({
                        "version": 1,
                        "last_updated": None,
                        "categories": {},
                    }) + "\n",
                    encoding="utf-8",
                )
                jobs.configure(vault)
                record = jobs.enqueue("compile", {"no_ai": True}, kick=False)

                def fetch():
                    conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                    conn.request("GET", f"/jobs/{record['id']}.json")
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                    conn.close()
                    return response.status, payload

                status, payload = fetch()
                self.assertEqual(status, 200)
                self.assertEqual(payload["state"], "queued")
                payload.update({
                    "state": "succeeded", "exit_code": 0,
                    "finished_at": jobs._now(), "updated_at": jobs._now(),
                    "payload_retained": False,
                })
                jobs._write_json(jobs._record_path(record["id"]), payload)
                _, converged = fetch()
                self.assertEqual(converged["state"], "succeeded")
                page = serve_wiki.layout("test", "body").decode()
                self.assertIn("state === 'queued'", page)
                self.assertIn("state === 'succeeded'", page)
            finally:
                vault_paths._reset_process_binding_for_tests()
                jobs.configure(original)


class SecondVoiceAckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_qp = qp.SECOND_VOICE_OFFERS_FILE
        self._orig_sw = serve_wiki.SECOND_VOICE_OFFERS_FILE
        self.offers = self.tmp / "sv.json"
        qp.SECOND_VOICE_OFFERS_FILE = self.offers
        serve_wiki.SECOND_VOICE_OFFERS_FILE = self.offers
        import datetime
        month = datetime.date.today().strftime("%Y-%m")
        self.offers.write_text(json.dumps({"version": 1, "offered": [
            {"key": "emma::first-memory", "person": "Emma", "month": month}]}))

    def tearDown(self):
        qp.SECOND_VOICE_OFFERS_FILE = self._orig_qp
        serve_wiki.SECOND_VOICE_OFFERS_FILE = self._orig_sw

    def test_ack_stamps_and_hides_card(self):
        card = serve_wiki._hub_card_second_voice()
        self.assertIsNotNone(card)
        self.assertIn("Got it", card["extra"])
        self.assertTrue(qp.acknowledge_second_voice_offer("emma::first-memory"))
        data = json.loads(self.offers.read_text())
        self.assertTrue(data["offered"][0]["acknowledged_at"])
        # Second ack is a no-op; the card is gone.
        self.assertFalse(qp.acknowledge_second_voice_offer("emma::first-memory"))
        self.assertIsNone(serve_wiki._hub_card_second_voice())

    def test_ack_unknown_key(self):
        self.assertFalse(qp.acknowledge_second_voice_offer("nope::nothing"))


class ActionUiTests(unittest.TestCase):
    def test_source_actions_page_has_all_forms(self):
        _, body = serve_wiki.source_actions_html("answers/A7.md")
        self.assertIn("/actions/reflect", body)
        self.assertIn("/actions/fix", body)
        self.assertIn("/actions/compile", body)
        self.assertIn('name="_token"', body)
        self.assertIn("answers/A7.md", body)

    def test_candidate_promote_requires_category(self):
        redirect, flash, job = serve_wiki.act_candidate(
            {"id": ["c1"], "op": ["promote"], "category": [""]})
        self.assertIsNone(job)
        self.assertIn("✗", flash)

    def test_artifact_slug_guard(self):
        redirect, flash, job = serve_wiki.act_artifact_final(
            {"slug": ["../escape"], "version": ["1"]})
        self.assertIn("✗", flash)
        self.assertIsNone(job)

    def test_artifact_actions_panel(self):
        panel = serve_wiki._artifact_actions_html("my-piece", 2, "hello", is_final=False)
        self.assertIn("/actions/artifact/save", panel)
        self.assertIn("/actions/artifact/revise", panel)
        self.assertIn("Mark v2 final", panel)
        self.assertIn("/actions/artifact/promote", panel)
        self.assertIn("/actions/artifact/delivered", panel)
        # A final version drops the mark-final button.
        panel_final = serve_wiki._artifact_actions_html("my-piece", 2, "hello", is_final=True)
        self.assertNotIn("Mark v2 final", panel_final)


if __name__ == "__main__":
    unittest.main()
