"""Tests for the viewer write actions (v101): POST auth, jobs, second-voice
acknowledge, and the action UI surfaces."""

import http.client
import json
import sys
import tempfile
import threading
import time
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

    def test_post_with_foreign_origin_403(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": serve_wiki.SESSION_TOKEN},
                             headers={"Origin": "https://evil.example.com"})
        self.assertEqual(resp.status, 403)

    def test_valid_post_redirects_with_flash(self):
        resp, _ = self._post("/actions/candidate",
                             {"id": "c1", "_token": serve_wiki.SESSION_TOKEN})
        self.assertEqual(resp.status, 303)
        self.assertIn("flash=stub+ok", resp.getheader("Location"))

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


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = jobs.JOBS_DIR
        jobs.JOBS_DIR = self.tmp / "jobs"

    def tearDown(self):
        jobs.JOBS_DIR = self._orig

    def _wait(self, job_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = jobs.load_job(job_id)
            if record and record["status"] != "running":
                return record
            time.sleep(0.1)
        self.fail("job never finished")

    def test_job_lifecycle_success(self):
        record = jobs.start_job("test", [sys.executable, "-c", "print('hi there')"])
        self.assertEqual(record["status"], "running")
        done = self._wait(record["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["rc"], 0)
        self.assertIn("hi there", done["tail"])

    def test_job_failure_recorded(self):
        record = jobs.start_job("test", [sys.executable, "-c", "import sys; sys.exit(3)"])
        done = self._wait(record["id"])
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["rc"], 3)

    def test_job_stdin_delivery_and_cleanup(self):
        record = jobs.start_job(
            "test", [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"],
            stdin_text="quiet words")
        done = self._wait(record["id"])
        self.assertIn("QUIET WORDS", done["tail"])
        self.assertFalse((jobs.JOBS_DIR / f"{record['id']}.stdin").exists())

    def test_load_job_rejects_bad_ids(self):
        self.assertIsNone(jobs.load_job("../../etc/passwd"))
        self.assertIsNone(jobs.load_job(""))
        self.assertIsNone(jobs.load_job("SHOUTY"))


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
