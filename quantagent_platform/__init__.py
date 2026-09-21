"""QuantAgent plugin host primitives.

The package is deliberately independent from the legacy Daily/Monitor runtime so
the first platform recipe can be adopted without changing its dependencies or
side-effect behaviour.
"""

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

__version__ = "0.1.0"
