# Architecture

## Memory boundary

- `session_id` identifies a local conversation buffer; it does not create a separate cloud memory entity.
- `memory_agent_name` and `namespace` identify the shared MemNetAI memory scope.
- Defaults are `personal-agent` and `default`; advanced users may override them later.

## Turn lifecycle

```text
before reply: append user message -> recall -> inject relevant memories
after reply:  append assistant message -> flush immediately when count threshold is reached
scheduled:    scan all pending sessions -> flush sessions idle for 10 minutes -> retry failures
              -> poll submitted taskId values -> complete only at progress 100
```

The scheduled scan is required because no host hook fires after a conversation becomes idle.

## Adapter policy

1. Use a verified native lifecycle Hook when available.
2. Unknown hosts may be inspected for an official Hook mechanism and validated before activation.
3. Hosts without Hooks fall back to global prompt instructions. This is best-effort and must not be described as guaranteed automation.
4. A local model gateway is intentionally out of scope.

## Reliability

- SQLite uses WAL mode, foreign keys and a busy timeout.
- Messages are sealed into an idempotent batch before submission.
- Asynchronous acceptance stores the returned `taskId`; source messages remain local and the
  batch becomes complete only when the documented progress endpoint reaches 100.
- The remote memories API does not guarantee idempotency. A progress-query failure never causes
  an already-submitted batch to be sent again.
- API failures never block the host Agent's ordinary response.

## User-visible failures

Authentication, balance, quota and rate-limit failures should be visible without repeated alert spam. User-actionable notices link directly to:

<https://dashboard.memnetai.com>
