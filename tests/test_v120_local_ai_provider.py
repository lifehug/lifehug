"""v120 — fail-closed on-machine OpenAI-compatible provider (issue #57)."""

import contextlib
import io
import json
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import ai_provider as aip  # noqa: E402
import lifehug as lh  # noqa: E402
import serve_wiki  # noqa: E402


@contextlib.contextmanager
def fake_openai_server(*, content="local answer", malformed=False, delay=0.0,
                       redirect_url=None):
    state = {"gets": [], "posts": [], "payloads": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — stdlib handler API
            state["gets"].append(self.path)
            body = json.dumps({"object": "list", "data": [{"id": "qwen-local"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 — stdlib handler API
            state["posts"].append(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            state["payloads"].append(json.loads(self.rfile.read(length)))
            if redirect_url:
                self.send_response(307)
                self.send_header("Location", redirect_url)
                self.end_headers()
                return
            if delay:
                time.sleep(delay)
            result = {"not_choices": True} if malformed else {
                "choices": [{"message": {"content": content}}]
            }
            body = json.dumps(result).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def local_config(base_url: str, *, timeout: str = "1") -> dict[str, str]:
    return {
        "ai_provider": "local",
        "local_ai_base_url": base_url,
        "local_ai_model": "qwen-local",
        "local_ai_timeout_seconds": timeout,
    }


class LocalProviderTests(unittest.TestCase):
    def test_routes_status_and_chat_to_configured_local_model(self):
        with fake_openai_server() as (base_url, state), \
                mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_call_anthropic") as anthropic:
            status = aip.provider_status()
            result = aip.call_ai("private source text", "claude-sonnet-5")
        self.assertTrue(status.ready)
        self.assertEqual(status.provider, "local-openai")
        self.assertEqual(status.model, "qwen-local")
        self.assertEqual(result, "local answer")
        self.assertEqual(state["gets"], ["/v1/models"])
        self.assertEqual(state["posts"], ["/v1/chat/completions"])
        self.assertEqual(state["payloads"][0]["model"], "qwen-local")
        anthropic.assert_not_called()

    def test_ai_status_reports_provider_model_and_non_mutating_readiness(self):
        with fake_openai_server() as (base_url, state), \
                mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = lh.cmd_ai_status(None)
        self.assertEqual(result, 0)
        self.assertIn("AI provider: local-openai", output.getvalue())
        self.assertIn("AI model: qwen-local", output.getvalue())
        self.assertIn("AI readiness: ready", output.getvalue())
        self.assertEqual(state["gets"], ["/v1/models"])
        self.assertEqual(state["posts"], [])

    def test_timeout_is_bounded_and_does_not_fall_through(self):
        secret = "source-body-must-not-appear"
        with fake_openai_server(delay=0.2) as (base_url, _state), \
                mock.patch.object(aip, "load_config",
                                  return_value=local_config(base_url, timeout="0.03")), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIUnavailableError) as caught:
            aip.call_ai(secret, "cloud-model")
        self.assertNotIn(secret, str(caught.exception))
        anthropic.assert_not_called()

    def test_malformed_response_is_metadata_only(self):
        secret = "another-private-source-body"
        with fake_openai_server(malformed=True) as (base_url, _state), \
                mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                self.assertRaises(aip.AIResponseError) as caught:
            aip.call_ai(secret, "cloud-model")
        self.assertIn("malformed", str(caught.exception))
        self.assertNotIn(secret, str(caught.exception))

    def test_unavailable_server_becomes_agent_task_without_cloud_leak(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        cfg = local_config(f"http://127.0.0.1:{port}/v1", timeout="0.05")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {"ANTHROPIC_API_KEY": "cloud-key"}, clear=True), \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                mock.patch.object(aip, "_call_openclaw") as openclaw, \
                mock.patch.object(aip, "_call_kimi") as kimi:
            status = aip.provider_status()
            self.assertFalse(status.ready)
            self.assertEqual(status.provider, "local-openai")
            self.assertIsNone(aip.ai_available())
            with self.assertRaises(aip.AIUnavailableError):
                aip.call_ai("private", "cloud-model")
        anthropic.assert_not_called()
        openclaw.assert_not_called()
        kimi.assert_not_called()

    def test_non_loopback_rejected_before_any_network_or_fallback(self):
        cfg = local_config("http://192.0.2.10:11434/v1")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {"ANTHROPIC_API_KEY": "cloud-key"}, clear=True), \
                mock.patch("urllib.request.urlopen") as urlopen, \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIConfigurationError):
            aip.call_ai("private", "cloud-model")
        urlopen.assert_not_called()
        anthropic.assert_not_called()

    def test_local_transport_refuses_redirect_without_fallback(self):
        with fake_openai_server() as (sink_url, sink_state), \
                fake_openai_server(redirect_url=f"{sink_url}/chat/completions") as (
                    base_url, source_state,
                ), \
                mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                mock.patch.dict(aip.os.environ,
                                {"ANTHROPIC_API_KEY": "cloud-key"}, clear=True), \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIUnavailableError) as caught:
            aip.call_ai("private", "cloud-model")
        self.assertIn("HTTP failure (307)", str(caught.exception))
        self.assertEqual(source_state["posts"], ["/v1/chat/completions"])
        self.assertEqual(sink_state["posts"], [])
        anthropic.assert_not_called()

    def test_local_transport_passes_empty_proxy_handler(self):
        real_build_opener = aip.urllib.request.build_opener
        with mock.patch.object(
            aip.urllib.request, "build_opener", wraps=real_build_opener
        ) as build_opener:
            opener = aip._local_opener()
        proxy_handlers = [handler for handler in build_opener.call_args.args
                          if isinstance(handler, aip.urllib.request.ProxyHandler)]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})
        self.assertTrue(any(
            isinstance(handler, aip._NoRedirectHandler) for handler in opener.handlers
        ))


class SharedRoutingTests(unittest.TestCase):
    def test_every_model_backed_surface_imports_authoritative_provider(self):
        surfaces = [
            "artifact.py",
            "classify_story.py",
            "connectors/dossier.py",
            "entity_roster.py",
            "mirror.py",
            "research_expand.py",
            "wiki_compile.py",
        ]
        for relative in surfaces:
            with self.subTest(surface=relative):
                text = (SYSTEM / relative).read_text(encoding="utf-8")
                self.assertIn("from ai_provider import", text)
                self.assertNotRegex(
                    text, r"from research_expand import[^\n]*\bcall_ai\b"
                )

    def test_explicit_openclaw_never_falls_through(self):
        cfg = {"ai_provider": "openclaw", "anthropic_api_key": "cloud-key"}
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip, "_call_openclaw",
                    side_effect=aip.AIUnavailableError("openclaw is unavailable"),
                ), \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIUnavailableError):
            aip.call_ai("private", "claude-sonnet-5")
        anthropic.assert_not_called()

    def test_explicit_anthropic_bypasses_openclaw(self):
        cfg = {"ai_provider": "anthropic", "anthropic_api_key": "cloud-key"}
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_call_anthropic", return_value="answer") as anthropic, \
                mock.patch.object(aip, "_call_openclaw") as openclaw:
            self.assertEqual(aip.call_ai("private", "claude-sonnet-5"), "answer")
        anthropic.assert_called_once()
        openclaw.assert_not_called()

    def test_viewer_route_discovery_never_performs_readiness_network_io(self):
        cfg = local_config("http://127.0.0.1:11434/v1")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch("urllib.request.urlopen") as urlopen, \
                mock.patch.object(aip, "_local_opener") as local_opener:
            self.assertEqual(serve_wiki._ai_route(), "local-openai")
        urlopen.assert_not_called()
        local_opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
