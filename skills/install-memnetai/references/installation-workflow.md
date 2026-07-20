# 安装工作流

## 状态机

```text
locate-source -> runtime-preflight -> detect-host -> plan -> confirm
  -> prepare -> waiting-for-api-key -> configure -> api-health-check
  -> hook-smoke-test -> scheduler-smoke-test -> complete
```

每次等待用户输入时，明确当前阶段、已经验证的结果和下一步。安装中断后从最近验证阶段继续，不重复执行已经成功的外部写入。

## 产品源

1. 当前 Skill 位于同时包含 `pyproject.toml`、`src/` 和 `skills/install-memnetai/` 的完整仓库时，直接使用该仓库。
2. 否则在新的系统临时目录获取 `https://github.com/DongLiStudio/memnetai-agent-integration`；不得复用非空目录或使用第三方镜像。
3. 回读来源 URL、ref/commit 和关键文件。结束时只清理本轮创建的临时产品源，不删除用户提供的本地仓库。

## 阶段一：准备

在用户确认影响范围后：

1. 找到或准备 Python 3.11+ 独立环境。
2. 安装锁定版本的项目包和 MemNetAI SDK。
3. 初始化本地配置目录与 SQLite。
4. 检测宿主并安装原生 Hook；没有 Hook 时生成待用户保存的全局提示词。
5. 注册当前操作系统的 `flush-due` 计划任务。
6. 备份并回读修改过的宿主配置。

API Key 尚未提供时，Hook 和计划任务可以安装，但不得向 MemNetAI 发送请求。阶段一状态必须是 `waiting-for-api-key`，不能称为安装完成。

## 阶段二：配置和验证

用户在对话中提供 API Key 后：

1. 不复述 Key；通过标准输入或临时进程环境写入凭证文件，避免出现在进程参数和日志中。
2. 使用 `personal-agent/default`，不询问记忆体名称。
3. 验证 API Key、memories 和 recall；测试消息使用可识别的健康检查内容，并避免污染正式记忆或在验证后清理测试数据。
4. 触发一次真实回复前/回复后流程。
5. 创建隔离测试会话，验证到期扫描与失败重试，不等待真实十分钟。

## 修复和卸载

- `doctor`：只读检查版本、配置、数据库、Hook、计划任务、待处理会话和最近错误。
- `repair`：先展示差异，备份后只修复缺失或失效部分。
- `uninstall`：移除 Hook、计划任务和程序文件；凭证、SQLite和未沉淀消息是否保留由用户明确选择。

## 安装验收

- 原生 Hook 配置或全局提示词降级状态可回读。
- 回复前 recall 与回复后消息写入分别通过测试。
- 数量阈值和静默到期扫描分别通过测试。
- API错误会显性通知但不阻塞普通回答。
- 重复安装不产生重复 Hook、重复计划任务或重复数据库结构。

