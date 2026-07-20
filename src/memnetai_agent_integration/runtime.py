"""Host-independent orchestration of recall, buffering, and durable submission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import MemNetAIError, SDKClient
from .config import DASHBOARD_URL, IntegrationDefaults
from .database import (
    append_message, batch_messages, complete_batch, get_batch, mark_batch_submitted,
    mark_batch_submitting, retry_batch, seal_batch,
)


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    ok: bool
    user_notice: str | None = None
    dashboard_url: str | None = None
    payload: Any = None


class MemoryRuntime:
    def __init__(self, config: IntegrationDefaults, client: SDKClient) -> None:
        self.config = config
        self.client = client

    def before_reply(self, *, session_id: str, host: str, prompt: str, message_id: str | None = None) -> RuntimeResult:
        append_message(self.config.database_path, session_id=session_id, host=host, role="user", content=prompt, message_id=message_id, idle_minutes=self.config.idle_timeout_minutes, memory_agent_name=self.config.memory_agent_name, namespace=self.config.namespace)
        try:
            recall = self.client.recall(memory_agent_name=self.config.memory_agent_name, namespace=self.config.namespace, query=prompt, timeout=self.config.recall_timeout_seconds)
            return RuntimeResult(True, payload=recall)
        except Exception as exc:
            return RuntimeResult(False, f"MemNetAI 回忆失败：{exc}。请前往控制台检查服务状态或余额。", DASHBOARD_URL)

    def after_reply(self, *, session_id: str, host: str, response: str, message_id: str | None = None) -> RuntimeResult:
        record = append_message(self.config.database_path, session_id=session_id, host=host, role="assistant", content=response, message_id=message_id, idle_minutes=self.config.idle_timeout_minutes, memory_agent_name=self.config.memory_agent_name, namespace=self.config.namespace)
        return RuntimeResult(True, payload=record)

    def submit_session(self, session_id: str, trigger_reason: str) -> RuntimeResult:
        batch = seal_batch(self.config.database_path, session_id=session_id, trigger_reason=trigger_reason)
        if batch is None:
            return RuntimeResult(True, payload={"action": "skip"})
        if not mark_batch_submitting(self.config.database_path, batch.batch_id):
            return RuntimeResult(True, payload={"action": "already_claimed", "batch_id": batch.batch_id})
        messages = [{"role": m.role, "content": m.content} for m in batch_messages(self.config.database_path, batch.batch_id)]
        try:
            response = self.client.memories(memory_agent_name=self.config.memory_agent_name, namespace=self.config.namespace, messages=messages, async_mode=1)
            task_id = _task_id(response)
            if not task_id:
                raise MemNetAIError("异步记忆请求未返回 taskId")
            mark_batch_submitted(self.config.database_path, batch.batch_id, task_id)
            return RuntimeResult(True, payload={"action": "submitted", "batch_id": batch.batch_id, "remote_task_id": task_id})
        except Exception as exc:
            retry_batch(self.config.database_path, batch.batch_id, str(exc))
            return RuntimeResult(False, f"MemNetAI 记忆提交失败：{exc}。请前往控制台检查服务状态或余额。", DASHBOARD_URL)

    def check_submission(self, batch_id: str, task_id: str) -> RuntimeResult:
        """Reconcile a submitted async task without resubmitting it on poll failures."""
        try:
            response = self.client.task_progress(task_id)
            progress = _progress(response)
            if progress is not None and progress >= 100:
                complete_batch(self.config.database_path, batch_id)
                return RuntimeResult(True, payload={"action": "complete", "batch_id": batch_id, "progress": progress})
            return RuntimeResult(True, payload={"action": "pending", "batch_id": batch_id, "progress": progress})
        except Exception as exc:
            return RuntimeResult(False, f"MemNetAI 记忆任务状态查询失败：{exc}。请前往控制台检查服务状态或余额。", DASHBOARD_URL)

    def retry_submission(self, batch_id: str) -> RuntimeResult:
        batch = get_batch(self.config.database_path, batch_id)
        if batch is None:
            return RuntimeResult(False, f"本地记忆批次不存在：{batch_id}")
        if batch.status != "retry":
            return RuntimeResult(True, payload={"action": "skip", "status": batch.status})
        if not mark_batch_submitting(self.config.database_path, batch_id):
            return RuntimeResult(True, payload={"action": "already_claimed", "batch_id": batch_id})
        messages = [
            {"role": item.role, "content": item.content}
            for item in batch_messages(self.config.database_path, batch_id)
        ]
        try:
            response = self.client.memories(
                memory_agent_name=self.config.memory_agent_name,
                namespace=self.config.namespace,
                messages=messages,
                async_mode=1,
            )
            task_id = _task_id(response)
            if not task_id:
                raise MemNetAIError("异步记忆请求未返回 taskId")
            mark_batch_submitted(self.config.database_path, batch_id, task_id)
            return RuntimeResult(True, payload={"action": "submitted", "batch_id": batch_id,
                                                "remote_task_id": task_id})
        except Exception as exc:
            retry_batch(self.config.database_path, batch_id, str(exc))
            return RuntimeResult(False, f"MemNetAI 记忆重试失败：{exc}。请前往控制台检查服务状态或余额。", DASHBOARD_URL)


def _task_id(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    inner = result.get("response_json", result)
    data = inner.get("data", inner) if isinstance(inner, dict) else {}
    if not isinstance(data, dict):
        return None
    value = data.get("task_id") or data.get("taskId") or data.get("id")
    return str(value) if value is not None else None


def _progress(result: Any) -> float | None:
    if not isinstance(result, dict):
        return None
    inner = result.get("response_json", result)
    data = inner.get("data", inner) if isinstance(inner, dict) else {}
    value = data.get("progress") if isinstance(data, dict) else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
