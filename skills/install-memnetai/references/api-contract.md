# MemNetAI 官方接口契约

实现和排错优先查阅 <https://docs.memnetai.com/>，不要根据旧安装包猜测当前接口。

## SDK

- 安装：`memnetai-python-sdk>=1.0.2,<2`
- 客户端：`MemNetAIClient(api_key, base_url="https://api.memnetai.com")`
- 消息：`Message(role, content, character="用户")`

## 回忆

每轮回复前调用 `recall(memory_agent_name, namespace, query, ...)`。优先注入响应中的 `data.memoryPrompt`；没有结果不是故障。Hook 总超时保持在 5 秒以内，失败时继续普通回答。

## 记忆

调用 `memories(memory_agent_name, namespace, messages, language="zh-CN", async_mode=1)`。官方说明服务端不保证幂等；因此必须先在 SQLite 封存稳定批次，状态查询失败时不得重新提交。

异步响应必须取得 `data.taskId`。计划任务通过 `GET /memories/task/progress?taskId=...` 查询 `data.progress`，请求头为 `Authorization: Token <api-key>`；只有进度达到 100 才把本地批次标记完成。

## 错误

响应含 `code` 时只把 `0`、`"0"` 和 `"00000"` 视为成功。认证、点数、额度、限流或服务错误不得阻断宿主回答；显性提示用户前往 <https://dashboard.memnetai.com>，但网络错误不得误称为余额不足。
