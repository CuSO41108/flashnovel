"""Base types for injectable runtime tools."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.llm.client import ChatMessage


class ToolError(RuntimeError):
    """Base error for tool execution failures."""


class StoreAPIUnavailable(ToolError):
    """Raised when the injected store does not provide an expected API."""


class LLMUnavailable(ToolError):
    """Raised when a tool needs an LLM but none was injected."""


@dataclass
class ToolContext:
    """Runtime dependencies injected into tools."""

    store: Any
    llm: Any | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Structured result returned by every tool."""

    tool: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, tool: str, **data: Any) -> "ToolResult":
        return cls(tool=tool, ok=True, data=data)

    @classmethod
    def failure(cls, tool: str, error: str, **data: Any) -> "ToolResult":
        return cls(tool=tool, ok=False, data=data, error=error)


class Tool(ABC):
    """Base class for graph/runtime tools."""

    name: ClassVar[str]
    description: ClassVar[str] = ""

    async def __call__(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        try:
            return await self.run(context, **kwargs)
        except ToolError as exc:
            return ToolResult.failure(self.name, str(exc))

    @abstractmethod
    async def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool."""

    async def call_store(
        self,
        context: ToolContext,
        method_name: str,
        /,
        *args: Any,
        optional: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Call a method on the injected store, supporting sync or async APIs."""

        if context.store is None:
            if optional:
                return None
            raise StoreAPIUnavailable("ToolContext.store is required")

        method = getattr(context.store, method_name, None)
        if method is None:
            if optional:
                return None
            raise StoreAPIUnavailable(
                f"store must implement {method_name} for tool {self.name}"
            )

        filtered_kwargs = self._filter_kwargs(method, kwargs)
        try:
            result = method(*args, **filtered_kwargs)
        except TypeError as exc:
            raise ToolError(f"store.{method_name} call failed for tool {self.name}: {exc}") from exc
        if inspect.isawaitable(result):
            return await result
        return result

    def require_llm(self, context: ToolContext) -> Any:
        if context.llm is None:
            raise LLMUnavailable(f"Tool {self.name} requires ToolContext.llm")
        return context.llm

    @staticmethod
    def _filter_kwargs(method: Any, kwargs: Mapping[str, Any]) -> dict[str, Any]:
        signature = inspect.signature(method)
        parameters = signature.parameters
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return dict(kwargs)
        return {key: value for key, value in kwargs.items() if key in parameters}


async def complete_text(
    llm: Any,
    messages: Sequence[ChatMessage | Mapping[str, Any]],
    **kwargs: Any,
) -> str:
    """Call a compatible LLM object and return text content."""

    method = getattr(llm, "complete", None)
    if method is None:
        method = getattr(llm, "chat", None)
        kwargs.setdefault("stream", False)
    if method is None:
        raise LLMUnavailable("llm must provide complete(...) or chat(...)")

    result = method(messages, **kwargs)
    if inspect.isawaitable(result):
        result = await result

    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(result, Mapping):
        mapped_content = result.get("content")
        if isinstance(mapped_content, str):
            return mapped_content
        choices = result.get("choices")
        if choices:
            message = choices[0].get("message") or {}
            choice_content = message.get("content")
            if isinstance(choice_content, str):
                return choice_content
    raise LLMUnavailable("llm completion result did not contain text content")


# TODO(store): the injected store layer is expected to provide these methods:
# get_writer_context, save_artifact, save_chapter_plan, save_candidate_memory,
# save_review_report, persist_candidate_memory, append_event.
