from typing import Protocol


class HostAdapter(Protocol):
    """Contract implemented by native host adapters."""

    name: str

    def detect(self) -> bool: ...

    def install(self) -> None: ...

    def verify(self) -> bool: ...

    def uninstall(self) -> None: ...

