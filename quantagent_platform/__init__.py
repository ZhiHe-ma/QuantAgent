"""QuantAgent plugin host, versioned packets, recipes, and allow-listed Agents."""

from .agents import AgentError, AgentRuntime, ResolvedAgentPlan
from .contracts import ContractError, DataPacket
from .manifests import AgentCatalog, ManifestError
from .runner import RecipeError, RecipeRunner, RunResult, default_registry

__all__ = [
    "AgentCatalog",
    "AgentError",
    "AgentRuntime",
    "ContractError",
    "DataPacket",
    "ManifestError",
    "RecipeError",
    "RecipeRunner",
    "ResolvedAgentPlan",
    "RunResult",
    "default_registry",
]

__version__ = "0.5.0"
