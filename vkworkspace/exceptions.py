from __future__ import annotations


class VKWorkspaceError(Exception):
    pass


class VKTeamsAPIError(VKWorkspaceError):
    def __init__(self, method: str, message: str) -> None:
        self.method = method
        self.message = message
        super().__init__(f"API error in {method}: {message}")


class InvalidToken(VKWorkspaceError):
    pass
