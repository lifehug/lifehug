#!/usr/bin/env python3
"""Authoritative AI provider selection and transport for Lifehug.

All model-backed Loop surfaces use :func:`call_ai`.  The local OpenAI-
compatible route is deliberately fail-closed: once selected, an invalid or
unavailable endpoint never falls through to a network provider with the
owner's source material.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from typing import NamedTuple
from urllib.parse import urlsplit

from lifehug_core import load_config

DEFAULT_AI_TIMEOUT_SECONDS = 600.0
DEFAULT_STATUS_MODEL = "claude-sonnet-5"
OPENCLAW_MODEL = "openclaw/default"
KIMI_MODEL_PREFIXES = ("kimi", "moonshot", "k3")
KIMI_DEFAULT_MODEL = "kimi-for-coding"
KIMI_DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"


class AIProviderError(RuntimeError):
    """Base error whose messages contain metadata only, never model content."""


class AIConfigurationError(AIProviderError):
    """The selected provider is configured unsafely or incompletely."""


class AIUnavailableError(AIProviderError):
    """The selected provider cannot currently accept a model call."""


class AIResponseError(AIProviderError):
    """The provider returned an unusable response."""


class ProviderStatus(NamedTuple):
    provider: str
    model: str
    ready: bool
    detail: str


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTP error instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _local_opener():
    """Local-only transport: ignore proxy env vars and refuse redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )


def _config() -> dict[str, str]:
    try:
        return load_config()
    except Exception:  # noqa: BLE001 — status/calls remain safely keyless
        return {}


def _setting(cfg: dict[str, str], env_name: str, config_name: str) -> str:
    return str(os.environ.get(env_name) or cfg.get(config_name) or "").strip()


def _positive_timeout(raw: str, *, field: str, default: float | None = None) -> float:
    if not raw and default is not None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AIConfigurationError(f"{field} must be a positive number") from None
    if value <= 0:
        raise AIConfigurationError(f"{field} must be a positive number")
    return value


def _truthy(raw: str) -> bool:
    return raw.lower() in {"1", "true", "yes", "on"}


def model_is_kimi(model: str) -> bool:
    """Kimi stays model-explicit unless ``ai_provider: kimi`` is selected."""
    return (model or "").lower().startswith(KIMI_MODEL_PREFIXES)


def _kimi_key(cfg: dict[str, str] | None = None) -> str | None:
    cfg = cfg if cfg is not None else _config()
    return _setting(cfg, "KIMI_API_KEY", "kimi_api_key") or None


def _anthropic_key(cfg: dict[str, str] | None = None) -> str | None:
    cfg = cfg if cfg is not None else _config()
    return _setting(cfg, "ANTHROPIC_API_KEY", "anthropic_api_key") or None


def _anthropic_sdk_available() -> bool:
    try:
        return importlib.util.find_spec("anthropic") is not None
    except (ImportError, ValueError):
        return False


def _openclaw_gateway() -> tuple[str, str] | None:
    """Return ``(base_url, token)`` when OpenClaw is locally configured."""
    cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        gateway = cfg.get("gateway", {})
        token = str(gateway.get("auth", {}).get("token", "")).strip()
        if token:
            port = int(gateway.get("port", 18789))
            return f"http://localhost:{port}/v1", token
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return None


def _provider_choice(requested_model: str, cfg: dict[str, str]) -> str:
    explicit = _setting(cfg, "LIFEHUG_AI_PROVIDER", "ai_provider").lower() or "auto"
    aliases = {"local-openai": "local", "sdk-key": "anthropic", "gateway": "openclaw"}
    explicit = aliases.get(explicit, explicit)
    if explicit not in {"auto", "local", "openclaw", "kimi", "anthropic"}:
        raise AIConfigurationError(
            "ai_provider must be auto, local, openclaw, kimi, or anthropic"
        )
    if explicit != "auto":
        return explicit
    # Merely defining the local route opts into its fail-closed boundary.
    if (_setting(cfg, "LIFEHUG_LOCAL_AI_BASE_URL", "local_ai_base_url") or
            _setting(cfg, "LIFEHUG_LOCAL_AI_MODEL", "local_ai_model")):
        return "local"
    if model_is_kimi(requested_model):
        return "kimi"
    if _openclaw_gateway() is not None:
        return "openclaw"
    if _anthropic_key(cfg):
        return "anthropic"
    return "agent-task"


def _is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validated_base_url(base_url: str, *, allow_non_loopback: bool) -> str:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port  # Force validation of a malformed port.
    except ValueError:
        raise AIConfigurationError("local_ai_base_url is not a valid URL") from None
    del port
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AIConfigurationError("local_ai_base_url must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AIConfigurationError(
            "local_ai_base_url cannot contain credentials, a query, or a fragment"
        )
    if not allow_non_loopback and not _is_loopback_host(parsed.hostname):
        raise AIConfigurationError(
            "local_ai_base_url is not loopback; set local_ai_allow_non_loopback: true "
            "only after explicitly accepting that source material will leave this machine"
        )
    return base_url.rstrip("/")


def _local_settings(cfg: dict[str, str]) -> tuple[str, str, float, str | None]:
    base_url = _setting(cfg, "LIFEHUG_LOCAL_AI_BASE_URL", "local_ai_base_url")
    model = _setting(cfg, "LIFEHUG_LOCAL_AI_MODEL", "local_ai_model")
    timeout_raw = _setting(cfg, "LIFEHUG_LOCAL_AI_TIMEOUT", "local_ai_timeout_seconds")
    if not base_url:
        raise AIConfigurationError("local_ai_base_url must be configured")
    if not model:
        raise AIConfigurationError("local_ai_model must be configured")
    if not timeout_raw:
        raise AIConfigurationError("local_ai_timeout_seconds must be configured")
    allow_remote = _truthy(
        _setting(cfg, "LIFEHUG_LOCAL_AI_ALLOW_NON_LOOPBACK", "local_ai_allow_non_loopback")
    )
    base_url = _validated_base_url(base_url, allow_non_loopback=allow_remote)
    timeout = _positive_timeout(timeout_raw, field="local_ai_timeout_seconds")
    key = _setting(cfg, "LIFEHUG_LOCAL_AI_API_KEY", "local_ai_api_key") or None
    return base_url, model, timeout, key


def _global_timeout(cfg: dict[str, str]) -> float:
    raw = _setting(cfg, "LIFEHUG_AI_TIMEOUT", "ai_timeout_seconds")
    return _positive_timeout(
        raw, field="ai_timeout_seconds", default=DEFAULT_AI_TIMEOUT_SECONDS
    )


def _decode_chat_response(body: bytes, provider: str) -> str:
    try:
        result = json.loads(body)
        content = result["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise AIResponseError(f"{provider} returned a malformed chat completion") from None
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError(f"{provider} returned an empty chat completion")
    return content


def _openai_compatible_call(
    *,
    provider: str,
    base_url: str,
    model: str,
    prompt: str,
    timeout: float,
    api_key: str | None,
    max_tokens: int,
    local_transport: bool = False,
) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions", data=payload, headers=headers
    )
    try:
        if local_transport:
            response_context = _local_opener().open(request, timeout=timeout)
        else:
            response_context = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
        with response_context as response:
            return _decode_chat_response(response.read(), provider)
    except AIResponseError:
        raise
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise AIUnavailableError(f"{provider} HTTP failure ({code})") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise AIUnavailableError(f"{provider} is unavailable") from None


def _call_local(prompt: str, cfg: dict[str, str]) -> str:
    base_url, model, timeout, key = _local_settings(cfg)
    return _openai_compatible_call(
        provider="local-openai",
        base_url=base_url,
        model=model,
        prompt=prompt,
        timeout=timeout,
        api_key=key,
        max_tokens=4096,
        local_transport=True,
    )


def _call_kimi(prompt: str, model: str, timeout: float, cfg: dict[str, str]) -> str:
    key = _kimi_key(cfg)
    if not key:
        raise AIUnavailableError(
            "Kimi is selected but no key is configured (KIMI_API_KEY or kimi_api_key)"
        )
    base_url = _setting(cfg, "KIMI_BASE_URL", "kimi_base_url") or KIMI_DEFAULT_BASE_URL
    try:
        max_tokens = int(cfg.get("kimi_max_tokens") or 16384)
    except (TypeError, ValueError):
        max_tokens = 16384
    last_error: AIProviderError | None = None
    for attempt in (1, 2):
        try:
            return _openai_compatible_call(
                provider="kimi",
                base_url=base_url,
                model=model,
                prompt=prompt,
                timeout=timeout,
                api_key=key,
                max_tokens=max_tokens,
            )
        except (AIUnavailableError, AIResponseError) as exc:
            last_error = exc
            if attempt == 1:
                print("  ↻ kimi call failed; retrying (1/2)")
    raise last_error or AIUnavailableError("kimi is unavailable")


def _call_openclaw(prompt: str, timeout: float) -> str:
    gateway = _openclaw_gateway()
    if gateway is None:
        raise AIUnavailableError("OpenClaw is not configured")
    base_url, token = gateway
    last_error: AIProviderError | None = None
    for attempt in range(1, 4):
        try:
            content = _openai_compatible_call(
                provider="openclaw",
                base_url=base_url,
                model=OPENCLAW_MODEL,
                prompt=prompt,
                timeout=timeout,
                api_key=token,
                max_tokens=4096,
            )
            if "Agent couldn’t generate" in content or "Agent couldn't generate" in content:
                raise AIResponseError("openclaw rejected the structured response")
            return content
        except AIResponseError:
            raise
        except AIUnavailableError as exc:
            last_error = exc
            if attempt < 3:
                print(f"  ↻ openclaw call failed; retrying ({attempt}/3)")
                time.sleep(10)
    raise last_error or AIUnavailableError("openclaw is unavailable")


def get_anthropic_client(cfg: dict[str, str] | None = None):
    """Build the optional Anthropic client without ever terminating Python."""
    cfg = cfg if cfg is not None else _config()
    key = _anthropic_key(cfg)
    if not key:
        raise AIUnavailableError(
            "Anthropic is selected but no key is configured "
            "(ANTHROPIC_API_KEY or anthropic_api_key)"
        )
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        raise AIUnavailableError(
            "Anthropic is selected but its optional SDK is not installed"
        ) from None
    return anthropic.Anthropic(api_key=key)


def _call_anthropic(prompt: str, model: str, cfg: dict[str, str]):
    client = get_anthropic_client(cfg)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        content = response.content[0].text if response.content else ""
    except (AttributeError, IndexError, TypeError):
        content = ""
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError("anthropic returned an empty completion")
    return content


def call_ai(prompt: str, model: str) -> str:
    """Call the selected provider and return response text.

    ``local`` is exclusive and fail-closed.  ``auto`` preserves the historical
    OpenClaw-to-Anthropic fallback, while Kimi remains model-explicit.
    """
    cfg = _config()
    provider = _provider_choice(model, cfg)
    if provider == "local":
        return _call_local(prompt, cfg)
    if provider == "kimi":
        kimi_model = _setting(cfg, "LIFEHUG_KIMI_MODEL", "kimi_model")
        selected_model = kimi_model or (model if model_is_kimi(model) else KIMI_DEFAULT_MODEL)
        return _call_kimi(prompt, selected_model,
                          _global_timeout(cfg), cfg)
    if provider == "anthropic":
        return _call_anthropic(prompt, model, cfg)
    if provider == "agent-task":
        raise AIUnavailableError("no unattended AI provider is ready; use agent-task mode")

    # Explicit OpenClaw never leaks into another provider.  Historical auto
    # mode retains its deliberate Anthropic fallback.
    explicit = _setting(cfg, "LIFEHUG_AI_PROVIDER", "ai_provider").lower()
    try:
        return _call_openclaw(prompt, _global_timeout(cfg))
    except AIProviderError as gateway_error:
        if explicit and explicit != "auto":
            raise
        if not _anthropic_key(cfg):
            raise gateway_error from None
        print("  ↻ openclaw failed; falling through to configured Anthropic provider")
        try:
            return _call_anthropic(prompt, model, cfg)
        except AIUnavailableError:
            # A configured key with no optional SDK must preserve the original
            # gateway failure as the actionable, catchable error (#47).
            raise gateway_error from None


def _local_readiness(
    base_url: str, model: str, timeout: float, api_key: str | None
) -> tuple[bool, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(f"{base_url}/models", headers=headers, method="GET")
    try:
        with _local_opener().open(request, timeout=min(timeout, 2.0)) as response:
            body = response.read()
        parsed = json.loads(body)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("data"), list):
            return False, "models readiness response was malformed"
        model_ids = {
            str(item.get("id")) for item in parsed["data"] if isinstance(item, dict)
        }
        if model not in model_ids:
            return False, "configured model was not listed by the server"
        return True, "configured model is listed and server is reachable"
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        return False, f"models readiness check returned HTTP {code}"
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, "server unavailable"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "models readiness response was malformed"


def provider_status(requested_model: str | None = None, *, probe: bool = False) -> ProviderStatus:
    """Resolve provider/model/readiness without making a mutating model call."""
    cfg = _config()
    requested_model = requested_model or cfg.get("classify_model") or DEFAULT_STATUS_MODEL
    try:
        provider = _provider_choice(requested_model, cfg)
    except AIConfigurationError as exc:
        return ProviderStatus("invalid", requested_model, False, str(exc))
    if provider == "local":
        model = _setting(cfg, "LIFEHUG_LOCAL_AI_MODEL", "local_ai_model") or "(missing)"
        try:
            base_url, model, timeout, key = _local_settings(cfg)
        except AIConfigurationError as exc:
            return ProviderStatus("local-openai", model, False, str(exc))
        if not probe:
            return ProviderStatus("local-openai", model, True, "configuration valid; not probed")
        ready, detail = _local_readiness(base_url, model, timeout, key)
        return ProviderStatus("local-openai", model, ready, detail)
    if provider == "openclaw":
        ready = _openclaw_gateway() is not None
        return ProviderStatus("openclaw", OPENCLAW_MODEL, ready,
                              "configured" if ready else "not configured")
    if provider == "kimi":
        configured = _setting(cfg, "LIFEHUG_KIMI_MODEL", "kimi_model")
        model = configured or (requested_model if model_is_kimi(requested_model)
                               else KIMI_DEFAULT_MODEL)
        ready = bool(_kimi_key(cfg))
        return ProviderStatus("kimi", model, ready,
                              "key configured" if ready else "key missing")
    if provider == "anthropic":
        key_ready = bool(_anthropic_key(cfg))
        sdk_ready = _anthropic_sdk_available()
        detail = "key and optional SDK available" if key_ready and sdk_ready else (
            "key missing" if not key_ready else "optional SDK not installed"
        )
        return ProviderStatus("anthropic", requested_model, key_ready and sdk_ready, detail)
    return ProviderStatus("agent-task", requested_model, False,
                          "no unattended provider configured")


def ai_available(requested_model: str | None = None) -> str | None:
    """Return the ready provider name, or ``None`` for agent-task mode."""
    status = provider_status(requested_model, probe=True)
    return status.provider if status.ready else None
