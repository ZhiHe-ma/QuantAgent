"""QuantAgent plugin host, versioned packets, recipes, and allow-listed Agents."""

from .agents import AgentError, AgentRuntime, ResolvedAgentPlan
from .contracts import ContractError, DataPacket
from .manifests import AgentCatalog, ManifestError
from .runner import RecipeError, RecipeRunner, RunCancelled, RunResult, default_registry
from .bootstrap import install_default_registry as _install_default_registry
from .p5_bootstrap import install_p5_services as _install_p5_services
from .api_bootstrap import install_api_app_factory as _install_api_app_factory
from .worker_bootstrap import install_worker_services as _install_worker_services
from .legacy_bootstrap import install_legacy_audit_factory as _install_legacy_audit_factory
from .legacy_bootstrap import install_legacy_recovery_factory as _install_legacy_recovery_factory

_install_p5_services()
_install_api_app_factory()
_install_worker_services()
_install_legacy_audit_factory()
_install_legacy_recovery_factory()
_install_default_registry()
del _install_default_registry, _install_p5_services, _install_api_app_factory, _install_worker_services, _install_legacy_audit_factory
del _install_legacy_recovery_factory

__all__ = [
    "AgentCatalog",
    "AgentError",
    "AgentRuntime",
    "ContractError",
    "DataPacket",
    "ManifestError",
    "RecipeError",
    "RecipeRunner",
    "RunCancelled",
    "ResolvedAgentPlan",
    "RunResult",
    "default_registry",
]

__version__ = "0.5.0"
