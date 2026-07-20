from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntegrationDefaults:
    memory_agent_name: str = "personal-agent"
    namespace: str = "default"
    idle_timeout_minutes: int = 10
    max_messages: int = 32

