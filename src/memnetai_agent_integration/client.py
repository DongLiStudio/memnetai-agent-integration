"""Small defensive adapter around the optional MemNetAI Python SDK."""

from __future__ import annotations

import importlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class MemNetAIError(RuntimeError):
    pass


class MemNetAITimeout(MemNetAIError):
    pass


@dataclass(frozen=True, slots=True)
class RecallResult:
    memories: tuple[str, ...]
    raw: Any


class SDKClient:
    def __init__(
        self, api_key: str, base_url: str = "https://api.memnetai.com",
        sdk_client: Any = None, http_open: Callable[..., Any] = urlopen,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if sdk_client is None:
            try:
                module = importlib.import_module("memnetai")
                sdk_client = module.MemNetAIClient(api_key=api_key, base_url=base_url)
            except (ImportError, AttributeError) as exc:
                raise MemNetAIError("memnetai-python-sdk is not installed or is incompatible") from exc
        self._client = sdk_client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._http_open = http_open

    @staticmethod
    def _with_timeout(call: Callable[[], Any], seconds: float) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memnetai-recall")
        future = executor.submit(call)
        try:
            return future.result(timeout=seconds)
        except TimeoutError as exc:
            future.cancel()
            raise MemNetAITimeout(f"MemNetAI recall exceeded {seconds:g}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def recall(self, *, memory_agent_name: str, namespace: str, query: str, timeout: float = 4.0) -> RecallResult:
        def invoke() -> Any:
            return self._client.recall(
                memory_agent_name=memory_agent_name, namespace=namespace, query=query[:500],
                character="用户", recall_deep=1, is_using_associative_thinking=1,
                is_using_common_sense_database=1, is_using_global_common_sense_database=1,
                is_using_memory_agent_common_sense_database=0,
                is_returning_detailed_memory_info=0,
            )
        try:
            raw = self._with_timeout(invoke, timeout)
        except MemNetAIError:
            raise
        except Exception as exc:
            raise MemNetAIError(self._safe_error(exc)) from exc
        _raise_for_response(raw)
        return RecallResult(tuple(_extract_memories(raw)), raw)

    def memories(self, *, memory_agent_name: str, namespace: str, messages: list[dict[str, str]], language: str = "zh-CN", async_mode: int = 1) -> Any:
        sdk_messages: Any = messages
        try:
            module = importlib.import_module("memnetai")
            sdk_messages = [module.Message(role=m["role"], content=m["content"]) for m in messages]
        except (ImportError, AttributeError):
            pass
        try:
            result = self._client.memories(memory_agent_name=memory_agent_name, namespace=namespace, messages=sdk_messages, language=language, async_mode=async_mode)
        except Exception as exc:
            raise MemNetAIError(self._safe_error(exc)) from exc
        _raise_for_response(result)
        return result

    def task_progress(self, task_id: str, timeout: float = 5.0) -> Any:
        """Query an asynchronous memories task using the documented REST endpoint."""
        if not task_id:
            raise ValueError("task_id is required")
        url = f"{self._base_url}/memories/task/progress?{urlencode({'taskId': task_id})}"
        request = Request(url, headers={"Authorization": f"Token {self._api_key}", "Accept": "application/json"})
        try:
            with self._http_open(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                _raise_for_response(result)
                return result
        except HTTPError as exc:
            body = _http_error_json(exc)
            if body.get("code") == "A0449":
                return {"code": "00000", "msg": "terminal task no longer retained",
                        "data": {"progress": 100, "terminalCode": "A0449"}}
            raise MemNetAIError(
                f"Unable to query memories task progress: {self._safe_error(exc)}"
            ) from exc
        except Exception as exc:
            raise MemNetAIError(
                f"Unable to query memories task progress: {self._safe_error(exc)}"
            ) from exc

    def _safe_error(self, exc: BaseException) -> str:
        message = str(exc).replace(self._api_key, "***")
        if isinstance(exc, AttributeError) and "NoneType" in message and "json" in message:
            return "API Key 无效、余额不足，或请求被服务端拒绝"
        return message


def _http_error_json(exc: HTTPError) -> dict[str, Any]:
    try:
        value = json.loads(exc.read().decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _raise_for_response(result: Any) -> None:
    if not isinstance(result, dict):
        return
    inner = result.get("response_json", result)
    if not isinstance(inner, dict) or "code" not in inner:
        return
    code = inner.get("code")
    if code in (0, "0", "00000", None):
        return
    message = str(inner.get("msg") or inner.get("message") or "MemNetAI API request failed")
    raise MemNetAIError(f"MemNetAI API error {code}: {message}")


def _extract_memories(result: Any) -> list[str]:
    if not isinstance(result, dict):
        return []
    inner = result.get("response_json", result)
    data = inner.get("data", inner) if isinstance(inner, dict) else {}
    if not isinstance(data, dict):
        return []
    prompt = data.get("memoryPrompt")
    if isinstance(prompt, str) and prompt.strip():
        return [prompt]
    candidates = data.get("memorySummaryList") or data.get("memories") or data.get("memory_list") or []
    output: list[str] = []
    for item in candidates if isinstance(candidates, list) else []:
        if isinstance(item, dict):
            value = item.get("content") or item.get("memory") or item.get("summary") or item.get("description")
            if value:
                output.append(str(value))
        elif item:
            output.append(str(item))
    return output
