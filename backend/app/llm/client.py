"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for an OpenAI-compatible `/chat/completions` endpoint."""

    base_url: str = "https://api.openai.com/v1"
    api_key: str | None = None
    model: str = "gpt-4.1-mini"
    stream: bool = False
    timeout: float = 60.0
    provider: str | None = None

    @classmethod
    def from_env(cls, prefix: str = "FLASHNOVEL") -> "LLMConfig":
        """Build config from environment variables.

        Uses FLASHNOVEL_* first and falls back to OPENAI_* for local
        compatibility.
        """

        return cls(
            base_url=os.getenv(f"{prefix}_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or cls.base_url,
            api_key=os.getenv(f"{prefix}_API_KEY") or os.getenv("OPENAI_API_KEY"),
            model=os.getenv(f"{prefix}_MODEL") or os.getenv("OPENAI_MODEL") or cls.model,
            stream=_env_bool(os.getenv(f"{prefix}_STREAM"), cls.stream),
            timeout=float(os.getenv(f"{prefix}_TIMEOUT") or cls.timeout),
            provider=os.getenv(f"{prefix}_PROVIDER"),
        )


@dataclass(frozen=True)
class ChatMessage:
    """A chat message accepted by OpenAI-compatible APIs."""

    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def to_openai(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        return payload


@dataclass(frozen=True)
class ChatUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "ChatUsage | None":
        if not payload:
            return None
        return cls(
            prompt_tokens=payload.get("prompt_tokens"),
            completion_tokens=payload.get("completion_tokens"),
            total_tokens=payload.get("total_tokens"),
        )


@dataclass(frozen=True)
class ChatCompletion:
    """Full chat completion response."""

    content: str
    raw: Mapping[str, Any]
    model: str | None = None
    usage: ChatUsage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class ChatDelta:
    """Streaming chat completion delta."""

    content: str = ""
    raw: Mapping[str, Any] | None = None
    model: str | None = None
    finish_reason: str | None = None
    done: bool = False


class LLMError(RuntimeError):
    """Base error for LLM client failures."""


class LLMAPIError(LLMError):
    """Raised when the upstream LLM endpoint returns an error."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OpenAICompatibleClient:
    """Small dependency-free client for OpenAI-compatible chat APIs."""

    def __init__(self, config: LLMConfig | None = None, **overrides: Any):
        if config is None:
            config = LLMConfig(**overrides)
        elif overrides:
            merged = {**config.__dict__, **overrides}
            config = LLMConfig(**merged)
        self.config = config

    @classmethod
    def from_env(cls, prefix: str = "FLASHNOVEL") -> "OpenAICompatibleClient":
        return cls(LLMConfig.from_env(prefix=prefix))

    def complete_sync(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> ChatCompletion:
        body = self._build_body(
            messages,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )
        payload = self._post_json(body)
        return self._parse_completion(payload)

    async def complete(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(
            self.complete_sync,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )

    def stream_sync(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> Iterator[ChatDelta]:
        body = self._build_body(
            messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )
        with self._open(body) as response:
            for payload in self._iter_sse_payloads(response):
                if payload is None:
                    yield ChatDelta(done=True)
                    continue
                yield self._parse_delta(payload)

    async def stream(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: str | Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[ChatDelta]:
        sync_iter = self.stream_sync(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )
        sentinel = object()

        def next_item() -> ChatDelta | object:
            try:
                return next(sync_iter)
            except StopIteration:
                return sentinel

        while True:
            item = await asyncio.to_thread(next_item)
            if item is sentinel:
                break
            yield item  # type: ignore[misc]

    def chat_sync(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> ChatCompletion | Iterator[ChatDelta]:
        if self.config.stream if stream is None else stream:
            return self.stream_sync(messages, **kwargs)
        return self.complete_sync(messages, **kwargs)

    def _build_body(
        self,
        messages: Sequence[ChatMessage | Mapping[str, Any]],
        *,
        stream: bool,
        temperature: float | None,
        max_tokens: int | None,
        response_format: str | Mapping[str, Any] | None,
        extra_body: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": stream,
        }
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if response_format is not None:
            body["response_format"] = (
                {"type": response_format} if isinstance(response_format, str) else dict(response_format)
            )
        if extra_body:
            body.update(extra_body)
        return body

    @staticmethod
    def _message_payload(message: ChatMessage | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(message, ChatMessage):
            return message.to_openai()
        payload = dict(message)
        if "role" not in payload or "content" not in payload:
            raise ValueError("chat message mappings must include 'role' and 'content'")
        return payload

    def _endpoint(self) -> str:
        base_url = (self.config.base_url or LLMConfig.base_url).rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _open(self, body: Mapping[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=self.config.timeout)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise LLMAPIError(
                f"LLM endpoint returned HTTP {exc.code}",
                status_code=exc.code,
                body=body_text,
            ) from exc
        except urllib.error.URLError as exc:
            raise LLMAPIError(f"LLM endpoint request failed: {exc.reason}") from exc

    def _post_json(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._open(body) as response:
            raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMAPIError("LLM endpoint returned invalid JSON", body=raw) from exc
        if not isinstance(payload, Mapping):
            raise LLMAPIError("LLM endpoint returned a non-object JSON payload", body=raw)
        return payload

    @staticmethod
    def _iter_sse_payloads(response: Any) -> Iterator[Mapping[str, Any] | None]:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                yield None
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise LLMAPIError("LLM stream returned invalid JSON", body=data) from exc
            if not isinstance(payload, Mapping):
                raise LLMAPIError("LLM stream returned a non-object JSON payload", body=data)
            yield payload

    @staticmethod
    def _parse_completion(payload: Mapping[str, Any]) -> ChatCompletion:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMAPIError("LLM endpoint returned no choices", body=json.dumps(payload))
        choice = choices[0]
        message = choice.get("message") or {}
        return ChatCompletion(
            content=message.get("content") or "",
            raw=payload,
            model=payload.get("model"),
            usage=ChatUsage.from_payload(payload.get("usage")),
            finish_reason=choice.get("finish_reason"),
        )

    @staticmethod
    def _parse_delta(payload: Mapping[str, Any]) -> ChatDelta:
        choices = payload.get("choices") or []
        if not choices:
            return ChatDelta(raw=payload, model=payload.get("model"))
        choice = choices[0]
        delta = choice.get("delta") or choice.get("message") or {}
        return ChatDelta(
            content=delta.get("content") or "",
            raw=payload,
            model=payload.get("model"),
            finish_reason=choice.get("finish_reason"),
            done=choice.get("finish_reason") is not None,
        )
