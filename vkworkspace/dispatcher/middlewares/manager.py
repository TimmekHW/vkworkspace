from __future__ import annotations

from .base import BaseMiddleware


class MiddlewareManager:
    def __init__(self) -> None:
        self.middlewares: list[BaseMiddleware] = []

    def __call__(self, middleware: BaseMiddleware) -> BaseMiddleware:
        self.middlewares.append(middleware)
        return middleware

    def register(self, middleware: BaseMiddleware) -> None:
        self.middlewares.append(middleware)

    def unregister(self, middleware: BaseMiddleware) -> None:
        self.middlewares.remove(middleware)
