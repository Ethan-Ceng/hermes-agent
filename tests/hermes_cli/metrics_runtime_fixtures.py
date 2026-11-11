"""Real metrics runtime fixtures and transport doubles shared by behavior tests."""

from __future__ import annotations

import contextvars
import threading
from types import SimpleNamespace
from typing import Any




class _Request:
    def __init__(self, headers: dict[str, Any], content: dict[str, Any]) -> None:
        self.headers = headers
        self.content = content


class _ToolExecutionResult:
    def __init__(self, result: Any, annotation: Any = None) -> None:
        self.result = result
        self.annotation = annotation


class _Relay:
    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []
        self._callbacks: dict[str, Any] = {}
        self._starts: dict[Any, dict[str, Any]] = {}
        self._tool_starts: dict[Any, dict[str, Any]] = {}
        self._scope_starts: dict[Any, dict[str, Any]] = {}
        self._scope = contextvars.ContextVar("relay_scope", default=None)
        self._scope_stack = contextvars.ContextVar("relay_scope_stack", default=None)
        self._scope_serial = 0
        self.ScopeType = SimpleNamespace(
            Agent="agent", Function="function", Tool="tool"
        )
        self.LLMRequest = _Request
        self.ToolExecutionResult = _ToolExecutionResult
        self.scope = SimpleNamespace(
            push=self._scope_push,
            pop=self._scope_pop,
            event=self._scope_event,
        )
        self.llm = SimpleNamespace(call=self._llm_call, call_end=self._llm_call_end)
        self.tools = SimpleNamespace(call=self._tool_call, call_end=self._tool_call_end)
        self.subscribers = SimpleNamespace(
            register=self._register,
            deregister=self._deregister,
            flush=self._flush,
        )
        self.get_scope_stack = self._get_scope_stack

    def _scope_push(self, name: str, scope_type: Any, **kwargs: Any) -> Any:
        self._scope_serial += 1
        handle = ("scope", name, self._scope_serial)
        stack = self._scope_stack.get()
        if stack is None:
            stack = []
            self._scope_stack.set(stack)
        stack.append(handle)
        self._scope.set(handle)
        self.events.append(("scope.push", name, scope_type, kwargs))
        if scope_type == self.ScopeType.Function:
            self._scope_starts[handle] = kwargs
            event = SimpleNamespace(
                kind="scope",
                category="function",
                name=name,
                scope_category="start",
                category_profile=None,
                metadata=kwargs.get("metadata"),
                data=kwargs.get("input"),
            )
            for callback in list(self._callbacks.values()):
                callback(event)
        return handle

    def _scope_pop(self, handle: Any, **kwargs: Any) -> None:
        stack = self._scope_stack.get()
        if not stack or stack[-1] != handle:
            current = stack[-1] if stack else None
            self.events.append(("scope.pop.rejected", handle, current))
            raise RuntimeError("scope handle is not at the top of the stack")
        stack.pop()
        self._scope.set(stack[-1] if stack else None)
        self.events.append(("scope.pop", handle, kwargs))
        start = self._scope_starts.pop(handle, None)
        if start is not None:
            event = SimpleNamespace(
                kind="scope",
                category="function",
                name=handle[1],
                scope_category="end",
                category_profile=None,
                metadata={
                    **(start.get("metadata") or {}),
                    **(kwargs.get("metadata") or {}),
                },
                data=kwargs.get("output"),
            )
            for callback in list(self._callbacks.values()):
                callback(event)

    def _scope_event(self, name: str, **kwargs: Any) -> None:
        self.events.append(("scope.event", name, kwargs))
        event = SimpleNamespace(
            kind="mark",
            category=None,
            name=name,
            scope_category=None,
            category_profile=None,
            metadata=kwargs.get("metadata"),
            data=kwargs.get("data"),
        )
        for callback in list(self._callbacks.values()):
            callback(event)

    def _get_scope_stack(self) -> Any:
        stack = self._scope_stack.get()
        current = stack[-1] if stack else None
        self._scope.set(current)
        self.events.append(("scope.sync", current))
        return current

    def _llm_call(
        self,
        name: str,
        request: _Request,
        **kwargs: Any,
    ) -> Any:
        handle = ("llm", name, len(self._starts))
        self._starts[handle] = kwargs
        self.events.append(("llm.call", name, request.content, kwargs))
        return handle

    def _llm_call_end(
        self,
        handle: Any,
        response: dict[str, Any],
        **kwargs: Any,
    ) -> None:
        start = self._starts.pop(handle)
        self.events.append(("llm.call_end", handle, response, kwargs))
        event = SimpleNamespace(
            kind="scope",
            category="llm",
            name=handle[1],
            scope_category="end",
            category_profile={"model_name": start["model_name"]},
            metadata={
                **start["metadata"],
                **kwargs["metadata"],
                "otel.status_code": "OK",
            },
            data=response,
        )
        for callback in list(self._callbacks.values()):
            callback(event)

    def _tool_call(
        self,
        name: str,
        args: dict[str, Any],
        **kwargs: Any,
    ) -> Any:
        handle = ("tool", name, len(self._tool_starts))
        self._tool_starts[handle] = kwargs
        self.events.append(("tool.call", name, args, kwargs))
        return handle

    def _tool_call_end(
        self,
        handle: Any,
        result: _ToolExecutionResult,
        **kwargs: Any,
    ) -> None:
        assert isinstance(result, _ToolExecutionResult)
        payload = result.result
        start = self._tool_starts.pop(handle)
        self.events.append(("tool.call_end", handle, payload, kwargs))
        event = SimpleNamespace(
            kind="scope",
            category="tool",
            name=handle[1],
            scope_category="end",
            category_profile={},
            metadata={
                **start["metadata"],
                **kwargs["metadata"],
                "otel.status_code": "OK",
            },
            data=payload,
        )
        for callback in list(self._callbacks.values()):
            callback(event)

    def _register(self, name: str, callback: Any) -> None:
        self._callbacks[name] = callback
        self.events.append(("subscribers.register", name))

    def _deregister(self, name: str) -> None:
        self._callbacks.pop(name, None)
        self.events.append(("subscribers.deregister", name))

    def _flush(self) -> None:
        self.events.append(("subscribers.flush",))


_EXPORT_WORKER = "hermes-shared-metrics-flush"


def _join_export_workers() -> None:
    """Task/session exports run on a background worker; wait for it before reading the store."""
    while workers := [t for t in threading.enumerate() if t.name == _EXPORT_WORKER]:
        for worker in workers:
            worker.join(timeout=10)
            assert not worker.is_alive()
