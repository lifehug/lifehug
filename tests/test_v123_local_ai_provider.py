"""v123 — fail-closed on-machine OpenAI-compatible provider (issue #57)."""

import contextlib
import io
import json
import socket
import sys
import tempfile
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
import classify_story  # noqa: E402
import lifehug as lh  # noqa: E402
import research_expand  # noqa: E402
import serve_wiki  # noqa: E402


@contextlib.contextmanager
def fake_openai_server(*, content="local answer", malformed=False, delay=0.0,
                       redirect_url=None, raw_chat_body=None, raw_models_body=None,
                       omit_content_length=False):
    state = {"gets": [], "posts": [], "payloads": [], "headers": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — stdlib handler API
            state["gets"].append(self.path)
            state["headers"].append(dict(self.headers))
            body = raw_models_body
            if body is None:
                body = json.dumps(
                    {"object": "list", "data": [{"id": "qwen-local"}]}
                ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if not omit_content_length:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 — stdlib handler API
            state["posts"].append(self.path)
            state["headers"].append(dict(self.headers))
            length = int(self.headers.get("Content-Length", "0"))
            state["payloads"].append(json.loads(self.rfile.read(length)))
            if redirect_url:
                self.send_response(307)
                self.send_header("Location", redirect_url)
                self.end_headers()
                return
            if delay:
                time.sleep(delay)
            if raw_chat_body is None:
                result = {"not_choices": True} if malformed else {
                    "choices": [{"message": {"content": content}}]
                }
                body = json.dumps(result).encode()
            else:
                body = raw_chat_body
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if not omit_content_length:
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
            status = aip.provider_status(probe=True)
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
            status = aip.provider_status(probe=True)
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

    def test_local_call_bypasses_a_bogus_proxy_in_a_real_request(self):
        with fake_openai_server() as (base_url, state), \
                mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                mock.patch.dict(aip.os.environ, {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "ALL_PROXY": "http://127.0.0.1:1",
                    "NO_PROXY": "",
                }, clear=True):
            self.assertEqual(aip.call_ai("private", "cloud-model"), "local answer")
        self.assertEqual(state["posts"], ["/v1/chat/completions"])

    def test_timeout_rejects_non_finite_values_before_network(self):
        for timeout in ("nan", "inf", "-inf", "1e309"):
            with self.subTest(timeout=timeout), \
                    mock.patch.object(
                        aip, "load_config",
                        return_value=local_config("http://127.0.0.1:11434/v1", timeout=timeout),
                    ), \
                    mock.patch.dict(aip.os.environ, {}, clear=True), \
                    mock.patch.object(aip, "_local_opener") as opener, \
                    self.assertRaises(aip.AIConfigurationError):
                aip.call_ai("private", "cloud-model")
            opener.assert_not_called()

    def test_url_and_authorization_controls_are_rejected_before_request(self):
        secret = "private-token"
        unsafe_configs = [
            local_config("http://127.0.0.1:11434/v1\r\nX-Injected: yes"),
            {**local_config("http://127.0.0.1:11434/v1"),
             "local_ai_api_key": f"{secret}\r\nX-Injected: yes"},
        ]
        for cfg in unsafe_configs:
            with self.subTest(cfg=sorted(cfg)), \
                    mock.patch.object(aip, "load_config", return_value=cfg), \
                    mock.patch.dict(aip.os.environ, {}, clear=True), \
                    mock.patch.object(aip, "_local_opener") as opener, \
                    self.assertRaises(aip.AIConfigurationError) as caught:
                aip.call_ai("private", "cloud-model")
            self.assertNotIn(secret, str(caught.exception))
            opener.assert_not_called()

    def test_request_construction_and_read_failures_are_typed_and_private(self):
        secret = "source-or-key-must-never-escape"
        cfg = local_config("http://127.0.0.1:11434/v1")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(
                    aip.urllib.request, "Request", side_effect=ValueError(secret)
                ), \
                self.assertRaises(aip.AIConfigurationError) as construction:
            aip.call_ai(secret, "cloud-model")
        self.assertNotIn(secret, str(construction.exception))

        response = mock.MagicMock()
        response.headers = {}
        response.read.side_effect = ValueError(secret)
        context = mock.MagicMock()
        context.__enter__.return_value = response
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_local_opener") as opener, \
                self.assertRaises(aip.AIResponseError) as read_failure:
            opener.return_value.open.return_value = context
            aip.call_ai(secret, "cloud-model")
        self.assertNotIn(secret, str(read_failure.exception))

    def test_chat_body_content_length_and_chunked_reads_are_bounded(self):
        oversized = b"x" * 257
        for omit_length in (False, True):
            with self.subTest(omit_content_length=omit_length), \
                    fake_openai_server(
                        raw_chat_body=oversized,
                        omit_content_length=omit_length,
                    ) as (base_url, _state), \
                    mock.patch.object(aip, "MAX_CHAT_RESPONSE_BYTES", 64), \
                    mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                    mock.patch.dict(aip.os.environ, {}, clear=True), \
                    self.assertRaises(aip.AIResponseError) as caught:
                aip.call_ai("private", "cloud-model")
            self.assertEqual(caught.exception.status, "response_too_large")
            self.assertLessEqual(caught.exception.response_bytes or 0, len(oversized))

    def test_models_body_content_length_and_chunked_reads_are_bounded(self):
        for omit_length in (False, True):
            with self.subTest(omit_content_length=omit_length), \
                    fake_openai_server(
                        raw_models_body=b"x" * 257,
                        omit_content_length=omit_length,
                    ) as (base_url, _state), \
                    mock.patch.object(aip, "MAX_MODELS_RESPONSE_BYTES", 64), \
                    mock.patch.object(aip, "load_config", return_value=local_config(base_url)), \
                    mock.patch.dict(aip.os.environ, {}, clear=True):
                status = aip.provider_status(probe=True)
            self.assertFalse(status.ready)
            self.assertIn("response_too_large", status.detail)


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

    def test_openclaw_bypasses_real_proxy_without_leaking_request(self):
        secret = "openclaw-private-prompt"
        token = "openclaw-private-token"
        for explicit in (True, False):
            cfg = {"ai_timeout_seconds": "1"}
            if explicit:
                cfg["ai_provider"] = "openclaw"
            with self.subTest(explicit=explicit), \
                    fake_openai_server() as (gateway_url, gateway_state), \
                    fake_openai_server() as (proxy_url, proxy_state), \
                    mock.patch.object(aip, "load_config", return_value=cfg), \
                    mock.patch.object(
                        aip, "_openclaw_gateway", return_value=(gateway_url, token)
                    ), \
                    mock.patch.dict(aip.os.environ, {
                        "HTTP_PROXY": proxy_url,
                        "HTTPS_PROXY": proxy_url,
                        "ALL_PROXY": proxy_url,
                        "NO_PROXY": "",
                    }, clear=True):
                result = aip.call_ai(secret, "claude-sonnet-5")
            self.assertEqual(result, "local answer")
            self.assertEqual(gateway_state["posts"], ["/v1/chat/completions"])
            self.assertEqual(proxy_state["posts"], [])
            self.assertEqual(proxy_state["gets"], [])
            self.assertEqual(proxy_state["headers"], [])

    def test_openclaw_refuses_redirect_without_leaking_to_sink(self):
        secret = "openclaw-private-prompt"
        token = "openclaw-private-token"
        for explicit in (True, False):
            cfg = {"ai_timeout_seconds": "1"}
            if explicit:
                cfg["ai_provider"] = "openclaw"
            else:
                cfg["anthropic_api_key"] = "synthetic-cloud-key"
            with self.subTest(explicit=explicit), \
                    fake_openai_server() as (sink_url, sink_state), \
                    fake_openai_server(
                        redirect_url=f"{sink_url}/chat/completions"
                    ) as (gateway_url, gateway_state), \
                    mock.patch.object(aip, "load_config", return_value=cfg), \
                    mock.patch.object(
                        aip, "_openclaw_gateway", return_value=(gateway_url, token)
                    ), \
                    mock.patch.dict(aip.os.environ, {}, clear=True), \
                    mock.patch.object(
                        aip, "_call_anthropic", return_value="auto fallback"
                    ) as anthropic:
                if explicit:
                    with self.assertRaises(aip.AIUnavailableError):
                        aip.call_ai(secret, "claude-sonnet-5")
                    anthropic.assert_not_called()
                else:
                    self.assertEqual(
                        aip.call_ai(secret, "claude-sonnet-5"), "auto fallback"
                    )
                    anthropic.assert_called_once()
            self.assertEqual(gateway_state["posts"], ["/v1/chat/completions"])
            self.assertEqual(sink_state["posts"], [])
            self.assertEqual(sink_state["gets"], [])
            self.assertEqual(sink_state["headers"], [])

    def test_openclaw_rejects_nonloopback_destination_before_network(self):
        cfg = {"ai_provider": "openclaw", "ai_timeout_seconds": "1"}
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.object(
                    aip, "_openclaw_gateway",
                    return_value=("http://192.0.2.10:18789/v1", "token"),
                ), \
                mock.patch.object(aip, "_local_opener") as opener, \
                self.assertRaises(aip.AIConfigurationError):
            aip.call_ai("private", "claude-sonnet-5")
        opener.assert_not_called()

    def test_openclaw_config_rejects_invalid_ports_and_token_controls(self):
        unsafe_gateways = [
            {"gateway": {"port": 0, "auth": {"token": "token"}}},
            {"gateway": {"port": 65536, "auth": {"token": "token"}}},
            {"gateway": {"port": "not-a-port", "auth": {"token": "token"}}},
            {"gateway": {"port": 18789.5, "auth": {"token": "token"}}},
            {"gateway": {"port": 18789, "auth": {"token": "token\nsecret"}}},
        ]
        for payload in unsafe_gateways:
            with self.subTest(payload=payload), \
                    mock.patch("builtins.open", mock.mock_open(
                        read_data=json.dumps(payload)
                    )), \
                    self.assertRaises(aip.AIConfigurationError):
                aip._openclaw_gateway()

    def test_config_read_failure_is_typed_fail_closed(self):
        secret = "config-parser-secret-context"
        with mock.patch.object(aip, "load_config", side_effect=ValueError(secret)), \
                mock.patch.dict(aip.os.environ, {"ANTHROPIC_API_KEY": "cloud"}, clear=True), \
                mock.patch.object(aip, "_call_openclaw") as openclaw, \
                mock.patch.object(aip, "_call_anthropic") as anthropic, \
                self.assertRaises(aip.AIConfigurationError) as caught:
            aip.call_ai("private", "claude-sonnet-5")
        self.assertNotIn(secret, str(caught.exception))
        openclaw.assert_not_called()
        anthropic.assert_not_called()
        with mock.patch.object(aip, "load_config", side_effect=ValueError(secret)):
            status = aip.provider_status(probe=True)
        self.assertEqual(status.provider, "invalid")
        self.assertFalse(status.ready)
        self.assertNotIn(secret, status.detail)

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

    def test_provider_discovery_does_not_probe_unless_requested(self):
        cfg = local_config("http://127.0.0.1:11434/v1")
        with mock.patch.object(aip, "load_config", return_value=cfg), \
                mock.patch.dict(aip.os.environ, {}, clear=True), \
                mock.patch.object(aip, "_local_opener") as local_opener:
            status = aip.provider_status()
        self.assertTrue(status.ready)
        self.assertIn("not probed", status.detail)
        local_opener.assert_not_called()


class FailureRedactionTests(unittest.TestCase):
    def test_classifier_failure_and_captured_scheduled_report_exclude_response(self):
        secret = "PRIVATE_MODEL_OUTPUT_IN_SCHEDULED_REPORT"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.md"
            source.write_text("---\ntype: manual_story\n---\nSynthetic story.\n", encoding="utf-8")
            with mock.patch.object(aip, "call_ai", return_value=secret), \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                result = classify_story.classify_file(
                    source, "synthetic-model", skip_candidates=True
                )
        scheduled_report = "## Classification\n\n```\n" + errors.getvalue() + "\n```"
        self.assertEqual(result, 1)
        self.assertNotIn(secret, scheduled_report)
        self.assertIn("failure=AIResponseError", scheduled_report)
        self.assertIn(f"response_bytes={len(secret)}", scheduled_report)

    def test_research_expansion_parse_failure_excludes_raw_response(self):
        secret = "PRIVATE_RESEARCH_MODEL_OUTPUT"
        args = mock.Mock(
            output="essay", dry_run=False, prompt=False, from_response=None,
            force=True, model="synthetic-model",
        )
        with mock.patch.object(research_expand, "load_config", return_value={}), \
                mock.patch.object(research_expand, "load_neighborhoods", return_value={}), \
                mock.patch.object(research_expand, "load_mission", return_value={}), \
                mock.patch.object(research_expand, "load_answers", return_value=[]), \
                mock.patch.object(research_expand, "call_ai", return_value=secret), \
                contextlib.redirect_stderr(io.StringIO()) as errors, \
                contextlib.redirect_stdout(io.StringIO()):
            result = research_expand._run_expansion(
                args, "Synthetic topic", "theme", "synthetic", "Synthetic source"
            )
        self.assertEqual(result, 1)
        self.assertNotIn(secret, errors.getvalue())
        self.assertIn("response_bytes", errors.getvalue())

    def test_model_callsite_guard_rejects_raw_exception_or_response_logging(self):
        guarded = [
            "research_expand.py",
            "classify_story.py",
            "connectors/dossier.py",
            "entity_roster.py",
            "wiki_compile.py",
        ]
        for relative in guarded:
            with self.subTest(relative=relative):
                source = (SYSTEM / relative).read_text(encoding="utf-8")
                self.assertNotIn("raw_response[:", source)
                self.assertNotRegex(source, r"str\(exc\)|\{exc[!}:]")


if __name__ == "__main__":
    unittest.main()
