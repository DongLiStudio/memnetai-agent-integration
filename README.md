# MemNetAI Agent Integration

面向 Codex、WorkBuddy 和 Hermes 的本地优先 MemNetAI 长期记忆接入器。

## 一句话安装

把下面这句话直接发给 Codex、WorkBuddy 或 Hermes：

> 请安装 MemNetAI 长期记忆系统：https://github.com/DongLiStudio/memnetai-agent-integration

Agent 会读取仓库中的 `skills/install-memnetai/SKILL.md`，自动准备 Python 环境、安装程序、识别当前宿主、写入 Hook、注册计划任务并逐项回读。用户只需在 Agent 询问时提供一次 MemNetAI API Key。

Agent 的确定性入口是仓库内的 `python scripts/bootstrap.py`；用户不需要自己运行命令。

Codex 会在首次运行新 Hook 时显示宿主自带的安全审核；这是 Codex 的强制信任机制，用户需要确认一次。它不是 MemNetAI 的额外配置，安装器不会使用危险参数绕过。

## 自动工作方式

- 每次用户提交消息：按 `session_id` 保存消息，调用 recall，并把官方返回的 `memoryPrompt` 注入当前轮。
- 每次 Agent 完成回复：保存最终助手消息；当前会话累计 32 条后立即封存并异步提交。
- 每分钟计划任务：扫描所有会话；最后活动超过 10 分钟时提交未沉淀消息，并轮询异步任务、处理重试。
- 所有会话默认共享 `personal-agent/default` 长期记忆体，但本地缓冲按会话隔离，避免并发乱序。
- recall 和记忆提交失败不会阻断普通回答；用户会看到 [MemNetAI 控制台](https://dashboard.memnetai.com)入口。

## 宿主支持

| 宿主 | 回复前 | 回复后 | 安装形态 | 注意事项 |
|---|---|---|---|---|
| Codex | `UserPromptSubmit` | `Stop` | `~/.codex/hooks.json` | 首次需通过 Codex Hook 信任审核 |
| WorkBuddy | `UserPromptSubmit` | `Stop` | `~/.workbuddy/settings.json` | Stop 无最终文本时从会话 JSONL 倒序读取 |
| Hermes | `pre_llm_call` | `post_llm_call` | `~/.hermes/plugins/memnetai-memory` | 自动启用 Python Plugin；结束/重置时补交 |

未知宿主会先检查官方 Hook 或插件机制。没有可靠 Hook 时，安装 Skill 只允许降级为全局提示词并标记为 best-effort，不会安装本地模型网关，也不会谎称强自动化。

详细的宿主契约和验证边界见 [`docs/compatibility.md`](docs/compatibility.md)。

## 安全与可靠性

- API Key 不支持命令行参数，只能通过标准输入或遮蔽交互输入。
- Windows 使用当前用户 DPAPI 加密；macOS/Linux 使用权限为 `0600` 的用户文件。
- API Key 不进入日志、SQLite 消息、Hook 输出、Git diff 或诊断结果。
- SQLite 使用 WAL、外键、busy timeout、会话内原子序号和稳定事件 ID。
- 消息先封存为稳定批次，再提交到 MemNetAI；异步请求返回 `taskId` 后持续查询进度，达到 100 才标记完成。
- 官方 API 不保证服务端幂等，因此本地不会在任务状态查询失败时重新提交同一批次。
- 安装和卸载只处理本项目拥有的 Hook、插件、计划任务和凭证，不覆盖用户已有配置。

## 默认配置

```json
{
  "memory_agent_name": "personal-agent",
  "namespace": "default",
  "idle_timeout_minutes": 10,
  "max_messages": 32,
  "recall_timeout_seconds": 4.0
}
```

非敏感配置默认存放在用户应用数据目录的 `config.json`；可用 `MEMNETAI_INTEGRATION_HOME` 改变整个本地数据根目录。高级用户可以修改记忆体和 namespace，普通安装无需选择。

## 手动命令

正常用户无需执行这些命令；它们供 Agent、开发和故障恢复使用。

```bash
# 第一阶段：返回 waiting_for_api_key
memnetai-integration install

# 第二阶段：API Key 从 stdin 读取，不进入进程参数
memnetai-integration install --api-key-stdin

memnetai-integration doctor --json
memnetai-integration repair
memnetai-integration flush-due
memnetai-integration uninstall
```

## 开发验证

要求 Python 3.11+，运行时依赖官方 `memnetai-python-sdk>=1.0.2,<2`。

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
ruff check .
```

没有真实 API Key 时，自动化测试覆盖模拟 API、SQLite 并发与恢复、三个宿主配置、跨平台计划任务、凭证和卸载；真实 API 与宿主生命周期仍应在发布前按兼容矩阵执行端到端验收。

## 项目结构

```text
src/memnetai_agent_integration/
  adapters/       Codex、WorkBuddy、Hermes 与提示词降级适配
  installers/     跨平台文件事务和计划任务
  client.py       官方 SDK 与任务进度接口
  runtime.py      recall、缓冲、提交、轮询和重试
  hooks.py        三宿主 Hook 输入归一化
  secrets.py      API Key 保护
  cli.py          安装与运行入口
skills/install-memnetai/  Agent 一键安装协调 Skill
tests/                    自动化测试
```

## 许可证

Apache License 2.0。参见 [LICENSE](LICENSE)。
