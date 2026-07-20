---
name: install-memnetai
description: 对话式安装、配置、修复、验证和卸载 MemNetAI Agent 长期记忆接入。用于用户给出 DongLiStudio/memnetai-agent-integration 仓库链接或安装包并要求安装，或要求接入 MemNetAI、配置 API Key、启用回复前 recall、回复后会话缓冲、满条数或静默十分钟自动记忆、排查 Hook/计划任务/余额/凭证问题时。优先使用 Hermes、Codex、WorkBuddy 原生 Hook；未知宿主先核实官方 Hook，无 Hook 时降级到全局提示词。
---

# 安装 MemNetAI 长期记忆

把本 Skill 当作安装协调器，把仓库中的 `memnetai-integration` CLI 当作文件、数据库、Hook 和计划任务操作的确定性实现。不要在 Skill 中重写安装逻辑，也不要把尚未实现或未验证的步骤宣称为成功。

## 读取契约

开始安装前完整读取：

- `references/installation-workflow.md`：两阶段安装、状态机和验收条件。
- `references/host-integration.md`：宿主识别、原生 Hook 映射和提示词降级规则。
- `references/runtime-contract.md`：会话缓冲、定时提交、错误提示和数据安全约束。

## 核心规则

- 用户正常只需表达安装意图，并在中途提供一次 MemNetAI API Key。
- 默认使用 `memory_agent_name=personal-agent`、`namespace=default`、静默 10 分钟、最多 32 条触发。
- API Key 可以由用户在当前对话中提供；收到后不得复述、写日志、进入会话缓冲或长期记忆。
- 优先安装当前宿主经过验证的原生生命周期 Hook。未知宿主只采用官方文档或本机可验证配置；没有 Hook 时直接降级为全局提示词，不使用本地模型网关。
- 安装前展示将修改的宿主配置和系统计划任务；备份配置并获得确认后再写入。
- 任何 API、Hook、计划任务或健康检查结果都要独立回读；命令退出码不等于安装成功。
- recall 或 memories 失败不能阻塞普通回答。余额、额度、凭证和限流问题显性提示用户前往 <https://dashboard.memnetai.com>。
- 当前产品尚处于预发布阶段时，只允许开发验证，不得把脚手架状态描述为可生产安装。

## 安装流程

1. 定位当前完整仓库；若只有仓库链接，在新的系统临时目录获取官方仓库并记录 URL、ref 和 commit。
2. 检查 Python 3.11+、项目 CLI、平台、当前宿主及目标配置文件，不自动安装未知来源依赖。
3. 运行安装计划或 dry-run，展示将创建的本地目录、SQLite、宿主 Hook、计划任务和全局提示词变化。
4. 用户确认后执行不依赖 API Key 的准备阶段；完成后回读文件、数据库、Hook 注册和计划任务状态。
5. 请求用户提供 API Key，立即写入受保护配置，不在后续输出中复述。
6. 使用默认 `personal-agent/default` 完成 memories 与 recall 健康检查。
7. 触发真实宿主测试，确认回复前 Hook 能注入 recall，回复后 Hook 能记录当前会话。
8. 验证 `flush-due` 能扫描所有未沉淀会话，并能处理满 32 条、静默 10 分钟及失败重试。
9. 输出已完成证据、降级能力、未验证项、控制台链接和卸载/修复入口。

## 完成条件

- 当前宿主模式明确标为原生 Hook 或全局提示词降级。
- SQLite、默认记忆体、namespace、静默时间和数量阈值均已回读。
- memories、recall、回复前、回复后和计划任务分别有验证结果。
- 凭证未出现在日志、数据库缓冲、Git diff 或最终输出中。
- 失败和降级项保持显性，不把准备完成等同于安装完成。

