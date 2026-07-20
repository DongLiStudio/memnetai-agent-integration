# MemNetAI Agent Integration

面向 AI Agent 宿主的本地优先 MemNetAI 长期记忆接入器。

> 当前处于工程初始化阶段，尚不可用于生产安装。

## 设计目标

- 对支持原生生命周期 Hook 的宿主，在回复前自动 recall，在回复后记录本轮消息。
- 每个会话独立维护本地缓冲，所有会话默认共享 `personal-agent/default` 长期记忆体。
- 会话满 32 条消息或静默 10 分钟后提交长期记忆。
- 使用 SQLite 保证并发、顺序、幂等和失败重试。
- 首批适配 Hermes、Codex 与 WorkBuddy；未知宿主优先探测原生 Hook，无 Hook 时降级为全局提示词。
- 记忆服务失败不阻塞普通回答，并向用户显示 MemNetAI 控制台入口。

## 技术路线

- Python 3.11+
- SQLite WAL
- MemNetAI Python SDK（接入版本将在实现阶段锁定）
- Windows Task Scheduler、macOS `launchd`、Linux systemd timer/cron

## 目录

```text
src/memnetai_agent_integration/
  adapters/       Agent 宿主适配器
  installers/     跨平台安装与计划任务注册
  cli.py          统一命令入口
  config.py       默认配置和配置解析
  database.py     SQLite 初始化与会话状态
tests/            自动化测试
docs/             架构与兼容性文档
```

## 计划中的用户体验

用户只需对 Agent 说“安装 MemNetAI”，安装器自动完成环境、Hook、数据库和计划任务准备；用户在中途提供一次 API Key，随后执行真实 recall、memories、Hook 与计划任务验证。

默认值：

```yaml
memory_agent_name: personal-agent
namespace: default
idle_timeout_minutes: 10
max_messages: 32
```

## 开发

当前最小骨架可直接运行：

```bash
python -m memnetai_agent_integration doctor
python -m unittest discover -s tests
```

## 许可证

Apache License 2.0。参见 [LICENSE](LICENSE)。

