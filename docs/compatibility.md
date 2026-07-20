# Host compatibility

This document records the lifecycle contracts used by the installer. Support means the adapter
can install and verify its configuration; release qualification still requires a real turn on the
specific host version.

| Host | Contract | Local configuration | Verification boundary |
|---|---|---|---|
| Codex | `UserPromptSubmit` injects `additionalContext`; `Stop` provides `last_assistant_message` | `~/.codex/hooks.json` | Codex requires first-use review/trust for non-managed command hooks |
| WorkBuddy | `UserPromptSubmit` injects context; `Stop` identifies the session/transcript | `~/.workbuddy/settings.json` | When Stop omits the final response, the adapter reverse-scans the provided JSONL transcript |
| Hermes | Python Plugin `pre_llm_call` returns `context`; `post_llm_call` observes the final response | `~/.hermes/plugins/memnetai-memory` | Installer enables the plugin without tool-override permission and verifies it through Hermes CLI |

All three adapters use a five-second reply-before command deadline and keep failures non-blocking.
Interrupted turns may omit the reply-after event, so the one-minute scheduler remains required.

## Unsupported hosts

The installation Skill first checks the host's official extension documentation and local schema.
If no verified before/after lifecycle exists, it writes or presents a marker-delimited global prompt
only when a real global instruction file can be identified. This mode is reported as
`automation_guaranteed=false`; it is not equivalent to native Hook support.
