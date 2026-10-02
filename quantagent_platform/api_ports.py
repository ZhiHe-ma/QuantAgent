"""Startup application-factory port without optional HTTP implementation imports."""
from typing import Any, Callable

_factory: Callable[..., Any] | None = None


def configure_api_app_factory(factory: Callable[..., Any]) -> None:
    """Trusted startup binding only; configuring performs no application IO."""
    if not callable(factory):
        raise TypeError("API application factory must be callable")
    global _factory
    _factory = factory


def get_api_app_factory() -> Callable[..., Any]:
    if _factory is None:
        raise RuntimeError("API application factory has not been configured at startup")
    return _factory
