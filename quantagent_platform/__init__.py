"""QuantAgent plugin host, versioned packets, recipes, and built-in adapters."""

from .contracts import ContractError, DataPacket
from .runner import RecipeError, RecipeRunner, RunResult, default_registry

__all__ = [
    "ContractError",
    "DataPacket",
    "RecipeError",
    "RecipeRunner",
    "RunResult",
    "default_registry",
]

__version__ = "0.2.0"
