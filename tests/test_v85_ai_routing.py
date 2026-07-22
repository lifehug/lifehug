"""v85 — resilient AI routing in call_ai (gateway → retry → SDK fall-through).

Pins the behavior promised in issue #34's fix: the gateway's deterministic
'Agent couldn't generate a response' sentinel is never retried and falls
straight through to the Anthropic SDK; transient gateway failures retry up
to 3 times, then fall through; without an API key, the original gateway
error surfaces (not the missing-key complaint). Also pins the classifier
default model on the current Sonnet alias.
"""

import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
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


rex = load("research_expand")

SENTINEL = "⚠️ Agent couldn't generate a response."


class _FakeResponse:
    def __init__(self, content: str):
        self._body = json.dumps(
            {"choices": [{"message": {"content": content}}]}).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeSDKClient:
    class _Messages:
        def create(self, **kwargs):
            block = mock.Mock()
            block.text = "sdk says hi"
            resp = mock.Mock()
            resp.content = [block]
            return resp

    messages = _Messages()


class CallAIRoutingTests(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(rex, "_openclaw_gateway",
                              return_value=("http://fake:1/v1", "tok")),
            mock.patch("time.sleep"),
            mock.patch.dict("os.environ", {"LIFEHUG_AI_TIMEOUT": "5"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_sentinel_is_not_retried_and_falls_through_to_sdk(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(SENTINEL)) as urlopen, \
                mock.patch.object(rex, "get_client",
                                  return_value=_FakeSDKClient()), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            result = rex.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(result, "sdk says hi")
        self.assertEqual(urlopen.call_count, 1)  # deterministic → no retries

    def test_transient_failure_retries_then_falls_through(self):
        err = urllib.error.URLError("boom")
        with mock.patch("urllib.request.urlopen", side_effect=err) as urlopen, \
                mock.patch.object(rex, "get_client",
                                  return_value=_FakeSDKClient()), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            result = rex.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(result, "sdk says hi")
        self.assertEqual(urlopen.call_count, 3)  # transient → retried

    def test_no_key_surfaces_gateway_error_not_missing_key(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse(SENTINEL)), \
                mock.patch.object(rex, "get_client",
                                  side_effect=RuntimeError("no key")), \
                mock.patch("sys.stdout", new_callable=io.StringIO), \
                self.assertRaises(RuntimeError) as ctx:
            rex.call_ai("prompt", "claude-sonnet-5")
        self.assertIn("generate", str(ctx.exception))  # the gateway error

    def test_gateway_success_never_touches_sdk(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResponse("gateway says hi")), \
                mock.patch.object(rex, "get_client") as get_client:
            result = rex.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(result, "gateway says hi")
        get_client.assert_not_called()

    def test_no_gateway_uses_sdk_directly(self):
        with mock.patch.object(rex, "_openclaw_gateway", return_value=None), \
                mock.patch.object(rex, "get_client",
                                  return_value=_FakeSDKClient()):
            result = rex.call_ai("prompt", "claude-sonnet-5")
        self.assertEqual(result, "sdk says hi")


class KimiRoutingTests(unittest.TestCase):
    """v113 — model-explicit Kimi routing: a kimi/moonshot/k3 model name sends
    the call to the Kimi OpenAI-compatible endpoint, bypassing the gateway
    remap and the Anthropic SDK; no key → a clear setup error."""

    def test_kimi_model_bypasses_gateway_and_sdk(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.headers.get("Authorization")
            return _FakeResponse("kimi says hi")

        with mock.patch.object(rex, "_openclaw_gateway",
                               return_value=("http://fake:1/v1", "tok")), \
                mock.patch.object(rex, "get_client") as get_client, \
                mock.patch.dict("os.environ", {"KIMI_API_KEY": "kimi-key-123"}), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = rex.call_ai("prompt", "kimi-for-coding")
        self.assertEqual(result, "kimi says hi")
        self.assertEqual(captured["url"],
                         "https://api.kimi.com/coding/v1/chat/completions")
        self.assertEqual(captured["auth"], "Bearer kimi-key-123")
        get_client.assert_not_called()  # Anthropic SDK never touched

    def test_kimi_key_falls_back_to_config(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(rex, "load_config",
                                  return_value={"kimi_api_key": "cfg-key"}):
            self.assertEqual(rex._kimi_key(), "cfg-key")

    def test_kimi_no_key_raises_clear_error(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(rex, "load_config", return_value={}), \
                self.assertRaises(RuntimeError) as ctx:
            rex.call_ai("prompt", "kimi-for-coding")
        self.assertIn("KIMI_API_KEY", str(ctx.exception))

    def test_model_prefixes(self):
        for kimi_model in ("kimi-for-coding", "kimi-for-coding-highspeed",
                           "k3", "moonshot-v1-8k", "Kimi-K2"):
            with self.subTest(model=kimi_model):
                self.assertTrue(rex.model_is_kimi(kimi_model))
        for other in ("claude-sonnet-5", "gpt-4o", ""):
            with self.subTest(model=other):
                self.assertFalse(rex.model_is_kimi(other))

    def test_kimi_base_url_override(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResponse("ok")

        with mock.patch.dict("os.environ", {"KIMI_API_KEY": "k"}), \
                mock.patch.object(rex, "load_config",
                                  return_value={"kimi_api_key": "k",
                                                "kimi_base_url": "https://api.moonshot.cn/v1"}), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            rex.call_ai("prompt", "moonshot-v1-8k")
        self.assertEqual(captured["url"],
                         "https://api.moonshot.cn/v1/chat/completions")


class DefaultModelTests(unittest.TestCase):
    def test_classifier_default_is_current_sonnet(self):
        # v85 reverted an unverified downgrade to claude-sonnet-4-6;
        # claude-sonnet-5 is the active current Sonnet alias.
        cls = load("classify_story")
        self.assertEqual(cls.DEFAULT_MODEL, "claude-sonnet-5")


if __name__ == "__main__":
    unittest.main()
