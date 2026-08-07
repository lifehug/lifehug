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
import math
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
MAX_CHAT_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_MODELS_RESPONSE_BYTES = 1024 * 1024


class AIProviderError(RuntimeError):
    """Base error whose messages contain metadata only, never model content."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "ai",
        operation: str = "request",
        status: str = "failed",
        response_bytes: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.status = status
        self.response_bytes = response_bytes


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
    """Loopback-only transport: ignore proxy env vars and refuse redirects."""
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )


def _safe_label(value: object, default: str = "unknown", max_length: int = 64) -> str:
    """Return bounded single-token metadata; never echo arbitrary exception text."""
    cleaned = "".join(
        char if char.isalnum() or char in "._-/" else "_"
        for char in str(value)
    ).strip("_")
    return (cleaned or default)[:max_length]


def failure_metadata(
    operation: str,
    exc: BaseException,
    *,
    provider: str = "ai",
    response_bytes: int | None = None,
) -> str:
    """Describe a failure using bounded metadata only, never ``str(exc)``."""
    if isinstance(exc, AIProviderError):
        provider = exc.provider or provider
        operation = exc.operation or operation
        status = exc.status
        if response_bytes is None:
            response_bytes = exc.response_bytes
    else:
        status = "failed"
    parts = [
        f"provider={_safe_label(provider)}",
        f"operation={_safe_label(operation)}",
        f"failure={_safe_label(type(exc).__name__)}",
        f"status={_safe_label(status)}",
    ]
    if response_bytes is not None:
        parts.append(f"response_bytes={max(0, int(response_bytes))}")
    return " ".join(parts)


def _config() -> dict[str, object]:
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — a lost privacy choice must fail closed
        raise AIConfigurationError(
            "provider configuration could not be loaded",
            provider="config",
            operation="load",
            status="invalid",
        ) from None
    if not isinstance(cfg, dict):
        raise AIConfigurationError(
            "provider configuration has an invalid shape",
            provider="config",
            operation="load",
            status="invalid",
        )
    return cfg


def _raw_setting(cfg: dict[str, object], env_name: str, config_name: str) -> str:
    value = os.environ.get(env_name)
    if value is None:
        value = cfg.get(config_name)
    return "" if value is None else str(value)


def _setting(cfg: dict[str, object], env_name: str, config_name: str) -> str:
    return _raw_setting(cfg, env_name, config_name).strip()


def _positive_timeout(raw: str, *, field: str, default: float | None = None) -> float:
    if not raw and default is not None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise AIConfigurationError(f"{field} must be a positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise AIConfigurationError(f"{field} must be a positive number")
    return value


def _truthy(raw: str) -> bool:
    return raw.lower() in {"1", "true", "yes", "on"}


def model_is_kimi(model: str) -> bool:
    """Kimi stays model-explicit unless ``ai_provider: kimi`` is selected."""
    return (model or "").lower().startswith(KIMI_MODEL_PREFIXES)


def _kimi_key(cfg: dict[str, object] | None = None) -> str | None:
    cfg = cfg if cfg is not None else _config()
    return _raw_setting(cfg, "KIMI_API_KEY", "kimi_api_key") or None


def _anthropic_key(cfg: dict[str, object] | None = None) -> str | None:
    cfg = cfg if cfg is not None else _config()
    return _raw_setting(cfg, "ANTHROPIC_API_KEY", "anthropic_api_key") or None


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
        if not isinstance(cfg, dict):
            raise TypeError
        gateway = cfg.get("gateway", {})
        if not isinstance(gateway, dict):
            raise TypeError
        auth = gateway.get("auth", {})
        if not isinstance(auth, dict):
            raise TypeError
        token = str(auth.get("token", ""))
        if token:
            raw_port = gateway.get("port", 18789)
            if not isinstance(raw_port, int) or isinstance(raw_port, bool):
                raise ValueError
            port = raw_port
            if not 1 <= port <= 65535:
                raise ValueError
            _validate_token(token, field="OpenClaw authorization token")
            base_url = f"http://localhost:{port}/v1"
            return _validated_base_url(
                base_url, allow_non_loopback=False, field="OpenClaw gateway URL"
            ), token
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        raise AIConfigurationError(
            "OpenClaw configuration could not be loaded safely",
            provider="openclaw",
            operation="config",
            status="invalid",
        ) from None
    return None


def _provider_choice(requested_model: str, cfg: dict[str, object]) -> str:
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


def _has_whitespace_or_control(value: str) -> bool:
    return any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)


def _validate_header_value(value: str, *, field: str) -> str:
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise AIConfigurationError(
            f"{field} contains forbidden whitespace or control characters",
            operation="request-build",
            status="invalid",
        )
    return value


def _validate_header_name(value: str) -> str:
    if _has_whitespace_or_control(value):
        raise AIConfigurationError(
            "header name contains forbidden whitespace or control characters",
            operation="request-build",
            status="invalid",
        )
    return value


def _validate_token(value: str, *, field: str) -> str:
    if _has_whitespace_or_control(value):
        raise AIConfigurationError(
            f"{field} contains forbidden whitespace or control characters",
            operation="request-build",
            status="invalid",
        )
    return value


def _validated_base_url(
    base_url: str,
    *,
    allow_non_loopback: bool,
    field: str = "local_ai_base_url",
) -> str:
    if _has_whitespace_or_control(base_url):
        raise AIConfigurationError(
            f"{field} contains forbidden whitespace or control characters",
            operation="request-build",
            status="invalid",
        )
    try:
        parsed = urlsplit(base_url)
        port = parsed.port  # Force validation of a malformed port.
    except ValueError:
        raise AIConfigurationError(f"{field} is not a valid URL") from None
    del port
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AIConfigurationError(f"{field} must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AIConfigurationError(
            f"{field} cannot contain credentials, a query, or a fragment"
        )
    if not allow_non_loopback and not _is_loopback_host(parsed.hostname):
        raise AIConfigurationError(
            "local_ai_base_url is not loopback; set local_ai_allow_non_loopback: true "
            "only after explicitly accepting that source material will leave this machine"
        )
    return base_url.rstrip("/")


def _local_settings(
    cfg: dict[str, object],
) -> tuple[str, str, float, str | None, bool]:
    base_url = _raw_setting(cfg, "LIFEHUG_LOCAL_AI_BASE_URL", "local_ai_base_url")
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
    key = _raw_setting(cfg, "LIFEHUG_LOCAL_AI_API_KEY", "local_ai_api_key") or None
    if key:
        _validate_token(key, field="local AI authorization token")
    return base_url, model, timeout, key, allow_remote


def _global_timeout(cfg: dict[str, object]) -> float:
    raw = _setting(cfg, "LIFEHUG_AI_TIMEOUT", "ai_timeout_seconds")
    return _positive_timeout(
        raw, field="ai_timeout_seconds", default=DEFAULT_AI_TIMEOUT_SECONDS
    )


def _decode_chat_response(body: bytes, provider: str) -> str:
    try:
        result = json.loads(body)
        content = result["choices"][0]["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        raise AIResponseError(
            f"{provider} returned a malformed chat completion",
            provider=provider,
            operation="decode-chat",
            status="malformed",
            response_bytes=len(body),
        ) from None
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError(
            f"{provider} returned an empty chat completion",
            provider=provider,
            operation="decode-chat",
            status="empty",
            response_bytes=len(body),
        )
    return content


def _bounded_response_read(response, *, provider: str, operation: str, limit: int) -> bytes:
    """Read at most ``limit`` bytes, including for chunked responses."""
    try:
        headers = getattr(response, "headers", None)
        declared_raw = headers.get("Content-Length") if headers is not None else None
        if declared_raw not in (None, ""):
            declared = int(declared_raw)
            if declared < 0:
                raise ValueError
            if declared > limit:
                raise AIResponseError(
                    f"{provider} response exceeded the size limit",
                    provider=provider,
                    operation=operation,
                    status="response_too_large",
                    response_bytes=declared,
                )
        body = response.read(limit + 1)
    except AIProviderError:
        raise
    except Exception:  # noqa: BLE001 — response objects can fail in arbitrary ways
        raise AIResponseError(
            f"{provider} response could not be read",
            provider=provider,
            operation=operation,
            status="read_failed",
        ) from None
    if not isinstance(body, bytes):
        raise AIResponseError(
            f"{provider} response was not bytes",
            provider=provider,
            operation=operation,
            status="malformed",
        )
    if len(body) > limit:
        raise AIResponseError(
            f"{provider} response exceeded the size limit",
            provider=provider,
            operation=operation,
            status="response_too_large",
            response_bytes=len(body),
        )
    return body


def _build_request(
    *,
    provider: str,
    base_url: str,
    path: str,
    headers: dict[str, str],
    data: bytes | None = None,
    method: str | None = None,
    loopback_transport: bool = False,
    allow_non_loopback: bool = False,
):
    try:
        base_url = _validated_base_url(
            base_url,
            allow_non_loopback=allow_non_loopback or not loopback_transport,
            field=f"{provider} base URL",
        )
        for name, value in headers.items():
            _validate_header_name(name)
            _validate_header_value(value, field="header value")
        return urllib.request.Request(
            f"{base_url.rstrip('/')}/{path.lstrip('/')}",
            data=data,
            headers=headers,
            method=method,
        )
    except AIProviderError:
        raise
    except Exception:  # noqa: BLE001 — normalize URL/header/request construction
        raise AIConfigurationError(
            f"{provider} request could not be constructed",
            provider=provider,
            operation="request-build",
            status="invalid",
        ) from None


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
    allow_non_loopback: bool = False,
) -> str:
    timeout = _positive_timeout(str(timeout), field=f"{provider} timeout")
    try:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            _validate_token(api_key, field=f"{provider} authorization token")
            headers["Authorization"] = f"Bearer {api_key}"
        request = _build_request(
            provider=provider,
            base_url=base_url,
            path="chat/completions",
            data=payload,
            headers=headers,
            loopback_transport=local_transport,
            allow_non_loopback=allow_non_loopback,
        )
    except AIProviderError:
        raise
    except Exception:  # noqa: BLE001 — JSON/request construction must stay typed
        raise AIConfigurationError(
            f"{provider} request could not be constructed",
            provider=provider,
            operation="request-build",
            status="invalid",
        ) from None
    try:
        if local_transport:
            response_context = _local_opener().open(request, timeout=timeout)
        else:
            response_context = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
        with response_context as response:
            body = _bounded_response_read(
                response,
                provider=provider,
                operation="chat-completion",
                limit=MAX_CHAT_RESPONSE_BYTES,
            )
            return _decode_chat_response(body, provider)
    except AIProviderError:
        raise
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise AIUnavailableError(
            f"{provider} HTTP failure ({code})",
            provider=provider,
            operation="chat-completion",
            status=f"http_{code}",
        ) from None
    except Exception:  # noqa: BLE001 — normalize open/read/close transport failures
        raise AIUnavailableError(
            f"{provider} is unavailable",
            provider=provider,
            operation="chat-completion",
            status="unavailable",
        ) from None


def _call_local(prompt: str, cfg: dict[str, object]) -> str:
    base_url, model, timeout, key, allow_remote = _local_settings(cfg)
    return _openai_compatible_call(
        provider="local-openai",
        base_url=base_url,
        model=model,
        prompt=prompt,
        timeout=timeout,
        api_key=key,
        max_tokens=4096,
        local_transport=True,
        allow_non_loopback=allow_remote,
    )


def _call_kimi(prompt: str, model: str, timeout: float, cfg: dict[str, object]) -> str:
    key = _kimi_key(cfg)
    if not key:
        raise AIUnavailableError(
            "Kimi is selected but no key is configured (KIMI_API_KEY or kimi_api_key)"
        )
    base_url = _raw_setting(cfg, "KIMI_BASE_URL", "kimi_base_url") or KIMI_DEFAULT_BASE_URL
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
                local_transport=True,
            )
            if "Agent couldn’t generate" in content or "Agent couldn't generate" in content:
                raise AIResponseError("openclaw rejected the structured response")
            return content
        except AIResponseError:
            raise
        except AIUnavailableError as exc:
            if exc.status.startswith("http_3"):
                # Redirect refusal is deterministic and security-sensitive.
                # Never replay the prompt just because the destination tried
                # to move it elsewhere.
                raise
            last_error = exc
            if attempt < 3:
                print(f"  ↻ openclaw call failed; retrying ({attempt}/3)")
                time.sleep(10)
    raise last_error or AIUnavailableError("openclaw is unavailable")


def get_anthropic_client(cfg: dict[str, object] | None = None):
    """Build the optional Anthropic client without ever terminating Python."""
    cfg = cfg if cfg is not None else _config()
    key = _anthropic_key(cfg)
    if not key:
        raise AIUnavailableError(
            "Anthropic is selected but no key is configured "
            "(ANTHROPIC_API_KEY or anthropic_api_key)"
        )
    _validate_token(key, field="Anthropic authorization token")
    try:
        import anthropic  # noqa: PLC0415
    except ImportError:
        raise AIUnavailableError(
            "Anthropic is selected but its optional SDK is not installed"
        ) from None
    try:
        return anthropic.Anthropic(api_key=key)
    except Exception:  # noqa: BLE001 — SDK exceptions may echo key material
        raise AIUnavailableError(
            "Anthropic client initialization failed",
            provider="anthropic",
            operation="client-init",
            status="unavailable",
        ) from None


def _call_anthropic(prompt: str, model: str, cfg: dict[str, object]):
    client = get_anthropic_client(cfg)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception:  # noqa: BLE001 — SDK exceptions may echo request content
        raise AIUnavailableError(
            "anthropic request failed",
            provider="anthropic",
            operation="chat-completion",
            status="unavailable",
        ) from None
    try:
        content = response.content[0].text if response.content else ""
    except (AttributeError, IndexError, TypeError):
        content = ""
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError(
            "anthropic returned an empty completion",
            provider="anthropic",
            operation="decode-chat",
            status="empty",
        )
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
    base_url: str,
    model: str,
    timeout: float,
    api_key: str | None,
    *,
    allow_non_loopback: bool,
) -> tuple[bool, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        request = _build_request(
            provider="local-openai",
            base_url=base_url,
            path="models",
            headers=headers,
            method="GET",
            loopback_transport=True,
            allow_non_loopback=allow_non_loopback,
        )
        with _local_opener().open(request, timeout=min(timeout, 2.0)) as response:
            body = _bounded_response_read(
                response,
                provider="local-openai",
                operation="models-readiness",
                limit=MAX_MODELS_RESPONSE_BYTES,
            )
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
    except AIProviderError as exc:
        return False, failure_metadata("models-readiness", exc, provider="local-openai")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "models readiness response was malformed"
    except Exception:  # noqa: BLE001 — readiness returns only safe metadata
        return False, "provider=local-openai operation=models-readiness status=unavailable"


def provider_status(requested_model: str | None = None, *, probe: bool = False) -> ProviderStatus:
    """Resolve provider/model/readiness without making a mutating model call."""
    try:
        cfg = _config()
    except AIProviderError as exc:
        model = requested_model or DEFAULT_STATUS_MODEL
        return ProviderStatus(
            "invalid", _safe_label(model, DEFAULT_STATUS_MODEL), False,
            failure_metadata("config-load", exc, provider="config"),
        )
    requested_model = requested_model or str(cfg.get("classify_model") or DEFAULT_STATUS_MODEL)
    try:
        provider = _provider_choice(requested_model, cfg)
    except AIConfigurationError as exc:
        return ProviderStatus(
            "invalid",
            _safe_label(requested_model, DEFAULT_STATUS_MODEL),
            False,
            failure_metadata("provider-select", exc, provider="config"),
        )
    if provider == "local":
        model = _setting(cfg, "LIFEHUG_LOCAL_AI_MODEL", "local_ai_model") or "(missing)"
        try:
            base_url, model, timeout, key, allow_remote = _local_settings(cfg)
        except AIConfigurationError as exc:
            return ProviderStatus(
                "local-openai",
                _safe_label(model, "missing"),
                False,
                failure_metadata("local-config", exc, provider="local-openai"),
            )
        if not probe:
            return ProviderStatus(
                "local-openai",
                _safe_label(model),
                True,
                "configuration valid; not probed",
            )
        ready, detail = _local_readiness(
            base_url, model, timeout, key, allow_non_loopback=allow_remote
        )
        return ProviderStatus("local-openai", _safe_label(model), ready, detail)
    if provider == "openclaw":
        ready = _openclaw_gateway() is not None
        return ProviderStatus("openclaw", OPENCLAW_MODEL, ready,
                              "configured" if ready else "not configured")
    if provider == "kimi":
        configured = _setting(cfg, "LIFEHUG_KIMI_MODEL", "kimi_model")
        model = configured or (requested_model if model_is_kimi(requested_model)
                               else KIMI_DEFAULT_MODEL)
        key = _kimi_key(cfg)
        try:
            if key:
                _validate_token(key, field="Kimi authorization token")
        except AIConfigurationError as exc:
            return ProviderStatus(
                "kimi", _safe_label(model), False,
                failure_metadata("request-build", exc, provider="kimi"),
            )
        ready = bool(key)
        return ProviderStatus("kimi", _safe_label(model), ready,
                              "key configured" if ready else "key missing")
    if provider == "anthropic":
        key = _anthropic_key(cfg)
        try:
            if key:
                _validate_token(key, field="Anthropic authorization token")
        except AIConfigurationError as exc:
            return ProviderStatus(
                "anthropic", _safe_label(requested_model), False,
                failure_metadata("request-build", exc, provider="anthropic"),
            )
        key_ready = bool(key)
        sdk_ready = _anthropic_sdk_available()
        detail = "key and optional SDK available" if key_ready and sdk_ready else (
            "key missing" if not key_ready else "optional SDK not installed"
        )
        return ProviderStatus(
            "anthropic", _safe_label(requested_model), key_ready and sdk_ready, detail
        )
    return ProviderStatus("agent-task", _safe_label(requested_model), False,
                          "no unattended provider configured")


def ai_available(requested_model: str | None = None) -> str | None:
    """Return the ready provider name, or ``None`` for agent-task mode."""
    status = provider_status(requested_model, probe=True)
    return status.provider if status.ready else None
