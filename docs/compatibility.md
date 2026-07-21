# Host compatibility

This document records the lifecycle contracts used by the installer. Support means the adapter
can install and verify its configuration; release qualification still requires a real turn on the
specific host version.

| Host | Contract | Local configuration | Verification boundary |
|---|---|---|---|
| Codex | `SessionStart`; `UserPromptSubmit` injects context; `Stop` captures the response | `~/.codex/hooks.json` with `hooks` wrapper | Trust through `/hooks`, open a new task, then require runtime receipts |
| WorkBuddy | `SessionStart`; `UserPromptSubmit` uses `user_prompt`; `Stop` identifies the transcript | top-level events in `~/.workbuddy/settings.json` | Restart, open a new task, and reverse-scan JSONL when Stop omits the response |
| Hermes | Python Plugin `pre_llm_call` returns `context`; `post_llm_call` observes the final response | `~/.hermes/plugins/memnetai-memory` | Installer enables the plugin without tool-override permission and verifies it through Hermes CLI |

On Windows, Hermes uses `%LOCALAPPDATA%/hermes` unless `HERMES_HOME` explicitly overrides it.

Configuration presence is not runtime activation. `doctor` reports healthy only after observing
`SessionStart`, reply-before, and reply-after receipts for a configured host.

All three adapters use a five-second reply-before command deadline and keep failures non-blocking.
Interrupted turns may omit the reply-after event, so the one-minute scheduler remains required.

The production task API can remove a completed asynchronous task before the next poll and then
return `A0449`. The integration only reconciles that explicit code as terminal for a task ID that
was previously returned by `memories`; all other HTTP and business errors remain failures.

## Universal Agent compatibility

Hosts not listed above are not categorically unsupported. The installation Skill first checks the
host's official extension documentation and local schema for a verifiable lifecycle integration.
If no verified before/after lifecycle exists, it writes or presents a marker-delimited global prompt
only when a real global instruction file can be identified. This mode is reported as
`automation_guaranteed=false`; it is not equivalent to native Hook support.
