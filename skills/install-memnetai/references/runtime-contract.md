# 运行时契约

## 记忆边界

- 每个会话按 `session_id` 独立缓冲，防止并发乱序。
- 所有会话默认共享 `memory_agent_name=personal-agent`、`namespace=default`。
- `session_id` 只用于本地顺序、状态、来源和故障定位，不用于创建独立长期记忆体。

## 触发规则

```yaml
idle_timeout_minutes: 10
max_messages: 32
memory_agent_name: personal-agent
namespace: default
```

- 回复后达到 32 条：立即封存当前会话批次。
- 最后一条完整消息后静默 10 分钟：计划任务封存批次。
- 宿主明确结束会话或用户明确要求记住：立即封存。
- 计划任务扫描所有 `pending_count > 0` 且已到 `next_flush_at` 的会话，并重试失败批次。

提交采用 `pending -> sealed -> submitting -> accepted -> processing -> completed` 状态。异步请求被接受后不得立即删除本地消息；只有确认完成后才清理或归档。

## 并发与恢复

- SQLite启用 WAL、外键和 busy timeout。
- 消息具有稳定 `message_id`、会话内 `sequence_number` 和批次 `idempotency_key`。
- 到期任务使用 `generation` 二次检查；到期同时出现新消息时，旧任务不得吞并新消息。
- 启动时扫描逾期会话；设备离线时保留本地数据，恢复联网后重试。

## 错误呈现

- 余额、额度不足：说明长期记忆暂不可用，链接 <https://dashboard.memnetai.com>。
- API Key无效：提示前往控制台检查或重新生成。
- 限流：说明系统会自动重试，并提供控制台入口。
- 网络或服务端错误：说明本地消息已保留，将自动重试；不得误称余额不足。
- recall无结果不是错误，通常不提醒。

同类错误首次立即提示，之后限制提醒频率；恢复后提示积压内容正在补交。

## API Key

用户允许在聊天正文提供 API Key，但集成程序必须：不复述、不写日志、不写 SQLite 消息、不提交长期记忆、不进入 Git或错误报告。宿主自身可能保留聊天记录，安装结果应说明这一客观边界。

